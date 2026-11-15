# RELOOP AI — Claude Code project guide

**Sort Smart. Reuse More. Waste Less.** An AI-powered waste segregation, recycling, reuse and donation platform for Indian households. The pilot covers Thakurli, Dombivli and Kalyan (Maharashtra), and the design supports expansion across India. Built for Project STACK.

## Tech stack
- **Python 3.12+** only. No React, Next.js, Node.js or JavaScript application code.
- **Web:** FastAPI with server-rendered Jinja2 HTML, plain forms and CSS. Small progressive-enhancement scripts are allowed only if a page truly needs one.
- **Why not Streamlit:** Vercel runs Python as serverless functions. Connections are capped at 300s and instances scale up and down, so Streamlit's persistent session server is lost. The user approved FastAPI + HTML on 2026-11-15.
- **Data:** Supabase PostgreSQL + pgvector + Storage, with row-level security on every table.
- **AI:** configurable vision LLM (`LLM_PROVIDER`: anthropic | mock) and embedding providers (env vars), with Pydantic-typed agents. Default model `claude-opus-5-5` (override with `LLM_MODEL`). Guardrails always run after the model, never instead of it.
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

## Design rules
- PRODUCT.md holds product truth. DESIGN.md holds the visual system (tokens, components). Follow both for any UI change.
- Interface text goes through `_()` in templates (Jinja i18n, null translations for now) so Hindi and Marathi can be added later.
- Lane colours are municipal bin colours, shared by the UI and `reloop/models/categories.py`.
- Visual checks: `.venv/Scripts/python -m pip show playwright` (dev only). Screenshots use the installed Edge (`channel="msedge"`) at 390, 1000 and 1440 widths.

## Local development
```
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app:app --reload
```

## Current status
- [x] Phase 1: architecture validated (FastAPI on Vercel), PoC app + health check, 4 tests passing locally
- [x] Phase 1: deployed. Repo https://github.com/ajitkpal1-hub/Project-Stack, live https://project-stack-wheat.vercel.app (health verified 2026-11-15)
- [ ] Set `APP_ENV=production` in Vercel env vars (currently reports "development")
- [x] Phase 2: interface and navigation. "Municipal Bin Stencils" visual world (see DESIGN.md, PRODUCT.md, `.impeccable/surfaces/`), full homepage, shared shell, 7 honest "Arrives in Phase N" pages, 21 tests passing, finish review: ship (2026-11-15)
- [x] Phase 3: AI waste classification. Claude vision via `reloop/services/classifier.py` (structured outputs, server-side refusal fallback), Python guardrails in `reloop/services/guardrails.py`, condition check before any donation advice, mock classifier for tests/demo. 56 tests passing (2026-11-15). Waiting on the user's Anthropic API key for a live test.
- [x] Phase 4: RAG knowledge assistant. `reloop/rag/` (chunking, Voyage embeddings, Supabase pgvector store, Claude answers with citations), `scripts/ingest.py`, `supabase/migrations/0001_knowledge_base.sql`, 87 tests passing (2026-11-15). Six official documents verified and placed in `knowledge/` (manifest filled from the PDFs). Supabase project created and migration 0001 run (project ref ilkhnbdamwisdraxdzdo, region Seoul).
- [x] Knowledge base loaded locally (2026-11-15): 6 documents, 423 chunks in Supabase. Voyage needs a payment method on file (free-tier limits fail ingestion); ingest batches and waits out 429s. `english_only = true` in the manifest drops scrambled Hindi from bilingual gazettes.
- [ ] Add SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EMBEDDING_PROVIDER=voyage, EMBEDDING_API_KEY to Vercel Production so the live assistant uses the knowledge base
- [ ] Phase 5: multi-agent workflow
- [ ] Phase 6: donations + accounts (Supabase)
- [ ] Phase 7: location search + verified partners
- [ ] Phase 8: user + admin dashboards
- [ ] Phase 9: security + end-to-end tests
- [ ] Phase 10: final GitHub push + Vercel deploy
