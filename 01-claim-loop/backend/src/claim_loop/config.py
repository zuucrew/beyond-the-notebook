"""Configuration.

Two sources, deliberately separated:

  config.yml   parameters: thresholds, model names, pool sizes, timeouts.
               Committed, so a change appears in a diff and can be reviewed.

  .env         secrets: API keys and connection strings. Gitignored, never
               in an image layer, never in a diff.

Mixing them means either secrets end up in version control, or every tuning
change becomes an environment variable nobody can find the origin of.

A named profile in config.yml is merged over `default` when APP_ENV is set, so
values that must differ between a laptop and a deployment do so without
becoming environment variables.
"""
import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATASET_DIR = PROJECT_ROOT / "dataset"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def _load_dotenv() -> None:
    """Secrets only. Fifteen lines, so you can see exactly what is read."""
    # .env sits at the repository root, one level above the backend, because
    # the frontend and compose read it too.
    env_file = PROJECT_ROOT.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # setdefault: a real environment variable always wins over .env
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _load_yaml() -> dict:
    raw = yaml.safe_load((PROJECT_ROOT / "config.yml").read_text()) or {}
    cfg = raw.get("default", {})
    profile = os.environ.get("APP_ENV")
    if profile:
        if profile not in raw:
            raise ValueError(f"APP_ENV={profile!r} has no section in config.yml")
        cfg = _merge(cfg, raw[profile])
    return cfg


_load_dotenv()
_cfg = _load_yaml()

# ---------------------------------------------------------------------------
# secrets: environment only
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///claimloop")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")

# ---------------------------------------------------------------------------
# parameters: config.yml only
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD: float = float(_cfg["routing"]["confidence_threshold"])
ALWAYS_ESCALATE: set[str] = set(_cfg["routing"]["always_escalate"])

LEASE_SECONDS: int = int(_cfg["queue"]["lease_seconds"])
MAX_ATTEMPTS: int = int(_cfg["queue"]["max_attempts"])

DB_POOL_MIN: int = int(_cfg["database"]["pool_min"])
DB_POOL_MAX: int = int(_cfg["database"]["pool_max"])

EXTRACTOR: str = _cfg["extraction"]["provider"]
LLM_BASE_URL: str = _cfg["extraction"]["base_url"]
LLM_MODEL: str = _cfg["extraction"]["model"]
PDF_DPI: int = int(_cfg["extraction"]["pdf_dpi"])
MAX_PAGES: int = int(_cfg["extraction"]["max_pages"])
