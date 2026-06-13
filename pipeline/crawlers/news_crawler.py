"""矿业新闻爬虫 — RSS + Sitemap 补充 + 全文提取。"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

from pipeline.config import NEWS_RSS_URLS, MAX_NEWS_PER_FEED, DAYS_BACK, REQUEST_DELAY_NEWS
from pipeline.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


class NewsCrawler(BaseCrawler):
    source_type = "news"
    _TARGET = 200  # 新闻目标条数

    def crawl(self, max_count: int = MAX_NEWS_PER_FEED) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
        seen_urls: set[str] = set()

        # Phase 1: RSS
        for rss_url in NEWS_RSS_URLS:
            logger.info("抓取 RSS: %s", rss_url)
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

            logger.info("RSS 在时间窗口内 %s 条", len(items))

            for entry, link in items[:max_count]:
                try:
                    record = self._process_article(entry, link, pub_dt=None)
                    if record:
                        records.append(record)
                except Exception as e:
                    self.log_error(link, str(e))

            time.sleep(REQUEST_DELAY_NEWS)

        # Phase 2: Sitemap 补充（针对 mining.com）补至目标条数
        needed = max(0, self._TARGET - len(records))
        if needed > 0:
            logger.info("RSS 共 %d 条，仍需 %d 条，从 sitemap 补充", len(records), needed)
            sitemap_urls = self._extract_sitemap_urls(cutoff, needed + 50)  # 多抓一些以抵消 paywall 损耗
            for url in sitemap_urls:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                try:
                    record = self._process_article_by_url(url)
                    if record:
                        records.append(record)
                        if len(records) >= self._TARGET:
                            break
                except Exception as e:
                    self.log_error(url, str(e))

        logger.info("新闻爬虫: %d 条", len(records))
        return records

    def _process_article(self, entry: Any, link: str, pub_dt: datetime | None) -> dict[str, Any] | None:
        full_text, _ = self._fetch_full_text(link)
        if not full_text or len(full_text.strip()) < 50:
            return None
        pub = entry.get("published_parsed") if hasattr(entry, "get") else None
        if pub:
            pub_dt = datetime(*pub[:6], tzinfo=timezone.utc)
        return {
            "url": link,
            "title": self.sanitize_text(entry.get("title", "")).strip(),
            "author": entry.get("author"),
            "summary": self.sanitize_text(entry.get("summary", "")).strip(),
            "published_at": pub_dt.isoformat() if pub_dt else None,
            "full_text": self.sanitize_text(full_text).strip(),
            "source_type": self.source_type,
            "language": "en",
        }

    def _process_article_by_url(self, url: str) -> dict[str, Any] | None:
        full_text, html = self._fetch_full_text(url)
        if not full_text or len(full_text.strip()) < 50:
            return None

        # 从 HTML 提取标题和发布日期
        title = ""
        published_at = None
        if html:
            soup = BeautifulSoup(html, "lxml")
            title_tag = soup.find("h1") or soup.find("title")
            if title_tag:
                title = self.sanitize_text(title_tag.get_text(strip=True))
            # 尝试从 meta 标签提取发布日期
            meta_date = soup.find("meta", attrs={"property": "article:published_time"})
            if meta_date and meta_date.get("content"):
                published_at = meta_date["content"]
            if not published_at:
                time_tag = soup.find("time")
                if time_tag and time_tag.get("datetime"):
                    published_at = time_tag["datetime"]

        return {
            "url": url,
            "title": title,
            "author": None,
            "summary": "",
            "published_at": published_at,
            "full_text": self.sanitize_text(full_text).strip(),
            "source_type": self.source_type,
            "language": "en",
        }

    def _fetch_full_text(self, url: str) -> tuple[str | None, str | None]:
        """抓取并提取正文，返回 (text, html) 元组。"""
        try:
            resp = httpx.get(
                url, follow_redirects=False, timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if resp.status_code == 302:
                loc = resp.headers.get("location", "")
                if "subscribe-login" in loc:
                    return None, None
            elif resp.status_code == 200:
                html = resp.text
                # 检测 paywall 页面
                if any(kw in html[:1000].lower() for kw in ["subscribe-login", "subscribe to continue", "please log in"]):
                    return None, None
                text = trafilatura.extract(html, include_comments=False, include_tables=False)
                return text, html
        except Exception as e:
            logger.warning("fetch failed: %s — %s", url, e)
        return None, None

    def _extract_sitemap_urls(self, cutoff: datetime, max_count: int) -> list[str]:
        """从 mining.com sitemap 提取近期文章 URL。"""
        try:
            resp = httpx.get(
                "https://www.mining.com/sitemap.xml",
                timeout=15,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            root = ET.fromstring(resp.content)
            post_sitemaps = [
                loc.text for loc in root.findall(".//sm:loc", SITEMAP_NS)
                if loc.text and "post-sitemap" in loc.text
            ]
        except Exception as e:
            logger.warning("sitemap 索引解析失败: %s", e)
            return []

        # 只取最后 5 个 sitemap（含最新文章）
        urls: list[str] = []
        for sm_url in post_sitemaps[-5:]:
            if len(urls) >= max_count:
                break
            try:
                resp2 = httpx.get(sm_url, timeout=15, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
                root2 = ET.fromstring(resp2.content)
                for url_elem in root2.findall(".//sm:url", SITEMAP_NS):
                    loc = url_elem.find("sm:loc", SITEMAP_NS)
                    lastmod = url_elem.find("sm:lastmod", SITEMAP_NS)
                    if loc is not None and lastmod is not None:
                        try:
                            lm = datetime.fromisoformat(lastmod.text.replace("Z", "+00:00"))
                            if lm >= cutoff and loc.text not in urls:
                                urls.append(loc.text)
                                if len(urls) >= max_count:
                                    break
                        except (ValueError, AttributeError):
                            continue
            except Exception as e:
                logger.warning("sitemap %s 解析失败: %s", sm_url, e)

        logger.info("sitemap 提取 %d 条 URL", len(urls))
        return urls


def main():
    """单独测试新闻爬虫。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    import sys
    # 解析可选参数：--count N
    count = 5
    show_full = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 1
        elif args[i] == "--full":
            show_full = True
        i += 1

    crawler = NewsCrawler()
    records = crawler.crawl(max_count=count)
    print(f"\n{'='*60}")
    print(f"抓取完成: {len(records)} 条记录")
    print(f"{'='*60}\n")

    for idx, r in enumerate(records, 1):
        title = r.get("title", "").strip() or "(NO TITLE, from sitemap)"
        print(f"[{idx}] {title}")
        print(f"    URL: {r.get('url', '')}")
        pub = r.get("published_at") or "N/A"
        print(f"    Published: {pub}")
        print(f"    Length: {len(r.get('full_text', ''))} chars")
        print(f"    full_text:{r.get('full_text', '')}")
        if show_full:
            print(f"    {'─'*40}")
            print(f"    {r.get('full_text', '')[:2000]}")
            if len(r.get('full_text', '')) > 2000:
                print(f"    ... (truncated, total {len(r.get('full_text', ''))} chars)")
            print(f"    {'─'*40}")
        print()


if __name__ == "__main__":
    main()
