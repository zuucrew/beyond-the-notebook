"""Real extraction: renders the PDF and asks a vision model to read it.

Deliberately not named after a provider. Groq, OpenRouter, Together, vLLM and
OpenAI itself all speak the same wire format, so this is the `openai` SDK with
whatever base_url and model config.yml names. Switching provider is two lines of
YAML and one environment variable -- no code, which is the point of the seam.

Interface is identical to stub.extract: take a storage_uri, return
{field_key: {value, confidence, source}}.
"""
import base64
import json
from pathlib import Path

import pymupdf
from openai import OpenAI

from ...config import (
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    MAX_PAGES,
    PDF_DPI,
    PROJECT_ROOT,
)
from ...domain.form_schema import FIELDS, prompt_schema

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not LLM_API_KEY:
            raise RuntimeError("LLM_API_KEY is not set")
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return _client


def _local_path(storage_uri: str) -> Path:
    if storage_uri.startswith("file://"):
        raw = storage_uri[len("file://"):]
    elif "://" not in storage_uri:
        raw = storage_uri
    else:
        raise NotImplementedError(f"no reader for {storage_uri.split('://')[0]!r}")
    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _render_pages(pdf: Path) -> list[str]:
    """PDF -> base64 PNGs, one per page.

    Image tokens scale with pixel area, so DPI is a direct cost lever and page
    count is a hard multiplier. Both are capped in config for that reason.
    """
    pages: list[str] = []
    with pymupdf.open(pdf) as doc:
        for page in doc[:MAX_PAGES]:
            pixmap = page.get_pixmap(dpi=PDF_DPI)
            pages.append(base64.b64encode(pixmap.tobytes("png")).decode())
    return pages


SYSTEM = """You read Australian insurance claim forms and return structured data.

Rules:
- Transcribe exactly what is printed. Never infer, complete or correct a value.
- Dates on these forms are DD/MM/YYYY. Return them in that format. If a date is
  ambiguous, lower your confidence rather than guessing.
- If a field is not present on the form, or its box is empty, return null.
- confidence is 0.0 to 1.0 and should reflect how legible and unambiguous the
  value was. Be honest: a value you had to squint at is not a 0.95.

Return ONLY a JSON object of the form:
  {"field_key": {"value": <string or null>, "confidence": <float>}, ...}
"""


def extract(storage_uri: str) -> dict[str, dict]:
    pdf = _local_path(storage_uri)
    pages = _render_pages(pdf)

    content: list[dict] = [{
        "type": "text",
        "text": (
            f"Extract these fields from the {len(pages)} page image(s):\n\n"
            f"{prompt_schema()}\n\n"
            "Return one entry per field, including fields you could not find."
        ),
    }]
    for b64 in pages:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"},
        })

    response = _get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": content},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(response.choices[0].message.content)

    # Normalise against the known field list rather than trusting the model's
    # key set. A model that invents a field, drops one, or nests differently
    # must not be able to corrupt the shape the rest of the system relies on.
    out: dict[str, dict] = {}
    for key in FIELDS:
        entry = raw.get(key)
        if not isinstance(entry, dict):
            # Field absent from the response entirely -- that is a failure to
            # read, not a blank form. Zero confidence sends it to a human.
            out[key] = {"value": None, "confidence": 0.0, "source": "model"}
            continue

        value = entry.get("value")
        try:
            confidence = float(entry.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = min(max(confidence, 0.0), 1.0)

        if value in (None, "", "null", "N/A"):
            # The model read the form and found nothing there. Distinct from the
            # case above: this is a blank box, which a reviewer cannot fix by
            # looking harder.
            out[key] = {"value": None, "confidence": confidence, "source": "blank"}
        else:
            out[key] = {"value": str(value).strip(), "confidence": confidence,
                        "source": "model"}
    return out
