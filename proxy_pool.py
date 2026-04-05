"""Proxy rotation for East Money (EM) API calls in akshare.

When PROXY_API_URL env var is set, EM-domain requests are routed through
a rotating proxy pool. Non-EM requests (Sina, XQ, THS, Baidu) pass through
unchanged. When PROXY_API_URL is unset, everything is a no-op.

Usage:
    from subagent_pipeline.proxy_pool import em_proxy_session

    with em_proxy_session():
        df = ak.stock_zh_a_spot_em()   # proxied (EM domain)
    df2 = ak.stock_zh_a_daily(...)     # not proxied (Sina, outside context)

Implementation: Uses module-level function replacement (NOT unittest.mock.patch)
with threading.local for thread safety. Each thread gets its own proxy state.
"""

import logging
import os
import random
import re
import threading
import time
from contextlib import contextmanager
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
    except Exception as _e:
        logger.debug("URL parse failed for is_em_url: %s", _e)
        return False


# ── Configuration ────────────────────────────────────────────────────────

def _proxy_config() -> Optional[Dict[str, Any]]:
    """Read proxy configuration from environment.

    Returns None when PROXY_API_URL is unset (disables proxy rotation).
    """
    url = os.environ.get("PROXY_API_URL", "").strip()
    if not url:
        return None
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

    Uses *original_get* (the un-patched ``requests.get``) to avoid recursion.
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

    # Validate one proxy against EM
    test_url = "https://82.push2.eastmoney.com/api/qt/clist/get"
    for p in proxies[:3]:
        try:
            r = original_get(test_url, proxies=p, timeout=5,
                             headers={"User-Agent": "Mozilla/5.0", "Connection": "close"})
            if r.status_code in (200, 403):
                logger.info("Proxy pool validated (%d proxies)", len(proxies))
                return proxies
        except Exception as _e:
            logger.debug("Proxy validation failed: %s", _e)
            continue

    logger.warning("No proxy passed validation, returning pool anyway (%d)", len(proxies))
    return proxies


# ── Core Rotation ────────────────────────────────────────────────────────

_RETRIABLE_EXC: Tuple[type, ...] = (
    ProxyError, ConnectTimeout, ReadTimeout, SSLError,
    ConnectionError, ChunkedEncodingError,
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
                pool = list(pool) + [None]

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
                    raise
                finally:
                    try:
                        session.close()
                    except Exception:
                        pass

            logger.debug("All proxies exhausted, refreshing pool (round %d)", refresh_round)
            time.sleep(random.uniform(*backoff))

        if last_exc:
            raise last_exc
        raise RuntimeError("EM request failed: no working proxy available")

    return rotating_get


# ── Thread-safe module-level injection ───────────────────────────────────
#
# Instead of unittest.mock.patch (global, not thread-safe), we use:
# 1. Save the original requests.get at import time
# 2. Replace requests.get with a dispatcher that checks thread-local state
# 3. Each thread's em_proxy_session() sets its own rotating_get in _tls
#
# This is thread-safe: concurrent threads each have their own proxy state.

_original_requests_get = requests.get  # saved at import time
_tls = threading.local()  # thread-local storage
_active_count_lock = threading.Lock()
_active_count = 0  # how many threads have an active session


def _dispatching_get(url: str, **kwargs: Any) -> requests.Response:
    """Thread-safe dispatcher: routes to per-thread rotating_get or original."""
    rotating = getattr(_tls, "rotating_get", None)
    if rotating is not None:
        return rotating(url, **kwargs)
    return _original_requests_get(url, **kwargs)


def _install_dispatcher() -> None:
    """Replace requests.get with our dispatcher (idempotent)."""
    global _active_count
    with _active_count_lock:
        _active_count += 1
        if _active_count == 1:
            requests.get = _dispatching_get


def _uninstall_dispatcher() -> None:
    """Restore original requests.get when no sessions are active."""
    global _active_count
    with _active_count_lock:
        _active_count = max(0, _active_count - 1)
        if _active_count == 0:
            requests.get = _original_requests_get


# ── Context Manager ──────────────────────────────────────────────────────

@contextmanager
def em_proxy_session():
    """Context manager that routes EM-domain akshare calls through proxy rotation.

    Thread-safe: each thread gets its own rotating_get via threading.local.
    Replaces requests.get with a dispatcher while any session is active.

    **No-op** when ``PROXY_API_URL`` environment variable is not set.
    """
    config = _proxy_config()
    if config is None:
        yield
        return

    proxy_auth = config.get("auth")

    def supplier():
        return _fetch_proxies(config["api_url"], _original_requests_get, auth=proxy_auth)

    rotating = build_rotating_get(
        proxies_supplier=supplier,
        original_get=_original_requests_get,
        timeout=config["timeout"],
        include_direct=True,
        max_supplier_refresh=2,
    )

    # Set thread-local rotating_get and install global dispatcher
    _tls.rotating_get = rotating
    _install_dispatcher()

    # Also patch akshare's request_with_retry if present
    _orig_rwr = None
    _akfunc = None
    try:
        import akshare.utils.func as _akfunc_mod
        _akfunc = _akfunc_mod
        _orig_rwr = _akfunc.request_with_retry

        def _proxy_rwr(url, params=None, **kwargs):
            if not is_em_url(url):
                return _orig_rwr(url, params=params, **kwargs)
            kwargs.setdefault("timeout", config["timeout"])
            return rotating(url, params=params, **kwargs)

        _akfunc.request_with_retry = _proxy_rwr
    except (ImportError, AttributeError):
        pass

    try:
        logger.info("EM proxy session active (API: %s...)", config["api_url"][:40])
        yield
    finally:
        # Restore thread-local state
        _tls.rotating_get = None
        _uninstall_dispatcher()

        # Restore akshare's request_with_retry
        if _akfunc is not None and _orig_rwr is not None:
            try:
                _akfunc.request_with_retry = _orig_rwr
            except Exception:
                pass

        logger.info("EM proxy session closed")
