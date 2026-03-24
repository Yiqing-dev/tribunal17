"""Tests for subagent_pipeline.proxy_pool — proxy rotation for EM API calls."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch, call

import pytest
import requests

from subagent_pipeline.proxy_pool import (
    _parse_proxy_line,
    _proxy_config,
    _fetch_proxies,
    build_rotating_get,
    em_proxy_session,
    is_em_url,
)


# ── is_em_url ────────────────────────────────────────────────────────────

class TestIsEmUrl:
    @pytest.mark.parametrize("url", [
        "https://push2.eastmoney.com/api/qt/clist/get",
        "https://82.push2.eastmoney.com/api/qt/clist/get",
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        "http://eastmoney.com/path",
        "https://quote.eastmoney.com/center/gridlist.html",
    ])
    def test_em_domains_detected(self, url):
        assert is_em_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php",
        "https://stock.xueqiu.com/v5/stock/realtime/quotec.json",
        "https://gushitong.baidu.com/opendata",
        "https://data.10jqka.com.cn/",
        "https://api.example.com/",
        "",
    ])
    def test_non_em_domains_rejected(self, url):
        assert is_em_url(url) is False


# ── _parse_proxy_line ────────────────────────────────────────────────────

class TestParseProxyLine:
    def test_ip_port_user_pass(self):
        p = _parse_proxy_line("1.2.3.4:8080:user:pass")
        assert p == {"http": "http://user:pass@1.2.3.4:8080/",
                     "https": "http://user:pass@1.2.3.4:8080/"}

    def test_ip_port_no_auth(self):
        p = _parse_proxy_line("1.2.3.4:8080")
        assert p == {"http": "http://1.2.3.4:8080/",
                     "https": "http://1.2.3.4:8080/"}

    def test_url_form(self):
        p = _parse_proxy_line("http://1.2.3.4:8080")
        assert p == {"http": "http://1.2.3.4:8080",
                     "https": "http://1.2.3.4:8080"}

    def test_empty_line(self):
        assert _parse_proxy_line("") is None
        assert _parse_proxy_line("  ") is None

    def test_invalid_format(self):
        assert _parse_proxy_line("not-a-proxy") is None


# ── _proxy_config ────────────────────────────────────────────────────────

class TestProxyConfig:
    def test_none_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure PROXY_API_URL is not in environment
            os.environ.pop("PROXY_API_URL", None)
            assert _proxy_config() is None

    def test_reads_env(self):
        with patch.dict(os.environ, {"PROXY_API_URL": "https://proxy.example.com/get"}):
            cfg = _proxy_config()
            assert cfg is not None
            assert cfg["api_url"] == "https://proxy.example.com/get"
            assert cfg["timeout"] == 20  # default

    def test_custom_timeout(self):
        with patch.dict(os.environ, {"PROXY_API_URL": "http://x", "PROXY_TIMEOUT": "30"}):
            cfg = _proxy_config()
            assert cfg["timeout"] == 30

    def test_empty_url_is_none(self):
        with patch.dict(os.environ, {"PROXY_API_URL": "  "}):
            assert _proxy_config() is None


# ── _fetch_proxies ───────────────────────────────────────────────────────

class TestFetchProxies:
    def test_parses_response(self):
        mock_get = MagicMock()
        # Supplier response
        supplier_resp = MagicMock()
        supplier_resp.text = "1.2.3.4:8080:user:pass\n5.6.7.8:9090:u2:p2"
        supplier_resp.raise_for_status = MagicMock()
        # Validation response
        validation_resp = MagicMock()
        validation_resp.status_code = 200
        mock_get.side_effect = [supplier_resp, validation_resp]

        result = _fetch_proxies("http://api.example.com/get", mock_get)
        assert len(result) == 2
        assert "http" in result[0]

    def test_empty_on_fetch_error(self):
        mock_get = MagicMock(side_effect=Exception("network down"))
        result = _fetch_proxies("http://api.example.com/get", mock_get)
        assert result == []

    def test_empty_on_empty_response(self):
        mock_get = MagicMock()
        resp = MagicMock()
        resp.text = ""
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp
        result = _fetch_proxies("http://api.example.com/get", mock_get)
        assert result == []


# ── build_rotating_get ───────────────────────────────────────────────────

def _mock_response(status=200, text="ok"):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


class TestBuildRotatingGet:
    def _build(self, supplier_returns=None, original_returns=None, **kwargs):
        supplier = MagicMock(return_value=supplier_returns or [])
        original = MagicMock(return_value=original_returns or _mock_response())
        defaults = dict(
            proxies_supplier=supplier,
            original_get=original,
            timeout=5,
            per_proxy_retries=0,
            backoff=(0.0, 0.01),
            include_direct=True,
            max_supplier_refresh=0,
        )
        defaults.update(kwargs)
        fn = build_rotating_get(**defaults)
        return fn, supplier, original

    def test_non_em_url_passthrough(self):
        """Non-EM URLs delegate to original_get, no proxy."""
        fn, supplier, original = self._build()
        resp = fn("https://money.finance.sina.com.cn/data")
        original.assert_called_once()
        supplier.assert_not_called()

    def test_em_url_uses_proxy(self):
        """EM URLs go through proxy rotation."""
        proxy = {"http": "http://1.2.3.4:8080/", "https": "http://1.2.3.4:8080/"}
        fn, supplier, original = self._build(supplier_returns=[proxy])

        # Patch Session.get to succeed
        mock_resp = _mock_response()
        with patch("subagent_pipeline.proxy_pool.requests.Session") as MockSession:
            session_instance = MagicMock()
            session_instance.get.return_value = mock_resp
            MockSession.return_value = session_instance
            resp = fn("https://push2.eastmoney.com/api/qt/clist/get")

        assert resp == mock_resp
        supplier.assert_called()

    def test_direct_fallback_when_no_proxies(self):
        """include_direct=True adds None (direct) to pool."""
        fn, supplier, original = self._build(
            supplier_returns=[], include_direct=True
        )

        mock_resp = _mock_response()
        with patch("subagent_pipeline.proxy_pool.requests.Session") as MockSession:
            session_instance = MagicMock()
            session_instance.get.return_value = mock_resp
            MockSession.return_value = session_instance
            resp = fn("https://push2.eastmoney.com/api/qt/clist/get")

        assert resp == mock_resp

    def test_all_fail_raises(self):
        """All proxies + direct fail → raises last exception."""
        fn, supplier, original = self._build(
            supplier_returns=[], include_direct=True, max_supplier_refresh=0
        )

        with patch("subagent_pipeline.proxy_pool.requests.Session") as MockSession:
            session_instance = MagicMock()
            session_instance.get.side_effect = ConnectionError("refused")
            MockSession.return_value = session_instance
            with pytest.raises(ConnectionError):
                fn("https://push2.eastmoney.com/api/qt/clist/get")

    def test_supplier_refresh_on_exhaustion(self):
        """When all proxies fail, supplier is called again."""
        call_count = [0]
        def counting_supplier():
            call_count[0] += 1
            return []  # always empty

        fn = build_rotating_get(
            proxies_supplier=counting_supplier,
            original_get=MagicMock(),
            timeout=5,
            per_proxy_retries=0,
            backoff=(0.0, 0.01),
            include_direct=False,
            max_supplier_refresh=2,
        )

        with pytest.raises((RuntimeError, Exception)):
            fn("https://push2.eastmoney.com/api/data")

        assert call_count[0] == 3  # initial + 2 refreshes


# ── em_proxy_session ─────────────────────────────────────────────────────

class TestEmProxySession:
    def test_noop_when_unconfigured(self):
        """No PROXY_API_URL → requests.get is not patched."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PROXY_API_URL", None)
            original = requests.get
            with em_proxy_session():
                assert requests.get is original

    def test_patches_requests_get_when_configured(self):
        """PROXY_API_URL set → requests.get IS patched inside context."""
        with patch.dict(os.environ, {"PROXY_API_URL": "http://proxy.test/get"}):
            original = requests.get
            with patch("subagent_pipeline.proxy_pool._fetch_proxies", return_value=[]):
                with em_proxy_session():
                    assert requests.get is not original
            # Restored after context
            assert requests.get is original

    def test_restores_on_exception(self):
        """requests.get restored even if body raises."""
        original = requests.get
        with patch.dict(os.environ, {"PROXY_API_URL": "http://proxy.test/get"}):
            with patch("subagent_pipeline.proxy_pool._fetch_proxies", return_value=[]):
                try:
                    with em_proxy_session():
                        raise ValueError("boom")
                except ValueError:
                    pass
            assert requests.get is original

    def test_composes_with_retry(self):
        """em_proxy_session can be nested inside _retry_call-like logic."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PROXY_API_URL", None)
            results = []
            for _ in range(3):
                with em_proxy_session():
                    results.append("ok")
            assert len(results) == 3
