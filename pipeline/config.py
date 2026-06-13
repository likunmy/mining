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
]

POLICY_SOURCES = {
    "china_ree": {
        "name": "中国稀土集团",
        "url": "https://www.creg.com.cn/",
        "language": "zh",
        "jurisdiction": "CN",
    },
    "australia_disr": {
        "name": "Australian DISR",
        "url": "https://www.industry.gov.au/resources-and-programs/critical-minerals-and-resources",
        "language": "en",
        "jurisdiction": "AU",
    },
}

PRICE_SOURCES = {
    "lme_copper": {"url": "https://www.lme.com/en/metals/non-ferrous/copper", "commodity": "copper", "exchange": "LME"},
    "lme_zinc": {"url": "https://www.lme.com/en/metals/non-ferrous/zinc", "commodity": "zinc", "exchange": "LME"},
    "lme_nickel": {"url": "https://www.lme.com/en/metals/non-ferrous/nickel", "commodity": "nickel", "exchange": "LME"},
    "shfe_lithium": {"url": "https://www.shfe.com.cn/en/products/Lithium/", "commodity": "lithium", "exchange": "SHFE"},
    "dce_iron_ore": {"url": "https://www.dce.com.cn/en/products/iron-ore/", "commodity": "iron_ore", "exchange": "DCE"},
}
