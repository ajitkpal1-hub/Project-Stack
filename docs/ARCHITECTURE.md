# Architecture

## Deployment decision: FastAPI + server-rendered HTML on Vercel

**Context.** The brief asked for Streamlit on Vercel. Vercel's Python runtime docs (checked 2026-11-15) say:
- Python apps run as Vercel Functions on Fluid compute. Python 3.12 is the default, and 3.13 and 3.14 are also supported.
- Maximum duration is 300s on Hobby. WebSocket connections "follow function duration limits, so clients need to handle reconnects."
- FastAPI, Flask and Django are detected with zero config when an `app` instance exists in `app.py`, `index.py`, `main.py` and similar files.
- Static files in `public/` are served from the CDN.

**Problem.** Streamlit keeps each user's session in the memory of one long-running server process and talks to the browser over a persistent WebSocket. On Vercel that socket drops within 5 minutes, and requests can land on different instances, so session state would be lost. Streamlit is not a supported framework there.

**Decision.** Use FastAPI with Jinja2 templates. Each page is HTML rendered on the server, and interactions use standard HTML forms. State lives in Supabase (and signed cookies), not in server memory, which fits serverless. Everything is still written in Python.

**Trade-offs.**
- Plain HTML forms instead of Streamlit widgets. Pages reload on submit, which is fine for upload → result flows.
- Vision LLM calls must finish within 300s. Typical calls take 5–20s.
- No background workers on Vercel. Knowledge-base ingestion runs as a local CLI script against Supabase.
- Uploaded images go straight to Supabase Storage, not the function's filesystem (it's ephemeral).

## Request flow
```
Browser ──HTML form──▶ Vercel Function (FastAPI)
                           ├─ routes/        validate input
                           ├─ agents/        Classification → Knowledge → Recommendation → Donation Matching → Safety Review
                           ├─ rag/           pgvector similarity search
                           ├─ services/      LLM API · Supabase · Maps/Places
                           └─ templates/     render HTML response
Vercel CDN ── public/ (CSS, images)
```

## Phase 1 proof of concept
- `GET /`: renders a Jinja2 template with integration status (booleans only).
- `GET /api/health`: JSON with the Python version, environment, Vercel detection and integration flags. Never returns secret values.
