"""Model access with routing, caching and a cost ledger.

Two tiers, chosen by the caller per task:
  fast  - bulk reading and extraction (classify, pull fields out of a filing or transcript)
  smart - the few steps that need judgment (synthesis across a company's record)

Any OpenAI-compatible endpoint works, so the same code runs on a free tier, a paid
API or a local model. Identical prompts are answered from cache and cost nothing.
Every call fails soft: callers get None and fall back to the deterministic path.
"""
import contextvars
import hashlib
import json
import re
import time

import requests

from . import cache, config

# Set per request by the API layer: model reading is an analyst capability, so a guest's
# request runs with this False and takes the rules path. Background jobs copy the context.
allowed: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_allowed", default=True)

SYSTEM = ("You are a careful equity research assistant. Use only the text you are given. "
          "Never add facts from memory. If the text does not contain the answer, say so.")


def ready() -> bool:
    return config.llm_ready() and allowed.get()


def over_budget() -> str | None:
    """Daily guard-rails. When either is hit, FINN falls back to rules until midnight UTC."""
    day = time.time() - time.time() % 86400
    s = cache.usage_summary(day)
    live = s["calls"] - s["cached"]
    if config.LLM_DAILY_CALLS and live >= config.LLM_DAILY_CALLS:
        return f"daily cap of {config.LLM_DAILY_CALLS} model calls reached"
    if config.LLM_DAILY_USD and s["usd"] >= config.LLM_DAILY_USD:
        return f"daily budget of ${config.LLM_DAILY_USD:g} reached"
    return None


def model_for(tier: str) -> str:
    return config.MODEL_SMART if tier == "smart" else config.MODEL_FAST


def chat(tier: str, task: str, prompt: str, max_tokens: int = 700, want_json: bool = False):
    if not ready():
        return None
    model = model_for(tier)
    key = "llm:" + hashlib.sha1(f"{model}|{max_tokens}|{want_json}|{prompt}".encode()).hexdigest()
    hit = cache.get(key)
    if hit is not None:
        cache.log_usage(tier, model, 0, 0, True, task)
        return hit
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if want_json:
        body["response_format"] = {"type": "json_object"}
    if over_budget():
        return None
    headers = {"Content-Type": "application/json"}
    if config.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {config.LLM_API_KEY}"
    for attempt in range(3):
        try:
            r = requests.post(f"{config.LLM_BASE_URL}/chat/completions", json=body, headers=headers, timeout=90)
            if r.status_code == 429:                      # free tiers rate-limit: wait and retry
                time.sleep(4 * (attempt + 1))
                continue
            if r.status_code == 400 and want_json and "response_format" in body:
                body.pop("response_format")               # endpoint without JSON mode
                continue
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
            use = data.get("usage") or {}
            cache.log_usage(tier, model, use.get("prompt_tokens", len(prompt) // 4),
                            use.get("completion_tokens", len(text) // 4), False, task)
            cache.put(key, text)
            return text
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    return None


def text_call(tier, task, prompt, max_tokens=300):
    return chat(tier, task, prompt, max_tokens)


def parse_json(text: str):
    """Models wrap JSON in prose and code fences. Take the outermost object or array."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = t.find(opener), t.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except json.JSONDecodeError:
                continue
    return None


def json_call(tier, task, prompt, max_tokens=900):
    return parse_json(chat(tier, task, prompt, max_tokens, want_json=True))


def meter() -> dict:
    day = time.time() - 86400
    return {"ready": ready(), "configured": config.llm_ready(), "fast": config.MODEL_FAST or None,
            "smart": config.MODEL_SMART or None, "budget": over_budget(),
            "caps": {"calls": config.LLM_DAILY_CALLS, "usd": config.LLM_DAILY_USD},
            "today": cache.usage_summary(day), "all": cache.usage_summary(0)}
