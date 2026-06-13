"""DeepSeek API 调用封装 (OpenAI-compatible)。"""

import json
import logging
from typing import Any

import httpx

from llm.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)

_CHAT_URL = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"


def call_llm(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 2048,
    timeout: int = 60,
    **kwargs: Any,
) -> str:
    """调用 DeepSeek Chat API，返回回复文本。

    Parameters
    ----------
    messages : list[dict[str, str]]
        OpenAI 格式的消息列表，如 [{"role": "user", "content": "..."}]
    model : str | None
        模型名称，默认使用 llm.config.DEEPSEEK_MODEL
    temperature : float
        生成温度，评估场景建议 0.0
    max_tokens : int
        最大输出 token 数
    timeout : int
        请求超时秒数
    **kwargs
        额外参数会传递到 API body（如 response_format={"type": "json_object"}）

    Returns
    -------
    str
        模型回复文本

    Raises
    ------
    RuntimeError
        API key 未配置或 API 返回错误
    """
    if not DEEPSEEK_API_KEY:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 未设置。请通过环境变量配置后重试。"
        )

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    body: dict[str, Any] = {
        "model": model or DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        **kwargs,
    }

    logger.debug("POST %s | model=%s | messages=%d", _CHAT_URL, body["model"], len(messages))

    try:
        with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
            resp = client.post(_CHAT_URL, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        detail = e.response.text[:500]
        raise RuntimeError(f"DeepSeek API 返回错误 [{status}]: {detail}") from e
    except httpx.RequestError as e:
        raise RuntimeError(f"DeepSeek API 请求失败: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"DeepSeek API 响应解析失败: {e}") from e

    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"DeepSeek API 返回空 choices: {json.dumps(data, ensure_ascii=False)}")

    msg = choices[0].get("message", {})
    content = msg.get("content", "") or ""
    # 推理模型：content 为空时尝试 reasoning_content
    if not content and msg.get("reasoning_content"):
        content = msg["reasoning_content"]

    logger.debug("LLM 返回 %d 字符 (finish_reason=%s)", len(content), choices[0].get("finish_reason", "?"))
    return content.strip()


def call_llm_structured(
    messages: list[dict[str, str]],
    *,
    system_prompt: str | None = None,
    **kwargs: Any,
) -> str:
    """带 system prompt 的便捷调用。"""
    msgs: list[dict[str, str]] = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.extend(messages)
    return call_llm(msgs, **kwargs)
