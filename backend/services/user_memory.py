"""
用户长期记忆服务

功能：
1. 事实存储/检索/删除
2. 记忆自动注入（拼接到 system prompt）
3. 对话后异步事实提取（通过 LLM）
"""
import json
import logging

from starlette.concurrency import run_in_threadpool

from ..database import get_db
from .ai_chat import get_ai_config, is_ai_configured
from .llm_urls import build_llm_api_url

logger = logging.getLogger(__name__)

# 最大注入记忆条数
_MAX_INJECT_FACTS = 50


def save_fact(username: str, fact_content: str, category: str = "general", source: str = "auto") -> int:
    """保存一条用户事实，返回 id。如果内容重复则跳过。"""
    fact_content = fact_content.strip()
    if not fact_content:
        return 0

    with get_db() as conn:
        with conn.cursor() as cursor:
            # 去重：相同用户相同内容不重复存
            cursor.execute(
                "SELECT id FROM user_facts WHERE username = %s AND fact_content = %s",
                (username, fact_content),
            )
            existing = cursor.fetchone()
            if existing:
                return existing[0]

            cursor.execute(
                "INSERT INTO user_facts (username, fact_content, category, source) VALUES (%s, %s, %s, %s)",
                (username, fact_content, category, source),
            )
            row_id = cursor.lastrowid
        conn.commit()
    logger.info("保存用户事实 [%s]: %s (category=%s, source=%s)", username, fact_content[:60], category, source)
    return row_id


def get_user_facts(username: str, limit: int = _MAX_INJECT_FACTS) -> list[dict]:
    """获取用户所有事实"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, fact_content, category, source, created_at FROM user_facts "
                "WHERE username = %s ORDER BY created_at DESC LIMIT %s",
                (username, limit),
            )
            rows = cursor.fetchall()
    return [
        {
            "id": r[0],
            "content": r[1],
            "category": r[2],
            "source": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def delete_fact(username: str, fact_id: int) -> bool:
    """删除一条事实"""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM user_facts WHERE id = %s AND username = %s",
                (fact_id, username),
            )
            affected = cursor.rowcount
        conn.commit()
    return affected > 0


def build_memory_prompt(username: str) -> str:
    """构建记忆注入的 system prompt 片段"""
    facts = get_user_facts(username)
    if not facts:
        return ""

    lines = ["[长期记忆] 以下是关于用户的已知信息，请在回复时自然地参考这些记忆："]
    for f in facts:
        category_label = {
            "general": "📝",
            "date": "📅",
            "preference": "❤️",
            "person": "👤",
        }.get(f["category"], "📝")
        lines.append(f"- {category_label} {f['content']}")

    return "\n".join(lines)


async def extract_facts_from_conversation(
    username: str,
    user_message: str,
    ai_response: str,
) -> list[str]:
    """
    对话结束后，异步调用 LLM 从对话中提取用户事实。
    使用轻量级提示，不走 Agent Loop。
    """
    import httpx

    extraction_prompt = f"""请从以下对话中提取关于用户的关键个人事实信息。

只提取明确的事实，例如：
- 重要日期（生日、纪念日、入职日等）
- 个人偏好（喜欢的食物、颜色、花、音乐等）
- 重要人物（女朋友/男朋友名字、家人信息等）
- 地点信息（住址、常去的地方等）
- 其他有价值的个人信息

【对话内容】
用户: {user_message}
AI: {ai_response[:500]}

请以 JSON 数组格式返回，每个元素是一个对象，包含 content（事实内容）和 category（分类：general/date/preference/person）。
如果没有值得记住的事实，返回空数组 []。
只返回 JSON，不要其他文字。"""

    try:
        cfg = get_ai_config()
        if not is_ai_configured(cfg):
            return []
        url = build_llm_api_url(cfg["base_url"], cfg["api_mode"])
        headers = {
            "Authorization": f"Bearer {cfg['api_key']}",
            "Content-Type": "application/json",
        }
        if cfg["api_mode"] == "responses":
            body = {
                "input": [{"role": "user", "content": extraction_prompt}],
            }
        else:
            body = {
                "max_tokens": 500,
                "messages": [{"role": "user", "content": extraction_prompt}],
            }
        if cfg["model"]:
            body["model"] = cfg["model"]
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                return []
            content_type = (resp.headers.get("content-type") or "").lower()
            if "text/event-stream" in content_type:
                if cfg["api_mode"] == "responses":
                    text = _extract_responses_event_stream_text(resp.text)
                else:
                    text = _extract_chat_event_stream_text(resp.text)
            else:
                data = resp.json()
                if cfg["api_mode"] == "responses":
                    text = _extract_responses_text(data)
                else:
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        # 解析 JSON
        text = text.strip()
        # 去除 markdown 代码块包裹
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        facts = json.loads(text)
        if not isinstance(facts, list):
            return []

        saved = []
        for fact in facts:
            if isinstance(fact, dict) and fact.get("content"):
                content = str(fact["content"]).strip()
                category = str(fact.get("category", "general")).strip()
                if category not in ("general", "date", "preference", "person"):
                    category = "general"
                await run_in_threadpool(save_fact, username, content, category, "auto")
                saved.append(content)

        if saved:
            logger.info("从对话中提取了 %d 条事实 [%s]", len(saved), username)
        return saved

    except Exception as e:
        logger.warning("事实提取失败: %s", e)
        return []


def _extract_responses_text(data: dict) -> str:
    direct = data.get("output_text")
    if direct:
        return str(direct)
    parts = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for part in item.get("content") or []:
            if isinstance(part, dict) and part.get("type") in {"output_text", "text"}:
                if part.get("text"):
                    parts.append(str(part["text"]))
    return "".join(parts)


def _extract_responses_event_stream_text(text: str) -> str:
    deltas = []
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
        if event_type == "response.output_text.delta":
            deltas.append(str(event.get("delta") or ""))
        elif event_type == "response.output_text.done":
            fallback = str(event.get("text") or "")
        elif event_type == "response.output_item.done":
            fallback = _extract_responses_text({"output": [event.get("item")]})
        elif event_type == "response.completed":
            fallback = _extract_responses_text(event.get("response") or {})
    return "".join(deltas).strip() or fallback


def _extract_chat_event_stream_text(text: str) -> str:
    chunks = []
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
        for choice in event.get("choices") or []:
            content = (choice.get("delta") or {}).get("content")
            if content:
                chunks.append(str(content))
    return "".join(chunks)
