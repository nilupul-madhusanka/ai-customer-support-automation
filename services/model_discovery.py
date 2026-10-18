"""Discover general-purpose Gemini generation candidates, not live capacity.

Metadata is cached for five minutes per credential fingerprint. No prompts or
customer data are sent to the model-list endpoint; clients are never cached.
"""
from hashlib import sha256
import re
import threading
import time

_cache = {}
_cache_guard = threading.Lock()
CACHE_SECONDS = 300


def clear_model_cache():
    with _cache_guard:
        _cache.clear()


def eligible_model(model):
    name = getattr(model, "name", None)
    actions = getattr(model, "supported_actions", None) or []
    if not isinstance(name, str):
        return None
    name = name.removeprefix("models/")
    if not re.fullmatch(r"gemini-[a-z0-9][a-z0-9.-]*", name):
        return None
    if not any(isinstance(action, str) and action.replace("_", "").lower() == "generatecontent" for action in actions):
        return None
    if not any(family in name for family in ("flash", "pro")):
        return None
    excluded = ("image", "audio", "tts", "live", "embedding", "robotics", "computer-use", "deep-research", "native")
    if any(word in name for word in excluded):
        return None
    return name


def model_rank(name):
    version = re.search(r"gemini-(\d+)(?:\.(\d+))?", name)
    major, minor = (int(version[1]), int(version[2] or 0)) if version else (0, 0)
    experimental = any(word in name for word in ("preview", "exp", "experimental"))
    return (experimental, "flash" not in name, -major, -minor, name)


def discover_models(client, api_key, *, timeout_ms):
    from google.genai import types

    key = sha256(api_key.encode()).hexdigest()
    now = time.monotonic()
    with _cache_guard:
        cached = _cache.get(key)
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
    pager = client.models.list(config=types.ListModelsConfig(
        page_size=100, http_options=types.HttpOptions(
            timeout=timeout_ms, retry_options=types.HttpRetryOptions(attempts=1)),
    ))
    candidates = set()
    # At most 200 catalog entries / two 100-entry pages. No unbounded paging.
    from itertools import islice
    for model in islice(pager, 200):
        name = eligible_model(model)
        if name:
            candidates.add(name)
    result = tuple(sorted(candidates, key=model_rank))
    with _cache_guard:
        # Bound memory even when multiple credentials are used in one process.
        if len(_cache) >= 32:
            _cache.pop(next(iter(_cache)))
        _cache[key] = (time.monotonic(), result)
    return result
