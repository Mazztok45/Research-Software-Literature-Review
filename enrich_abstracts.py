"""
Download supplementary_title_screening.xlsx (file 20965) from KDrive folder 20645,
read the first 128 rows of the 'All Records' sheet, fetch full abstracts via DOI
(Semantic Scholar with CrossRef fallback), add an 'abstract_full' column, and
upload the enriched file back to the same folder.

Usage:
    INFOMANIAK_TOKEN=<token> python enrich_abstracts.py
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from infomaniak import FOLDER_ID, download_file, upload_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

FILE_ID    = "20965"
SHEET      = "All Records"
LOCAL_PATH = Path("supplementary_title_screening.xlsx")
OUTPUT_PATH = Path("supplementary_title_screening_with_abstracts.xlsx")
N_ROWS     = 128

SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
CR_BASE = "https://api.crossref.org/works"


def _strip_jats(text: str) -> str:
    """Remove JATS XML tags sometimes returned by CrossRef."""
    return re.sub(r"<[^>]+>", "", text).strip()


def fetch_abstract_semantic_scholar(doi: str, session: requests.Session) -> str:
    try:
        r = session.get(
            f"{SS_BASE}/DOI:{doi}",
            params={"fields": "abstract"},
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("abstract") or ""
    except Exception as e:
        logger.debug("Semantic Scholar error for %s: %s", doi, e)
    return ""


def fetch_abstract_crossref(doi: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{CR_BASE}/{doi}", timeout=15)
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("abstract") or ""
            return _strip_jats(raw)
    except Exception as e:
        logger.debug("CrossRef error for %s: %s", doi, e)
    return ""


def fetch_abstract(doi: str, session: requests.Session) -> str:
    if not doi or str(doi).strip().lower() in ("", "nan", "none"):
        return ""
    doi = str(doi).strip()
    abstract = fetch_abstract_semantic_scholar(doi, session)
    if not abstract:
        abstract = fetch_abstract_crossref(doi, session)
    return abstract


def main() -> None:
    # 1. Download
    logger.info("Downloading file %s (%s) from KDrive...", FILE_ID, LOCAL_PATH.name)
    if not download_file(FILE_ID, str(LOCAL_PATH)):
        logger.error("Download failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)

    # 2. Read first 128 rows from 'All Records'
    logger.info("Reading first %d rows from sheet '%s'...", N_ROWS, SHEET)
    df = pd.read_excel(LOCAL_PATH, sheet_name=SHEET, nrows=N_ROWS)
    logger.info("Shape: %s  |  Columns: %s", df.shape, list(df.columns))

    # 3. Fetch abstracts
    session = requests.Session()
    session.headers.update({"User-Agent": "research-software-literature-review/1.0"})

    abstracts: list[str] = []
    total = len(df)
    for i, doi in enumerate(df["doi"], start=1):
        abstract = fetch_abstract(doi, session)
        abstracts.append(abstract)
        status = "found" if abstract else "missing"
        logger.info("[%d/%d] %s  →  %s", i, total, doi, status)
        time.sleep(0.5)

    df["abstract_full"] = abstracts
    found = sum(1 for a in abstracts if a)
    logger.info("Abstracts found: %d/%d", found, total)

    # 4. Save enriched file (xlsx, same sheet name)
    df.to_excel(OUTPUT_PATH, sheet_name=SHEET, index=False)
    logger.info("Saved: %s", OUTPUT_PATH)

    # 5. Upload
    logger.info("Uploading %s to KDrive folder %s...", OUTPUT_PATH.name, FOLDER_ID)
    if upload_file(str(OUTPUT_PATH), FOLDER_ID):
        logger.info("Upload complete.")
    else:
        logger.error("Upload failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
