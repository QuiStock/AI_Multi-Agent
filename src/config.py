import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FAQ_DATA_DIR = Path(os.getenv("FAQ_DATA_DIR", str(PROJECT_ROOT / "src" / "data")))
FAQ_DOCS_DIR = Path(os.getenv("FAQ_DOCS_DIR", str(FAQ_DATA_DIR / "docs")))
FAQ_VECTORSTORE_DIR = Path(
    os.getenv("FAQ_VECTORSTORE_DIR", str(FAQ_DATA_DIR / "vectorstore"))
)
FAQ_METADATA_FILE = Path(
    os.getenv("FAQ_METADATA_FILE", str(FAQ_DATA_DIR / "metadata.json"))
)

FAQ_CHUNK_SIZE = int(os.getenv("FAQ_CHUNK_SIZE", "1000"))
FAQ_CHUNK_OVERLAP = int(os.getenv("FAQ_CHUNK_OVERLAP", "200"))
FAQ_RETRIEVAL_K = int(os.getenv("FAQ_RETRIEVAL_K", "4"))
FAQ_RETRIEVAL_MIN_RELEVANCE = float(os.getenv("FAQ_RETRIEVAL_MIN_RELEVANCE", "0.30"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_EMBEDDING_MODEL = os.getenv(
    "GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001"
)
