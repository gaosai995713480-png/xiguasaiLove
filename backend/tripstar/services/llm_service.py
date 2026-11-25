"""TripStar OpenAI-compatible LLM service."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ...services.llm_urls import build_llm_api_url, normalize_api_mode
from ..config import TripStarSettings

logger = logging.getLogger(__name__)


class TripStarLLMError(RuntimeError):
    """TripStar 大模型调用失败。"""


def _extract_json_object(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象，兼容少量 markdown 包裹。"""
    content = (text or "").strip()
    if not content:
        raise TripStarLLMError("大模型返回内容为空")

    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise TripStarLLMError("大模型返回内容不是 JSON 对象")
        try:
            parsed = json.loads(content[start : end + 1])
        except json.JSONDecodeError as exc:
            logger.warning("LLM JSON 解析失败，尝试修复: %s", content[:200])
            raise TripStarLLMError("大模型返回 JSON 解析失败，请重试") from exc

    if not isinstance(parsed, dict):
        raise TripStarLLMError("大模型返回 JSON 顶层必须是对象")
    return parsed


def _extract_chat_event_stream_content(text: str) -> str:
    """兼容 Chat Completions 始终返回 text/event-stream 的情况。"""
    chunks: list[str] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.split(":", 1)[1].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in event.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            content = delta.get("content")
            if content is None:
                content = message.get("content")
            if content:
                chunks.append(str(content))
    return "".join(chunks).strip()


def _extract_responses_output_text(data: Any) -> str:
    """Extract assistant text from a Responses API JSON object."""
    if not isinstance(data, dict):
        return ""

    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            chunks.append(content)
            continue
        for part in content or []:
            if isinstance(part, str):
                chunks.append(part)
                continue
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                chunks.append(text)
    return "".join(chunks).strip()


def _extract_responses_event_stream_content(text: str) -> str:
    """Extract text from Responses API streaming events."""
    deltas: list[str] = []
    fallback = ""
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line.split(":", 1)[1].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = event.get("type", "")
        delta = event.get("delta")
        if event_type == "response.output_text.delta" and isinstance(delta, str):
            deltas.append(delta)
        elif event_type == "response.output_text.done":
            candidate = event.get("text")
            if isinstance(candidate, str) and candidate.strip():
                fallback = candidate.strip()
        elif event_type == "response.output_item.done":
            candidate = _extract_responses_output_text({"output": [event.get("item")]})
            if candidate:
                fallback = candidate
        elif event_type == "response.completed":
            candidate = _extract_responses_output_text(event.get("response"))
            if candidate:
                fallback = candidate

    return "".join(deltas).strip() or fallback


def _extract_chat_content(content_type: str, text: str, data: dict[str, Any]) -> str:
    """从 Chat Completions 的普通 JSON 或 SSE 响应中提取内容。"""
    if "text/event-stream" in (content_type or "").lower():
        content = _extract_chat_event_stream_content(text)
        if not content:
            raise TripStarLLMError("大模型流式响应未包含有效内容")
        return content

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TripStarLLMError("大模型接口响应缺少 choices[0].message.content") from exc
    if not isinstance(content, str) or not content.strip():
        raise TripStarLLMError("大模型接口响应内容为空")
    return content


def _extract_responses_content(content_type: str, text: str, data: dict[str, Any]) -> str:
    """从 Responses API 的普通 JSON 或 SSE 响应中提取内容。"""
    if "text/event-stream" in (content_type or "").lower():
        content = _extract_responses_event_stream_content(text)
    else:
        content = _extract_responses_output_text(data)
        if not content:
            # Some compatibility proxies still return Chat Completions JSON.
            try:
                content = _extract_chat_content("", text, data)
            except TripStarLLMError:
                content = ""

    if not content:
        raise TripStarLLMError("Responses 接口响应未包含有效内容")
    return content


class TripStarLLMClient:
    """Single OpenAI-compatible client for Responses and Chat Completions."""

    def __init__(self, settings: TripStarSettings):
        if not settings.has_llm_config:
            raise TripStarLLMError("TripStar 大模型配置不完整")
        self.api_mode = normalize_api_mode(settings.llm_api_mode)
        self.model = settings.llm_model_id
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.timeout = settings.llm_timeout

    @property
    def api_url(self) -> str:
        return build_llm_api_url(self.base_url, self.api_mode)

    def _payload(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if self.api_mode == "responses":
            payload: dict[str, Any] = {
                "input": [{"role": "user", "content": user_prompt}],
            }
            if system_prompt:
                payload["instructions"] = system_prompt
        else:
            payload = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        if self.model:
            payload["model"] = self.model
        return payload

    def chat_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        payload = self._payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/event-stream" in content_type.lower():
                    data: dict[str, Any] = {}
                else:
                    raw_data = response.json()
                    data = raw_data if isinstance(raw_data, dict) else {}
        except httpx.HTTPError as exc:
            raise TripStarLLMError(f"大模型接口请求失败：{exc}") from exc
        except ValueError as exc:
            raise TripStarLLMError("大模型接口返回了无法解析的 JSON") from exc

        if self.api_mode == "responses":
            content = _extract_responses_content(content_type, response.text, data)
        else:
            content = _extract_chat_content(content_type, response.text, data)
        return _extract_json_object(content)
