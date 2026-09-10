"""
Download supplementary_title_screening.xlsx (file 20965) from KDrive folder 20645,
fetch full abstracts for ALL rows, add 'abstract_full' and 'abstract_source'
columns, and upload the enriched file back to the same folder.

Lookup order per row:
  1.  DOI column → Semantic Scholar
  2.  DOI column → CrossRef
  3.  DOI column → Zenodo API (10.5281/zenodo.* DOIs)
  4.  DOI column → OpenAlex
  5.  DOI extracted from URL → Semantic Scholar
  6.  DOI extracted from URL → CrossRef
  7.  DOI extracted from URL → Zenodo API
  8.  DOI extracted from URL → OpenAlex
  9.  Zenodo record ID extracted from URL → Zenodo API
 10.  HAL identifier extracted from URL → HAL API
 11.  Semantic Scholar CorpusID extracted from URL → SS API
 12.  EPrints URL → OAI-PMH
 13.  Title search → Semantic Scholar
 14.  Title search → OpenAlex
 15.  Fallback to abstract_snippet

Already-enriched rows (from a previous partial run) are reused — only rows
with an empty abstract_full are fetched anew.

Usage:
    INFOMANIAK_TOKEN=<token> python enrich_abstracts.py
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlencode

import pandas as pd
import requests

from infomaniak import FOLDER_ID, download_file, upload_file_overwrite

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

FILE_ID      = "20965"
SHEET        = "All Records"
LOCAL_PATH   = Path("supplementary_title_screening.xlsx")
OUTPUT_PATH  = Path("supplementary_title_screening_with_abstracts.xlsx")

SS_BASE      = "https://api.semanticscholar.org/graph/v1/paper"
SS_SEARCH    = "https://api.semanticscholar.org/graph/v1/paper/search"
CR_BASE      = "https://api.crossref.org/works"
ZENODO_BASE  = "https://zenodo.org/api/records"
HAL_BASE     = "https://api.archives-ouvertes.fr/search"
OA_BASE      = "https://api.openalex.org/works"
FIGSHARE_BASE = "https://api.figshare.com/v2"

_DOI_RE      = re.compile(r"10\.\d{4,9}/\S+")
_ZENODO_RE   = re.compile(r"zenodo\.org/(?:record|records)/(\d+)", re.IGNORECASE)
_HAL_RE      = re.compile(r"(hal-\d+|hal\.\d+)", re.IGNORECASE)
_SS_CORPUS_RE = re.compile(r"semanticscholar\.org/CorpusID:(\d+)", re.IGNORECASE)
_EPRINTS_RE  = re.compile(r"(https?://[^/]*eprints[^/]*/\d+/?)", re.IGNORECASE)
_FIGSHARE_RE = re.compile(r"figshare\.com/(?:articles/[^/]+/[^/]+/|articles/)(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_jats(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _clean_doi(raw) -> str:
    if not raw or str(raw).strip().lower() in ("", "nan", "none"):
        return ""
    doi = re.sub(r"^doi:\s*", "", str(raw).strip(), flags=re.IGNORECASE).strip()
    return doi if _DOI_RE.match(doi) else ""


def _extract_doi_from_url(url) -> str:
    if not url or str(url).strip().lower() in ("", "nan", "none"):
        return ""
    m = _DOI_RE.search(str(url))
    return m.group(0).rstrip(".,;)") if m else ""


# ---------------------------------------------------------------------------
# Semantic Scholar
# ---------------------------------------------------------------------------

def _ss_request(url: str, params: dict, session: requests.Session) -> dict | None:
    for wait in (0, 5, 15):
        if wait:
            time.sleep(wait)
        try:
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code != 429:
                return None
        except Exception as e:
            logger.debug("SS request error: %s", e)
            return None
    return None


def _ss_by_doi(doi: str, session: requests.Session) -> str:
    data = _ss_request(f"{SS_BASE}/DOI:{doi}", {"fields": "abstract"}, session)
    return (data or {}).get("abstract") or ""


def _ss_by_corpus_id(corpus_id: str, session: requests.Session) -> str:
    data = _ss_request(f"{SS_BASE}/CorpusID:{corpus_id}", {"fields": "abstract"}, session)
    return (data or {}).get("abstract") or ""


def _ss_by_title(title, session: requests.Session) -> str:
    if not title or str(title).strip().lower() in ("", "nan", "none"):
        return ""
    data = _ss_request(SS_SEARCH,
                       {"query": str(title).strip(), "fields": "abstract", "limit": 1},
                       session)
    items = (data or {}).get("data", [])
    return (items[0].get("abstract") or "") if items else ""


# ---------------------------------------------------------------------------
# CrossRef
# ---------------------------------------------------------------------------

def _crossref_by_doi(doi: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{CR_BASE}/{doi}", timeout=15)
        if r.status_code == 200:
            raw = r.json().get("message", {}).get("abstract") or ""
            return _strip_jats(raw)
    except Exception as e:
        logger.debug("CrossRef DOI %s: %s", doi, e)
    return ""


# ---------------------------------------------------------------------------
# Zenodo
# ---------------------------------------------------------------------------

def _zenodo_by_record_id(record_id: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{ZENODO_BASE}/{record_id}", timeout=15)
        if r.status_code == 200:
            meta = r.json().get("metadata", {})
            desc = meta.get("description") or meta.get("abstract") or ""
            return _strip_jats(desc)
    except Exception as e:
        logger.debug("Zenodo record %s: %s", record_id, e)
    return ""


def _zenodo_by_doi(doi: str, session: requests.Session) -> str:
    """Query Zenodo for a DOI. For 10.5281/zenodo.<id> DOIs, hits the record directly."""
    # Extract record ID from Zenodo DOI pattern: 10.5281/zenodo.<id>
    m = re.search(r"10\.5281/zenodo\.(\d+)", doi, re.IGNORECASE)
    if m:
        return _zenodo_by_record_id(m.group(1), session)
    # Generic Zenodo DOI search
    try:
        r = session.get(ZENODO_BASE,
                        params={"q": f'doi:"{doi}"', "size": 1},
                        timeout=15)
        if r.status_code == 200:
            hits = r.json().get("hits", {}).get("hits", [])
            if hits:
                meta = hits[0].get("metadata", {})
                desc = meta.get("description") or meta.get("abstract") or ""
                return _strip_jats(desc)
    except Exception as e:
        logger.debug("Zenodo DOI %s: %s", doi, e)
    return ""


def _extract_zenodo_id_from_url(url) -> str:
    if not url or str(url).strip().lower() in ("", "nan", "none"):
        return ""
    m = _ZENODO_RE.search(str(url))
    return m.group(1) if m else ""


# ---------------------------------------------------------------------------
# HAL (archives-ouvertes.fr / hal.science)
# ---------------------------------------------------------------------------

def _extract_hal_id_from_url(url) -> str:
    if not url or str(url).strip().lower() in ("", "nan", "none"):
        return ""
    m = _HAL_RE.search(str(url))
    return m.group(1).lower() if m else ""


def _hal_by_id(hal_id: str, session: requests.Session) -> str:
    """Query HAL search API for a HAL identifier like hal-01234567."""
    try:
        params = {
            "q": f"halId_s:{hal_id}",
            "fl": "abstract_s",
            "rows": 1,
            "wt": "json",
        }
        r = session.get(HAL_BASE, params=params, timeout=15)
        if r.status_code == 200:
            docs = r.json().get("response", {}).get("docs", [])
            if docs:
                abstracts = docs[0].get("abstract_s", [])
                if isinstance(abstracts, list) and abstracts:
                    return abstracts[0]
                if isinstance(abstracts, str):
                    return abstracts
    except Exception as e:
        logger.debug("HAL %s: %s", hal_id, e)
    return ""


# ---------------------------------------------------------------------------
# OpenAlex
# ---------------------------------------------------------------------------

def _openalex_by_doi(doi: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{OA_BASE}/doi:{doi}",
                        params={"select": "abstract_inverted_index"},
                        headers={"User-Agent": "research-software-review/1.0 (mailto:yvpu4ih77@mozmail.com)"},
                        timeout=15)
        if r.status_code == 200:
            inv = r.json().get("abstract_inverted_index") or {}
            return _invert_abstract(inv)
    except Exception as e:
        logger.debug("OpenAlex DOI %s: %s", doi, e)
    return ""


def _openalex_by_title(title, session: requests.Session) -> str:
    if not title or str(title).strip().lower() in ("", "nan", "none"):
        return ""
    try:
        r = session.get(OA_BASE,
                        params={"search": str(title).strip(),
                                "select": "abstract_inverted_index",
                                "per-page": 1},
                        headers={"User-Agent": "research-software-review/1.0 (mailto:yvpu4ih77@mozmail.com)"},
                        timeout=15)
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                inv = results[0].get("abstract_inverted_index") or {}
                return _invert_abstract(inv)
    except Exception as e:
        logger.debug("OpenAlex title: %s", e)
    return ""


def _invert_abstract(inv: dict) -> str:
    """Reconstruct abstract text from OpenAlex inverted index."""
    if not inv:
        return ""
    length = max(pos for positions in inv.values() for pos in positions) + 1
    words = [""] * length
    for word, positions in inv.items():
        for pos in positions:
            words[pos] = word
    return " ".join(w for w in words if w)


# ---------------------------------------------------------------------------
# EPrints OAI-PMH
# ---------------------------------------------------------------------------

def _eprints_by_url(url: str, session: requests.Session) -> str:
    """Extract abstract from an EPrints record via OAI-PMH."""
    m = re.search(r"eprints[^/]*/(\d+)", str(url), re.IGNORECASE)
    if not m:
        return ""
    record_id = m.group(1)
    base = re.match(r"(https?://[^/]+)", str(url))
    if not base:
        return ""
    oai_url = f"{base.group(1)}/cgi/oai2"
    try:
        r = session.get(oai_url,
                        params={"verb": "GetRecord",
                                "identifier": f"oai:{urlparse(url).hostname}:{record_id}",
                                "metadataPrefix": "oai_dc"},
                        timeout=15)
        if r.status_code == 200:
            m2 = re.search(r"<dc:description>(.*?)</dc:description>", r.text, re.DOTALL)
            if m2:
                return _strip_jats(m2.group(1)).strip()
    except Exception as e:
        logger.debug("EPrints OAI %s: %s", url, e)
    return ""


# ---------------------------------------------------------------------------
# FigShare
# ---------------------------------------------------------------------------

def _extract_figshare_id_from_doi(doi: str) -> str:
    """Extract FigShare article ID from DOI like 10.6084/m9.figshare.<id>[.v<n>]."""
    m = re.search(r"10\.6084/m9\.figshare\.(\d+)", doi, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_figshare_id_from_url(url: str) -> str:
    """Extract FigShare article ID from figshare.com URLs."""
    if not url or str(url).strip().lower() in ("", "nan", "none"):
        return ""
    m = _FIGSHARE_RE.search(str(url))
    return m.group(1) if m else ""


def _figshare_by_article_id(article_id: str, session: requests.Session) -> str:
    try:
        r = session.get(f"{FIGSHARE_BASE}/articles/{article_id}", timeout=15)
        if r.status_code == 200:
            desc = r.json().get("description") or ""
            return _strip_jats(desc)
    except Exception as e:
        logger.debug("FigShare article %s: %s", article_id, e)
    return ""


def _figshare_by_doi(doi: str, session: requests.Session) -> str:
    article_id = _extract_figshare_id_from_doi(doi)
    if article_id:
        return _figshare_by_article_id(article_id, session)
    # Generic DOI search via FigShare API
    try:
        r = session.post(f"{FIGSHARE_BASE}/articles/search",
                         json={"doi": doi}, timeout=15)
        if r.status_code == 200:
            hits = r.json()
            if hits:
                return _figshare_by_article_id(str(hits[0]["id"]), session)
    except Exception as e:
        logger.debug("FigShare DOI search %s: %s", doi, e)
    return ""


# ---------------------------------------------------------------------------
# Main fetch logic
# ---------------------------------------------------------------------------

def fetch_abstract(doi, url, title, snippet, session: requests.Session) -> tuple[str, str]:
    """Return (abstract, source_label). Tries every available signal."""
    url_s = str(url).strip() if url else ""
    doi_clean = _clean_doi(doi)

    # 1 & 2 — DOI column → SS then CrossRef
    if doi_clean:
        ab = _ss_by_doi(doi_clean, session)
        if ab:
            return ab, "doi→SS"
        ab = _crossref_by_doi(doi_clean, session)
        if ab:
            return ab, "doi→CrossRef"
        # 3 — Zenodo (handles 10.5281/zenodo.* and others hosted on Zenodo)
        if "zenodo" in doi_clean.lower() or "5281" in doi_clean:
            ab = _zenodo_by_doi(doi_clean, session)
            if ab:
                return ab, "doi→Zenodo"
        # 4 — FigShare (10.6084/m9.figshare.*)
        if "figshare" in doi_clean.lower() or "6084" in doi_clean:
            ab = _figshare_by_doi(doi_clean, session)
            if ab:
                return ab, "doi→FigShare"
        # 5 — OpenAlex by DOI
        ab = _openalex_by_doi(doi_clean, session)
        if ab:
            return ab, "doi→OpenAlex"

    # 6-9 — DOI extracted from URL
    url_doi = _extract_doi_from_url(url_s)
    if url_doi and url_doi != doi_clean:
        ab = _ss_by_doi(url_doi, session)
        if ab:
            return ab, "url-doi→SS"
        ab = _crossref_by_doi(url_doi, session)
        if ab:
            return ab, "url-doi→CrossRef"
        if "zenodo" in url_doi.lower() or "5281" in url_doi:
            ab = _zenodo_by_doi(url_doi, session)
            if ab:
                return ab, "url-doi→Zenodo"
        if "figshare" in url_doi.lower() or "6084" in url_doi:
            ab = _figshare_by_doi(url_doi, session)
            if ab:
                return ab, "url-doi→FigShare"
        ab = _openalex_by_doi(url_doi, session)
        if ab:
            return ab, "url-doi→OpenAlex"

    # 10 — Zenodo record ID from URL (zenodo.org/record/XXXXX)
    zenodo_id = _extract_zenodo_id_from_url(url_s)
    if zenodo_id:
        ab = _zenodo_by_record_id(zenodo_id, session)
        if ab:
            return ab, "url→Zenodo"

    # 11 — HAL identifier from URL
    hal_id = _extract_hal_id_from_url(url_s)
    if hal_id:
        ab = _hal_by_id(hal_id, session)
        if ab:
            return ab, "url→HAL"

    # 12 — Semantic Scholar CorpusID from URL
    m_corpus = _SS_CORPUS_RE.search(url_s)
    if m_corpus:
        ab = _ss_by_corpus_id(m_corpus.group(1), session)
        if ab:
            return ab, "url→SS-CorpusID"

    # 13 — EPrints OAI-PMH
    if "eprints" in url_s.lower():
        ab = _eprints_by_url(url_s, session)
        if ab:
            return ab, "url→EPrints"

    # 14 — FigShare by article ID extracted from URL
    figshare_id = _extract_figshare_id_from_url(url_s)
    if figshare_id:
        ab = _figshare_by_article_id(figshare_id, session)
        if ab:
            return ab, "url→FigShare"

    # 15 — Title search on SS
    ab = _ss_by_title(title, session)
    if ab:
        return ab, "title→SS"

    # 16 — Title search on OpenAlex
    ab = _openalex_by_title(title, session)
    if ab:
        return ab, "title→OpenAlex"

    # 17 — snippet fallback
    if snippet and str(snippet).strip().lower() not in ("", "nan", "none"):
        return str(snippet).strip(), "snippet"

    return "", "none"


def main() -> None:
    # 1. Download original file
    logger.info("Downloading file %s (%s)...", FILE_ID, LOCAL_PATH.name)
    if not download_file(FILE_ID, str(LOCAL_PATH)):
        logger.error("Download failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)

    df = pd.read_excel(LOCAL_PATH, sheet_name=SHEET)
    logger.info("Total rows: %d", len(df))

    # 2. Download latest enriched file from KDrive (so cloud-side progress is reused)
    from infomaniak import kdrive_list_all
    remote_files = kdrive_list_all(FOLDER_ID)
    output_name = OUTPUT_PATH.name
    if output_name in remote_files:
        logger.info("Downloading latest enriched file from KDrive (%s)...", output_name)
        download_file(remote_files[output_name], str(OUTPUT_PATH))
    else:
        logger.info("No enriched file found on KDrive — will start fresh or use local copy.")

    # 3. Reuse already-enriched rows if the output file exists
    df["abstract_full"]   = ""
    df["abstract_source"] = ""
    if OUTPUT_PATH.exists():
        prev = pd.read_excel(OUTPUT_PATH, sheet_name=SHEET)
        for col in ("abstract_full", "abstract_source"):
            if col in prev.columns:
                df.loc[prev.index, col] = prev[col].fillna("").values
        already = (df["abstract_full"].str.strip() != "").sum()
        logger.info("Reusing %d already-enriched rows from %s", already, OUTPUT_PATH.name)

    # 4. Fetch abstracts only for rows still missing one
    session = requests.Session()
    session.headers.update({"User-Agent": "research-software-literature-review/1.0"})

    todo = df[df["abstract_full"].str.strip() == ""]
    logger.info("Rows to fetch: %d", len(todo))

    for i, row in enumerate(todo.itertuples(), start=1):
        ab, src = fetch_abstract(row.doi, row.url, row.title,
                                 row.abstract_snippet, session)
        df.at[row.Index, "abstract_full"]   = ab
        df.at[row.Index, "abstract_source"] = src
        logger.info("[%d/%d] %-26s | %s", i, len(todo), src, str(row.doi)[:60])
        time.sleep(0.5)

    # Summary
    found = (df["abstract_full"].str.strip() != "").sum()
    logger.info("Abstracts found: %d/%d", found, len(df))
    all_sources = (
        "doi→SS", "doi→CrossRef", "doi→Zenodo", "doi→FigShare", "doi→OpenAlex",
        "url-doi→SS", "url-doi→CrossRef", "url-doi→Zenodo", "url-doi→FigShare", "url-doi→OpenAlex",
        "url→Zenodo", "url→HAL", "url→SS-CorpusID", "url→EPrints", "url→FigShare",
        "title→SS", "title→OpenAlex", "snippet", "none",
    )
    for src in all_sources:
        n = (df["abstract_source"] == src).sum()
        if n:
            logger.info("  %-28s %d", src, n)

    # 5. Save and upload
    df.to_excel(OUTPUT_PATH, sheet_name=SHEET, index=False)
    logger.info("Saved: %s", OUTPUT_PATH)

    logger.info("Uploading to KDrive folder %s...", FOLDER_ID)
    if upload_file_overwrite(str(OUTPUT_PATH), FOLDER_ID):
        logger.info("Upload complete.")
    else:
        logger.error("Upload failed — check INFOMANIAK_TOKEN.")
        sys.exit(1)


if __name__ == "__main__":
    main()
