"""
Download supplementary_title_screening.xlsx (file 20965) from KDrive folder 20645,
read the first 128 rows of the 'All Records' sheet, fetch full abstracts via a
four-tier strategy, add an 'abstract_full' column, and upload the enriched file.

Lookup order per row:
  1. DOI column → Semantic Scholar, then CrossRef
  2. DOI extracted from url column → same APIs
  3. Title search on Semantic Scholar
  4. Fallback to abstract_snippet if all else fails

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

from infomaniak import FOLDER_ID, download_file, upload_file_overwrite

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

FILE_ID     = "20965"
SHEET       = "All Records"
LOCAL_PATH  = Path("supplementary_title_screening.xlsx")
OUTPUT_PATH = Path("supplementary_title_screening_with_abstracts.xlsx")
N_ROWS      = 128

SS_BASE = "https://api.semanticscholar.org/graph/v1/paper"
SS_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
CR_BASE = "https://api.crossref.org/works"

_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")


def _strip_jats(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _extract_doi_from_url(url: str) -> str:
    """Pull a bare DOI out of any URL that contains one."""
    if not url or str(url).strip().lower() in ("", "nan", "none"):
        return ""
    m = _DOI_RE.search(str(url))
    return m.group(0).rstrip(".,;)") if m else ""


def _via_doi_ss(doi: str, session: requests.Session) -> str:
    for wait in (0, 5, 15):
        try:
            if wait:
                time.sleep(wait)
            r = session.get(f"{SS_BASE}/DOI:{doi}", params={"fields": "abstract"}, timeout=15)
            if r.status_code == 200:
                return r.json().get("abstract") or ""
            if r.status_code == 429:
                continue
            break
        except Exception as e:
            logger.debug("SS DOI error %s: %s", doi, e)
            break
    return ""


def _via_doi_crossref(doi: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{CR_BASE}/{doi}", timeout=15)
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("abstract") or ""
            return _strip_jats(raw)
    except Exception as e:
        logger.debug("CrossRef error %s: %s", doi, e)
    return ""


def _via_title(title: str, session: requests.Session) -> str:
    if not title or str(title).strip().lower() in ("", "nan", "none"):
        return ""
    for wait in (0, 5, 15):
        try:
            if wait:
                time.sleep(wait)
            r = session.get(
                SS_SEARCH,
                params={"query": str(title).strip(), "fields": "title,abstract", "limit": 1},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    return data[0].get("abstract") or ""
                return ""
            if r.status_code == 429:
                continue
            break
        except Exception as e:
            logger.debug("SS title search error: %s", e)
            break
    return ""


def fetch_abstract(doi, url, title, snippet, session: requests.Session) -> tuple[str, str]:
    """Return (abstract, source_label)."""
    # 1. DOI column
    clean_doi = str(doi).strip() if doi and str(doi).strip().lower() not in ("", "nan", "none") else ""
    if clean_doi:
        # clean up accidental "doi: " prefix
        clean_doi = re.sub(r"^doi:\s*", "", clean_doi, flags=re.IGNORECASE).strip()
        ab = _via_doi_ss(clean_doi, session)
        if ab:
            return ab, "doi→SS"
        ab = _via_doi_crossref(clean_doi, session)
        if ab:
            return ab, "doi→CrossRef"

    # 2. DOI extracted from URL
    url_doi = _extract_doi_from_url(str(url))
    if url_doi and url_doi != clean_doi:
        ab = _via_doi_ss(url_doi, session)
        if ab:
            return ab, "url-doi→SS"
        ab = _via_doi_crossref(url_doi, session)
        if ab:
            return ab, "url-doi→CrossRef"

    # 3. Title search
    ab = _via_title(str(title), session)
    if ab:
        return ab, "title→SS"

    # 4. Snippet fallback
    if snippet and str(snippet).strip().lower() not in ("", "nan", "none"):
        return str(snippet).strip(), "snippet"

    return "", "none"


def main() -> None:
    # 1. Download
    logger.info("Downloading file %s (%s) from KDrive...", FILE_ID, LOCAL_PATH.name)
    if not download_file(FILE_ID, str(LOCAL_PATH)):
        logger.error("Download failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)

    # 2. Read first 128 rows
    logger.info("Reading first %d rows from sheet '%s'...", N_ROWS, SHEET)
    df = pd.read_excel(LOCAL_PATH, sheet_name=SHEET, nrows=N_ROWS)
    logger.info("Shape: %s", df.shape)

    # 3. Fetch abstracts
    session = requests.Session()
    session.headers.update({"User-Agent": "research-software-literature-review/1.0"})

    abstracts, sources = [], []
    total = len(df)
    for i, row in enumerate(df.itertuples(), start=1):
        ab, src = fetch_abstract(row.doi, row.url, row.title, row.abstract_snippet, session)
        abstracts.append(ab)
        sources.append(src)
        logger.info("[%d/%d] %-18s | %s", i, total, src, str(row.doi)[:60])
        time.sleep(0.5)

    df["abstract_full"]   = abstracts
    df["abstract_source"] = sources

    found = sum(1 for a in abstracts if a)
    logger.info("Abstracts found: %d/%d", found, total)
    for src in ("doi→SS", "doi→CrossRef", "url-doi→SS", "url-doi→CrossRef", "title→SS", "snippet", "none"):
        n = sources.count(src)
        if n:
            logger.info("  %-22s %d", src, n)

    # 4. Save
    df.to_excel(OUTPUT_PATH, sheet_name=SHEET, index=False)
    logger.info("Saved: %s", OUTPUT_PATH)

    # 5. Upload
    logger.info("Uploading to KDrive folder %s...", FOLDER_ID)
    if upload_file_overwrite(str(OUTPUT_PATH), FOLDER_ID):
        logger.info("Upload complete.")
    else:
        logger.error("Upload failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
