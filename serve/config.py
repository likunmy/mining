from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CHROMA_DIR = str(BASE_DIR / "chroma_data")
CHROMA_COLLECTION = "mining_aggregator"
EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
