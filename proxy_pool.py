"""Proxy rotation for East Money (EM) API calls in akshare.

When PROXY_API_URL env var is set, EM-domain requests are routed through
a rotating proxy pool. Non-EM requests (Sina, XQ, THS, Baidu) pass through
unchanged. When PROXY_API_URL is unset, everything is a no-op.

Usage:
    from subagent_pipeline.proxy_pool import em_proxy_session

    with em_proxy_session():
        df = ak.stock_zh_a_spot_em()   # proxied (EM domain)
    df2 = ak.stock_zh_a_daily(...)     # not proxied (Sina, outside context)

Ported from akshare-stock-data-fetcher/stock_zh_a_spot_em_proxy_strength.py.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,
    ConnectTimeout,
    ProxyError,
    ReadTimeout,
    SSLError,
)
from unittest.mock import patch

try:
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    Retry = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

# ── EM Domain Detection ──────────────────────────────────────────────────

_EM_DOMAIN = "eastmoney.com"


def is_em_url(url: str) -> bool:
    """Check if *url* targets an East Money domain."""
    try:
        host = urlparse(url).hostname or ""
        return host.endswith(_EM_DOMAIN)
    except Exception:
        return False


# ── Configuration ────────────────────────────────────────────────────────

def _proxy_config() -> Optional[Dict[str, Any]]:
    """Read proxy configuration from environment.

    Returns None when PROXY_API_URL is unset (disables proxy rotation).
    """
    url = os.environ.get("PROXY_API_URL", "").strip()
    if not url:
        return None
    # PROXY_AUTH format: "username:password" — applied to all extracted proxies
    auth = os.environ.get("PROXY_AUTH", "").strip()
    return {
        "api_url": url,
        "timeout": int(os.environ.get("PROXY_TIMEOUT", "20")),
        "auth": auth if auth else None,
    }


# ── Proxy Supplier ──────────────────────────────────────────────────────

def _parse_proxy_line(line: str, auth: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Parse a single proxy line.

    Supports formats:
      ip:port                     (no auth, or uses *auth*)
      ip:port:username:password   (inline auth)
      http://ip:port              (URL form)

    *auth*: Optional ``"username:password"`` applied when the line is ``ip:port``.
    """
    line = line.strip()
    if not line:
        return None

    # Already a URL
    if line.startswith("http://") or line.startswith("https://"):
        return {"http": line, "https": line}

    parts = line.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        url = f"http://{user}:{pwd}@{ip}:{port}/"
        return {"http": url, "https": url}
    elif len(parts) == 2:
        ip, port = parts
        if auth:
            url = f"http://{auth}@{ip}:{port}/"
        else:
            url = f"http://{ip}:{port}/"
        return {"http": url, "https": url}
    return None


def _fetch_proxies(api_url: str, original_get: Callable,
                   auth: Optional[str] = None) -> List[Dict[str, str]]:
    """Fetch proxy list from supplier API and validate against EM endpoint.

    Uses *original_get* (the un-patched ``requests.get``) to avoid recursion
    when ``requests.get`` is already patched by ``em_proxy_session``.
    *auth*: Optional ``"username:password"`` applied to ``ip:port`` proxies.
    """
    try:
        resp = original_get(api_url, timeout=10)
        resp.raise_for_status()
        text = resp.text.strip()
    except Exception as e:
        logger.warning("Proxy supplier fetch failed: %s", e)
        return []

    proxies: List[Dict[str, str]] = []
    for line in text.splitlines():
        p = _parse_proxy_line(line, auth=auth)
        if p:
            proxies.append(p)

    if not proxies:
        logger.warning("Proxy supplier returned no valid proxies")
        return []

    # Validate one proxy against EM to confirm the pool is alive
    test_url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    for p in proxies[:3]:  # test first 3 at most
        try:
            r = original_get(test_url, proxies=p, timeout=5,
                             headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
            if r.status_code in (200, 403):  # 403 = reached EM, just no valid params
                logger.info("Proxy pool validated (%d proxies)", len(proxies))
                return proxies
        except Exception:
            continue

    logger.warning("No proxy passed validation, returning pool anyway (%d)", len(proxies))
    return proxies


# ── Core Rotation ────────────────────────────────────────────────────────

_RETRIABLE_EXC: Tuple[type, ...] = (
    ProxyError, ConnectTimeout, ReadTimeout, SSLError,
    ConnectionError, ChunkedEncodingError,
    # Low-level network errors (narrowed from OSError)
    ConnectionResetError, BrokenPipeError,
)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


def build_rotating_get(
    proxies_supplier: Callable[[], List[Optional[Dict[str, str]]]],
    original_get: Callable,
    timeout: int = 20,
    per_proxy_retries: int = 1,
    backoff: Tuple[float, float] = (0.3, 0.8),
    include_direct: bool = True,
    max_supplier_refresh: int = 2,
) -> Callable:
    """Build a rotating-proxy GET function.

    Returns a callable with the same signature as ``requests.get``.
    Only EM-domain URLs are proxied; others delegate to *original_get*.
    """

    def rotating_get(url: str, **kwargs: Any) -> requests.Response:
        # Non-EM URLs pass through unchanged
        if not is_em_url(url):
            return original_get(url, **kwargs)

        last_exc: Optional[Exception] = None

        for refresh_round in range(max_supplier_refresh + 1):
            try:
                pool = proxies_supplier() or []
            except Exception as e:
                pool = []
                last_exc = e

            if include_direct:
                pool = list(pool) + [None]  # None = direct connection

            random.shuffle(pool)

            for proxy in pool:
                session = requests.Session()
                try:
                    session.trust_env = False
                    session.headers.update({
                        "User-Agent": _UA,
                        "Accept": "*/*",
                        "Connection": "close",
                        "Referer": "https://quote.eastmoney.com/",
                    })
                    if proxy:
                        session.proxies.update(proxy)

                    if Retry is not None:
                        retry = Retry(
                            total=per_proxy_retries,
                            connect=per_proxy_retries,
                            read=per_proxy_retries,
                            backoff_factor=0.5,
                            status_forcelist=[429, 500, 502, 503, 504],
                            allowed_methods=["GET"],
                            raise_on_status=False,
                        )
                        adapter = HTTPAdapter(max_retries=retry,
                                              pool_connections=1, pool_maxsize=1)
                        session.mount("http://", adapter)
                        session.mount("https://", adapter)

                    req_kwargs = dict(kwargs)
                    req_kwargs.setdefault("timeout", timeout)

                    resp = session.get(url, **req_kwargs)
                    resp.raise_for_status()
                    return resp

                except _RETRIABLE_EXC as e:
                    last_exc = e
                    tag = re.sub(r'://[^@]+@', '://***@', str(proxy))[:40] if proxy else "direct"
                    logger.debug("Proxy %s failed for %s: %s", tag, url[:60], e)
                    time.sleep(random.uniform(*backoff))
                    continue
                except Exception:
                    # Non-retriable (ValueError, etc.) — fail fast
                    raise
                finally:
                    try:
                        session.close()
                    except Exception:
                        pass

            # All proxies in this pool exhausted — refresh
            logger.debug("All proxies exhausted, refreshing pool (round %d)", refresh_round)
            time.sleep(random.uniform(*backoff))

        # Every refresh round failed
        if last_exc:
            raise last_exc
        raise RuntimeError("EM request failed: no working proxy available")

    return rotating_get


# ── Context Manager ──────────────────────────────────────────────────────

@contextmanager
def em_proxy_session():
    """Context manager that routes EM-domain akshare calls through proxy rotation.

    Patches ``requests.get`` and (if available) ``akshare.utils.func.request_with_retry``
    so that akshare's internal HTTP calls are intercepted.

    **No-op** when ``PROXY_API_URL`` environment variable is not set.
    """
    config = _proxy_config()
    if config is None:
        yield
        return

    # Save original before patching (critical for recursion prevention)
    original_get = requests.get

    proxy_auth = config.get("auth")

    def supplier():
        # Temporarily restore original get so proxy fetching works
        with patch("requests.get", new=original_get):
            return _fetch_proxies(config["api_url"], original_get, auth=proxy_auth)

    rotating = build_rotating_get(
        proxies_supplier=supplier,
        original_get=original_get,
        timeout=config["timeout"],
        include_direct=True,
        max_supplier_refresh=2,
    )

    # WARNING: Global monkey-patch of requests.get. NOT thread-safe —
    # concurrent threads share the same rotated proxy. Acceptable for the
    # current single-threaded pipeline; refactor to session-level injection
    # before any multi-threaded usage.
    patches = [patch("requests.get", new=rotating)]

    # Also patch akshare's request_with_retry (used by stock_zh_a_spot_em)
    try:
        import akshare.utils.func as _akfunc
        _orig_rwr = _akfunc.request_with_retry

        def _proxy_rwr(url, params=None, **kwargs):
            if not is_em_url(url):
                return _orig_rwr(url, params=params, **kwargs)
            kwargs.setdefault("timeout", config["timeout"])
            return rotating(url, params=params, **kwargs)

        patches.append(patch.object(_akfunc, "request_with_retry", new=_proxy_rwr))
    except (ImportError, AttributeError):
        pass  # akshare version without request_with_retry — skip

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        logger.info("EM proxy session active (API: %s...)", config["api_url"][:40])
        yield

    logger.info("EM proxy session closed")
