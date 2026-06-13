"""Pipeline orchestrator: crawl → process → embed."""

import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("pipeline")


def run():
    from pipeline.crawlers.news_crawler import NewsCrawler
    from pipeline.crawlers.policy_crawler import PolicyCrawler
    from pipeline.crawlers.price_crawler import PriceCrawler
    from pipeline.processor import process_all
    from pipeline.embedder import embed_all

    t0 = time.time()

    # Phase 1: crawl
    logger.info("=== PHASE 1: CRAWL ===")
    crawlers = [NewsCrawler, PolicyCrawler, PriceCrawler]
    for Cls in crawlers:
        name = Cls.__name__
        logger.info("--- starting %s ---", name)
        try:
            inst = Cls()
            records = inst.crawl()
            inst.save_raw(records)
            inst.close()
        except Exception as e:
            logger.error("%s failed: %s", name, e, exc_info=True)

    # Phase 2: process
    logger.info("=== PHASE 2: PROCESS ===")
    process_all()

    # Phase 3: embed
    logger.info("=== PHASE 3: EMBED ===")
    embed_all()

    elapsed = time.time() - t0
    logger.info("=== pipeline done in %.1fs ===", elapsed)


if __name__ == "__main__":
    run()
