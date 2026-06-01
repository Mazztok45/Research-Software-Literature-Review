"""
Infomaniak KDrive upload/download helpers (optional).

Set the following environment variables to use KDrive:
  INFOMANIAK_TOKEN    — OAuth2 bearer token
  KDRIVE_DRIVE_ID     — numeric drive ID (defaults to the project drive 705884)
  KDRIVE_INPUT_DIR    — numeric directory ID for Pipeline 1 imports
  KDRIVE_OUTPUT_DIR   — numeric directory ID for Pipeline 2 exports

All functions fail gracefully (log a warning) when the token is absent.

File-ID registry
----------------
The constants below encode every artifact file ID observed across the six
Colab notebooks used to execute the pipelines.  They let any script call the
named download helpers without knowing the underlying numeric IDs.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://api.infomaniak.com"

# ── Project-level KDrive coordinates ─────────────────────────────────────────

_DEFAULT_DRIVE_ID = "705884"

# Folder IDs
FOLDER_PIPELINE2_RESULTS = "20716"   # pipeline 2 repos + alignment JSONL files
FOLDER_GROUND_TRUTH      = "20727"   # gt_{domain}.json + discoverable_{domain}.json
FOLDER_PIPELINE4_RESULTS = "20949"   # LLM-judge outputs (pipeline 4)

# Pipeline 1 artifact file IDs
PIPELINE1_FILE_IDS: Dict[str, str] = {
    "msc_enhanced.owl":       "20703",
    "msc_embeddings.h5":      "20704",
    "msc_metadata.pkl":       "20705",
    "msc_manifest.json":      "20706",
    "physh_enhanced.owl":     "20707",
    "physh_embeddings.h5":    "20708",
    "physh_metadata.pkl":     "20709",
    "physh_manifest.json":    "20710",
    "edam_enhanced.owl":      "20711",
    "edam_embeddings.h5":     "20712",
    "edam_metadata.pkl":      "20713",
    "edam_manifest.json":     "20714",
    "pipeline1_summary.json": "20715",
}

# Pipeline 1 manifest-only subset (needed by pipelines 5 & 6 without heavy OWL files)
PIPELINE1_MANIFEST_IDS: Dict[str, str] = {
    "msc_manifest.json":      "20706",
    "physh_manifest.json":    "20710",
    "edam_manifest.json":     "20714",
    "pipeline1_summary.json": "20715",
}

# README semantic-similarity cache produced by pipeline 2 readme_only ablation
README_CACHE_FILE_IDS: Dict[str, str] = {
    "math_readme_scores.json":    "20819",
    "physics_readme_scores.json": "20820",
    "biology_readme_scores.json": "20821",
}

# Box²EL math embeddings (shared across domains as structural proxy)
BOX2EL_FILE_ID   = "20810"   # full_box2el_embeddings.npz

# Raw SWH blob store (needed by pipeline 3 for README extraction)
BLOB_STORE_FILE_ID = "20736"  # blobs-by-swhid.tar.zst


def get_token() -> Optional[str]:
    """Return the Infomaniak OAuth token from the environment, or None."""
    token = os.environ.get("INFOMANIAK_TOKEN")
    if token:
        return token
    # Colab fallback
    try:
        from google.colab import userdata
        token = userdata.get("INFOMANIAK_TOKEN")
        if token:
            os.environ["INFOMANIAK_TOKEN"] = token
            return token
    except Exception:
        pass
    return None


def _drive_id() -> str:
    return os.environ.get("KDRIVE_DRIVE_ID", _DEFAULT_DRIVE_ID)


def upload_file(file_path: str, directory_id: str) -> bool:
    """Upload a single file to a KDrive directory. Returns True on success."""
    token = get_token()
    if not token:
        logger.warning("INFOMANIAK_TOKEN not set — skipping upload of %s", file_path)
        return False
    if not Path(file_path).exists():
        logger.warning("File not found: %s", file_path)
        return False

    payload = Path(file_path).read_bytes()
    try:
        r = requests.post(
            f"{_API_BASE}/3/drive/{_drive_id()}/upload",
            headers={"Authorization": f"Bearer {token}"},
            params={"total_size": len(payload),
                    "directory_id": directory_id,
                    "file_name": Path(file_path).name},
            data=payload, timeout=120,
        )
        ok = r.status_code == 200
        logger.info("%s  %s  (HTTP %d)", "OK  " if ok else "FAIL", file_path, r.status_code)
        return ok
    except Exception as e:
        logger.warning("Upload error %s: %s", file_path, e)
        return False


def upload_files(file_paths: List[str], directory_id: str) -> int:
    """Upload multiple files; return count of successes."""
    seen: set = set()
    unique = [p for p in file_paths if p not in seen and not seen.add(p)]
    n_ok = sum(1 for p in unique if upload_file(p, directory_id))
    logger.info("Uploaded %d/%d files.", n_ok, len(unique))
    return n_ok


def download_file(file_id: str, output_path: str) -> bool:
    """Download a single file from KDrive by its file ID."""
    token = get_token()
    if not token:
        logger.warning("INFOMANIAK_TOKEN not set — cannot download file %s", file_id)
        return False
    try:
        url = f"{_API_BASE}/2/drive/{_drive_id()}/files/{file_id}/download"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         stream=True, timeout=120)
        r.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("Downloaded %s", output_path)
        return True
    except Exception as e:
        logger.warning("Download failed for file %s: %s", file_id, e)
        return False


def download_folder(folder_id: str, output_dir: str, skip_existing: bool = True) -> int:
    """Download all files from a KDrive folder. Returns count of downloaded files."""
    token = get_token()
    if not token:
        logger.warning("INFOMANIAK_TOKEN not set — cannot list KDrive folder %s", folder_id)
        return 0
    try:
        url = f"{_API_BASE}/3/drive/{_drive_id()}/files/{folder_id}/files"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        items = r.json().get("data", [])
        n_ok = 0
        for item in items:
            if item.get("type") != "file":
                continue
            dest = str(Path(output_dir) / item["name"])
            if skip_existing and Path(dest).exists():
                logger.info("Already exists: %s", dest)
                n_ok += 1
                continue
            if download_file(str(item["id"]), dest):
                n_ok += 1
        return n_ok
    except Exception as e:
        logger.warning("Folder download failed (folder=%s): %s", folder_id, e)
        return 0


def upload_pipeline1_results(artifacts: Dict[str, Dict[str, str]],
                              summary_file: Optional[str] = None) -> None:
    """Upload all Pipeline 1 artifacts to the KDrive input directory."""
    dir_id = os.environ.get("KDRIVE_INPUT_DIR", "")
    if not dir_id:
        logger.warning("KDRIVE_INPUT_DIR not set — skipping upload.")
        return
    files: List[str] = []
    for domain_artifacts in artifacts.values():
        files.extend(v for v in domain_artifacts.values() if isinstance(v, str))
    if summary_file:
        files.append(summary_file)
    upload_files(files, dir_id)


def upload_pipeline2_results(artifacts: Dict[str, Dict[str, str]],
                              summary_file: Optional[str] = None) -> None:
    """Upload all Pipeline 2 artifacts to the KDrive output directory."""
    dir_id = os.environ.get("KDRIVE_OUTPUT_DIR", "")
    if not dir_id:
        logger.warning("KDRIVE_OUTPUT_DIR not set — skipping upload.")
        return
    files: List[str] = []
    for domain_artifacts in artifacts.values():
        files.extend(v for v in domain_artifacts.values() if isinstance(v, str))
    if summary_file:
        files.append(summary_file)
    upload_files(files, dir_id)


def download_pipeline1_artifacts(output_dir: str,
                                  manifests_only: bool = False) -> int:
    """Download Pipeline 1 artifacts using the project file-ID registry.

    Falls back to KDRIVE_INPUT_DIR folder listing when that env var is set,
    which lets callers override without touching the registry.
    Set *manifests_only* to skip the heavy OWL / embeddings files and fetch
    only the four manifest/summary JSON files (used by pipelines 5 and 6).
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Prefer explicit folder override
    folder_id = os.environ.get("KDRIVE_INPUT_DIR", "")
    if folder_id:
        return download_folder(folder_id, output_dir)

    registry = PIPELINE1_MANIFEST_IDS if manifests_only else PIPELINE1_FILE_IDS
    n_ok = 0
    for name, fid in registry.items():
        dest = out / name
        if dest.exists():
            logger.info("Already exists: %s", name)
            n_ok += 1
            continue
        if download_file(fid, str(dest)):
            n_ok += 1
    return n_ok


def download_readme_cache(output_dir: str) -> int:
    """Download the three per-domain README score cache files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    n_ok = 0
    for name, fid in README_CACHE_FILE_IDS.items():
        dest = out / name
        if dest.exists():
            logger.info("Already exists: %s", name)
            n_ok += 1
            continue
        if download_file(fid, str(dest)):
            n_ok += 1
    return n_ok


def download_box2el_embeddings(output_dir: str) -> bool:
    """Download the Box²EL embeddings archive (full_box2el_embeddings.npz)."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / "box2el_embeddings.npz"
    if dest.exists():
        logger.info("Already exists: %s", dest)
        return True
    return download_file(BOX2EL_FILE_ID, str(dest))


def download_ground_truth(output_dir: str) -> int:
    """Download gt_{domain}.json and discoverable_{domain}.json from the GT folder."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    gt_files = kdrive_list_all(FOLDER_GROUND_TRUTH)
    domains = ("math", "physics", "biology")
    wanted = {
        f"gt_{d}.json"           for d in domains
    } | {
        f"discoverable_{d}.json" for d in domains
    }
    n_ok = 0
    for name, fid in gt_files.items():
        if name not in wanted:
            continue
        dest = out / name
        if dest.exists():
            logger.info("Already exists: %s", name)
            n_ok += 1
            continue
        if download_file(fid, str(dest)):
            n_ok += 1
    return n_ok


def kdrive_list_all(folder_id: str) -> Dict[str, str]:
    """Cursor-paginated folder listing → {filename: file_id}."""
    token = get_token()
    if not token:
        logger.warning("INFOMANIAK_TOKEN not set — cannot list KDrive folder %s", folder_id)
        return {}
    headers = {"Authorization": f"Bearer {token}"}
    all_files: Dict[str, str] = {}
    cursor = None
    while True:
        params: Dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(
            f"{_API_BASE}/3/drive/{_drive_id()}/files/{folder_id}/files",
            headers=headers, params=params, timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        for item in body.get("data", []):
            if item.get("type") == "file":
                all_files[item["name"]] = str(item["id"])
        if not body.get("has_more"):
            break
        cursor = body.get("cursor")
    return all_files
