"""价格数据爬虫 — 新浪财经期货 API 实时获取，无回退生成。"""

import json
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.request import Request, urlopen

from pipeline.config import PRICE_SOURCES, REQUEST_DELAY_PRICE
from pipeline.crawlers.base import BaseCrawler

logger = logging.getLogger(__name__)

SINA_GLOBAL_API = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_t=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={symbol}&_={date}&source=web"
SINA_INNER_API = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_t=/InnerFuturesNewService.getDailyKLine?symbol={symbol}&_={date}"
DAYS_BACK = 30

# 内盘 API 使用短字段名，映射到标准字段名
_INNER_FIELD_MAP = {
    "d": "date", "o": "open", "h": "high",
    "l": "low", "c": "close", "v": "volume",
    "p": "position", "s": "settle",
}


def _normalize_item(item: dict[str, str], is_inner: bool) -> dict[str, str]:
    """将 API 返回的字段名统一为标准名。"""
    if not is_inner:
        return item
    return {_INNER_FIELD_MAP.get(k, k): v for k, v in item.items()}


class PriceCrawler(BaseCrawler):
    source_type = "price"

    def crawl(self, max_count: int = 200) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for key, src in PRICE_SOURCES.items():
            sina_symbol = src.get("sina_symbol")
            if not sina_symbol:
                logger.warning("跳过 %s: 无新浪代码", key)
                continue
            logger.info("获取 %s (%s) 代码=%s", src["commodity"], src["exchange"], sina_symbol)
            try:
                src_records = self._fetch_sina(sina_symbol, src)
                records.extend(src_records)
            except Exception as e:
                self.log_error(src["url"], str(e))
                logger.warning("%s 获取失败: %s", key, e)
            time.sleep(REQUEST_DELAY_PRICE)

        logger.info("价格爬虫: %d 条真实记录", len(records))
        return records

    def _fetch_sina(self, symbol: str, src: dict[str, Any]) -> list[dict[str, Any]]:
        """从新浪 API 获取日 K 线数据，返回最近 DAYS_BACK 条记录。"""
        is_inner = src.get("is_inner", False)
        now = datetime.now()
        date_str = f"{now.year}_{now.month}_{now.day}"
        api_url = SINA_INNER_API if is_inner else SINA_GLOBAL_API
        url = api_url.format(symbol=symbol, date=date_str)
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/futures/",
        })
        resp = urlopen(req, timeout=15).read().decode("utf-8")

        # 解析 JSONP: /*...*/ var _t=([{...}]);
        m = re.search(r"\[.*\]", resp, re.DOTALL)
        if not m:
            logger.warning("新浪 API 返回格式异常: %s", symbol)
            return []
        try:
            raw_data: list[dict[str, str]] = json.loads(m.group())
        except json.JSONDecodeError as e:
            logger.warning("新浪 API JSON 解析失败: %s", e)
            return []

        if not raw_data:
            logger.warning("新浪 API 返回空数据: %s", symbol)
            return []

        # 归一化字段名，按日期降序取最近 DAYS_BACK 条
        data = [_normalize_item(item, is_inner) for item in raw_data]
        data.sort(key=lambda x: x.get("date", ""), reverse=True)
        cutoff = datetime.now() - timedelta(days=DAYS_BACK)

        records = []
        for item in data:
            date_str = item.get("date", "")
            if not date_str:
                continue
            try:
                item_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            if item_date < cutoff:
                break
            records.append(self._make_record(src, item))
            if len(records) >= 200:
                break

        return records

    def _make_record(self, src: dict[str, Any], item: dict[str, str]) -> dict[str, Any]:
        date_str = item.get("date", "")
        close = self._to_float(item.get("close"))
        return {
            "url": src["url"],
            "title": f"{src['exchange']} {src['commodity']} {date_str}",
            "full_text": (
                f"{src['commodity']} {src['exchange']} {date_str} "
                f"O:{item.get('open','')} H:{item.get('high','')} "
                f"L:{item.get('low','')} C:{item.get('close','')} "
                f"V:{item.get('volume','')} {src.get('unit','')}"
            ),
            "published_at": date_str,
            "source_type": self.source_type,
            "language": "zh",
            "commodity": src["commodity"],
            "price_open": self._to_float(item.get("open")),
            "price_high": self._to_float(item.get("high")),
            "price_low": self._to_float(item.get("low")),
            "price_close": close,
            "price_settle": self._to_float(item.get("settle")),
            "volume": self._to_int(item.get("volume")),
            "unit": src.get("unit", "CNY/t"),
            "currency": "CNY",
            "exchange": src["exchange"],
            "date": date_str,
        }

    @staticmethod
    def _to_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return round(float(str(val).replace(",", "")), 2)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_int(val: Any) -> int | None:
        if val is None:
            return None
        try:
            return int(float(str(val).replace(",", "")))
        except (ValueError, TypeError):
            return None


def main():
    """单独测试价格爬虫。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    import sys
    args = sys.argv[1:]
    if "--list" in args:
        print("可用价格源:")
        for k, v in PRICE_SOURCES.items():
            sym = v.get("sina_symbol", "N/A")
            print(f"  {k}: {v['exchange']} {v['commodity']} ({sym})")
        return

    crawler = PriceCrawler()
    if len(args) >= 2 and args[0] == "--source":
        target = args[1]
        if target not in PRICE_SOURCES:
            print(f"未知源: {target}")
            return
        src = PRICE_SOURCES[target]
        logger.info("测试单源: %s (%s)", src["commodity"], src["exchange"])
        records = crawler._fetch_sina(src["sina_symbol"], src)
    else:
        records = crawler.crawl()

    print(f"\n{'='*60}")
    print(f"获取完成: {len(records)} 条记录")
    print(f"{'='*60}\n")

    by_commodity: dict[str, list[dict]] = {}
    for r in records:
        c = r.get("commodity", "unknown")
        by_commodity.setdefault(c, []).append(r)

    for comm, items in sorted(by_commodity.items()):
        prices = [r.get("price_close") or 0 for r in items]
        print(f"{comm.upper()} ({items[0].get('exchange','')}) — {len(items)} 条记录")
        print(f"    最新: {prices[0]:.2f} {items[0].get('unit','')}")
        print(f"    区间: {min(prices):.2f} — {max(prices):.2f}")
        for r in items[:3]:
            print(f"    {r.get('date')}: O={r.get('price_open')} H={r.get('price_high')} "
                  f"L={r.get('price_low')} C={r.get('price_close')} V={r.get('volume')}")
        print()

    if not records:
        print("未获取到数据\n")


if __name__ == "__main__":
    main()
