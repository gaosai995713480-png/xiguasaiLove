"""Single OpenAI-compatible Agent loop.

Supports both the Responses API (default) and Chat Completions, including
streaming text and function/tool calls.
"""
import json
import logging
from typing import AsyncGenerator

import httpx
from starlette.concurrency import run_in_threadpool

from ..database import get_config
from .agent_tools import (
    execute_tool,
    get_tools_for_chat_completions,
    get_tools_for_responses,
)
from .llm_urls import build_llm_api_url, normalize_api_mode

logger = logging.getLogger(__name__)

_TIMEOUT = 120


def _get_max_rounds() -> int:
    try:
        return int(get_config("AGENT_MAX_TOOL_ROUNDS") or 5)
    except (ValueError, TypeError):
        return 5


async def ai_agent_loop(
    base_url: str,
    api_key: str,
    model: str,
    api_mode: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    """Dispatch to the configured OpenAI-compatible protocol."""
    mode = normalize_api_mode(api_mode)
    if mode == "responses":
        async for chunk in _responses_agent_loop(
            base_url, api_key, model, messages
        ):
            yield chunk
        return

    async for chunk in _chat_completions_agent_loop(
        base_url, api_key, model, messages
    ):
        yield chunk


def _model_body(model: str) -> dict:
    return {"model": model} if model else {}


async def _chat_completions_agent_loop(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    tools = get_tools_for_chat_completions()
    max_rounds = await run_in_threadpool(_get_max_rounds)
    url = build_llm_api_url(base_url, "chat_completions")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    working_messages = list(messages)

    for round_index in range(max_rounds):
        body = {
            **_model_body(model),
            "messages": working_messages,
            "tools": tools,
            "stream": True,
        }
        full_content = ""
        tool_calls_acc: dict[int, dict] = {}

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    logger.error(
                        "AI Chat Completions API 错误 [%s]: %s",
                        resp.status_code,
                        error_body[:500],
                    )
                    yield json.dumps(
                        {"type": "error", "content": f"API 返回 {resp.status_code}"}
                    )
                    return

                content_type = (resp.headers.get("content-type") or "").lower()
                if "application/json" in content_type:
                    raw_body = await resp.aread()
                    try:
                        data = json.loads(raw_body)
                    except json.JSONDecodeError:
                        data = {}
                    choices = data.get("choices") or []
                    if choices:
                        message = choices[0].get("message") or {}
                        full_content = str(message.get("content") or "")
                        if full_content:
                            yield json.dumps(full_content)
                        for index, tool_call in enumerate(
                            message.get("tool_calls") or []
                        ):
                            function = tool_call.get("function") or {}
                            tool_calls_acc[index] = {
                                "id": tool_call.get("id", ""),
                                "name": function.get("name", ""),
                                "arguments": function.get("arguments", ""),
                            }
                else:
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            event = json.loads(data_str)
                            choices = event.get("choices", [])
                            if not choices:
                                continue
                            delta = choices[0].get("delta", {})

                            content = delta.get("content")
                            if content:
                                full_content += content
                                yield json.dumps(content)

                            for tool_call in delta.get("tool_calls", []):
                                index = tool_call.get("index", 0)
                                if index not in tool_calls_acc:
                                    tool_calls_acc[index] = {
                                        "id": tool_call.get("id", ""),
                                        "name": "",
                                        "arguments": "",
                                    }
                                if tool_call.get("id"):
                                    tool_calls_acc[index]["id"] = tool_call["id"]
                                function = tool_call.get("function", {})
                                if function.get("name"):
                                    tool_calls_acc[index]["name"] = function["name"]
                                if function.get("arguments"):
                                    tool_calls_acc[index]["arguments"] += function["arguments"]
                        except json.JSONDecodeError:
                            continue

        if not tool_calls_acc:
            return

        for call_index, tool_call in enumerate(tool_calls_acc.values()):
            if not tool_call["id"]:
                tool_call["id"] = f"call_{round_index}_{call_index}"

        working_messages.append(
            {
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": [
                    {
                        "id": tool_call["id"],
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": tool_call["arguments"],
                        },
                    }
                    for tool_call in tool_calls_acc.values()
                ],
            }
        )

        for tool_call in tool_calls_acc.values():
            result = await _execute_tool_result(
                tool_call["name"],
                tool_call["arguments"],
            )

            working_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": result,
                }
            )

    working_messages.append(
        {
            "role": "system",
            "content": "你已达到工具调用次数上限，请基于已获取的信息直接回答用户问题，不要再调用工具。",
        }
    )
    yield json.dumps("[提示] 已达到最大工具调用轮数，正在生成总结...")

    summary_body = {
        **_model_body(model),
        "messages": working_messages,
        "stream": True,
    }
    async for chunk in _stream_chat_completions_text(url, headers, summary_body):
        yield chunk


async def _stream_chat_completions_text(
    url: str,
    headers: dict,
    body: dict,
) -> AsyncGenerator[str, None]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200:
                    yield json.dumps(f"\n\n抱歉，无法生成总结（HTTP {resp.status_code}）")
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices", [])
                    if not choices:
                        continue
                    content = (choices[0].get("delta") or {}).get("content")
                    if content:
                        yield json.dumps(content)
    except Exception as exc:
        logger.error("总结生成失败: %s", exc, exc_info=True)
        yield json.dumps(f"\n\n总结生成失败：{exc}")


async def _responses_agent_loop(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
) -> AsyncGenerator[str, None]:
    tools = get_tools_for_responses()
    max_rounds = await run_in_threadpool(_get_max_rounds)
    url = build_llm_api_url(base_url, "responses")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    instructions, working_input = _split_responses_messages(messages)

    for round_index in range(max_rounds):
        state = _new_responses_state()
        body = {
            **_model_body(model),
            "input": working_input,
            "tools": tools,
            "stream": True,
        }
        if instructions:
            body["instructions"] = instructions

        async for chunk in _stream_responses_request(url, headers, body, state):
            yield chunk
        if state["error"]:
            return

        output_items, tool_calls = _responses_follow_up_items(state)
        if not tool_calls:
            return

        for call_index, tool_call in enumerate(tool_calls):
            if not tool_call["call_id"]:
                tool_call["call_id"] = f"call_{round_index}_{call_index}"
        working_input.extend(output_items)

        for tool_call in tool_calls:
            result = await _execute_tool_result(
                tool_call["name"],
                tool_call["arguments"],
            )

            working_input.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call["call_id"],
                    "output": result,
                }
            )

    summary_instructions = (
        f"{instructions}\n\n"
        "你已达到工具调用次数上限，请基于已获取的信息直接回答用户问题，不要再调用工具。"
    ).strip()
    yield json.dumps("[提示] 已达到最大工具调用轮数，正在生成总结...")
    state = _new_responses_state()
    body = {
        **_model_body(model),
        "input": working_input,
        "stream": True,
    }
    if summary_instructions:
        body["instructions"] = summary_instructions
    async for chunk in _stream_responses_request(url, headers, body, state):
        yield chunk


def _split_responses_messages(messages: list[dict]) -> tuple[str, list[dict]]:
    instructions: list[str] = []
    items: list[dict] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            if content:
                instructions.append(str(content))
            continue
        if role not in ("user", "assistant"):
            continue
        items.append({"role": role, "content": str(content)})
    return "\n\n".join(instructions), items


def _new_responses_state() -> dict:
    return {
        "text": "",
        "items": {},
        "final_output": [],
        "error": "",
    }


def _response_item_key(item: dict, event: dict) -> str:
    item_id = item.get("id") or event.get("item_id")
    if item_id is not None and str(item_id) != "":
        return str(item_id)
    output_index = event.get("output_index")
    return "" if output_index is None else str(output_index)


def _event_item_key(event: dict) -> str:
    item_id = event.get("item_id")
    if item_id is not None and str(item_id) != "":
        return str(item_id)
    output_index = event.get("output_index")
    return "" if output_index is None else str(output_index)


async def _stream_responses_request(
    url: str,
    headers: dict,
    body: dict,
    state: dict,
) -> AsyncGenerator[str, None]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    logger.error(
                        "AI Responses API 错误 [%s]: %s",
                        resp.status_code,
                        error_body[:500],
                    )
                    state["error"] = f"API 返回 {resp.status_code}"
                    yield json.dumps(
                        {"type": "error", "content": state["error"]}
                    )
                    return

                content_type = (resp.headers.get("content-type") or "").lower()
                if "application/json" in content_type:
                    raw_body = await resp.aread()
                    try:
                        data = json.loads(raw_body)
                    except json.JSONDecodeError:
                        data = {}
                    output = data.get("output") or []
                    if isinstance(output, list):
                        state["final_output"] = output
                    fallback_text = _extract_response_output_text(
                        output if isinstance(output, list) else []
                    )
                    text = str(data.get("output_text") or "") or fallback_text
                    if text:
                        state["text"] = text
                        yield json.dumps(text)
                    error = data.get("error") or {}
                    if isinstance(error, dict) and error.get("message"):
                        state["error"] = str(error["message"])
                        yield json.dumps(
                            {"type": "error", "content": state["error"]}
                        )
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = event.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = event.get("delta", "")
                        if delta:
                            state["text"] += delta
                            yield json.dumps(delta)
                    elif event_type == "response.output_text.done":
                        text = str(event.get("text") or "")
                        if text and not state["text"]:
                            state["text"] = text
                            yield json.dumps(text)
                    elif event_type == "response.output_item.added":
                        item = event.get("item") or {}
                        key = _response_item_key(item, event)
                        if key:
                            state["items"][key] = dict(item)
                    elif event_type == "response.function_call_arguments.delta":
                        key = _event_item_key(event)
                        item = state["items"].setdefault(
                            key,
                            {
                                "type": "function_call",
                                "call_id": "",
                                "name": "",
                                "arguments": "",
                            },
                        )
                        item["arguments"] = (
                            str(item.get("arguments") or "")
                            + str(event.get("delta") or "")
                        )
                    elif event_type == "response.function_call_arguments.done":
                        key = _event_item_key(event)
                        item = state["items"].setdefault(
                            key,
                            {
                                "type": "function_call",
                                "call_id": "",
                                "name": "",
                                "arguments": "",
                            },
                        )
                        item["arguments"] = str(event.get("arguments") or "")
                    elif event_type == "response.output_item.done":
                        item = event.get("item") or {}
                        key = _response_item_key(item, event)
                        if key:
                            state["items"][key] = dict(item)
                        if item.get("type") == "message" and not state["text"]:
                            text = _extract_response_message_text(item)
                            if text:
                                state["text"] = text
                                yield json.dumps(text)
                    elif event_type == "response.completed":
                        output = (event.get("response") or {}).get("output") or []
                        if isinstance(output, list):
                            state["final_output"] = output
                            if not state["text"]:
                                text = _extract_response_output_text(output)
                                if text:
                                    state["text"] = text
                                    yield json.dumps(text)
                    elif event_type in {"response.failed", "error"}:
                        response_error = (event.get("response") or {}).get("error") or {}
                        message = (
                            response_error.get("message")
                            or (event.get("error") or {}).get("message")
                            or event.get("message")
                            or "Responses API 调用失败"
                        )
                        state["error"] = str(message)
                        yield json.dumps(
                            {"type": "error", "content": state["error"]}
                        )
                        return
    except Exception as exc:
        logger.error("Responses API 请求失败: %s", exc, exc_info=True)
        state["error"] = str(exc)
        yield json.dumps({"type": "error", "content": str(exc)})


def _responses_follow_up_items(state: dict) -> tuple[list[dict], list[dict]]:
    raw_items = state["final_output"] or []
    if not raw_items:
        raw_items = list(state["items"].values())

    follow_up: list[dict] = []
    tool_calls: list[dict] = []
    saw_message = False
    for item in raw_items:
        item_type = item.get("type")
        if item_type == "message":
            text = _extract_response_message_text(item)
            if text:
                follow_up.append({"role": "assistant", "content": text})
                saw_message = True
        elif item_type == "function_call":
            tool_call = {
                "type": "function_call",
                "call_id": str(item.get("call_id") or item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "arguments": str(item.get("arguments") or ""),
            }
            follow_up.append(tool_call)
            tool_calls.append(tool_call)

    if state["text"] and not saw_message:
        follow_up.insert(0, {"role": "assistant", "content": state["text"]})
    return follow_up, tool_calls


def _extract_response_message_text(item: dict) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") in {
            "output_text",
            "text",
        }:
            text = part.get("text")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _extract_response_output_text(output: list[dict]) -> str:
    parts = []
    for item in output:
        if isinstance(item, dict) and item.get("type") == "message":
            text = _extract_response_message_text(item)
            if text:
                parts.append(text)
    return "".join(parts)


async def _execute_tool_result(name: str, arguments: str) -> str:
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        args = {}
    return await execute_tool(name, args)
