# RELOOP AI

**Sort Smart. Reuse More. Waste Less.**

RELOOP AI helps Indian households sort waste correctly, handle hazardous items safely, find recycling
facilities and give usable items a second life. The pilot covers Thakurli, Dombivli and Kalyan
(Kalyan-Dombivli Municipal Corporation, Maharashtra). Built for Project STACK.

**Live:** https://project-stack-wheat.vercel.app

## What it does

| Page | What it does |
|---|---|
| **Scan** (`/scan`) | Photo of an item → the bin it belongs in, with a Clear / Likely / Unsure certainty word (never a made-up percentage), safety warnings, ranked options and what the official rules say. Asks about condition before suggesting a donation. |
| **Ask** (`/assistant`) | Questions answered only from loaded official documents (Solid Waste, E-Waste and Bio-Medical Waste Rules), with numbered citations. Says so when the documents don't cover it. |
| **Donate / Explore** (`/donate`, `/donations`) | List an item (admin-reviewed), browse by category and PIN, request it. The donor chooses who gets it; contact notes are shared only between the two of them. |
| **Recycling** (`/centres`) | Search by locality or PIN: places verified by the RELOOP team first, then OpenStreetMap places clearly marked "not verified". |
| **My dashboard** (`/dashboard`) | Your listings and requests, saved scans and answers, and plain totals (no carbon claims). |
| **Admin** (`/admin`) | Overview, listing queue, recycling directory, knowledge documents, reported AI answers. |

### How a scan is worked out
Every photo goes through five steps (`reloop/agents/`), shown on the result page under "How we worked this out":

1. **Classification:** Claude vision names the item and its lane; Python guardrails run straight after.
2. **Knowledge:** the knowledge base is asked about this item; answers cite loaded documents only.
3. **Recommendation:** options ranked by the waste hierarchy (reuse → repair → donate → recycle → dispose).
4. **Donation matching:** never hazardous or medical, never before condition is confirmed; names only verified NGOs.
5. **Safety review:** runs last and corrects anything unsafe the earlier steps produced.

## Product rules (non-negotiable)
No fabricated confidence numbers. Never assume an item works or is safe from a photo. Answers cite only
loaded documents. No invented NGOs, centres, rules or links; map results stay "unverified" until an admin
checks them. No precise carbon claims. Hazardous and medical waste can never be listed. Donor contact details
are never public. Full detail: [PRODUCT.md](PRODUCT.md).

## Tech stack
Python 3.12 · FastAPI · Jinja2 server-rendered HTML (no JavaScript) · Supabase (PostgreSQL + pgvector +
Auth + Storage, row-level security on every table) · Anthropic Claude (vision + cited answers) ·
Voyage embeddings · OpenStreetMap (Nominatim + Overpass) · Vercel.
Why not Streamlit: see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run locally
Requires [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
cp .env.example .env          # fill in what you have; empty settings switch features off
.venv/Scripts/python -m uvicorn app:app --reload    # Windows
# .venv/bin/python -m uvicorn app:app --reload      # macOS/Linux
```
Open http://localhost:8000 and http://localhost:8000/api/health.
With no settings at all the site still runs: scanning can use `LLM_PROVIDER=mock` (labelled demo answers),
and pages for accounts and the knowledge base say plainly that they aren't switched on.

### Set up Supabase
1. Create a project, then run the files in `supabase/migrations/` **in order** (0001 → 0005) in the SQL editor.
2. Authentication → Sign In / Providers → Email: turn off "Confirm email" (until an email sender is set up).
3. Put the URL, publishable key, secret key and `ADMIN_EMAILS` in `.env` (see [.env.example](.env.example)).
4. Load the knowledge base: put official PDFs in `knowledge/`, describe them in `knowledge/manifest.toml`,
   then `.venv/Scripts/python scripts/ingest.py` (add `--dry-run` to check without calling any service).

## Tests
```bash
.venv/Scripts/python -m pytest -q
```
About 250 tests. They need no API keys or network: AI, database and map calls are replaced by fakes.
`tests/e2e/` drives the real pages in Microsoft Edge with Playwright and is skipped where Edge isn't installed.

## Deploy
Vercel imports the GitHub repo and detects FastAPI from `app.py`; every push to `main` deploys.
Settings, checks and recovery steps: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project docs
- [PRODUCT.md](PRODUCT.md): product truth, users, rules
- [DESIGN.md](DESIGN.md): visual system ("Municipal Bin Stencils")
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the code is organised and why
- [docs/SECURITY.md](docs/SECURITY.md): access model, protections, known gaps
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): production settings and checklist
- [CLAUDE.md](CLAUDE.md): development guide and phase history
