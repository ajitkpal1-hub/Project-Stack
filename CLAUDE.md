# RELOOP AI — Claude Code project guide

**Sort Smart. Reuse More. Waste Less.** An AI-powered waste segregation, recycling, reuse and donation platform for Indian households. The pilot covers Thakurli, Dombivli and Kalyan (Maharashtra), and the design supports expansion across India. Built for Project STACK.

## Tech stack
- **Python 3.12+** only. No React, Next.js, Node.js or JavaScript application code.
- **Web:** FastAPI with server-rendered Jinja2 HTML, plain forms and CSS. Small progressive-enhancement scripts are allowed only if a page truly needs one.
- **Why not Streamlit:** Vercel runs Python as serverless functions. Connections are capped at 300s and instances scale up and down, so Streamlit's persistent session server is lost. The user approved FastAPI + HTML on 2026-11-15.
- **Data:** Supabase PostgreSQL + pgvector + Storage, with row-level security on every table.
- **AI:** configurable vision LLM and embedding providers (env vars), with Pydantic-typed agents.
- **Deploy:** Vercel, zero-config FastAPI detection via root `app.py` exposing `app`. Source lives on GitHub (`reloop-ai`), and Vercel deploys through its GitHub import, not the CLI.

## Architecture
```
app.py                 Vercel entrypoint (re-exports reloop.web:app)
reloop/web.py          FastAPI app factory, route registration
reloop/config.py       Settings from env vars (pydantic-settings)
reloop/routes/         One module per page/feature (APIRouter)
reloop/templates/      Jinja2 pages; partials/ for shared components
reloop/agents/         Classification, Knowledge, Recommendation, Donation Matching, Safety Review
reloop/services/       External clients: LLM, Supabase, Maps (thin, mockable)
reloop/rag/            Ingestion, chunking, embedding, retrieval
reloop/database/       Repository functions over Supabase
reloop/models/         Pydantic models shared across layers
reloop/utils/          Small helpers (validation, logging)
public/                Static assets served by Vercel's CDN (mounted locally only)
supabase/migrations/   SQL migrations (tables, indexes, RLS, storage)
scripts/               CLI tools (e.g. knowledge-base ingestion)
tests/                 pytest; AI and network calls are mocked
docs/                  Architecture, deployment, decisions
```
Agent pipeline: Input → Classification → Knowledge → Recommendation → Donation Matching → Safety Review → Response.

## Coding conventions
- Type hints everywhere. Pydantic models at every boundary (agent I/O, forms, DB rows).
- Routes stay thin: validate, then call services/agents, then render. No SQL or API calls inside templates or routes.
- External services sit behind small interfaces so tests can swap in fakes.
- Keep dependencies minimal and pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (dev/test).
- Plain English in user-facing copy, with Indian context (PIN codes, localities, INR).

## Security requirements
- All secrets come from env vars. Never hardcode, log or render them, and never commit `.env`.
- The Supabase service-role key is server-side only.
- Server-side authorization on every admin route and write operation. RLS is the second line of defence.
- Never expose donor phone, email or precise address publicly.
- Hazardous or medical waste can never be listed as a donation.

## Product-truth rules (non-negotiable)
- No fabricated confidence percentages: use qualitative certainty levels.
- Never assume an item is functional, clean or safe from a photo. Ask the user to confirm.
- RAG answers cite only ingested documents. If retrieval finds nothing, say so. Never present model knowledge as verified.
- Never invent NGOs, recycling centres, regulations, citations or URLs. External search results are "unverified" until an admin verifies them.
- No precise carbon or impact claims without a documented methodology.
- Demo data must be visibly labelled as demonstration data.

## Testing rules
- `.venv/Scripts/python -m pytest -q` (Windows) runs the suite. Tests must pass without API keys or network access.
- Every feature ships with tests, including failure paths (API errors, invalid uploads, missing knowledge).
- Never claim tests passed unless they ran in this session.

## Deployment rules
- Vercel detects `app.py` → `app`. Python version is pinned by `.python-version`.
- Don't mount `public/` on Vercel (the CDN serves it). `reloop/web.py` mounts it only when `VERCEL` is unset.
- Set env vars in Vercel Project Settings. Confirm with the user before any push, repo creation or deploy.
- Verify after deploy: `/api/health` returns `status: ok` and the expected integration flags.

## Local development
```
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app:app --reload
```

## Current status
- [x] Phase 1: architecture validated (FastAPI on Vercel), PoC app + health check, 4 tests passing locally
- [ ] Phase 1: first Vercel deploy (waiting on GitHub repo + Vercel import)
- [ ] Phase 2: interface and navigation
- [ ] Phase 3: AI waste classification
- [ ] Phase 4: RAG knowledge assistant
- [ ] Phase 5: multi-agent workflow
- [ ] Phase 6: donations + accounts (Supabase)
- [ ] Phase 7: location search + verified partners
- [ ] Phase 8: user + admin dashboards
- [ ] Phase 9: security + end-to-end tests
- [ ] Phase 10: final GitHub push + Vercel deploy
