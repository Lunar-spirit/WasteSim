"""Direct calls to whichever chat-completion provider is configured, for the
freeform (non-tool, non-FAQ) reply path in app/chat/service.py's
answer_chat_message(). OpenAI and Ollama are called via plain httpx REST
requests rather than pulling in the `openai` SDK as a new dependency — it
isn't in the project's approved stack (CLAUDE.md section 4) and a single
chat-completion call doesn't need it; `anthropic` was already installed and
used elsewhere in this module before this file existed, so that one keeps
its own SDK.

Every function returns None on any failure whatsoever — no key/URL
configured, timeout, non-2xx, malformed body — so the caller always has a
safe path to a deterministic fallback instead of a 500 (the same contract
app/chat/router_llm.py's llm_match() already established for intent
extraction, extended here to two more providers and to freeform prose).
"""

from __future__ import annotations

import asyncio

import httpx

from app.core.config import settings

_TIMEOUT_SECONDS = 12.0


def _anthropic_reply(system: str, history: list[dict[str, str]], message: str) -> str | None:
    if not settings.anthropic_api_key:
        return None
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=500,
            system=system,
            messages=[*history, {"role": "user", "content": message}],
        )
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        return text or None
    except Exception:
        return None


async def _openai_reply(system: str, history: list[dict[str, str]], message: str) -> str | None:
    if not settings.openai_api_key:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": [{"role": "system", "content": system}, *history, {"role": "user", "content": message}],
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            return text or None
    except Exception:
        return None


async def _ollama_reply(system: str, history: list[dict[str, str]], message: str) -> str | None:
    if not settings.ollama_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"{settings.ollama_url.rstrip('/')}/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [{"role": "system", "content": system}, *history, {"role": "user", "content": message}],
                    "stream": False,
                },
            )
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "").strip()
            return text or None
    except Exception:
        return None


async def call_llm(system: str, history: list[dict[str, str]], message: str) -> str | None:
    """Anthropic, then OpenAI, then Ollama — first configured-and-reachable
    provider wins. None means none of the three (including "none
    configured") produced a usable reply; the caller falls back."""
    reply = await asyncio.to_thread(_anthropic_reply, system, history, message)
    if reply:
        return reply
    reply = await _openai_reply(system, history, message)
    if reply:
        return reply
    return await _ollama_reply(system, history, message)


def any_provider_configured() -> bool:
    return bool(settings.anthropic_api_key or settings.openai_api_key or settings.ollama_url)


__all__ = ["call_llm", "any_provider_configured"]
