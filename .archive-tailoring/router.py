"""
Routes both generation AND embedding calls across multiple free-tier
providers, in priority order, tracking daily usage locally
(usage_state.json) so it can skip a provider proactively once it's near
its free-tier cap -- not just react to a 429 after the fact.

- `generate()`: resume tailoring, via each provider's /chat/completions
  endpoint.
- `embed()`: semantic match-scoring, via each provider's /embeddings
  endpoint (OpenAI-compatible). No local model required.

All providers here are called through OpenAI-compatible endpoints (Groq,
OpenRouter, Mistral, and Gemini's OpenAI-compatibility layer all support
this), so adding a new provider is just a new block in config.yaml's
`providers` list -- no new code needed unless a provider's shape genuinely
differs.

API keys are read from environment variables (the names in each provider's
`api_key_env` field). A .env file in this directory is auto-loaded into
the environment if present, so `python main.py` just works without manual
exports.

Free-tier limits and even model availability change often and aren't
guaranteed by anyone -- the numbers in config.yaml's comments are a
starting point, not a promise. Treat 429s as normal and expected, not bugs.
"""
import json
import os
import threading
import time
from datetime import date

import requests
import yaml


class RateLimited(Exception):
    pass


class _RateLimiter:
    """Min-interval throttle: no more than `requests_per_minute` calls per
    minute (spacing = 60/rpm seconds). Shared across all outbound requests
    so the whole pipeline respects the cap together."""

    def __init__(self, requests_per_minute: int = 0):
        x = float(requests_per_minute or 0)
        self._min_interval = (60.0 / x) if x > 0 else 0.0
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        if self._min_interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._last + self._min_interval - now
            if wait > 0:
                print(f"[router] rate limit: waiting {wait:.0f}s "
                      f"({60.0 / self._min_interval:.0f} req/min cap)")
                time.sleep(wait)
                now = time.monotonic()
            self._last = now


def _load_dotenv(path=".env"):
    """Minimal dotenv loader: sets unset env vars from KEY=VALUE lines."""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()


def _usage_path(cfg: dict) -> str:
    return cfg.get("paths", {}).get("usage_state", "usage_state.json")


def _load_usage(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def _save_usage(path: str, usage: dict):
    with open(path, "w") as f:
        json.dump(usage, f, indent=2)


def _today() -> str:
    return date.today().isoformat()


def _get_entry(usage: dict, name: str) -> dict:
    entry = usage.get(name)
    if not entry or entry.get("date") != _today():
        entry = {"date": _today(), "requests": 0, "tokens": 0}
        usage[name] = entry
    return entry


def _has_budget(provider_cfg: dict, entry: dict) -> bool:
    req_budget = provider_cfg.get("daily_request_budget", 0)
    tok_budget = provider_cfg.get("daily_token_budget", 0)
    if req_budget and entry["requests"] >= req_budget:
        return False
    if tok_budget and entry["tokens"] >= tok_budget:
        return False
    return True


def _estimate_tokens(text: str) -> int:
    # Rough fallback (~4 chars/token) when a provider doesn't return usage counts.
    return max(1, len(text) // 4)


def _call_openai_compatible(provider_cfg: dict, prompt: str, limiter: _RateLimiter = None):
    api_key = os.environ.get(provider_cfg.get("api_key_env", ""))
    if not api_key:
        raise RuntimeError(
            f"{provider_cfg['name']}: {provider_cfg.get('api_key_env')} not set in environment"
        )
    if limiter is not None:
        limiter.wait()
    base_url = provider_cfg["base_url"].rstrip("/")
    r = requests.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": provider_cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 4000,
        },
        timeout=60,
    )
    if r.status_code == 429:
        raise RateLimited(f"{provider_cfg['name']} returned 429")
    r.raise_for_status()
    data = r.json()
    content = data["choices"][0]["message"].get("content") or ""
    if not content.strip():
        raise RuntimeError(f"{provider_cfg['name']} returned an empty response")
    usage = data.get("usage", {}) or {}
    tokens_used = usage.get("total_tokens") or (
        _estimate_tokens(prompt) + _estimate_tokens(content)
    )
    return content, tokens_used


def _call_embed(provider_cfg: dict, texts: list, limiter: _RateLimiter = None) -> tuple:
    """Embed a list of texts via an OpenAI-compatible /embeddings endpoint.

    Returns (vectors, tokens_used), one embedding per input text, in order.
    The error messages deliberately avoid echoing the API key value back.
    """
    api_key = os.environ.get(provider_cfg.get("api_key_env", ""))
    if not api_key:
        raise RuntimeError(
            f"{provider_cfg['name']}: {provider_cfg.get('api_key_env')} not set in environment"
        )
    embedding_model = provider_cfg.get("embedding_model")
    if not embedding_model:
        raise RuntimeError(f"{provider_cfg['name']}: no embedding_model configured")
    if limiter is not None:
        limiter.wait()
    base_url = provider_cfg["base_url"].rstrip("/")
    r = requests.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": embedding_model, "input": texts},
        timeout=60,
    )
    if r.status_code == 429:
        raise RateLimited(f"{provider_cfg['name']} returned 429")
    r.raise_for_status()
    data = r.json()
    vectors = [item["embedding"] for item in data["data"]]
    usage = data.get("usage", {}) or {}
    tokens_used = usage.get("total_tokens") or sum(_estimate_tokens(t) for t in texts)
    return vectors, tokens_used


def _retry_settings(cfg: dict) -> tuple:
    r = cfg.get("router", {})
    return r.get("max_429_retries", 0), r.get("retry_backoff_seconds", 20)


def _limiter_for(cfg: dict) -> _RateLimiter:
    rpm = cfg.get("rate_limit", {}).get("requests_per_minute", 0)
    return _RateLimiter(rpm)


def generate(cfg: dict, prompt: str) -> str:
    """
    Tries each enabled provider in config['providers'] order. Skips any
    provider already at/over its tracked daily budget. On a live 429,
    retries with backoff (config['router']), and only after retries are
    exhausted marks that provider exhausted for the rest of today and moves
    on. Raises if every provider is skipped or fails -- no local fallback.
    """
    providers = [p for p in cfg.get("providers", []) if p.get("enabled", True)]
    max_retries, backoff = _retry_settings(cfg)
    limiter = _limiter_for(cfg)
    usage_path = _usage_path(cfg)
    usage = _load_usage(usage_path)
    last_error = None

    for provider_cfg in providers:
        name = provider_cfg["name"]
        entry = _get_entry(usage, name)

        if not _has_budget(provider_cfg, entry):
            print(f"[router] {name}: at/near daily budget, skipping")
            continue

        exhausted = False
        for attempt in range(max_retries + 1):
            try:
                content, tokens_used = _call_openai_compatible(provider_cfg, prompt, limiter)
                entry["requests"] += 1
                entry["tokens"] += tokens_used
                _save_usage(usage_path, usage)
                print(f"[router] used {name} (today: {entry['requests']} req, {entry['tokens']} tok)")
                return content

            except RateLimited:
                if attempt < max_retries:
                    wait = backoff * (attempt + 1)
                    print(f"[router] {name}: 429, retrying in {wait}s (attempt {attempt + 2}/{max_retries + 1})")
                    time.sleep(wait)
                    continue
                print(f"[router] {name}: rate-limited (429) -- marking exhausted for today, trying next provider")
                # Force this provider to look "over budget" for the rest of today,
                # even if our own counters hadn't caught up to the real limit yet.
                entry["requests"] = max(entry["requests"], provider_cfg.get("daily_request_budget") or entry["requests"] + 1)
                entry["tokens"] = max(entry["tokens"], provider_cfg.get("daily_token_budget") or entry["tokens"])
                _save_usage(usage_path, usage)
                last_error = f"{name} rate-limited"
                exhausted = True

            except Exception as e:
                print(f"[router] {name}: failed ({e}), trying next provider")
                last_error = str(e)
                exhausted = True

            if exhausted:
                break

    raise RuntimeError(
        f"All providers exhausted or failed. Set the API keys in your "
        f"environment / .env (GROQ_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY). "
        f"Last error: {last_error}"
    )


def embed(cfg: dict, texts: list) -> list:
    """Embed a list of texts and return one vector per input, in order.

    Uses the first enabled provider that has an `embedding_model` and an
    available API key, respecting per-provider daily budgets (429s get
    retried with backoff like generate()). The vectors are plain lists
    (floats) so this module stays numpy-free; consumers convert as needed.
    Raises if every provider fails.
    """
    providers = [
        p for p in cfg.get("providers", [])
        if p.get("enabled", True) and p.get("embedding_model")
    ]
    max_retries, backoff = _retry_settings(cfg)
    limiter = _limiter_for(cfg)
    usage_path = _usage_path(cfg)
    usage = _load_usage(usage_path)
    last_error = None

    for provider_cfg in providers:
        name = provider_cfg["name"]
        entry = _get_entry(usage, name)

        if not _has_budget(provider_cfg, entry):
            continue

        exhausted = False
        for attempt in range(max_retries + 1):
            try:
                vectors, tokens_used = _call_embed(provider_cfg, texts, limiter)
                entry["requests"] += 1
                entry["tokens"] += tokens_used
                _save_usage(usage_path, usage)
                print(f"[router] embedded {len(texts)} text(s) with {name} (today: {entry['requests']} req, {entry['tokens']} tok)")
                return vectors

            except RateLimited:
                if attempt < max_retries:
                    wait = backoff * (attempt + 1)
                    print(f"[router] {name}: 429, retrying in {wait}s (attempt {attempt + 2}/{max_retries + 1})")
                    time.sleep(wait)
                    continue
                entry["requests"] = max(entry["requests"], provider_cfg.get("daily_request_budget") or entry["requests"] + 1)
                entry["tokens"] = max(entry["tokens"], provider_cfg.get("daily_token_budget") or entry["tokens"])
                _save_usage(usage_path, usage)
                last_error = f"{name} rate-limited"
                exhausted = True

            except Exception as e:
                print(f"[router] {name}: embedding failed ({e}), trying next provider")
                last_error = str(e)
                exhausted = True

            if exhausted:
                break

    raise RuntimeError(
        f"All providers failed to embed. Set the API keys in your "
        f"environment / .env and make sure at least one provider has an "
        f"`embedding_model` set. Last error: {last_error}"
    )


def usage_report(cfg: dict) -> str:
    """Quick human-readable summary of today's usage per provider, for a status check."""
    usage = _load_usage(_usage_path(cfg))
    lines = []
    for provider_cfg in cfg.get("providers", []):
        name = provider_cfg["name"]
        entry = usage.get(name, {})
        if entry.get("date") != _today():
            entry = {"requests": 0, "tokens": 0}
        req_budget = provider_cfg.get("daily_request_budget", 0) or "∞"
        tok_budget = provider_cfg.get("daily_token_budget", 0) or "∞"
        lines.append(
            f"{name}: {entry.get('requests', 0)}/{req_budget} requests, "
            f"{entry.get('tokens', 0)}/{tok_budget} tokens"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    print(usage_report(cfg))
