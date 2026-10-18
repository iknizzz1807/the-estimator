# syntax=docker/dockerfile:1
# Single-service image: FastAPI serves the API and the statically-exported
# Next.js frontend on ONE port (one public URL, no CORS, no second service).
#
# Build from the REPO ROOT:
#   docker build -f backend/Dockerfile -t the-estimator .
#   docker run -p 8000:8000 -e LLM_PROVIDER=stub the-estimator
#
# The frontend is built in-image (stage 1) -> no local frontend/out needed.
# Requires .dockerignore at the repo root (excludes node_modules/.next/out/.env
# from the build context).

# ---- Stage 1: static frontend export (next build -> /build/frontend/out) ----
FROM node:20-slim AS frontend-build
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-bin-links || npm install --no-bin-links

COPY frontend/ ./
RUN node ./node_modules/next/dist/bin/next build

# ---- Stage 2: Python API + static export on one port ------------------------
FROM python:3.13-slim

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# The Codebase Lab shells out to `git` (on-demand demo-repo builder + the
# read-only history analyzer). python:slim images ship without it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
COPY data/synthetic_history.csv ./data/synthetic_history.csv

# Pre-clone the Codebase Lab example repos so a visitor can click an example and
# get a result instantly (no clone at request time). Best-effort: a network
# hiccup must never fail the deploy — the app simply offers fewer examples.
RUN cd /app/backend && python scripts/fetch_example_repos.py \
    || echo "example repos not fetched - examples will be hidden"
COPY --from=frontend-build /build/frontend/out ./frontend/out
# Repo history makes Codebase Lab's repo="self" work inside the image
# (read-only git analysis). The context only contains .git when building
# locally from a full checkout: Render builds from GitHub, where the context
# has no .git, so copy it conditionally and never fail the whole deploy over
# an optional extra. Without it, repo="self" returns the existing clean
# "not a git repository" error and demo_a/demo_b work unchanged.
RUN --mount=type=bind,target=/ctx if [ -d /ctx/.git ]; then cp -r /ctx/.git ./.git; fi

WORKDIR /app/backend
ENV HOST=0.0.0.0 PYTHON=python3
EXPOSE 8000
CMD ["bash", "scripts/run_api.sh"]
