"""Thin LLM client: Gemini (default, as in the W4 course material), Groq, or any OpenAI-compatible API.

The API key stays on the server. Responses are cached by prompt hash to cut cost/latency.
If no key is configured every call returns None and the app falls back to rule-based logic.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time

import httpx

from .. import db
from ..config import settings

log = logging.getLogger(__name__)
STATS = {"calls": 0, "cache_hits": 0, "errors": 0, "last_latency_ms": None}


def enabled() -> bool:
    return settings.llm_enabled and not settings.demo_mode


def _strip_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    m = re.search(r"[\[{].*[\]}]", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


GEMINI_FALLBACKS = ["gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]
_RETRY = {429, 500, 502, 503, 504}
_dead: dict[str, float] = {}  # model -> time it last failed with a retryable/unknown-model error


def _gemini(system: str, user: str, json_mode: bool) -> str:
    """Try the configured model, then lighter fallbacks; overloaded models (503) are skipped for 10 minutes."""
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        # newer Gemini models deprecate sampling parameters (temperature/top_p/top_k)
        "generationConfig": {"maxOutputTokens": 4096},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    models = [settings.gemini_model] + [m for m in GEMINI_FALLBACKS if m != settings.gemini_model]
    live = [m for m in models if time.time() - _dead.get(m, 0) > 600] or models
    last = None
    for model in live:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(2):
            # key in a header, never in the URL (URLs end up in access logs)
            r = httpx.post(url, headers={"x-goog-api-key": settings.gemini_api_key}, json=body, timeout=90)
            if r.status_code < 400:
                cands = r.json().get("candidates", [])
                parts = cands[0].get("content", {}).get("parts", []) if cands else []
                STATS["model"] = model
                return "".join(p.get("text", "") for p in parts)
            last = f"{model}: HTTP {r.status_code} {r.text[:160]}"
            if r.status_code in _RETRY and attempt == 0:
                time.sleep(1.5)
                continue
            break
        if r.status_code in _RETRY or r.status_code == 404:
            _dead[model] = time.time()
            continue
        break  # 400/401/403: a request or key problem, other models will not help
    raise RuntimeError(last or "Gemini call failed")


def _openai_like(base: str, key: str, model: str, system: str, user: str, json_mode: bool) -> str:
    body = {"model": model, "temperature": 0.1, "max_tokens": 4096,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = httpx.post(f"{base}/chat/completions", json=body, timeout=60,
                   headers={"Authorization": f"Bearer {key}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def _call(system: str, user: str, json_mode: bool) -> str | None:
    if not enabled():
        return None
    key = "llm:" + hashlib.sha256(f"{settings.llm_label}|{json_mode}|{system}|{user}".encode()).hexdigest()
    hit = db.cache_get(key)
    if hit is not None:
        STATS["cache_hits"] += 1
        return hit
    t0 = time.time()
    try:
        p = settings.llm_provider
        if p == "gemini":
            out = _gemini(system, user, json_mode)
        elif p == "groq":
            out = _openai_like("https://api.groq.com/openai/v1", settings.groq_api_key, settings.groq_model,
                               system, user, json_mode)
        else:
            out = _openai_like(settings.openai_base_url, settings.openai_api_key, settings.openai_model,
                               system, user, json_mode)
    except Exception as e:  # network, quota, safety block ...
        STATS["errors"] += 1
        log.warning("LLM call failed: %s", e)
        return None
    STATS["calls"] += 1
    STATS["last_latency_ms"] = int((time.time() - t0) * 1000)
    if out:
        db.cache_set(key, out)
    return out


def complete_json(system: str, user: str):
    raw = _call(system, user, json_mode=True)
    return _strip_json(raw) if raw else None


def complete_text(system: str, user: str) -> str | None:
    return _call(system, user, json_mode=False)
