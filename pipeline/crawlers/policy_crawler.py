"""政策文档爬虫 — 各政策源通过 handler 路由到对应的抓取策略。"""

import json
import logging
import os
import re
import tempfile
import time
from typing import Any

import httpx
import pypdf
import trafilatura
from bs4 import BeautifulSoup

from pipeline.config import (
    MAX_ENTRIES_PER_SOURCE,
    POLICY_SOURCES,
    REQUEST_DELAY_POLICY,
    REQUEST_TIMEOUT_PDF,
)
from pipeline.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)


class PolicyCrawler(BaseCrawler):
    source_type = "policy"

    def crawl(self, max_count: int = MAX_ENTRIES_PER_SOURCE) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for key, src in POLICY_SOURCES.items():
            logger.info("抓取政策源: %s (%s)", key, src["url"])
            try:
                src_records = self._crawl_source(src, max_count)
                records.extend(src_records)
            except Exception as e:
                self.log_error(src["url"], str(e))
                logger.warning("政策源 %s 失败: %s", key, e)
            time.sleep(REQUEST_DELAY_POLICY)
        logger.info("政策爬虫: %d 条", len(records))
        return records

    def _crawl_source(self, src: dict[str, Any], max_count: int) -> list[dict[str, Any]]:
        handler = src.get("handler")
        if handler:
            method = getattr(self, f"_crawl_{handler}", None)
            if method:
                return method(src, max_count)
            logger.warning("[%s] handler %s 未实现", src["name"], handler)
        return []

    # ── handler: ac_rei ──────────────────────────────────────────────

    def _crawl_ac_rei(self, src: dict[str, Any], max_count: int) -> list[dict[str, Any]]:
        """中国稀土学会 — POST JSON list API（分页）+ article page fetch。"""
        records: list[dict[str, Any]] = []
        list_url = src["list_url"]
        article_base = src["article_base"]
        module_ids = src["module_ids"]

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        }

        # 遍历所有 module 分页获取文章列表
        article_ids: list[tuple[str, str, str]] = []  # (id, title, date)
        for module_id in module_ids:
            if len(article_ids) >= max_count:
                break
            for page in range(5):
                start = page + 1  # start 是页码，不是偏移量
                body = f"moduleId={module_id}&start={start}&limit=10"
                logger.info("[%s] 请求列表 module=%s page=%d", src["name"], module_id[:8], start)

            resp = self.post(list_url, data=body, headers=headers)
            if not resp:
                logger.warning("[%s] 第 %d 页列表获取失败", src["name"], page + 1)
                break

            try:
                data = json.loads(resp)
            except json.JSONDecodeError:
                logger.warning("[%s] JSON 解析失败", src["name"])
                break

            items = data.get("data", {}).get("list") if isinstance(data.get("data"), dict) else None
            if not items:
                logger.info("[%s] 列表为空，停止翻页", src["name"])
                break

            for item in items:
                aid = item.get("id", "")
                if not aid:
                    continue
                title = item.get("title", "").strip() or aid
                date_str = (item.get("cTime") or "")[:10]
                article_ids.append((aid, title, date_str))

            logger.info("[%s] 第 %d 页获取 %d 条，累计 %d 条",
                        src["name"], page + 1, len(items), len(article_ids))

            if len(article_ids) >= max_count:
                break
            time.sleep(REQUEST_DELAY_POLICY)

        logger.info("[%s] 共 %d 条文章待获取", src["name"], len(article_ids))
        logger.info("[%s] 开始获取 %d 篇文章详情", src["name"], min(len(article_ids), max_count))
        for idx, (aid, title, date_str) in enumerate(article_ids[:max_count], 1):
            url = f"{article_base.rstrip('/')}/{aid}"
            logger.info("[%s] 获取文章 (%d/%d): %s", src["name"], idx, min(len(article_ids), max_count), url)

            html = self.fetch(url)
            if not html:
                logger.warning("[%s] ✗ 文章页获取失败: %s", src["name"], url)
                continue

            text = trafilatura.extract(html, include_comments=False, include_tables=True)
            if not text or len(text.strip()) < 200:
                logger.info("[%s] ✗ 跳过（内容不足）: %s", src["name"], url)
                continue

            logger.info("正文预览 (%s): %s...", url, text.strip()[:200].replace("\n", " "))

            soup = BeautifulSoup(html, "lxml")
            page_title_tag = soup.find("h1") or soup.find("h2") or soup.find("title")
            page_title = page_title_tag.get_text(strip=True) if page_title_tag else ""
            final_title = page_title or title

            page_date = self._extract_date(soup)
            final_date = page_date or date_str or None

            record = {
                "url": url,
                "title": final_title,
                "full_text": text.strip(),
                "published_at": final_date,
                "source_type": self.source_type,
                "language": src["language"],
                "jurisdiction": src["jurisdiction"],
                "policy_type": self._classify_policy(final_title, text),
                "source_name": src["name"],
            }
            records.append(record)
            logger.info("[%s] ✓ 成功: %s (%d chars)", src["name"], final_title[:60], len(text))

            time.sleep(REQUEST_DELAY_POLICY)

        logger.info("[%s] 完成: 共 %d 条记录", src["name"], len(records))
        return records

    # ── handler: aus_pdf ─────────────────────────────────────────────

    def _crawl_aus_pdf(self, src: dict[str, Any], max_count: int) -> list[dict[str, Any]]:
        """Stream-download large PDF, extract text with pypdf.

        Uses httpx streaming + temp file to avoid loading entire PDF into memory.
        """
        records: list[dict[str, Any]] = []
        url = src["url"]
        doc_title = src.get("doc_title", src["name"])

        logger.info("[%s] 开始下载 PDF: %s", src["name"], url)
        tmp_path: str | None = None
        try:
            with httpx.Client(timeout=REQUEST_TIMEOUT_PDF, follow_redirects=True) as client:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()

                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp_path = tmp.name
                        downloaded = 0
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            tmp.write(chunk)
                            downloaded += len(chunk)

                    logger.info("[%s] PDF 下载完成: %d bytes", src["name"], downloaded)

            # Extract text with pypdf
            text_parts: list[str] = []
            reader = pypdf.PdfReader(tmp_path)
            total_pages = len(reader.pages)
            logger.info("[%s] PDF 共 %d 页", src["name"], total_pages)

            for i, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text.strip():
                    text_parts.append(page_text.strip())
                if (i + 1) % 50 == 0:
                    logger.info("[%s] 已提取 %d/%d 页", src["name"], i + 1, total_pages)

            full_text = "\n\n".join(text_parts)
            if len(full_text) < 200:
                logger.info("[%s] ✗ 跳过（内容不足）: %s", src["name"], url)
                return records

            logger.info("[%s] PDF 文本提取完成: %d chars", src["name"], len(full_text))

            record = {
                "url": url,
                "title": doc_title,
                "full_text": full_text,
                "published_at": None,
                "source_type": self.source_type,
                "language": src["language"],
                "jurisdiction": src["jurisdiction"],
                "policy_type": self._classify_policy(doc_title, full_text),
                "source_name": src["name"],
            }
            records.append(record)
            logger.info("[%s] ✓ 成功: %s (%d chars)", src["name"], doc_title[:60], len(full_text))

        except Exception as e:
            logger.warning("[%s] PDF 处理失败: %s — %s", src["name"], url, e)
            self.log_error(url, str(e))
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        return records

    # ── handler: aus_req ──────────────────────────────────────────────

    def _crawl_aus_req(self, src: dict[str, Any], max_count: int) -> list[dict[str, Any]]:
        """Resources and Energy Quarterly — listing page → edition pages → PDFs."""
        records: list[dict[str, Any]] = []
        url = src["url"]

        html = self.fetch(url)
        if not html:
            return records

        soup = BeautifulSoup(html, "lxml")

        # Find links to individual REQ edition pages
        edition_links: list[tuple[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if "resources-and-energy-quarterly" in href and href != url:
                if not href.startswith("http"):
                    href = "https://www.industry.gov.au" + href
                edition_links.append((href, text or href))

        # Deduplicate
        seen: set[str] = set()
        unique_links = [(u, t) for u, t in edition_links if not (u in seen or seen.add(u))]

        logger.info("[%s] 发现 %d 个版本链接", src["name"], len(unique_links))

        for edition_url, title in unique_links[:max_count]:
            logger.info("[%s] 获取版本页: %s", src["name"], edition_url)

            edition_html = self.fetch(edition_url)
            if not edition_html:
                continue

            edition_soup = BeautifulSoup(edition_html, "lxml")

            # Find first PDF download link
            pdf_url = None
            for a in edition_soup.find_all("a", href=True):
                href = a["href"]
                if ".pdf" in href.lower():
                    pdf_url = href if href.startswith("http") else "https://www.industry.gov.au" + href
                    break

            if not pdf_url:
                logger.info("[%s] ✗ 未找到 PDF: %s", src["name"], edition_url)
                continue

            logger.info("[%s] 发现 PDF: %s", src["name"], pdf_url)

            # Reuse aus_pdf handler with edition-level src
            pdf_src: dict[str, Any] = {
                "url": pdf_url,
                "name": src["name"],
                "language": src["language"],
                "jurisdiction": src["jurisdiction"],
                "doc_title": title or "Resources and Energy Quarterly",
            }
            pdf_records = self._crawl_aus_pdf(pdf_src, max_count)
            records.extend(pdf_records)

            time.sleep(REQUEST_DELAY_POLICY)

        return records

    # ── handler: aus_policy ───────────────────────────────────────────

    def _crawl_aus_policy(self, src: dict[str, Any], max_count: int) -> list[dict[str, Any]]:
        """Generic Australian policy website — fetch, extract text, return record."""
        records: list[dict[str, Any]] = []
        url = src["url"]

        html = self.fetch(url)
        if not html:
            return records

        text = trafilatura.extract(html, include_comments=False, include_tables=True)
        if not text or len(text.strip()) < 200:
            logger.info("[%s] ✗ 跳过（内容不足）: %s", src["name"], url)
            return records

        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else src["name"]

        record = {
            "url": url,
            "title": title,
            "full_text": text.strip(),
            "published_at": None,
            "source_type": self.source_type,
            "language": src["language"],
            "jurisdiction": src["jurisdiction"],
            "policy_type": self._classify_policy(title, text),
            "source_name": src["name"],
        }
        records.append(record)
        logger.info("[%s] ✓ 成功: %s (%d chars)", src["name"], title[:60], len(text))

        return records

    # ── 通用工具 ────────────────────────────────────────────────────

    def _extract_date(self, soup: BeautifulSoup) -> str | None:
        for attrs in [
            {"property": "article:published_time"},
            {"name": "dc.date"},
            {"name": "DC.date"},
            {"name": "date"},
            {"property": "article:modified_time"},
        ]:
            meta = soup.find("meta", attrs={**attrs, "content": True})
            if meta:
                m = re.search(r"\d{4}-\d{2}-\d{2}", meta["content"])
                if m:
                    return m.group()
        time_tag = soup.find("time", datetime=True) or soup.find("time")
        if time_tag:
            dt = time_tag.get("datetime") or time_tag.get_text(strip=True)
            if dt:
                m = re.search(r"\d{4}-\d{2}-\d{2}", dt)
                if m:
                    return m.group()
        text = soup.get_text()
        for pat in [r"\d{4}-\d{2}-\d{2}", r"\d{4}/\d{2}/\d{2}",
                     r"\d{4}年\d{1,2}月\d{1,2}日", r"\d{4}\.\d{2}\.\d{2}"]:
            m = re.search(pat, text)
            if m:
                return m.group()
        return None

    def _classify_policy(self, title: str, text: str) -> str:
        t = (title + " " + text[:500]).lower()
        if any(kw in t for kw in ["strategy", "战略", "策略"]):
            return "strategy"
        if any(kw in t for kw in ["regulation", "规则", "管制"]):
            return "regulation"
        if any(kw in t for kw in ["law", "法案", "法律"]):
            return "law"
        if any(kw in t for kw in ["通知", "announcement"]):
            return "announcement"
        return "report"


def main():
    """单独测试政策爬虫。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    import sys
    sources = list(POLICY_SOURCES.keys())
    target = None
    count = 3
    show_full = False
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--count" and i + 1 < len(args):
            count = int(args[i + 1])
            i += 1
        elif args[i] == "--full":
            show_full = True
        elif args[i] == "--source" and i + 1 < len(args):
            target = args[i + 1]
            i += 1
        elif args[i] == "--list":
            print("可用政策源:")
            for k, v in POLICY_SOURCES.items():
                print(f"  {k}: {v['name']} ({v['url']})")
            return
        i += 1

    crawler = PolicyCrawler()
    if target:
        if target not in POLICY_SOURCES:
            print(f"未知源: {target}，可用: {', '.join(sources)}")
            return
        src = POLICY_SOURCES[target]
        logger.info("测试单源: %s (%s)", target, src["url"])
        records = crawler._crawl_source(src, count)
    else:
        records = crawler.crawl(max_count=count)

    print(f"\n{'='*60}")
    print(f"抓取完成: {len(records)} 条记录")
    print(f"{'='*60}\n")

    for idx, r in enumerate(records, 1):
        title = r.get("title", "").strip() or "(NO TITLE)"
        print(f"[{idx}] {title}")
        print(f"    URL: {r.get('url', '')}")
        print(f"    Type: {r.get('policy_type', 'N/A')}, Lang: {r.get('language', 'N/A')}, Jurisdiction: {r.get('jurisdiction', 'N/A')}")
        pub = r.get("published_at") or "N/A"
        print(f"    Published: {pub}")
        print(f"    Length: {len(r.get('full_text', ''))} chars")
        print(f"    full_text: {r.get('full_text', '')} chars")
        if show_full:
            print(f"    {'─'*40}")
            text = r.get('full_text', '')[:1500]
            print(f"    {text}")
            if len(r.get('full_text', '')) > 1500:
                print(f"    ... (truncated, total {len(r.get('full_text', ''))} chars)")
            print(f"    {'─'*40}")
        print()


if __name__ == "__main__":
    main()
