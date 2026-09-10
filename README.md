# Research Software Discovery: A Review of Scholarly Infrastructures and Associated Literature

Scripts used to collect, deduplicate, and enrich the literature corpus for the
systematic review **"Research Software Discovery: A Review of Scholarly
Infrastructures and Associated Literature"**. The review covers scholarly
infrastructures and literature on discovering, recommending, and citing
research/scientific software (metadata standards, persistent identifiers,
repositories, and recommender systems).

## Contents

| File | Purpose |
|---|---|
| `openalex.py` | Runs the query blocks (Q1–Q8) against the OpenAlex Works API, deduplicates results, and exports a formatted title/abstract screening spreadsheet (`openalex_results/`). |
| `scopus.py` | Same pipeline against the Scopus Search API (`scopus_results/`), with queries adapted to Scopus `TITLE-ABS-KEY` syntax. |
| `enrich_abstracts.py` | Fills in missing abstracts for the merged screening sheet by querying Semantic Scholar, CrossRef, Zenodo, OpenAlex, HAL, FigShare, and OAI-PMH (in that priority order), reusing previously-enriched rows across runs. Downloads/uploads the sheet from/to Infomaniak kDrive. |
| `infomaniak.py` | kDrive upload/download helpers used by `enrich_abstracts.py`; fails gracefully if no token is set. |
| `install.sh` | Installs `openaire-py` and `uv`. |

## Query strategy

Both `openalex.py` and `scopus.py` run the same set of query blocks, restricted
to publications after 2013:

- **Q1 — Core software recsys**: research/scientific software + recommender/discoverability terms
- **Q2 — Repository context**: software repositories/registries/catalogs + findability in a scholarly context
- **Q3 — Metadata standards**: CodeMeta, Bioschemas, software metadata + FAIR/findability
- **Q4 — Intrinsic identifiers**: Software Heritage, SWHID, persistent identifiers + citation/archiving
- **Q5 — Infrastructure discovery**: scholarly/research infrastructure, digital libraries + software discoverability
- **Q6 — Software citation**: software citation principles/practices
- **Q7 — Scholarly recsys**: recommender systems in scholarly/academic contexts
- **Q8** (OpenAlex only, supporting): see `openalex.py` for the remaining query block

Each script deduplicates across query blocks and writes an Excel workbook with
a `Summary` sheet (query counts, abstract coverage) and a formatted screening
sheet ready for title/abstract screening.

## Setup

```bash
pip install requests pandas openpyxl
./install.sh   # optional: openaire-py + uv
```

### API credentials (environment variables)

| Variable | Used by | Notes |
|---|---|---|
| `OPENALEX_API_KEY` | `openalex.py` | Free, register at https://openalex.org/settings/api |
| `OPENALEX_EMAIL` | `openalex.py` | Polite-pool identification fallback |
| `SCOPUS_API_KEY` | `scopus.py` | Elsevier Scopus Search API key |
| `SCOPUS_INST_TOKEN` | `scopus.py` | Optional institutional token |
| `INFOMANIAK_TOKEN` | `enrich_abstracts.py`, `infomaniak.py` | OAuth2 bearer token for kDrive |
| `KDRIVE_DRIVE_ID` | `infomaniak.py` | Defaults to the project drive |

## Usage

```bash
# Search and export screening spreadsheets
python openalex.py
python scopus.py

# After merging/curating results into supplementary_title_screening.xlsx on kDrive:
INFOMANIAK_TOKEN=<token> python enrich_abstracts.py
```

`openalex.py` and `scopus.py` are standalone and do not depend on
`infomaniak.py` or kDrive — they only need `requests`, `pandas`, `openpyxl`,
and the relevant API key(s) above. Only `enrich_abstracts.py` requires
`INFOMANIAK_TOKEN`.

⚠️ **Abstract coverage note**: ACM/IEEE records rarely expose abstracts via
Crossref/OpenAlex, so a share of those records need manual abstract retrieval
before title+abstract screening — `enrich_abstracts.py` narrows this gap
automatically where possible.
