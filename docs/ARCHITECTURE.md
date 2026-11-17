# Architecture

## Deployment decision: FastAPI + server-rendered HTML on Vercel

**Context.** The brief asked for Streamlit on Vercel. Vercel runs Python as serverless functions: each
request may land on a different instance, and connections are capped (300 s).

**Problem.** Streamlit keeps each user's session in the memory of one long-running process and talks to the
browser over a persistent WebSocket. On Vercel that socket drops and requests move between instances, so
session state would be lost. Streamlit is not a supported framework there.

**Decision (approved 2026-11-15).** FastAPI with Jinja2 templates and plain HTML forms. Every request is
self-contained: state lives in Supabase or in signed-in cookies, never in server memory (per-instance caches
are only an optimisation). Pages reload on submit, which suits upload → result flows and works on slow
mobile data.

## Request flow
```
Browser ──HTML form──▶ Vercel Function (app.py → reloop.web:app)
                         ├─ security.py    session cookie, CSRF, security headers
                         ├─ routes/        validate input, check who you are, call services, render
                         ├─ agents/        scan pipeline: Classification → Knowledge → Recommendation
                         │                 → Donation Matching → Safety Review
                         ├─ services/      classifier (Claude), guardrails, donations, partners,
                         │                 dashboards, geo (OpenStreetMap), rate limits
                         ├─ rag/           chunking, Voyage embeddings, pgvector store, cited answers
                         ├─ database/      thin Supabase REST client + repositories (and in-memory fakes)
                         └─ templates/     Jinja2 pages; partials/ for shared pieces
ElevenLabs voice agent ──JSON + X-Reloop-Voice-Key──▶ routes/voice.py (/api/voice/ask, classify, centres)
                         same agents, guardrails and Safety Review as the website; replies carry a `say` line to speak
Vercel CDN ── public/ (CSS, fonts, favicon)
Supabase  ── Postgres + pgvector + Auth + Storage, row-level security on every table
```

## Layers and rules
- **Routes stay thin.** No SQL or API calls in routes or templates. They validate, call a service, render.
- **Services hold the rules** (who may approve, which status changes are allowed, what may be donated) and
  check permission themselves. Row-level security in Supabase is the second line.
- **Every external service sits behind a small interface** (`Classifier`, `Embedder`, `KnowledgeStore`,
  `DonationRepo`, `PartnerRepo`, `DashboardRepo`, `Geo`, rate-limit `Counter`), with an in-memory or mock
  version for tests and demo mode.
- **Guardrails run after the model, never instead of it.** The classifier's output is schema-checked, then
  `services/guardrails.py` and the Safety Review agent correct unsafe advice.
- **Graceful degradation.** Only classification is essential for a scan. If the knowledge base, map search or
  directory is down, the page says so and the rest still works.

## Data (supabase/migrations)
| Migration | Tables |
|---|---|
| 0001 | `knowledge_documents`, `knowledge_chunks` (pgvector), `match_knowledge_chunks()` |
| 0002 | `profiles`, `donation_listings`, `donation_requests`, private `listing-photos` bucket |
| 0003 | `partners` (recycling and donation directory) |
| 0004 | `saved_items`, `ai_flags` |
| 0005 | `rate_limits`, `hit_rate_limit()` |

## Key choices
- **Almost no JavaScript.** One small file (`public/js/scan.js`) starts a scan as soon as a photo is taken and shows
  a "Scanning" state; every page still works without it. The policy allows only that file (`script-src 'self'`).
- **Sign-in on the server.** Supabase Auth via REST; tokens in an HttpOnly cookie, so page scripts never see them.
- **Deterministic ranking.** Recommendation and donation matching use fixed rules: cheaper, testable, can't invent.
- **Qualitative certainty.** Clear / Likely / Unsure, never a percentage.
- **OpenStreetMap, not Google Places.** No key or billing. Results are labelled unverified; the admin-verified
  directory carries the pilot area, where OSM coverage is thin.
