"""
Filter rows from supplementary_title_screening.xlsx by a list of idx values
and upload the result to KDrive.

Usage:
    python filter_records.py                    # uses IDs hardcoded below
    python filter_records.py 1 2 4 5 ...        # override with CLI args
"""
from __future__ import annotations

import logging
import sys

import pandas as pd

from infomaniak import FOLDER_ID, upload_file_overwrite

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INPUT_FILE = "supplementary_title_screening.xlsx"
OUTPUT_FILE = "supplementary_title_screening_filtered.xlsx"
SHEET = "All Records"

DEFAULT_IDS = [
    1,2,4,5,6,7,11,14,15,18,20,21,25,26,28,29,30,32,33,34,35,36,38,39,
    68,69,71,72,76,77,78,79,88,105,124,127,129,140,141,142,143,145,155,
    156,159,166,174,175,184,194,197,206,217,218,219,220,221,223,230,233,
    234,240,245,246,248,252,253,255,256,257,259,260,261,262,263,264,265,
    267,268,269,270,271,272,273,278,280,281,282,283,291,317,322,329,330,
    332,335,337,339,340,341,344,345,346,349,350,352,354,355,356,358,359,
    360,361,362,363,364,365,366,367,368,372,373,375,376,377,378,379,
]


def filter_records(ids: list[int]) -> pd.DataFrame:
    df = pd.read_excel(INPUT_FILE, sheet_name=SHEET)
    missing = set(ids) - set(df["idx"].tolist())
    if missing:
        logger.warning("IDs not found in source: %s", sorted(missing))
    filtered = df[df["idx"].isin(ids)].copy()
    logger.info("Filtered %d/%d rows", len(filtered), len(df))
    return filtered


def main() -> None:
    ids = [int(x) for x in sys.argv[1:]] if len(sys.argv) > 1 else DEFAULT_IDS
    filtered = filter_records(ids)
    filtered.to_excel(OUTPUT_FILE, sheet_name=SHEET, index=False)
    logger.info("Saved %s", OUTPUT_FILE)
    upload_file_overwrite(OUTPUT_FILE, FOLDER_ID)


if __name__ == "__main__":
    main()
