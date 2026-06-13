import logging
from datetime import datetime, timezone, timedelta

import feedparser
import trafilatura

from pipeline.config import NEWS_RSS_URLS, MAX_ENTRIES_PER_SOURCE, DAYS_BACK, REQUEST_DELAY_NEWS
from pipeline.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class NewsCrawler(BaseCrawler):
    source_type = "news"

    def crawl(self, max_count: int = MAX_ENTRIES_PER_SOURCE):
        records = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
        seen_urls: set[str] = set()

        for rss_url in NEWS_RSS_URLS:
            logger.info("fetching RSS: %s", rss_url)
            feed = feedparser.parse(rss_url)
            items = []
            for entry in feed.entries:
                pub = entry.get("published_parsed")
                if pub:
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                link = entry.get("link", "")
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                items.append((entry, link))

            logger.info("RSS yielded %d items within window", len(items))

            for entry, link in items[:max_count]:
                try:
                    full_text = self._fetch_full_text(link)
                    if not full_text or len(full_text.strip()) < 50:
                        continue

                    pub = entry.get("published_parsed")
                    pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else None

                    record = {
                        "url": link,
                        "title": entry.get("title", "").strip(),
                        "author": entry.get("author"),
                        "summary": entry.get("summary", "").strip(),
                        "published_at": pub_dt.isoformat() if pub_dt else None,
                        "full_text": full_text.strip(),
                        "source_type": self.source_type,
                        "language": "en",
                    }
                    records.append(record)
                    self.save_checkpoint("news", pub_dt)
                except Exception as e:
                    self.log_error(link, str(e))
                    logger.warning("failed to process %s: %s", link, e)

            import time as _time
            _time.sleep(REQUEST_DELAY_NEWS)

        logger.info("news crawler: %d records", len(records))
        return records

    def _fetch_full_text(self, url: str) -> str | None:
        html = self.fetch(url)
        if not html:
            return None
        return trafilatura.extract(html, include_comments=False, include_tables=False)
