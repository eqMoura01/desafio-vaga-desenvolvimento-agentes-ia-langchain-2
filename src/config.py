import os
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PACKAGE_ROOT / ".env")

RAW_DIR = PACKAGE_ROOT / "data" / "raw"
OUTPUT_PATH = PACKAGE_ROOT / "data" / "processed" / "documentos.json"
DEFAULT_ZIP = PACKAGE_ROOT.parent / "anexo_desafio_2.zip"


def model_name() -> str:
    return os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def ocr_min_confidence() -> float:
    raw = os.environ.get("OCR_MIN_CONFIDENCE", "0.80").strip() or "0.80"
    return float(raw)
