"""Configuration, read from .env or the environment.

No pydantic-settings, no framework. A .env parser is fifteen lines and this way
you can see exactly what is being read.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # setdefault: a real environment variable always wins over .env
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql:///claimloop"
)

DATASET_DIR = PROJECT_ROOT / "dataset"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"

# D-007. A number chosen to be argued with, not defended.
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.80"))

# How long a worker or reviewer may hold a claim before it is handed to someone
# else. Short enough that abandoned work recovers quickly, long enough that a
# reviewer mid-form does not get robbed. 15 minutes is a guess; measure it.
LEASE_SECONDS = int(os.environ.get("LEASE_SECONDS", "900"))

# After this many attempts a claim goes to extraction_failed rather than being
# retried forever. This is what stops a poison document looping.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))

# Connection pool size, per process.
#
# This is the number that breaks a serverless deployment. Cloud Run runs N
# instances, each holding its own pool, and Cloud SQL enforces a hard
# max_connections tied to instance size -- roughly 25-50 on the smallest tiers:
#
#     instances x DB_POOL_MAX  <=  max_connections
#
# Twenty instances at 5 is a hundred connections against a limit of fifty, and
# the app fails from traffic rather than from a bug. On serverless the usual
# answer is 1 or 2, because an instance serves one request at a time anyway.
#
# Configuration, not code, so local and production differ without a rebuild --
# and so the arithmetic sits somewhere you can see it.
DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "5"))

# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------

# Which extractor the worker uses: "stub" reads the ground-truth JSON beside
# each PDF and corrupts it deterministically; "groq" actually reads the pages.
EXTRACTOR = os.environ.get("EXTRACTOR", "groq")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Groq speaks the OpenAI wire format, so the openai SDK works against it
# unchanged -- only base_url differs. Point this at OpenRouter or anywhere else
# OpenAI-compatible and nothing in the code changes.
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

# Verify against Groq's current catalogue before trusting this default -- model
# ids move, and vision-capable models are a smaller list than text ones.
GROQ_MODEL = os.environ.get("GROQ_MODEL", "qwen2.5-vl-72b-instruct")

# Rasterisation resolution. Higher reads small print better and costs more
# image tokens; image tokens scale with pixel area, so 200 is roughly twice
# the cost of 140. Measure before raising it.
PDF_DPI = int(os.environ.get("PDF_DPI", "150"))

# Cap pages per document. A 40-page pack at 150 DPI is a lot of image tokens.
MAX_PAGES = int(os.environ.get("MAX_PAGES", "8"))
