"""
OpenAlex API Literature Search Tool
======================================
Executes pre-defined query blocks against the OpenAlex Works API,
deduplicates results, and exports a screening spreadsheet.

Usage:
    python openalex_search.py

Requirements:
    pip install requests pandas openpyxl

API key (free):
    Register at https://openalex.org/settings/api
    Then set the key below or via:  export OPENALEX_API_KEY="your_key"

OpenAlex API docs:
    https://docs.openalex.org/

⚠️  ABSTRACT COVERAGE WARNING
    OpenAlex pulls metadata primarily from Crossref and MAG. ACM (like IEEE)
    does not openly share abstracts via Crossref, so a significant share of
    ACM records in OpenAlex will have an empty abstract field.
    Plan for additional manual abstract retrieval for those records before
    the title+abstract screening stage.
"""

import os
import time
import json
import requests
import pandas as pd
from datetime import datetime
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
API_KEY           = os.environ.get("OPENALEX_API_KEY", "YOUR_KEY_HERE")
# OpenAlex asks you to identify yourself even without a key (polite pool).
# With a key you get higher rate limits. Always set this.
EMAIL             = os.environ.get("OPENALEX_EMAIL", "your@email.com")   # fallback polite pool
BASE_URL          = "https://api.openalex.org/works"
YEAR_FILTER_START = 2014           # equivalent to PUBYEAR > 2013
MAX_RESULTS_PER_QUERY = 2000        # set higher if needed; OpenAlex page size max is 200
RESULTS_PER_PAGE  = 25            # keep low to stay within per-request limits
OUTPUT_DIR        = "openalex_results"
RATE_LIMIT_DELAY  = 0.12          # OpenAlex allows ~10 req/sec with a key; be conservative

# ─── QUERY BLOCKS ─────────────────────────────────────────────────────────────
# STRATEGY: Use OpenAlex filter-based field-scoped search rather than the
# global `search=` parameter (which searches full text and inflates counts).
#
# Each query is a dict with two keys:
#   "title_abs"  – passed as filter=title_and_abstract.search:<value>
#                  (searches title + abstract only, equivalent to Scopus TITLE-ABS-KEY)
#   "extra_filter" – optional additional filter string appended with comma
#                    e.g. to pin a specific concept or publisher
#
# OpenAlex title_and_abstract.search supports:
#   Phrase search : "double quotes"
#   Boolean       : AND  OR  (no NOT — prefix term with minus: -term)
#   No wildcards  : spell out variants explicitly
#
# Target result counts for a rigorous but manageable SLR:
#   Core queries   (Q1–Q5): ideally < 500 total each, retrieve all
#   Support queries (Q6–Q8): ideally < 300 total each, retrieve all
# If a query still returns > 1 000 after tightening, consider splitting it or
# adding a concept filter (see extra_filter examples below).

QUERIES = {
    # ── Core literature (Q1–Q5) ──────────────────────────────────────────────

    # Q1: Papers specifically about recommending / discovering research software.
    # Tight: requires a research/scientific/academic software term AND a
    # recommender-system or discoverability term — both in title or abstract.
    "Q1_core_software_recsys": {
        "title_abs": (
            '("research software" OR "scientific software" OR "academic software")'
            ' AND ("recommender" OR "recommendation system" OR "discoverability"'
            ' OR "software discovery" OR "suggestion system")'
        ),
    },

    # Q2: Software repositories / registries in a scholarly context with
    # findability / recommendation angle.
    # Removed the bare word "discovery" and "research" which were too generic.
    "Q2_repository_context": {
        "title_abs": (
            '("software repository" OR "software registry" OR "software catalog"'
            ' OR "software portal") AND ("recommend" OR "findability"'
            ' OR "discoverability" OR "similar software") AND'
            ' ("scholarly" OR "scientific" OR "research infrastructure")'
        ),
    },

    # Q3: Metadata standards for research software + FAIR / findability.
    # CodeMeta and Bioschemas are specific enough; FAIR anchor prevents noise.
    "Q3_metadata_standards": {
        "title_abs": (
            '("CodeMeta" OR "Bioschemas" OR "software metadata")'
            ' AND ("findability" OR "discoverability" OR "FAIR software"'
            ' OR "FAIR4RS" OR "recommend")'
        ),
    },

    # Q4: Software Heritage / persistent identifiers for software.
    # SWHID and "software heritage" are highly specific — keep broad within topic.
    "Q4_intrinsic_identifiers": {
        "title_abs": (
            '("Software Heritage" OR "SWHID" OR "software identifier"'
            ' OR "persistent identifier" AND "software")'
            ' AND ("discoverability" OR "findability" OR "citation" OR "archiving")'
        ),
    },

    # Q5: Infrastructure for software discovery in scholarly / library context.
    # Removed bare "search" and "software" which were causing the 59k explosion.
    # Now requires a software-specific discoverability term in title/abstract.
    "Q5_infrastructure_discovery": {
        "title_abs": (
            '("scholarly infrastructure" OR "research infrastructure"'
            ' OR "digital library" OR "institutional repository")'
            ' AND ("software discoverability" OR "software findability"'
            ' OR "software search" OR "software recommendation"'
            ' OR "software discovery")'
        ),
    },

    # ── Supporting literature (Q6–Q8) ────────────────────────────────────────

    # Q6: Software citation principles / practices — already fairly specific.
    # Tightened by requiring a normative or infrastructure term.
    "Q6_software_citation": {
        "title_abs": (
            '("software citation" OR "code citation")'
            ' AND ("principles" OR "practices" OR "credit" OR "infrastructure"'
            ' OR "persistent identifier" OR "FORCE11")'
        ),
    },

    # Q7: Recommender systems for scholarly artefacts including software.
    # Previous query matched any paper mentioning "recommender" + "software"
    # anywhere. Now requires the recommender to be in a scholarly/research context.
    "Q7_scholarly_recsys": {
        "title_abs": (
            '("recommender system" OR "recommendation system")'
            ' AND ("research software" OR "scientific software" OR "code reuse"'
            ' OR "software tool" OR "scholarly artefact" OR "software package")'
        ),
    },

    # Q8: FAIR for research software — FAIR4RS is very specific; "FAIR principles"
    # AND software is still broad, so we anchor with a concrete FAIR dimension.
    "Q8_fair4rs": {
        "title_abs": (
            '("FAIR4RS" OR ("FAIR" AND "research software"))'
            ' AND ("findability" OR "reusability" OR "interoperability"'
            ' OR "metadata" OR "principles")'
        ),
    },
}


# ─── API HELPERS ──────────────────────────────────────────────────────────────
def build_headers():
    """
    OpenAlex prefers identification via the User-Agent header (polite pool)
    or the api_key query param (authenticated pool, higher rate limits).
    """
    return {
        "User-Agent": f"mailto:{EMAIL}",
        "Accept": "application/json",
    }


def search_openalex(query_dict, max_results=MAX_RESULTS_PER_QUERY):
    """
    Execute a paginated OpenAlex search and return all result entries.

    query_dict keys:
        "title_abs"     – passed as filter title_and_abstract.search:<value>
                          Searches title + abstract only (equivalent to Scopus
                          TITLE-ABS-KEY). Much more precise than global search=.
        "extra_filter"  – optional additional filter string (comma-prefixed
                          fragment appended to the main filter string)

    Key OpenAlex API parameters used:
        filter            – Structured filters, comma-separated:
                              title_and_abstract.search – scoped text search
                              from_publication_date     – YYYY-MM-DD lower bound
                              is_paratext               – exclude front-matter
        select            – Comma-separated list of fields to return (bandwidth)
        sort              – Field to sort on (cited_by_count:desc)
        per-page          – Page size (max 200)
        page              – 1-based page number
        api_key           – Your OpenAlex API key
    """
    headers   = build_headers()
    all_items = []
    page      = 1

    title_abs_query = query_dict["title_abs"]
    extra_filter    = query_dict.get("extra_filter", "")

    # Fields we actually need — keep this list tight to reduce payload size
    select_fields = ",".join([
        "id", "doi", "title", "publication_year", "publication_date",
        "primary_location", "type", "cited_by_count",
        "authorships", "keywords", "topics",
        "open_access", "abstract_inverted_index",
        "best_oa_location",
    ])

    # Build the base filter string
    # title_and_abstract.search must be the LAST filter clause because its
    # value may contain spaces (OpenAlex parses up to the next comma-filter)
    base_filter = (
        f"from_publication_date:{YEAR_FILTER_START}-01-01,"
        f"is_paratext:false"
        f"{(',' + extra_filter) if extra_filter else ''},"
        f"title_and_abstract.search:{title_abs_query}"
    )

    while (page - 1) * RESULTS_PER_PAGE < max_results:
        params = {
            "filter":   base_filter,
            "select":   select_fields,
            "sort":     "cited_by_count:desc",
            "per-page": min(RESULTS_PER_PAGE, max_results - (page - 1) * RESULTS_PER_PAGE),
            "page":     page,
        }

        # Prefer key-based auth; fall back to polite-pool email
        if API_KEY and API_KEY != "YOUR_KEY_HERE":
            params["api_key"] = API_KEY

        resp = requests.get(BASE_URL, headers=headers, params=params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 10))
            print(f"    Rate limited — waiting {retry_after} s...")
            time.sleep(retry_after)
            continue

        if resp.status_code != 200:
            print(f"    ERROR {resp.status_code}: {resp.text[:300]}")
            break

        data  = resp.json()
        meta  = data.get("meta", {})
        items = data.get("results", [])

        total_available = meta.get("count", 0)

        if not items:
            break

        all_items.extend(items)
        page += 1

        if (page - 1) * RESULTS_PER_PAGE >= total_available:
            break

        time.sleep(RATE_LIMIT_DELAY)

    return all_items, total_available


def reconstruct_abstract(inverted_index):
    """
    OpenAlex stores abstracts as an inverted index  {word: [positions]}.
    This function reconstructs the original abstract string.
    Returns empty string if the inverted index is None or empty.
    """
    if not inverted_index:
        return ""
    # Build a position → word map, then join in order
    position_word = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word[pos] = word
    return " ".join(position_word[i] for i in sorted(position_word))


def extract_record(item):
    """
    Normalise an OpenAlex work entry into a flat dict for the
    screening spreadsheet.

    Key OpenAlex fields used:
        id                       – OpenAlex work ID (stable URI)
        doi                      – DOI (may be None)
        title                    – Work title
        publication_year         – Integer year
        publication_date         – ISO date string
        primary_location         – Dict with source (journal/conf) info
        type                     – 'article', 'proceedings-article', etc.
        cited_by_count           – Integer citation count
        authorships              – List of author objects
        keywords                 – List of {keyword, score} objects
        open_access              – Dict with is_oa and oa_status
        abstract_inverted_index  – Inverted index for abstract reconstruction
    """
    # ── Authors ──────────────────────────────────────────────────────────────
    authorships = item.get("authorships", [])
    first_author = ""
    if authorships:
        author_obj = authorships[0].get("author", {})
        first_author = author_obj.get("display_name", "")

    # ── Source (journal / conference) ─────────────────────────────────────
    primary_location = item.get("primary_location") or {}
    source_obj       = primary_location.get("source") or {}
    source_name      = source_obj.get("display_name", "")
    source_type      = source_obj.get("type", "")       # 'journal', 'conference', etc.
    publisher        = source_obj.get("host_organization_name", "")

    # ── Keywords & topics ────────────────────────────────────────────────
    kw_list     = item.get("keywords", []) or []
    keywords    = " | ".join(k.get("keyword", "") for k in kw_list)

    # ── Open access ──────────────────────────────────────────────────────
    oa_obj      = item.get("open_access") or {}
    is_oa       = str(oa_obj.get("is_oa", ""))
    oa_status   = oa_obj.get("oa_status", "")          # gold, green, hybrid, bronze, closed

    # ── Abstract ─────────────────────────────────────────────────────────
    abstract = reconstruct_abstract(item.get("abstract_inverted_index"))

    # ── Identifiers & links ──────────────────────────────────────────────
    openalex_id   = item.get("id", "")                  # e.g. https://openalex.org/W123
    short_id      = openalex_id.split("/")[-1]          # e.g. W123
    doi_raw       = item.get("doi", "") or ""
    doi_clean     = doi_raw.replace("https://doi.org/", "")

    return {
        "openalex_id":   short_id,
        "doi":           doi_clean,
        "title":         item.get("title", ""),
        "first_author":  first_author,
        "source":        source_name,
        "source_type":   source_type,
        "publisher":     publisher,
        "year":          str(item.get("publication_year", "")),
        "date":          item.get("publication_date", ""),
        "cited_by":      int(item.get("cited_by_count", 0) or 0),
        "doc_type":      item.get("type", ""),
        "keywords":      keywords,
        "is_oa":         is_oa,
        "oa_status":     oa_status,
        "abstract":      abstract,
        "openalex_link": openalex_id,
    }


# ─── MAIN EXECUTION ───────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    all_records = []
    search_log  = []

    print("=" * 70)
    print(f"OPENALEX LITERATURE SEARCH — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    if API_KEY == "YOUR_KEY_HERE":
        print("\n⚠️  WARNING: No API key set. Running in polite-pool mode.")
        print("   Rate limits are stricter. Get a free key at:")
        print("   https://openalex.org/settings/api\n")

    for block_id, query_dict in QUERIES.items():
        print(f"\n▸ Running {block_id}...")
        items, total = search_openalex(query_dict)
        records = [extract_record(i) for i in items]

        for r in records:
            r["source_query"] = block_id
            r["query_type"]   = "core" if int(block_id[1]) <= 5 else "supporting"

        all_records.extend(records)

        # Warn if the query is still returning a very large pool
        if total > 1000:
            print(f"  ⚠️  {total:,} total results — query may still be too broad.")
            print(f"     Only top {len(records)} (by citation) retrieved.")
            print(f"     Consider tightening the query string in QUERIES.")
        else:
            print(f"  Found {total:,} total, retrieved {len(records)}")

        search_log.append({
            "query_block":              block_id,
            "query_string":             query_dict["title_abs"],
            "extra_filter":             query_dict.get("extra_filter", ""),
            "date_searched":            datetime.now().strftime("%Y-%m-%d"),
            "total_results_available":  total,
            "results_retrieved":        len(records),
            "query_too_broad":          total > 1000,
        })

    # ── Deduplication ────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"Total records before dedup: {len(all_records)}")

    df = pd.DataFrame(all_records)

    if not df.empty:
        # Use openalex_id as stable unique identifier
        query_sources = (
            df.groupby("openalex_id")["source_query"]
            .apply(lambda x: "; ".join(sorted(set(x))))
            .reset_index()
        )
        query_sources.columns = ["openalex_id", "found_in_queries"]

        df = df.drop_duplicates(subset="openalex_id", keep="first")
        df = df.merge(query_sources, on="openalex_id", how="left")
        df = df.drop(columns=["source_query"], errors="ignore")
    else:
        df["found_in_queries"] = ""

    print(f"Unique records after dedup:  {len(df)}")

    # ── Abstract coverage report ─────────────────────────────────────────────
    if not df.empty:
        n_with_abstract    = (df["abstract"].str.strip() != "").sum()
        n_missing_abstract = len(df) - n_with_abstract
        pct = 100 * n_with_abstract / len(df)
        print(f"\nAbstract coverage: {n_with_abstract}/{len(df)} ({pct:.0f}%)")
        if n_missing_abstract > 0:
            print(f"  ⚠️  {n_missing_abstract} records have no abstract.")
            print("     These may be ACM/IEEE records that don't share")
            print("     abstracts via Crossref. Retrieve manually if needed.")

    # ── Add screening columns ────────────────────────────────────────────────
    df["stage1_reviewer_A"] = ""
    df["stage1_reviewer_B"] = ""
    df["stage1_decision"]   = ""
    df["stage2_decision"]   = ""
    df["final_inclusion"]   = ""
    df["exclusion_reason"]  = ""
    df["gate_assignment"]   = ""
    df["notes"]             = ""

    # Sort by citations descending
    df = df.sort_values("cited_by", ascending=False).reset_index(drop=True)

    # ── Save search log ──────────────────────────────────────────────────────
    log_path = os.path.join(OUTPUT_DIR, f"search_log_{timestamp}.json")
    with open(log_path, "w") as f:
        json.dump(search_log, f, indent=2)
    print(f"\nSearch log saved: {log_path}")

    # ── Export to Excel ──────────────────────────────────────────────────────
    xlsx_path = os.path.join(OUTPUT_DIR, f"screening_sheet_{timestamp}.xlsx")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Records", index=False)
        pd.DataFrame(search_log).to_excel(writer, sheet_name="Search Log", index=False)

    # ── Format the Excel file ────────────────────────────────────────────────
    wb = load_workbook(xlsx_path)
    format_screening_sheet(wb["Records"])
    format_log_sheet(wb["Search Log"])
    add_summary_sheet(wb, df, search_log)
    wb.save(xlsx_path)

    print(f"Screening spreadsheet saved: {xlsx_path}")
    print(f"\n{'=' * 70}")
    print("DONE. Next steps:")
    print("  1. Open the spreadsheet and review records")
    print("  2. For records with missing abstracts, retrieve manually")
    print("     (search by DOI on the publisher site or Google Scholar)")
    print("  3. Each reviewer fills stage1_reviewer_A / B columns")
    print("     (Include / Exclude / Unsure)")
    print("  4. Resolve disagreements → fill stage1_decision")
    print("  5. Full-text screen → fill stage2_decision")
    print("  6. Assign included papers to gates → gate_assignment column")
    print(f"{'=' * 70}")


# ─── EXCEL FORMATTING ─────────────────────────────────────────────────────────
HEADER_FILL    = PatternFill("solid", fgColor="1A5276")   # dark blue
HEADER_FONT    = Font(name="Arial", size=10, bold=True, color="FFFFFF")
SCREENING_FILL = PatternFill("solid", fgColor="FFF2CC")
SCREENING_FONT = Font(name="Arial", size=10, bold=True, color="7D6608")
BODY_FONT      = Font(name="Arial", size=10)
THIN_BORDER    = Border(
    left=Side(style="thin",   color="D5D8DC"),
    right=Side(style="thin",  color="D5D8DC"),
    top=Side(style="thin",    color="D5D8DC"),
    bottom=Side(style="thin", color="D5D8DC"),
)
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")
TOP_ALIGNMENT  = Alignment(vertical="top")

COLUMN_WIDTHS = {
    "openalex_id":      14, "doi":          22, "title":         50,
    "first_author":     20, "source":       28, "source_type":   14,
    "publisher":        20, "year":          7, "date":          12,
    "cited_by":          9, "doc_type":     14, "keywords":      30,
    "is_oa":             8, "oa_status":    10, "abstract":      60,
    "openalex_link":    20, "found_in_queries": 22, "query_type": 10,
    "stage1_reviewer_A": 14, "stage1_reviewer_B": 14,
    "stage1_decision":  14, "stage2_decision": 14,
    "final_inclusion":  14, "exclusion_reason": 22,
    "gate_assignment":  14, "notes":        25,
}

SCREENING_COLUMNS = {
    "stage1_reviewer_A", "stage1_reviewer_B", "stage1_decision",
    "stage2_decision", "final_inclusion", "exclusion_reason",
    "gate_assignment", "notes",
}


def format_screening_sheet(ws):
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions

    for col_idx, cell in enumerate(ws[1], 1):
        col_name     = cell.value
        is_screening = col_name in SCREENING_COLUMNS
        cell.font      = SCREENING_FONT if is_screening else HEADER_FONT
        cell.fill      = SCREENING_FILL if is_screening else HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border    = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = COLUMN_WIDTHS.get(col_name, 15)

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.font   = BODY_FONT
            cell.border = THIN_BORDER
            col_name = ws.cell(row=1, column=cell.column).value
            if col_name in ("title", "abstract", "keywords"):
                cell.alignment = WRAP_ALIGNMENT
            else:
                cell.alignment = TOP_ALIGNMENT


def format_log_sheet(ws):
    for col_idx, cell in enumerate(ws[1], 1):
        cell.font      = HEADER_FONT
        cell.fill      = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border    = THIN_BORDER

    widths = [18, 80, 14, 18, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w

    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.font      = BODY_FONT
            cell.border    = THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def add_summary_sheet(wb, df, search_log):
    ws = wb.create_sheet("Summary", 0)

    title_font = Font(name="Arial", size=14, bold=True, color="1A5276")
    label_font = Font(name="Arial", size=11, bold=True)
    value_font = Font(name="Arial", size=11)
    note_font  = Font(name="Arial", size=10, italic=True, color="888888")

    ws["A1"] = "OpenAlex Literature Search Summary"
    ws["A1"].font = title_font
    ws.merge_cells("A1:D1")

    ws["A3"] = "Search date:"
    ws["B3"] = datetime.now().strftime("%Y-%m-%d")
    ws["A4"] = "Total queries run:"
    ws["B4"] = len(search_log)
    ws["A5"] = "Total records retrieved:"
    ws["B5"] = sum(l["results_retrieved"] for l in search_log)
    ws["A6"] = "Unique after dedup:"
    ws["B6"] = len(df)
    ws["A7"] = "Core literature records:"
    ws["B7"] = len(df[df["query_type"] == "core"]) if "query_type" in df.columns else ""
    ws["A8"] = "Supporting lit. records:"
    ws["B8"] = len(df[df["query_type"] == "supporting"]) if "query_type" in df.columns else ""

    if not df.empty and "abstract" in df.columns:
        n_with = (df["abstract"].str.strip() != "").sum()
        ws["A9"] = "Records with abstract:"
        ws["B9"] = f"{n_with} / {len(df)} ({100*n_with//len(df)}%)"
        ws["C9"] = "⚠️ Missing abstracts may be ACM/IEEE records — retrieve manually"
        ws["C9"].font = note_font

    for r in range(3, 10):
        ws.cell(r, 1).font = label_font
        ws.cell(r, 2).font = value_font

    ws["A11"] = "Results per query block:"
    ws["A11"].font = label_font
    warn_font = Font(name="Arial", size=10, color="C0392B", bold=True)
    for i, log in enumerate(search_log, 12):
        ws.cell(i, 1).value = log["query_block"]
        ws.cell(i, 1).font  = value_font
        ws.cell(i, 2).value = log["total_results_available"]
        ws.cell(i, 2).font  = value_font
        ws.cell(i, 3).value = f"(retrieved {log['results_retrieved']})"
        ws.cell(i, 3).font  = Font(name="Arial", size=10, color="888888")
        if log.get("query_too_broad"):
            ws.cell(i, 4).value = "⚠️ query too broad — tighten"
            ws.cell(i, 4).font  = warn_font

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 25
    ws.column_dimensions["D"].width = 30


if __name__ == "__main__":
    main()
