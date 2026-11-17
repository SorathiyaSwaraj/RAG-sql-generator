import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from schema_rag.generation.llm import (
    Completion,
    FallbackProvider,
    GeminiProvider,
    LLMError,
    OllamaProvider,
    RateLimitError,
)


class ScriptedProvider:
    name = "scripted"
    sends_data_off_machine = False

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return Completion(self.answers.pop(0), self.name)


class _Handler(BaseHTTPRequestHandler):
    status = 200
    body: dict = {}
    seen: list = []

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        headers = {name.lower(): value for name, value in self.headers.items()}
        type(self).seen.append((self.path, headers, payload))
        self.send_response(self.status)
        self.end_headers()
        self.wfile.write(json.dumps(self.body).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    handler = type("Handler", (_Handler,), {"seen": []})
    httpd = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield handler, f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_gemini_request_and_response_format(server):
    handler, url = server
    handler.body = {"candidates": [{"content": {"parts": [{"text": "SELECT 1"}]}}]}

    completion = GeminiProvider("key123", "m", url).complete("hello")

    path, headers, payload = handler.seen[0]
    assert completion.text == "SELECT 1"
    assert path == "/v1beta/models/m:generateContent"
    assert "key123" not in path
    assert headers["x-goog-api-key"] == "key123"
    assert payload["contents"][0]["parts"][0]["text"] == "hello"


def test_gemini_429_is_rate_limit(server):
    handler, url = server
    handler.status = 429

    with pytest.raises(RateLimitError):
        GeminiProvider("k", "m", url).complete("hello")


def test_gemini_blocked_response_is_an_error(server):
    handler, url = server
    handler.body = {"candidates": []}

    with pytest.raises(LLMError):
        GeminiProvider("k", "m", url).complete("hello")


def test_ollama_request_and_response_format(server):
    handler, url = server
    handler.body = {"response": "SELECT 2"}

    completion = OllamaProvider("m", url).complete("hello")

    assert completion.text == "SELECT 2"
    assert handler.seen[0][0] == "/api/generate"
    assert handler.seen[0][2]["stream"] is False


class _Limited:
    name = "limited"
    sends_data_off_machine = True
    calls = 0

    def complete(self, prompt):
        self.calls += 1
        raise RateLimitError("quota")


def test_fallback_switches_on_rate_limit_and_stays_switched():
    limited = _Limited()
    local = ScriptedProvider("one", "two")
    provider = FallbackProvider([limited, local])

    assert provider.complete("a").provider == "scripted"
    assert provider.complete("b").text == "two"
    assert limited.calls == 1


def test_fallback_does_not_hide_other_errors():
    class Broken:
        name = "broken"
        sends_data_off_machine = True

        def complete(self, prompt):
            raise LLMError("bad key")

    with pytest.raises(LLMError, match="bad key"):
        FallbackProvider([Broken(), ScriptedProvider("x")]).complete("a")
