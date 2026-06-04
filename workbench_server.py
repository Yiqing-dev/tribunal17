"""Local product server for the static report workbench.

It serves generated files from ``data/reports`` and adds a tiny JSON API for
state writeback, daily review refresh, and calibration refresh.
"""

from __future__ import annotations

import argparse
import json
import logging
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from .workbench_monitor import run_review_monitor_once
from .workbench_state import load_workbench_state, merge_workbench_state, save_workbench_state

logger = logging.getLogger(__name__)


class PayloadTooLarge(ValueError):
    """Request JSON body exceeds the local API safety limit."""


class WorkbenchRequestHandler(SimpleHTTPRequestHandler):
    """Serve static report files plus local JSON APIs."""

    output_dir: Path
    storage_dir: Path
    max_json_bytes: int = 2_000_000

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/workbench/state":
                return self._json_response(load_workbench_state(self.output_dir))
            if path == "/api/workbench/health":
                return self._json_response({"ok": True})
        except Exception as e:
            return self._api_error(e)
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/workbench/state":
                payload = self._read_json()
                merged = merge_workbench_state(payload, self.output_dir)
                return self._json_response({"ok": True, "state": merged})
            if path == "/api/workbench/state/replace":
                payload = self._read_json()
                save_workbench_state(payload, self.output_dir)
                return self._json_response({"ok": True, "state": load_workbench_state(self.output_dir)})
            if path == "/api/workbench/review/run":
                report = run_review_monitor_once(
                    output_dir=str(self.output_dir),
                    storage_dir=str(self.storage_dir),
                )
                return self._json_response({"ok": True, "report": report.to_dict()})
            if path == "/api/workbench/calibration/run":
                from .renderers.calibration_renderer import generate_calibration_page

                result = generate_calibration_page(
                    output_dir=str(self.output_dir),
                    auto_build=True,
                )
                return self._json_response({"ok": True, "path": result})
        except PayloadTooLarge as e:
            return self._api_error(e, status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        except Exception as e:
            return self._api_error(e)
        self.send_error(HTTPStatus.NOT_FOUND, "unknown API endpoint")

    def _read_json(self) -> Dict[str, Any]:
        try:
            n = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            n = 0
        if n <= 0:
            return {}
        if n > self.max_json_bytes:
            raise PayloadTooLarge(f"JSON body too large: {n} bytes")
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _json_response(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api_error(self, exc: Exception, status: int = HTTPStatus.INTERNAL_SERVER_ERROR) -> None:
        logger.warning("Workbench API error: %s", exc, exc_info=True)
        return self._json_response({"ok": False, "error": str(exc)}, status=int(status))


def serve_workbench(
    *,
    output_dir: str = "data/reports",
    storage_dir: str = "data/replays",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    """Start a local workbench server and block forever."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    WorkbenchRequestHandler.output_dir = out
    WorkbenchRequestHandler.storage_dir = Path(storage_dir).resolve()
    handler = partial(WorkbenchRequestHandler, directory=str(out))
    server = ThreadingHTTPServer((host, int(port)), handler)
    logger.info("Serving workbench at http://%s:%s/workbench.html", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the TradingAgents workbench locally.")
    parser.add_argument("--output-dir", default="data/reports")
    parser.add_argument("--storage-dir", default="data/replays")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    serve_workbench(
        output_dir=args.output_dir,
        storage_dir=args.storage_dir,
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
