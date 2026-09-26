"""Pure protocol helpers for the public fnOS store endpoints."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urljoin

DEFAULT_BASE_URL = "https://aps.fnnas.com/api/v1"
DEFAULT_LIVEUPDATE_URL = "https://apiv2-liveupdate.fnnas.com/"
PLATFORMS = ("x86", "arm")
MACHINE_ID = hashlib.sha1(b"fnos-store-external").hexdigest()


def endpoint(base_url: str, path: str) -> str:
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def liveupdate_endpoint(base_url: str, platform: str) -> str:
    return f"{base_url.rstrip('/')}/?platform={platform}"


def parse_trim_version(payload: Any) -> str:
    """Read the last ``trim`` package version from a liveupdate response."""

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", errors="ignore")
    if isinstance(payload, str):
        data, _ = json.JSONDecoder().raw_decode(payload.lstrip())
    else:
        data = payload
    packages = data.get("packages") if isinstance(data, dict) else None
    versions = [
        str(item["version"])
        for item in packages or []
        if isinstance(item, dict)
        and item.get("packageName") == "trim"
        and item.get("version")
    ]
    if not versions:
        raise ValueError("the liveupdate response has no trim package")
    return versions[-1]


def request_headers(*, platform: str, os_version: str, machine_id: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "fnos-store/1.0",
        "trim-platform": platform,
        "trim-os-version": os_version,
        "trim-machine-id": machine_id,
    }


def safe_output_name(app_name: str, version: str | None) -> str:
    raw = f"{app_name}-{version or 'unknown'}.fpk"
    result = "".join(char if char.isalnum() or char in "._-" else "_" for char in raw)
    return result if result.endswith(".fpk") else "package.fpk"


def compact(values: dict[str, Any]) -> dict[str, Any]:
    """Omit unavailable optional values without inventing replacement fields."""

    return {key: value for key, value in values.items() if value not in (None, "", [])}


def user_app(item: dict[str, Any], *, platform: str) -> dict[str, Any]:
    """Convert a catalog item to the compact user-facing list shape."""

    result = compact({
        "appName": item.get("appName"),
        "name": item.get("displayName"),
        "version": item.get("lastVersion"),
        "versionId": item.get("lastVersionId"),
        "source": item.get("source"),
        "platform": platform,
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "icon": item.get("icon"),
    })
    if item.get("isBeta"):
        result["beta"] = True
    if item.get("isDocker"):
        result["docker"] = True
    return result
