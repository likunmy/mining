"""Eval: recall@5 + faithfulness via ragas (replaces keyword + LLM scoring)."""

import asyncio
import json
import logging
import os
import sys
from typing import Any

# Windows asyncio fix: use SelectorEventLoop to avoid "Event loop is closed"
# errors from httpx/httpcore async cleanup on Windows ProactorEventLoop
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Disable ragas telemetry before any ragas import
os.environ["RAGAS_DO_NOT_TRACK"] = "true"

from datasets import Dataset
from langchain_openai import ChatOpenAI
from ragas import evaluate
from ragas.metrics._context_recall import context_recall
from ragas.metrics._faithfulness import faithfulness

from eval.config import GROUND_TRUTH, RESULTS_DIR
from llm.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from serve.generator import generate_answer
from serve.reranker import Reranker
from serve.retriever import Retriever
from serve.router import plan as plan_search

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("eval")


def load_ground_truth() -> list[dict[str, Any]]:
    with open(GROUND_TRUTH, encoding="utf-8") as f:
        return json.load(f)


def _build_judge_llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=f"{DEEPSEEK_BASE_URL}/v1",
        temperature=0.0,
    )


def compute_ragas_metrics(
    question: str,
    contexts: list[str],
    answer: str,
    ground_truth: str,
    judge_llm: ChatOpenAI,
) -> dict[str, float | None]:
    """Compute context_recall and faithfulness for a single Q&A pair."""
    metric_cr = context_recall
    metric_faith = faithfulness
    metric_cr.llm = judge_llm
    metric_faith.llm = judge_llm

    ds = Dataset.from_dict({
        "question": [question],
        "contexts": [contexts],
        "answer": [answer],
        "ground_truth": [ground_truth],
    })

    try:
        result = evaluate(ds, metrics=[metric_cr, metric_faith])
        df = result.to_pandas()
        return {
            "recall@5": float(df["context_recall"].iloc[0]),
            "faithfulness": float(df["faithfulness"].iloc[0]),
        }
    except Exception as e:
        logger.warning("Ragas evaluation failed: %s", e)
        return {"recall@5": None, "faithfulness": None}


def run() -> dict[str, Any]:
    retriever = Retriever()
    reranker = Reranker()
    gt_list = load_ground_truth()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    judge_llm = _build_judge_llm()

    results_summary: list[dict[str, Any]] = []
    recall_scores: list[float] = []
    faith_scores: list[float] = []

    for gt in gt_list:
        q = gt["question"]

        # Router → multi-query → reranker (no manual filters)
        logger.debug("=== ROUTER INPUT ===\nquestion: %s", q)
        plan = plan_search(q)
        logger.debug("=== ROUTER OUTPUT ===\n%s", plan)

        all_results = retriever.multi_query(plan.searches)
        all_results = reranker.rerank(q, all_results)
        top5 = all_results[:5]

        logger.debug(
            "=== GENERATOR INPUT ===\nquestion: %s\ndocs: %d | top snippets:\n%s",
            q,
            len(top5),
            "\n".join(
                f"  [{i}] {r.get('title','')} | {r.get('snippet','')[:200]}"
                for i, r in enumerate(top5, 1)
            ),
        )

        # LLM generation
        answer = generate_answer(q, top5)
        logger.debug("=== GENERATOR OUTPUT ===\nanswer: %s", answer or "NONE")

        # Ragas metrics (skip if generation failed)
        metrics: dict[str, float | None] = {}
        if answer:
            contexts = [r.get("snippet", "") for r in top5]
            logger.debug(
                "=== RAGAS INPUT ===\nquestion: %s\ngt: %s\ncontexts:\n%s",
                q,
                gt["expected_answer"],
                "\n".join(f"  [{i}] {c[:200]}" for i, c in enumerate(contexts, 1)),
            )
            metrics = compute_ragas_metrics(
                question=q,
                contexts=contexts,
                answer=answer,
                ground_truth=gt["expected_answer"],
                judge_llm=judge_llm,
            )
            logger.debug(
                "=== RAGAS OUTPUT ===\nrecall@5: %s\nfaithfulness: %s",
                metrics.get("recall@5"),
                metrics.get("faithfulness"),
            )
        else:
            metrics = {"recall@5": None, "faithfulness": None}

        recall = metrics["recall@5"]
        faith = metrics["faithfulness"]

        if recall is not None:
            recall_scores.append(float(recall))
        if faith is not None:
            faith_scores.append(float(faith))

        item: dict[str, Any] = {
            "id": gt["id"],
            "question": q,
            "recall@5": round(float(recall), 3) if recall is not None else None,
            "faithfulness": round(float(faith), 3) if faith is not None else None,
            "generated_answer": answer or "",
            "top5_hits": [r.get("title") for r in top5],
        }
        results_summary.append(item)

        log_recall = f"{item['recall@5']:.3f}" if item["recall@5"] is not None else "N/A"
        log_faith = f"{item['faithfulness']:.3f}" if item["faithfulness"] is not None else "N/A"
        logger.info("Q%d recall@5=%-7s faith=%-7s — %s", gt["id"], log_recall, log_faith, q[:50])

    # Aggregates
    n = len(gt_list)
    avg_recall = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0
    avg_faith = sum(faith_scores) / len(faith_scores) if faith_scores else 0.0

    report: dict[str, Any] = {
        "avg_recall@5": round(avg_recall, 3),
        "avg_faithfulness": round(avg_faith, 3),
        "num_questions": n,
        "per_item": results_summary,
    }

    report_path = RESULTS_DIR / "eval_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== 评估结果 ===")
    print(f"  recall@5:            {avg_recall:.3f}")
    print(f"  faithfulness:        {avg_faith:.3f}")
    print(f"  问题数:              {n}")
    print(f"  报告:                {report_path}")

    return report


def main() -> None:
    run()


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.DEBUG)
    for handler in logging.getLogger().handlers:
        handler.setLevel(logging.DEBUG)
    main()
