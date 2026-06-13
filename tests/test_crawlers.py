"""测试: 价格爬虫数字提取逻辑。"""

from pipeline.crawlers.price_crawler import PriceCrawler


def test_to_float_simple() -> None:
    assert PriceCrawler._to_float("1234.56") == 1234.56


def test_to_float_with_commas() -> None:
    assert PriceCrawler._to_float("1,234.56") == 1234.56


def test_to_float_none() -> None:
    assert PriceCrawler._to_float(None) is None


def test_to_float_empty() -> None:
    assert PriceCrawler._to_float("") is None


def test_to_float_negative() -> None:
    assert PriceCrawler._to_float("-50.5") == -50.5


def test_content_hash_deterministic() -> None:
    """相同输入应产生相同 content_hash。"""
    from pipeline.crawlers.base import BaseCrawler
    h1 = BaseCrawler.content_hash(None, "Hello World")
    h2 = BaseCrawler.content_hash(None, "Hello World")
    assert h1 == h2
    h3 = BaseCrawler.content_hash(None, "Hello  World")  # extra space
    assert h1 == h3  # 应归一化
