"""Testler icin denetimli sahte Ollama servisi.

Sadece calistiricinin davranisini sinar. Bu servisin dondurdugu metinler
gercek model ciktisi DEGILDIR ve model kalitesi hakkinda hicbir sey soylemez.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> "FakeOllama":
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, *args) -> None:  # testleri sessiz tut
        pass

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/version":
            self._send_json(200, {"version": "0.0.0-test"})
        elif self.path == "/api/tags":
            self._send_json(
                200,
                {
                    "models": [
                        {
                            "name": self.app.model,
                            "model": self.app.model,
                            "digest": "deadbeefcafe0123456789abcdef0123456789abcdef0123456789abcdef0123",
                        }
                    ]
                },
            )
        else:
            self._send_json(404, {"error": "bilinmeyen yol"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8")

        if self.path == "/api/show":
            self._send_json(
                200,
                {
                    "details": {"family": "test", "parameter_size": "4B"},
                    "parameters": "num_ctx 4096",
                    "capabilities": ["completion"],
                    "model_info": {"general.architecture": "test"},
                },
            )
            return

        if self.path != "/api/chat":
            self._send_json(404, {"error": "bilinmeyen yol"})
            return

        self.app.chat_requests.append(json.loads(raw))
        behavior = self.app.next_behavior()
        kind = behavior.get("kind", "ok")

        if kind == "hang":
            time.sleep(behavior.get("seconds", 3))
            try:
                self._send_json(200, {"message": {"role": "assistant", "content": "gec geldi"}})
            except OSError:
                # Istemci zaman asimina ugrayip soketi kapatmis olabilir; beklenen durum.
                self.close_connection = True
            return

        if kind == "bad_json":
            self._send(200, b"bu bir JSON degil {{{", content_type="application/json")
            return

        if kind == "raw_text":
            # Govdeyi oldugu gibi gonderir (ör. 1e999 gibi json.dumps'in uretemeyecegi sayilar).
            self._send(200, behavior["body"].encode("utf-8"))
            return

        if kind == "http_error":
            self._send_json(behavior.get("status", 500), {"error": "sahte sunucu hatasi"})
            return

        if kind == "raw_json":
            # Gecerli JSON ama beklenmeyen yapi (liste, null, yanlis tipte alanlar...).
            self._send(200, json.dumps(behavior["payload"]).encode("utf-8"))
            return

        if kind == "incomplete":
            # Content-Length'ten az bayt gonderip baglantiyi kapatir -> IncompleteRead.
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "1000")
            self.end_headers()
            self.wfile.write(b'{"message": {"con')
            self.wfile.flush()
            self.close_connection = True
            return

        content = behavior.get("content", "sahte yanit")
        done_reason = "stop"
        if kind == "length":
            done_reason = "length"
        elif kind == "empty":
            content = ""

        payload = {
            "model": self.app.model,
            "created_at": "2026-09-24T00:00:00Z",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": done_reason,
            "prompt_eval_count": 123,
            "eval_count": 45,
            "total_duration": 2_500_000_000,
            "load_duration": 1_000_000_000,
            "prompt_eval_duration": 300_000_000,
            "eval_duration": 1_200_000_000,
        }
        payload.update(behavior.get("override", {}))
        for field in behavior.get("drop", []):
            payload.pop(field, None)
        self._send_json(200, payload)


class FakeOllama:
    """Senaryolu sahte servis. `behaviors` sirayla tuketilir; son davranis tekrarlanir."""

    def __init__(self, behaviors: list[dict] | None = None, model: str = "sahte-model:test") -> None:
        self.model = model
        self.behaviors = list(behaviors or [{"kind": "ok"}])
        self.chat_requests: list[dict] = []
        self._index = 0
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.app = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def next_behavior(self) -> dict:
        behavior = self.behaviors[min(self._index, len(self.behaviors) - 1)]
        self._index += 1
        return behavior

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "FakeOllama":
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
