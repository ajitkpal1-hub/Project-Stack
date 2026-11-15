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
- [x] Phase 1: deployed. Repo https://github.com/ajitkpal1-hub/Project-Stack, live https://reloop-india.vercel.app (added 2026-11-15; original https://project-stack-wheat.vercel.app still works)
- [x] `APP_ENV=production` set in Vercel (health reports production, 2026-11-15)
- [x] Phase 2: interface and navigation. "Municipal Bin Stencils" visual world (see DESIGN.md, PRODUCT.md, `.impeccable/surfaces/`), full homepage, shared shell, 7 honest "Arrives in Phase N" pages, 21 tests passing, finish review: ship (2026-11-15)
- [x] Phase 3: AI waste classification. Claude vision via `reloop/services/classifier.py` (structured outputs, server-side refusal fallback), Python guardrails in `reloop/services/guardrails.py`, condition check before any donation advice, mock classifier for tests/demo. 56 tests passing (2026-11-15). Live with Claude (LLM_PROVIDER=anthropic, LLM_MODEL=claude-haiku-5-5) locally and on Vercel; scanner and assistant verified live 2026-11-15.
- [x] Phase 4: RAG knowledge assistant. `reloop/rag/` (chunking, Voyage embeddings, Supabase pgvector store, Claude answers with citations), `scripts/ingest.py`, `supabase/migrations/0001_knowledge_base.sql`, 87 tests passing (2026-11-15). Six official documents verified and placed in `knowledge/` (manifest filled from the PDFs). Supabase project created and migration 0001 run (project ref ilkhnbdamwisdraxdzdo, region Seoul).
- [x] Knowledge base loaded locally (2026-11-15): 6 documents, 423 chunks in Supabase. Voyage needs a payment method on file (free-tier limits fail ingestion); ingest batches and waits out 429s. `english_only = true` in the manifest drops scrambled Hindi from bilingual gazettes.
- [x] Supabase + Voyage keys in Vercel Production; live assistant answers from 6 loaded documents (health: supabase and embeddings true, verified 2026-11-15)
- [x] Phase 5: multi-agent workflow. `reloop/agents/` (classification, knowledge, recommendation, donation, safety + `pipeline.py`) drives `/scan`; Safety Review runs last and fixes rather than trusts; knowledge failures degrade gracefully; condition re-plan makes no AI calls; no named partners until the Phase 7 verified directory. 127 tests passing, live local run with Claude + screenshots at 390/1000/1440; deployed and verified live (2026-11-15).
- [x] Phase 6: accounts + donations. Email+password via Supabase Auth (server-side, HttpOnly session cookie, CSRF on every form), migration 0002 (profiles, listings, requests, private `listing-photos` bucket, RLS), donate/explore/listing/dashboard/admin queue (`ADMIN_EMAILS`), contact notes shared only after approval, hazardous words blocked, photo location data stripped. Accounts refuse to start if `SUPABASE_ANON_KEY` holds a secret key. 176 tests; live journey against real Supabase passed 20/20 with cleanup (2026-11-15). Deployed and verified live (accounts on, sign-up/login/logout, CSRF, secure cookies).
- [x] Phase 7: recycling directory. Migration 0003 (`partners`, RLS: verified public, members insert pending only, verified needs a source link), `/centres` search by locality/PIN + material (verified first, OpenStreetMap results labelled not verified, ODbL attribution, works when OSM is down, no map pins for medical), member suggestions, `/admin/partners` (add/verify/reject/remove), scan donation matching names verified NGOs. OSM via `reloop/services/geo.py` (generic User-Agent `OSM_USER_AGENT`, 1 req/s, cached). Public Overpass servers often time out from Vercel, so nearby search has an 8s cap, a backup mirror and a 5-minute outage memory (verified live 2026-11-15). OSM coverage near Dombivli is minimal, so the verified directory needs real entries from the team. 199 tests; live DB check 13/13 with cleanup (2026-11-15).
- [x] Phase 8: dashboards. Migration 0004 (`saved_items` own-rows RLS, `ai_flags` server-only). My dashboard: plain totals (no carbon claims) and opt-in saved scans/answers (text summary only, never photos, max 50). Save + Report a problem under every AI answer. Admin: overview `/admin`, queue at `/admin/listings`, `/admin/partners`, `/admin/knowledge` (archive/restore), `/admin/flags` (review/close). 221 tests; live DB check 20/20 with cleanup; deployed and verified live (2026-11-15).
- [x] Phase 9: security review (see docs/SECURITY.md). Fixed a decompression-bomb crash (40 MP cap), usage limits for scans/assistant/reports/sign-in (hashed IP, site-wide daily caps, Supabase-backed via migration 0005 with in-memory fallback), strict CSP and security headers, friendly 500 page. 250 tests incl. 6 Edge browser journeys in `tests/e2e/` (skipped without Playwright). Live rate-limit check 4/4; deployed and verified live: headers, bomb refusal, real AI scan + assistant, no CSP console errors (2026-11-15). Follow-up: enable Dependabot alerts.
- [x] Phase 10: release. README, docs/ARCHITECTURE.md, docs/DEPLOYMENT.md (settings, post-deploy checklist, troubleshooting, rollback), current .env.example; unused MAPS_API_KEY removed. 250 tests, link crawl clean, final deploy verified live against the DEPLOYMENT.md checklist (2026-11-15). Open follow-ups: Dependabot, real directory entries, email sender for confirmation/password reset, Supabase backups before scale.
