import os
from pathlib import Path

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent

DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
CLEAN_DIR = DATA_DIR / "clean"
CHROMA_DIR = str(BASE_DIR / "chroma_data")
ERROR_LOG = str(DATA_DIR / "errors.jsonl")
CHECKPOINT = str(DATA_DIR / "checkpoint.json")

EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"  # small, free, supports CN+EN
CHROMA_COLLECTION = "mining_aggregator"
CHROMA_BATCH_SIZE = 100

REQUEST_TIMEOUT = 30
REQUEST_TIMEOUT_PDF = 300  # 5 min for large PDF downloads
REQUEST_DELAY_NEWS = 2.0
REQUEST_DELAY_POLICY = 3.0
REQUEST_DELAY_PRICE = 1.5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
]

MAX_ENTRIES_PER_SOURCE = 200
DAYS_BACK = 30

# Sources
NEWS_RSS_URLS = [
    "https://www.mining.com/feed/",
    "https://www.mining-journal.com/feed/rss/",
    "https://im-mining.com/feed/",
    "https://www.theassay.com/feed/",
    "https://www.canadianminingjournal.com/feed/",
    "https://www.e-mj.com/rss/",
    "https://www.energyconnects.com/rss/",
]

# Fallback: max entries to fetch per RSS feed
MAX_NEWS_PER_FEED = 30

POLICY_SOURCES = {
    "ac_rei": {
        "name": "中国稀土学会",
        "url": "https://www.ac-rei.org.cn",
        "language": "zh",
        "jurisdiction": "CN",
        "handler": "ac_rei",
        "list_url": "https://www.ac-rei.org.cn/module/list.json",
        "article_base": "https://www.ac-rei.org.cn/article/",
        "module_ids": [
            "6625868c-80c5-4a2f-8cd4-279107a377ca",
            "a5fb265f-1d88-4ce7-8b57-d288d7e84f9f",
        ],
    },
    "aus_critical_minerals": {
        "name": "Australia Critical Minerals Strategy 2023-2030",
        "url": "https://www.industry.gov.au/sites/default/files/2023-06/critical-minerals-strategy-2023-2030.pdf",
        "language": "en",
        "jurisdiction": "AU",
        "handler": "aus_pdf",
        "doc_title": "Australia's Critical Minerals Strategy 2023-2030",
    },
    "aus_req": {
        "name": "Resources and Energy Quarterly 2025",
        "url": "https://www.industry.gov.au/publications/resources-and-energy-quarterly",
        "language": "en",
        "jurisdiction": "AU",
        "handler": "aus_req",
    },
    "aus_aimr": {
        "name": "Australia's Identified Mineral Resources 2025",
        "url": "https://www.ga.gov.au/aimr2025",
        "language": "en",
        "jurisdiction": "AU",
        "handler": "aus_policy",
    },
    "aus_industry": {
        "name": "Australian Government - Resources",
        "url": "https://www.industry.gov.au/resources-and-energy",
        "language": "en",
        "jurisdiction": "AU",
        "handler": "aus_policy",
    },
}

PRICE_SOURCES = {
    "copper": {
        "commodity": "copper", "exchange": "SHFE", "unit": "CNY/t",
        "sina_symbol": "CAD", "is_inner": False,
        "url": "https://finance.sina.com.cn/futures/quotes/CAD.shtml",
    },
    "zinc": {
        "commodity": "zinc", "exchange": "SHFE", "unit": "CNY/t",
        "sina_symbol": "ZSD", "is_inner": False,
        "url": "https://finance.sina.com.cn/futures/quotes/ZSD.shtml",
    },
    "nickel": {
        "commodity": "nickel", "exchange": "DCE", "unit": "CNY/t",
        "sina_symbol": "NID", "is_inner": False,
        "url": "https://finance.sina.com.cn/futures/quotes/NID.shtml",
    },
    "lithium": {
        "commodity": "lithium", "exchange": "GFEX", "unit": "CNY/t",
        "sina_symbol": "LC0", "is_inner": True,
        "url": "https://finance.sina.com.cn/futures/quotes/gfex/LC0.shtml",
    },
    "iron_ore": {
        "commodity": "iron_ore", "exchange": "DCE", "unit": "CNY/t",
        "sina_symbol": "I0", "is_inner": True,
        "url": "https://finance.sina.com.cn/futures/quotes/I0.shtml",
    },
}
