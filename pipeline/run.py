"""Pipeline orchestrator: crawl -> process -> embed."""

import argparse
import logging
import sys
import time
from typing import NoReturn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("pipeline")

RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


def _ensure_models() -> None:
    """Pre-download embedding & reranker models to HF cache so serve/eval find them."""
    from sentence_transformers import SentenceTransformer, CrossEncoder
    from pipeline.config import EMBEDDING_MODEL

    logger.info("pre-loading embedding model: %s", EMBEDDING_MODEL)
    SentenceTransformer(EMBEDDING_MODEL)
    logger.info("pre-loading reranker model: %s", RERANKER_MODEL)
    CrossEncoder(RERANKER_MODEL)


def _run_pipeline(*, skip_crawl: bool = False, skip_process: bool = False, skip_embed: bool = False) -> float:
    """Execute pipeline phases.

    Returns elapsed time in seconds.
    """
    _ensure_models()

    t0 = time.time()

    if not skip_crawl:
        from pipeline.crawlers.news_crawler import NewsCrawler
        from pipeline.crawlers.policy_crawler import PolicyCrawler
        from pipeline.crawlers.price_crawler import PriceCrawler

        logger.info("=== CRAWL ===")
        for Cls in [NewsCrawler, PolicyCrawler, PriceCrawler]:
            try:
                inst = Cls()
                inst.save_raw(inst.crawl())
                inst.close()
            except Exception as e:
                logger.error("%s failed: %s", Cls.__name__, e, exc_info=True)

    if not skip_process:
        from pipeline.processor import process_all
        logger.info("=== PROCESS ===")
        process_all()

    if not skip_embed:
        from pipeline.embedder import embed_all
        logger.info("=== EMBED ===")
        embed_all()

    elapsed = time.time() - t0
    return elapsed


def cli() -> NoReturn:
    """CLI entry point (pyproject.toml scripts)."""
    parser = argparse.ArgumentParser(description="Mining aggregation pipeline")
    parser.add_argument("--skip-crawl", action="store_true", help="skip crawling phase")
    parser.add_argument("--skip-process", action="store_true", help="skip processing phase")
    parser.add_argument("--skip-embed", action="store_true", help="skip embedding phase")
    args = parser.parse_args()

    elapsed = _run_pipeline(
        skip_crawl=args.skip_crawl,
        skip_process=args.skip_process,
        skip_embed=args.skip_embed,
    )
    logger.info("=== pipeline done in %.1fs ===", elapsed)
    sys.exit(0)


# Backward-compatible alias for programmatic use
run = _run_pipeline


if __name__ == "__main__":
    cli()
