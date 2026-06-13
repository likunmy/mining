"""LLM routing: question → search plan (source type, query, filters)."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from llm.client import call_llm

logger = logging.getLogger(__name__)

ROUTER_SYSTEM = (
    "你是矿业情报路由分析助手。分析用户的问题，输出搜索计划 JSON。\n\n"
    "可用来源类型：\n"
    '- "news" — 矿业新闻、并购、运营、环境影响\n'
    '- "policy" — 政府法规、关键矿产、贸易政策\n'
    '- "price" — 大宗商品价格数据（LME/SHFE/DCE 期货）\n\n'
    "已知品种：copper（铜）、zinc（锌）、nickel（镍）、lithium（锂）、iron_ore（铁矿石）\n\n"
    "输出 JSON 格式：\n"
    '{\n'
    '  "analysis": "简要分析",\n'
    '  "searches": [\n'
    '    {\n'
    '      "source_types": ["news"],\n'
    '      "query": "向量搜索文本",\n'
    '      "where": {}\n'
    '    }\n'
    '  ]\n'
    "}\n\n"
    "规则：\n"
    "- 价格类问题 → query 设为 null，品种信息填入 where\n"
    "- 中文新闻 → 同时搜索中英文查询词\n"
    "- 中国政策 → 中文查询词；EU/IEA 政策 → 英文查询词\n"
    "- source_types 必须是 news、policy、price 中的一个或多个"
)

ROUTER_USER = """问题：{question}

请输出搜索计划 JSON："""


@dataclass
class SearchPlan:
    source_types: list[str] = field(default_factory=list)
    query: str | None = None
    where: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchPlanResult:
    analysis: str = ""
    searches: list[SearchPlan] = field(default_factory=list)


def _parse_plan(raw: str) -> SearchPlanResult | None:
    """Parse LLM JSON response into SearchPlanResult."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON block from markdown
        import re
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
            except json.JSONDecodeError:
                return None
        else:
            return None

    searches = [
        SearchPlan(
            source_types=s.get("source_types", ["news"]),
            query=s.get("query"),
            where=s.get("where", {}),
        )
        for s in data.get("searches", [])
    ]
    return SearchPlanResult(
        analysis=data.get("analysis", ""),
        searches=searches,
    )


def plan(question: str) -> SearchPlanResult:
    """Analyze question and produce a search plan."""
    try:
        resp = call_llm(
            [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": ROUTER_USER.format(question=question)},
            ],
            temperature=0.0,
            max_tokens=1024,
        )
        result = _parse_plan(resp)
        if result and result.searches:
            return result
        logger.warning("Router returned empty plan, falling back")
    except Exception as e:
        logger.warning("Router LLM call failed: %s", e)

    # Fallback: single news search with the question as query
    return SearchPlanResult(
        analysis="fallback: single vector search",
        searches=[SearchPlan(source_types=["news", "policy"], query=question)],
    )
