"""LLM providers behind one small interface, so switching only needs configuration."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_TIMEOUT_SECONDS = 600


class LLMError(RuntimeError):
    pass


class RateLimitError(LLMError):
    """The provider's quota is used up, which is the one failure that triggers fallback."""


@dataclass
class Completion:
    text: str
    provider: str


class LLMProvider(Protocol):
    name: str
    sends_data_off_machine: bool

    def complete(self, prompt: str) -> Completion: ...


def _post_json(url: str, payload: dict, headers: dict[str, str], timeout: float) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 429:
            raise RateLimitError(f"{url.split('/')[2]} rate limit reached") from error
        raise LLMError(f"request failed with HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise LLMError(f"could not reach {url.split('/')[2]}: {error}") from error


class GeminiProvider:
    name = "gemini"
    sends_data_off_machine = True

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-flash-latest",
        base_url: str = "https://generativelanguage.googleapis.com",
    ) -> None:
        self.api_key, self.model, self.base_url = api_key, model, base_url

    def complete(self, prompt: str) -> Completion:
        # The key goes in a header, not the URL, so it cannot end up in logs or errors.
        body = _post_json(
            f"{self.base_url}/v1beta/models/{self.model}:generateContent",
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0},
            },
            {"x-goog-api-key": self.api_key},
            _TIMEOUT_SECONDS,
        )
        try:
            parts = body["candidates"][0]["content"]["parts"]
            return Completion("".join(part.get("text", "") for part in parts), self.name)
        except (KeyError, IndexError) as error:
            raise LLMError(
                "Gemini returned no text, possibly blocked by a safety filter"
            ) from error


class OllamaProvider:
    name = "ollama"
    sends_data_off_machine = False

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434") -> None:
        self.model, self.base_url = model, base_url

    def complete(self, prompt: str) -> Completion:
        body = _post_json(
            f"{self.base_url}/api/generate",
            {"model": self.model, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
            {},
            _TIMEOUT_SECONDS,
        )
        if "response" not in body:
            raise LLMError("Ollama returned no response")
        return Completion(body["response"], self.name)


class FallbackProvider:
    """Moves to the next provider for the rest of the run once quota is exhausted."""

    def __init__(self, providers: list[LLMProvider]) -> None:
        self.providers = providers
        self.name = "+".join(provider.name for provider in providers)
        self.sends_data_off_machine = any(p.sends_data_off_machine for p in providers)
        self._current = 0

    def complete(self, prompt: str) -> Completion:
        while True:
            try:
                return self.providers[self._current].complete(prompt)
            except RateLimitError:
                if self._current == len(self.providers) - 1:
                    raise
                self._current += 1


def build_provider(choice: str) -> LLMProvider:
    ollama = OllamaProvider(
        model=os.environ.get("OLLAMA_MODEL", "llama3.2"),
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    if choice == "ollama":
        return ollama
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMError("GEMINI_API_KEY is not set. Use --provider ollama to stay fully local.")
    gemini = GeminiProvider(api_key, os.environ.get("GEMINI_MODEL", "gemini-flash-latest"))
    return gemini if choice == "gemini" else FallbackProvider([gemini, ollama])
