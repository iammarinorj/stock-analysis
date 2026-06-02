"""Shared HTTP session: retry/backoff + optional on-disk response cache.

Every raw `requests.get` caller (FRED macro CSVs, Nasdaq calendar API) goes
through `get_session()` instead of calling `requests` directly, so they all get:

  - connection pooling — one session reused across calls
  - automatic retry with exponential backoff on transient failures
    (timeouts, 429 rate-limits, 5xx) instead of failing on the first blip
  - persistent response caching to data/http_cache.sqlite when `requests-cache`
    is installed. This survives app restarts AND, with stale_if_error, serves the
    last good response if the source is briefly down. If the library isn't
    installed the app still works — it just falls back to a plain session.

`with_retry()` is a tiny helper for the data sources we *can't* route through the
session (yfinance's curl_cffi client, the finvizfinance scraper).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, TypeVar

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry
except Exception:  # pragma: no cover - urllib3 always present in practice
    Retry = None

_CACHE_NAME = str(Path(__file__).resolve().parent.parent / "data" / "http_cache")
_session: requests.Session | None = None


def _retry_adapter() -> HTTPAdapter:
    if Retry is None:
        return HTTPAdapter(pool_connections=10, pool_maxsize=10)
    retry = Retry(
        total=3,
        backoff_factor=0.5,  # 0.5s, 1s, 2s between attempts
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    return HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)


def get_session() -> requests.Session:
    """Return the process-wide session (built once). Persistent-cached + retrying
    when possible, plain-but-retrying otherwise."""
    global _session
    if _session is not None:
        return _session

    sess: requests.Session
    try:
        import requests_cache

        sess = requests_cache.CachedSession(
            cache_name=_CACHE_NAME,
            backend="sqlite",
            expire_after=3600,          # default freshness; st.cache_data gates real calls
            allowable_codes=(200,),
            stale_if_error=True,        # serve last good response if the source is down
        )
    except Exception:
        sess = requests.Session()

    adapter = _retry_adapter()
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    _session = sess
    return sess


T = TypeVar("T")


def with_retry(fn: Callable[[], T], attempts: int = 3, backoff: float = 0.4,
               default: T | None = None) -> T | None:
    """Call fn() with up to `attempts` tries and exponential backoff.

    For sources we can't route through the shared session (yfinance, finviz).
    Returns fn()'s result, or `default` if every attempt raised.
    """
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - best-effort fetch
            last_exc = e
            if i < attempts - 1:
                time.sleep(backoff * (2 ** i))
    return default
