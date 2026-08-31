"""The stub extractor.

It does NOT read a PDF. It reads the ground-truth JSON sitting next to it in
dataset/ and applies deterministic, controlled corruption -- dropping fields,
mangling values, assigning confidence.

It is better than a real model while the queue is being built, because:

  * it is deterministic, so the same claim behaves the same way every run
  * it costs nothing and takes no time, so tests stay fast
  * the correct answer is known, so you can actually measure whether routing
    sent the right things to a human

A real vision model replaces this later. The interface -- take a storage_uri,
return {field: {value, confidence, source}} -- must not change when it does.
That stability is the whole point of putting it behind this seam.
"""
import hashlib
import json
from pathlib import Path

from ...config import PROJECT_ROOT


def _local_path(storage_uri: str) -> Path:
    """file://... -> Path. gs:// will need a download once documents move to
    object storage.

    Paths are stored RELATIVE to the project root. An absolute host path such as
    /Users/me/claim-loop/dataset/x.pdf does not exist inside a container, so
    baking one into storage_uri makes every claim unreadable the moment the
    worker runs anywhere but the machine that submitted it.

    Containerisation is what surfaces this. It is worth noticing that the fix is
    a storage decision, not a Docker one.
    """
    if storage_uri.startswith("file://"):
        raw = storage_uri[len("file://"):]
    elif "://" not in storage_uri:
        raw = storage_uri
    else:
        scheme = storage_uri.split("://", 1)[0]
        raise NotImplementedError(f"no reader for scheme {scheme!r} yet")

    path = Path(raw)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _unit(seed: str) -> float:
    """A stable pseudo-random float in [0, 1) derived from a string."""
    digest = hashlib.sha256(seed.encode()).digest()
    return int.from_bytes(digest[:4], "big") / 0x1_0000_0000


def _confidence(claim_key: str, field_key: str) -> float:
    """Skewed high: most fields read cleanly, a few do not.

    Roughly 2-3% of fields land below a 0.80 threshold. That sounds tiny until
    you notice a form has 22 fields -- so a little over half of documents come
    out clean and the rest escalate. Per-field thresholds compound, and that
    compounding is the thing that actually sets your escalation rate. Worth
    playing with this curve and watching the auto-approve rate move.
    """
    return round(0.62 + _unit(f"{claim_key}:{field_key}") ** 0.2 * 0.38, 2)


def _corrupt(value: str, seed: str) -> str:
    """Simulate a realistic misread.

    Dates get their day and month swapped, which is the actual failure mode for
    DD/MM/YYYY source documents -- 03/04/2025 is genuinely ambiguous and a model
    will sometimes read it as the 4th of March.
    """
    parts = value.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[1]}/{parts[0]}/{parts[2]}"
    if len(value) > 3:
        i = 1 + int(_unit(seed) * (len(value) - 2))
        return value[:i] + value[i + 1:]
    return value


def extract(storage_uri: str) -> dict[str, dict]:
    """Return {field_key: {value, confidence, source}} for one document."""
    pdf = _local_path(storage_uri)
    truth_file = pdf.with_suffix(".json")
    if not truth_file.exists():
        raise FileNotFoundError(f"no ground truth beside {pdf.name}")

    truth = json.loads(truth_file.read_text())
    deliberately_missing = set(truth.get("deliberately_missing", []))
    claim_key = pdf.name

    out: dict[str, dict] = {}
    for field_key, true_value in truth["fields"].items():
        if true_value is None:
            # Two different nulls, and the difference decides the outcome:
            #   blank       -- the field is on the form and genuinely empty.
            #                  A reviewer cannot fix this by looking harder.
            #   not_present -- the field does not apply to this variant at all.
            out[field_key] = {
                "value": None,
                "confidence": 1.0,
                "source": "blank" if field_key in deliberately_missing else "not_present",
            }
            continue

        confidence = _confidence(claim_key, field_key)
        value = true_value
        if confidence < 0.80:
            value = _corrupt(true_value, f"{claim_key}:{field_key}")

        out[field_key] = {
            "value": value,
            "confidence": confidence,
            "source": "model",
        }
    return out
