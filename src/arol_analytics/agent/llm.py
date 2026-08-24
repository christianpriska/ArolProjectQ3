# Thin client for the Ollama chat API. No OpenAI/Anthropic paid API -- but this
# works against either a local `ollama serve` (http://localhost:11434, no auth)
# or Ollama's hosted Cloud API (https://ollama.com, needs an OLLAMA_API_KEY from
# ollama.com/settings/keys) with no local install required. Setting OLLAMA_API_KEY
# switches the default host to the cloud automatically; AROL_OLLAMA_HOST always
# wins if set explicitly. Cloud model names are the plain names from GET /api/tags
# on the cloud host (e.g. "gpt-oss:120b") -- NOT the local ":cloud"-suffixed
# aliases, which only make sense when routing through a local `ollama serve`.

from __future__ import annotations

import logging
import os

import requests

logger = logging.getLogger(__name__)

OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY")
_DEFAULT_HOST = "https://ollama.com" if OLLAMA_API_KEY else "http://localhost:11434"
OLLAMA_HOST = os.environ.get("AROL_OLLAMA_HOST", _DEFAULT_HOST)
DEFAULT_MODEL = os.environ.get("AROL_LLM_MODEL", "mistral")
CONNECT_TIMEOUT_S = 5.0
CHAT_TIMEOUT_S = 120.0


class OllamaUnavailableError(RuntimeError):
    """Raised when the Ollama server (local or cloud) can't be reached or errors out."""


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {OLLAMA_API_KEY}"} if OLLAMA_API_KEY else {}


def is_ollama_available() -> bool:
    """Quick check: is an Ollama server (local or cloud) reachable at OLLAMA_HOST?"""
    try:
        resp = requests.get(f"{OLLAMA_HOST}/api/tags", headers=_headers(), timeout=CONNECT_TIMEOUT_S)
        return resp.ok
    except requests.RequestException:
        return False


def chat(messages: list[dict[str, str]], model: str | None = None, temperature: float = 0.0) -> str:
    """Send a chat request to Ollama (local or cloud) and return the assistant's text content.

    Raises OllamaUnavailableError if the server can't be reached or returns an error.
    """
    model = model or DEFAULT_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    try:
        resp = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, headers=_headers(), timeout=CHAT_TIMEOUT_S)
    except requests.RequestException as exc:
        hint = "is `ollama serve` running?" if not OLLAMA_API_KEY else "check network access to ollama.com."
        raise OllamaUnavailableError(f"Could not reach Ollama at {OLLAMA_HOST} -- {hint} ({exc})") from exc

    if not resp.ok:
        hint = " (check OLLAMA_API_KEY and that the model name is valid on ollama.com/models)" if OLLAMA_API_KEY else ""
        raise OllamaUnavailableError(f"Ollama returned HTTP {resp.status_code}{hint}: {resp.text[:500]}")

    try:
        data = resp.json()
        return data["message"]["content"]
    except (ValueError, KeyError) as exc:
        raise OllamaUnavailableError(f"Unexpected Ollama response shape: {resp.text[:500]}") from exc
