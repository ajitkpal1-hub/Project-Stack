# RELOOP AI

**Sort Smart. Reuse More. Waste Less.**

RELOOP AI helps Indian households segregate waste correctly, dispose of hazardous items safely, find recycling facilities and donate usable items to verified NGOs. The pilot covers Thakurli, Dombivli and Kalyan, Maharashtra.

**Live:** https://project-stack-wheat.vercel.app

> **Status:** Phase 1 complete (proof of concept deployed). See [CLAUDE.md](CLAUDE.md) for the phase checklist.

## Tech stack
Python 3.12 · FastAPI · Jinja2 (server-rendered HTML) · Supabase (PostgreSQL, pgvector, Storage) · configurable vision LLM · Vercel

Why not Streamlit? See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run locally
Requires [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
cp .env.example .env          # then fill in values (optional for Phase 1)
.venv/Scripts/python -m uvicorn app:app --reload    # Windows
# .venv/bin/python -m uvicorn app:app --reload      # macOS/Linux
```
Open http://localhost:8000 and http://localhost:8000/api/health.

## Tests
```bash
.venv/Scripts/python -m pytest -q
```
Tests don't need API keys or network access.

## Deploy (Vercel via GitHub)
1. Push this repo to GitHub (`reloop-ai`).
2. On vercel.com, go to **Add New → Project → Import** and pick the repo. No build settings are needed. Vercel detects FastAPI from `app.py`.
3. Add environment variables from `.env.example` under **Settings → Environment Variables**.
4. Visit `https://<your-project>.vercel.app/api/health` and confirm it shows `"status": "ok"`.

## Screenshots
_Placeholders, added after Phase 2._

## Project docs
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): architecture and deployment decision
- [CLAUDE.md](CLAUDE.md): development guide and status
