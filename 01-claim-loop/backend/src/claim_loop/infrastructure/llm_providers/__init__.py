"""Extraction providers.

Every provider exposes the same function:

    extract(storage_uri: str) -> {field_key: {value, confidence, source}}

so swapping one for another is a config change, not a code change. That seam is
the reason this is a package rather than a function in the worker.
"""
from ...config import EXTRACTOR


def get_extractor():
    if EXTRACTOR == "stub":
        from .stub import extract
    elif EXTRACTOR == "api":
        from .openai_compatible import extract
    else:
        raise ValueError(f"unknown provider {EXTRACTOR!r}; use 'stub' or 'api'")
    return extract
