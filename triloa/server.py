"""Loopback-only API used by the Edge extension."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .translator import model_identity, model_session, translate_texts


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        # Windowed executables have no stderr for BaseHTTPRequestHandler.
        pass

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return not origin or origin.startswith(("chrome-extension://", "edge-extension://"))

    def _headers(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if self._origin_allowed():
            origin = self.headers.get("Origin")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._headers(status)
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self._headers(204 if self._origin_allowed() else 403)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"error": "not found"})
            return
        self._send_json(200, {"name": "Triloa", "status": "running", "offline": True,
                              "model_id": model_identity()})

    def do_POST(self) -> None:
        if self.path != "/translate":
            self._send_json(404, {"error": "not found"})
            return
        if not self._origin_allowed():
            self._send_json(403, {"error": "origin not allowed"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 262_144:
                raise ValueError("请求内容过大或为空")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("请求体必须是 JSON 对象")
            texts = payload.get("texts")
            if not isinstance(texts, list) or len(texts) > 32 or any(not isinstance(t, str) or len(t) > 10_000 for t in texts):
                raise ValueError("texts 必须是最多 32 条短文本")
            with model_session() as model_id:
                result = translate_texts(texts, payload.get("source", "auto"), payload.get("target", "zh"))
                self._send_json(200, {"translations": result, "model_id": model_id})
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": str(exc)})
        except RuntimeError as exc:
            self._send_json(503, {"error": str(exc)})


def make_server() -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", 8765), Handler)
