from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
PROCESSED_DIR = OUTPUT_DIR / "processed"
FAILED_DIR = OUTPUT_DIR / "failed"
STAGING_DIR = OUTPUT_DIR / "_staging"
PRODUCTS_DIR = OUTPUT_DIR / "products"

TEMPLATE_DIR = BASE_DIR / "templates"
TEMPLATE_PATH = TEMPLATE_DIR / "upload_template.xlsx"

LOG_FILE = OUTPUT_DIR / "termsheet_uploader.log"

DIRECTORIES = (
    INPUT_DIR,
    OUTPUT_DIR,
    PROCESSED_DIR,
    FAILED_DIR,
    STAGING_DIR,
    PRODUCTS_DIR,
    TEMPLATE_DIR,
)


def ensure_directories() -> None:
    for directory in DIRECTORIES:
        directory.mkdir(parents=True, exist_ok=True)
