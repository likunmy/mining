"""Eval: recall@5 + answer faithfulness."""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from serve.retriever import Retriever
from eval.config import GROUND_TRUTH, RESULTS_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stderr)
logger = logging.getLogger("eval")


def load_ground_truth() -> list[dict]:
    with open(GROUND_TRUTH, encoding="utf-8") as f:
        return json.load(f)


def recall_at_5(results: list[dict], gt: dict) -> float:
    top5 = results[:5]
    keywords = gt.get("keywords", [])
    if not keywords:
        return 0.0

    hits = 0
    for r in top5:
        title = (r.get("title") or "").lower()
        snippet = (r.get("snippet") or "").lower()
        combined = title + " " + snippet
        if any(kw.lower() in combined for kw in keywords):
            hits += 1
    return hits / min(5, len(keywords))


def faithfulness(results: list[dict], gt: dict) -> float:
    """Estimate faithfulness via keyword coverage in top snippets."""
    keywords = gt.get("keywords", [])
    if not keywords:
        return 0.0

    all_snippets = " ".join(
        ((r.get("title") or "") + " " + (r.get("snippet") or "")).lower()
        for r in results[:5]
    )
    covered = sum(1 for kw in keywords if kw.lower() in all_snippets)
    return covered / len(keywords)


def run():
    retriever = Retriever()
    gt_list = load_ground_truth()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    results_summary = []
    recall_scores = []
    faith_scores = []

    for gt in gt_list:
        q = gt["question"]
        where = {}
        if gt.get("source_type"):
            where["source_type"] = gt["source_type"]

        resp = retriever.query(q, k=10, where=where or None)
        results = resp["results"]

        recall = recall_at_5(results, gt)
        faith = faithfulness(results, gt)
        recall_scores.append(recall)
        faith_scores.append(faith)

        results_summary.append({
            "id": gt["id"],
            "question": q,
            "recall@5": round(recall, 3),
            "faithfulness": round(faith, 3),
            "top5_hits": [r.get("title") for r in results[:5]],
        })

        logger.info("Q%d recall@5=%.3f faith=%.3f — %s", gt["id"], recall, faith, q[:50])

    avg_recall = sum(recall_scores) / len(recall_scores)
    avg_faith = sum(faith_scores) / len(faith_scores)

    report = {
        "avg_recall@5": round(avg_recall, 3),
        "avg_faithfulness": round(avg_faith, 3),
        "num_questions": len(gt_list),
        "per_item": results_summary,
    }

    report_path = RESULTS_DIR / "eval_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n=== EVAL RESULTS ===")
    print(f"  recall@5:        {avg_recall:.3f}")
    print(f"  faithfulness:    {avg_faith:.3f}")
    print(f"  questions:       {len(gt_list)}")
    print(f"  report:          {report_path}")


if __name__ == "__main__":
    run()
