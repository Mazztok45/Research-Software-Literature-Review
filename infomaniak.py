"""
Infomaniak KDrive upload/download helpers (optional).

Set the following environment variables to use KDrive:
  INFOMANIAK_TOKEN  — OAuth2 bearer token
  KDRIVE_DRIVE_ID   — numeric drive ID (defaults to the project drive 705884)

All functions fail gracefully (log a warning) when the token is absent.
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

# Shared folder for downloads and uploads
FOLDER_ID = "20645"


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
    params = {
        "total_size": len(payload),
        "directory_id": directory_id,
        "file_name": Path(file_path).name,
    }
    try:
        r = requests.post(
            f"{_API_BASE}/3/drive/{_drive_id()}/upload",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
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


def delete_file(file_id: str) -> bool:
    """Delete a file from KDrive by its file ID. Returns True on success."""
    token = get_token()
    if not token:
        logger.warning("INFOMANIAK_TOKEN not set — cannot delete file %s", file_id)
        return False
    try:
        r = requests.delete(
            f"{_API_BASE}/2/drive/{_drive_id()}/files/{file_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        ok = r.status_code in (200, 204)
        logger.info("%s  delete file %s  (HTTP %d)", "OK  " if ok else "FAIL", file_id, r.status_code)
        return ok
    except Exception as e:
        logger.warning("Delete error for file %s: %s", file_id, e)
        return False


def upload_file_overwrite(file_path: str, directory_id: str) -> bool:
    """Upload a file, deleting any existing file with the same name first."""
    name = Path(file_path).name
    existing = kdrive_list_all(directory_id)
    if name in existing:
        logger.info("Deleting existing '%s' (id=%s) before upload", name, existing[name])
        delete_file(existing[name])
    return upload_file(file_path, directory_id)


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
