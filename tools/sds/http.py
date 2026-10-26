"""Cached HTTP fetches so re-running the importer is fast and deterministic."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

USER_AGENT = "sds-vault/0.1 (+https://github.com/; SDS markdown generator)"
_last_request = 0.0


def _get(url: str) -> requests.Response:
    # PubChem allows <= 5 requests/second; stay well under it.
    global _last_request
    wait = 0.3 - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    resp = requests.get(quote(url, safe=":/?=&%+"), headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp


def _cache_path(cache: str, key: str) -> Path:
    path = Path(cache) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def fetch_json(url: str, cache: str, key: str, refresh: bool = False) -> Any:
    """GET a JSON document, caching it under `cache/key`."""
    path = _cache_path(cache, key)
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    try:
        data = _get(url).json()
    except requests.HTTPError as err:
        if err.response is not None and err.response.status_code == 404:
            data = {}
        else:
            raise
    path.write_text(json.dumps(data))
    return data


def fetch_text(url: str, cache: str, key: str, refresh: bool = False) -> str:
    path = _cache_path(cache, key)
    if path.exists() and not refresh:
        return path.read_text()
    text = _get(url).text
    path.write_text(text)
    return text


def fetch_bytes(url: str, cache: str, key: str, refresh: bool = False) -> Path:
    """Download a binary file (e.g. a supplier SDS PDF) into the cache."""
    path = _cache_path(cache, key)
    if path.exists() and not refresh:
        return path
    resp = _get(url)
    path.write_bytes(resp.content)
    return path
