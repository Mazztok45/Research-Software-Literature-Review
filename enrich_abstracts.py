"""
Download file 20659 from KDrive folder 20645, read the first 128 data rows,
fetch abstracts via DOI (Semantic Scholar with CrossRef fallback), add an
'abstract' column, and upload the enriched file back to the same folder.

Usage:
    INFOMANIAK_TOKEN=<token> python enrich_abstracts.py
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from infomaniak import FOLDER_ID, download_file, upload_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

FILE_ID       = "20659"
LOCAL_PATH    = Path("file_20659_raw.csv")
OUTPUT_PATH   = Path("file_20659_with_abstracts.csv")
N_ROWS        = 128

SS_BASE  = "https://api.semanticscholar.org/graph/v1/paper"
CR_BASE  = "https://api.crossref.org/works"


def _doi_column(df: pd.DataFrame) -> str:
    """Return the name of the DOI column (case-insensitive)."""
    for col in df.columns:
        if col.strip().lower() == "doi":
            return col
    raise ValueError(f"No 'doi' column found. Columns: {list(df.columns)}")


def fetch_abstract_semantic_scholar(doi: str, session: requests.Session) -> str:
    """Try Semantic Scholar first; returns abstract string or empty string."""
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
    """CrossRef fallback; returns abstract string or empty string."""
    try:
        r = session.get(f"{CR_BASE}/{doi}", timeout=15)
        if r.status_code == 200:
            msg = r.json().get("message", {})
            return msg.get("abstract") or ""
    except Exception as e:
        logger.debug("CrossRef error for %s: %s", doi, e)
    return ""


def fetch_abstract(doi: str, session: requests.Session) -> str:
    if not doi or str(doi).strip().lower() in ("", "nan", "none", "no doi"):
        return ""
    doi = str(doi).strip()
    abstract = fetch_abstract_semantic_scholar(doi, session)
    if not abstract:
        abstract = fetch_abstract_crossref(doi, session)
    return abstract


def main() -> None:
    # 1. Download
    logger.info("Downloading file %s from KDrive...", FILE_ID)
    if not download_file(FILE_ID, str(LOCAL_PATH)):
        logger.error("Download failed — check INFOMANIAK_TOKEN and file ID.")
        sys.exit(1)

    # 2. Read first 128 rows
    logger.info("Reading first %d rows from %s", N_ROWS, LOCAL_PATH)
    df = pd.read_csv(LOCAL_PATH, nrows=N_ROWS)
    logger.info("Shape: %s  |  Columns: %s", df.shape, list(df.columns))

    doi_col = _doi_column(df)
    logger.info("DOI column: '%s'", doi_col)

    # 3. Fetch abstracts
    session = requests.Session()
    session.headers.update({"User-Agent": "research-software-literature-review/1.0"})

    abstracts: list[str] = []
    total = len(df)
    for i, doi in enumerate(df[doi_col], start=1):
        abstract = fetch_abstract(doi, session)
        abstracts.append(abstract)
        status = "found" if abstract else "missing"
        logger.info("[%d/%d] DOI=%s  →  %s", i, total, doi, status)
        time.sleep(0.5)   # stay well within Semantic Scholar's 1 req/s limit

    df["abstract"] = abstracts
    found = sum(1 for a in abstracts if a)
    logger.info("Abstracts found: %d/%d", found, total)

    # 4. Save enriched file
    df.to_csv(OUTPUT_PATH, index=False)
    logger.info("Saved enriched file: %s", OUTPUT_PATH)

    # 5. Upload
    logger.info("Uploading %s to KDrive folder %s...", OUTPUT_PATH, FOLDER_ID)
    if upload_file(str(OUTPUT_PATH), FOLDER_ID):
        logger.info("Upload complete.")
    else:
        logger.error("Upload failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
