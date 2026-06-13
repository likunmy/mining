import logging
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import trafilatura

from pipeline.config import POLICY_SOURCES, MAX_ENTRIES_PER_SOURCE, REQUEST_DELAY_POLICY
from pipeline.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class PolicyCrawler(BaseCrawler):
    source_type = "policy"

    def crawl(self, max_count: int = MAX_ENTRIES_PER_SOURCE):
        records = []
        for key, src in POLICY_SOURCES.items():
            logger.info("crawling policy source: %s (%s)", key, src["url"])
            try:
                src_records = self._crawl_source(src, max_count // len(POLICY_SOURCES))
                records.extend(src_records)
            except Exception as e:
                self.log_error(src["url"], str(e))
                logger.warning("policy source %s failed: %s", key, e)
            time.sleep(REQUEST_DELAY_POLICY)
        logger.info("policy crawler: %d records", len(records))
        return records

    def _crawl_source(self, src: dict, max_count: int) -> list[dict]:
        records = []
        html = self.fetch(src["url"])
        if not html:
            return records

        soup = BeautifulSoup(html, "lxml")
        links = self._extract_links(soup, src["url"])

        for url in links[:max_count]:
            try:
                record = self._process_policy_page(url, src)
                if record:
                    records.append(record)
            except Exception as e:
                self.log_error(url, str(e))
            time.sleep(REQUEST_DELAY_POLICY)

        return records

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        links = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Prioritize article/news/policy looking paths
            if any(kw in href.lower() for kw in ["policy", "news", "article", "resource", "strategy", "regulation", "announcement", "notice", "xxgk", "zwgk", "tzgg"]):
                full = urljoin(base_url, href)
                if full.startswith(("http://", "https://")):
                    links.add(full)
        # fallback — collect all same-domain links
        if not links:
            for a in soup.find_all("a", href=True):
                full = urljoin(base_url, a["href"])
                if full.startswith(base_url.rstrip("/")):
                    links.add(full)
        return list(links)

    def _process_policy_page(self, url: str, src: dict) -> dict | None:
        html = self.fetch(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        main = soup.find("main") or soup.find("article") or soup.find("body")
        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if not text or len(text.strip()) < 50:
            return None

        date_str = self._extract_date(soup)

        return {
            "url": url,
            "title": title,
            "full_text": text.strip(),
            "published_at": date_str,
            "source_type": self.source_type,
            "language": src["language"],
            "jurisdiction": src["jurisdiction"],
            "policy_type": self._classify_policy(title, text),
            "source_name": src["name"],
        }

    def _extract_date(self, soup: BeautifulSoup) -> str | None:
        patterns = [
            r"\d{4}-\d{2}-\d{2}",
            r"\d{4}/\d{2}/\d{2}",
            r"\d{4}年\d{1,2}月\d{1,2}日",
        ]
        for p in patterns:
            m = re.search(p, soup.get_text())
            if m:
                return m.group()
        return None

    def _classify_policy(self, title: str, text: str) -> str:
        t = (title + " " + text[:500]).lower()
        if any(kw in t for kw in ["strategy", "战略", "strategy"]):
            return "strategy"
        if any(kw in t for kw in ["regulation", "规则", "regulation"]):
            return "regulation"
        if any(kw in t for kw in ["law", "法案", "law"]):
            return "law"
        return "announcement"
