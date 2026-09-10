"""
Scopus API Literature Search Tool
==================================
Executes pre-defined query blocks against the Scopus Search API,
deduplicates results, and exports a screening spreadsheet.
Usage:
    python scopus_search.py
Configuration:
    Set your API key below or via the SCOPUS_API_KEY environment variable.
    If you have an institutional token, set SCOPUS_INST_TOKEN as well.
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
# ─── CONFIGURATION ───────────────────────────────────────────────────────────
API_KEY = os.environ.get("SCOPUS_API_KEY")
INST_TOKEN = os.environ.get("SCOPUS_INST_TOKEN", "")  # optional
BASE_URL = "https://api.elsevier.com/content/search/scopus"
YEAR_FILTER = " AND PUBYEAR > 2013"
MAX_RESULTS_PER_QUERY = 2000  # aligned with OpenAlex setting
RESULTS_PER_PAGE = 25
OUTPUT_DIR = "scopus_results"
RATE_LIMIT_DELAY = 0.35  # seconds between API calls (Scopus allows ~3/sec)

# ─── QUERY BLOCKS ────────────────────────────────────────────────────────────
# Adapted from OpenAlex queries to Scopus TITLE-ABS-KEY syntax.
# Key differences from OpenAlex → Scopus:
#   - Wildcards restored (e.g. "recommend*", "discover*", "findab*")
#   - "NOT" used instead of OpenAlex "-term" syntax
#   - Wrapped in TITLE-ABS-KEY(...) for field-scoped search
QUERIES = {
    # ── Core literature (Q1–Q5) ──────────────────────────────────────────────

    # Q1: Papers specifically about recommending / discovering research software.
    "Q1_core_software_recsys": (
        'TITLE-ABS-KEY(("research software" OR "scientific software" OR '
        '"academic software") AND ("recommender" OR "recommendation system" OR '
        '"discoverability" OR "software discovery" OR "suggestion system"))'
    ),

    # Q2: Software repositories / registries in a scholarly context with
    # findability / recommendation angle.
    "Q2_repository_context": (
        'TITLE-ABS-KEY(("software repository" OR "software registry" OR '
        '"software catalog" OR "software portal") AND ("recommend*" OR '
        '"findability" OR "discoverability" OR "similar software") AND '
        '("scholarly" OR "scientific" OR "research infrastructure"))'
    ),

    # Q3: Metadata standards for research software + FAIR / findability.
    "Q3_metadata_standards": (
        'TITLE-ABS-KEY(("CodeMeta" OR "Bioschemas" OR "software metadata") '
        'AND ("findability" OR "discoverability" OR "FAIR software" OR '
        '"FAIR4RS" OR "recommend*"))'
    ),

    # Q4: Software Heritage / persistent identifiers for software.
    "Q4_intrinsic_identifiers": (
        'TITLE-ABS-KEY(("Software Heritage" OR "SWHID" OR "software identifier" '
        'OR ("persistent identifier" AND "software")) AND ("discoverability" OR '
        '"findability" OR "citation" OR "archiving"))'
    ),

    # Q5: Infrastructure for software discovery in scholarly / library context.
    "Q5_infrastructure_discovery": (
        'TITLE-ABS-KEY(("scholarly infrastructure" OR "research infrastructure" '
        'OR "digital library" OR "institutional repository") AND '
        '("software discoverability" OR "software findability" OR '
        '"software search" OR "software recommendation" OR "software discovery"))'
    ),

    # ── Supporting literature (Q6–Q8) ────────────────────────────────────────

    # Q6: Software citation principles / practices.
    "Q6_software_citation": (
        'TITLE-ABS-KEY(("software citation" OR "code citation") AND '
        '("principles" OR "practices" OR "credit" OR "infrastructure" OR '
        '"persistent identifier" OR "FORCE11"))'
    ),

    # Q7: Recommender systems for scholarly artefacts including software.
    "Q7_scholarly_recsys": (
        'TITLE-ABS-KEY(("recommender system" OR "recommendation system") AND '
        '("research software" OR "scientific software" OR "code reuse" OR '
        '"software tool" OR "scholarly artefact" OR "software package"))'
    ),

    # Q8: FAIR for research software.
    "Q8_fair4rs": (
        'TITLE-ABS-KEY(("FAIR4RS" OR ("FAIR" AND "research software")) AND '
        '("findability" OR "reusability" OR "interoperability" OR "metadata" '
        'OR "principles"))'
    ),
}

# ─── API HELPERS ─────────────────────────────────────────────────────────────
def build_headers():
    headers = {
        "X-ELS-APIKey": API_KEY,
        "Accept": "application/json",
    }
    if INST_TOKEN:
        headers["X-ELS-Insttoken"] = INST_TOKEN
    return headers
def search_scopus(query, max_results=MAX_RESULTS_PER_QUERY):
    """Execute a paginated Scopus search and return all result entries."""
    headers = build_headers()
    full_query = query + YEAR_FILTER
    all_entries = []
    start = 0
    while start < max_results:
        params = {
            "query": full_query,
            "count": min(RESULTS_PER_PAGE, max_results - start),
            "start": start,
            "sort": "citedby-count",
            "field": (
                "dc:identifier,eid,dc:title,dc:creator,prism:publicationName,"
                "prism:coverDate,prism:doi,citedby-count,subtypeDescription,"
                "authkeywords,prism:aggregationType,source-id,openaccess,"
                "dc:description"
            ),
        }
        resp = requests.get(BASE_URL, headers=headers, params=params)
        if resp.status_code == 429:
            print("    Rate limited — waiting 10s...")
            time.sleep(10)
            continue
        if resp.status_code != 200:
            print(f"    ERROR {resp.status_code}: {resp.text[:300]}")
            break
        data = resp.json().get("search-results", {})
        total_available = int(data.get("opensearch:totalResults", 0))
        entries = data.get("entry", [])
        if not entries or (len(entries) == 1 and "error" in entries[0]):
            break
        all_entries.extend(entries)
        start += RESULTS_PER_PAGE
        if start >= total_available:
            break
        time.sleep(RATE_LIMIT_DELAY)
    return all_entries, total_available
def extract_record(entry):
    """Normalise a Scopus entry into a flat dict for the screening spreadsheet."""
    return {
        "scopus_id": entry.get("dc:identifier", "").replace("SCOPUS_ID:", ""),
        "eid": entry.get("eid", ""),
        "doi": entry.get("prism:doi", ""),
        "title": entry.get("dc:title", ""),
        "first_author": entry.get("dc:creator", ""),
        "source": entry.get("prism:publicationName", ""),
        "date": entry.get("prism:coverDate", ""),
        "year": entry.get("prism:coverDate", "")[:4] if entry.get("prism:coverDate") else "",
        "cited_by": int(entry.get("citedby-count", 0)),
        "doc_type": entry.get("subtypeDescription", ""),
        "agg_type": entry.get("prism:aggregationType", ""),
        "keywords": entry.get("authkeywords", ""),
        "open_access": entry.get("openaccess", ""),
        "abstract": entry.get("dc:description", ""),
        "scopus_link": f"https://www.scopus.com/record/display.uri?eid={entry.get('eid', '')}&origin=resultslist",
    }
# ─── MAIN EXECUTION ─────────────────────────────────────────────────────────
def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    all_records = []
    search_log = []
    print("=" * 70)
    print(f"SCOPUS LITERATURE SEARCH — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)
    for block_id, query in QUERIES.items():
        print(f"\n▸ Running {block_id}...")
        entries, total = search_scopus(query)
        records = [extract_record(e) for e in entries]
        for r in records:
            r["source_query"] = block_id
            r["query_type"] = "core" if int(block_id[1]) <= 5 else "supporting"
        all_records.extend(records)
        log_entry = {
            "query_block": block_id,
            "query_string": query + YEAR_FILTER,
            "date_searched": datetime.now().strftime("%Y-%m-%d"),
            "total_results_available": total,
            "results_retrieved": len(records),
        }
        search_log.append(log_entry)
        print(f"  Found {total} total, retrieved {len(records)}")
    # ── Deduplication ────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    print(f"Total records before dedup: {len(all_records)}")
    df = pd.DataFrame(all_records)
    # Track which queries found each record (before dedup)
    if not df.empty:
        query_sources = df.groupby("eid")["source_query"].apply(
            lambda x: "; ".join(sorted(set(x)))
        ).reset_index()
        query_sources.columns = ["eid", "found_in_queries"]
        df = df.drop_duplicates(subset="eid", keep="first")
        df = df.merge(query_sources, on="eid", how="left")
        df = df.drop(columns=["source_query"], errors="ignore")
    else:
        df["found_in_queries"] = ""
    print(f"Unique records after dedup:  {len(df)}")
    # ── Add screening columns ────────────────────────────────────────────────
    df["stage1_reviewer_A"] = ""
    df["stage1_reviewer_B"] = ""
    df["stage1_decision"] = ""
    df["stage2_decision"] = ""
    df["final_inclusion"] = ""
    df["exclusion_reason"] = ""
    df["gate_assignment"] = ""
    df["notes"] = ""
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
    print("  2. Each reviewer fills stage1_reviewer_A / B columns")
    print("     (Include / Exclude / Unsure)")
    print("  3. Resolve disagreements → fill stage1_decision")
    print("  4. Full-text screen → fill stage2_decision")
    print("  5. Assign included papers to gates → gate_assignment column")
    print(f"{'=' * 70}")
# ─── EXCEL FORMATTING ────────────────────────────────────────────────────────
HEADER_FILL = PatternFill("solid", fgColor="1B4F72")
HEADER_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
SCREENING_FILL = PatternFill("solid", fgColor="FFF2CC")
SCREENING_FONT = Font(name="Arial", size=10, bold=True, color="7D6608")
BODY_FONT = Font(name="Arial", size=10)
THIN_BORDER = Border(
    left=Side(style="thin", color="D5D8DC"),
    right=Side(style="thin", color="D5D8DC"),
    top=Side(style="thin", color="D5D8DC"),
    bottom=Side(style="thin", color="D5D8DC"),
)
WRAP_ALIGNMENT = Alignment(wrap_text=True, vertical="top")
TOP_ALIGNMENT = Alignment(vertical="top")
COLUMN_WIDTHS = {
    "scopus_id": 14, "eid": 16, "doi": 22, "title": 50, "first_author": 20,
    "source": 28, "date": 12, "year": 7, "cited_by": 9, "doc_type": 14,
    "agg_type": 12, "keywords": 30, "open_access": 7, "abstract": 60,
    "scopus_link": 20, "found_in_queries": 22, "query_type": 10,
    "stage1_reviewer_A": 14, "stage1_reviewer_B": 14, "stage1_decision": 14,
    "stage2_decision": 14, "final_inclusion": 14, "exclusion_reason": 22,
    "gate_assignment": 14, "notes": 25,
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
        col_name = cell.value
        is_screening = col_name in SCREENING_COLUMNS
        cell.font = SCREENING_FONT if is_screening else HEADER_FONT
        cell.fill = SCREENING_FILL if is_screening else HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
        width = COLUMN_WIDTHS.get(col_name, 15)
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.font = BODY_FONT
            cell.border = THIN_BORDER
            col_name = ws.cell(row=1, column=cell.column).value
            if col_name in ("title", "abstract", "keywords"):
                cell.alignment = WRAP_ALIGNMENT
            else:
                cell.alignment = TOP_ALIGNMENT
def format_log_sheet(ws):
    for col_idx, cell in enumerate(ws[1], 1):
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = THIN_BORDER
    widths = [18, 80, 14, 18, 16]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=ws.max_column):
        for cell in row:
            cell.font = BODY_FONT
            cell.border = THIN_BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
def add_summary_sheet(wb, df, search_log):
    ws = wb.create_sheet("Summary", 0)
    title_font = Font(name="Arial", size=14, bold=True, color="1B4F72")
    label_font = Font(name="Arial", size=11, bold=True)
    value_font = Font(name="Arial", size=11)
    ws["A1"] = "Literature Search Summary"
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
    for r in range(3, 9):
        ws.cell(r, 1).font = label_font
        ws.cell(r, 2).font = value_font
    ws["A10"] = "Results per query block:"
    ws["A10"].font = label_font
    for i, log in enumerate(search_log, 11):
        ws.cell(i, 1).value = log["query_block"]
        ws.cell(i, 1).font = value_font
        ws.cell(i, 2).value = log["total_results_available"]
        ws.cell(i, 2).font = value_font
        ws.cell(i, 3).value = f"(retrieved {log['results_retrieved']})"
        ws.cell(i, 3).font = Font(name="Arial", size=10, color="888888")
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 20
if __name__ == "__main__":
    main()
