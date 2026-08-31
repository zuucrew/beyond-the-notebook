# Multi-stage. The point of the split is that the runtime image contains the
# virtualenv and the source, and nothing that was needed to build them --
# no uv, no compiler, no build cache.

# ---------- build ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies get their own layer, installed against a stub package.
# Editing src/ then does NOT invalidate this layer, so a code change rebuilds
# in seconds instead of re-resolving every dependency. Copying source first is
# the single most common Dockerfile mistake.
COPY pyproject.toml ./
RUN mkdir -p src/claim_loop && touch src/claim_loop/__init__.py \
 && uv sync --no-dev

# Now the real source. Only this layer and below rebuild on a code change.
COPY src ./src
RUN uv sync --no-dev


# ---------- runtime ----------
FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY src ./src
COPY migrations ./migrations

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Not root. A container that never needs to write to its own filesystem should
# not be able to.
RUN useradd --create-home --uid 1000 app && chown -R app:app /app
USER app

# dataset/ is mounted, not copied: it changes often and does not belong in an
# image. In production it is object storage anyway (see README, Document storage).

ENTRYPOINT ["claim-loop"]
CMD ["--help"]
