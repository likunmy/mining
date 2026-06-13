"""LLM answer generation for RAG queries — reusable by server and eval."""

import logging
from typing import Any

from llm.client import call_llm

logger = logging.getLogger(__name__)

GENERATION_SYSTEM = (
    "你是专业矿业行业分析师。请仅基于提供的上下文文档简洁地回答用户问题。"
    "如果上下文信息不足，说明缺失哪些内容。不要编造事实或使用外部知识。"
)

GENERATION_USER = """上下文文档：
{context}

问题：{question}

请严格基于以上上下文，用 2-4 句话简洁回答。"""


def format_context(docs: list[dict], max_snippet_chars: int = 600) -> str:
    """Format retrieved docs into a prompt-ready context string."""
    lines: list[str] = []
    for i, d in enumerate(docs, 1):
        title = (d.get("title") or "").strip()
        snippet = (d.get("snippet") or "")[:max_snippet_chars]
        score = d.get("score", 0)
        header = f"[{i}] (score: {score:.2f})"
        if title:
            header += f" {title}"
        lines.append(header)
        lines.append(f"    {snippet}")
        lines.append("")
    return "\n".join(lines)


def generate_answer(question: str, docs: list[dict]) -> str | None:
    """Generate an answer from retrieved documents using the LLM.

    Returns the generated answer string, or None on failure.
    """
    if not docs:
        return "No relevant documents found."

    context = format_context(docs)
    try:
        answer = call_llm(
            [
                {"role": "system", "content": GENERATION_SYSTEM},
                {
                    "role": "user",
                    "content": GENERATION_USER.format(
                        context=context, question=question
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=2048,
        )
        return answer.strip()
    except Exception as e:
        logger.warning("Answer generation failed: %s", e)
        return None
