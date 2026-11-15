# Deployment and production checklist

Production: https://reloop-india.vercel.app, also https://project-stack-wheat.vercel.app (Vercel project `project-stack`, GitHub repo
`ajitkpal1-hub/Project-Stack`, Supabase project ref `ilkhnbdamwisdraxdzdo`, region Seoul).

## How deploys work
Vercel imports the GitHub repo and detects FastAPI from `app.py`. Every push to `main` builds and deploys
in about a minute. The Python version is pinned in `.python-version`; dependencies in `requirements.txt`.
`public/` is served by Vercel's CDN (the app mounts it only locally).

## Environment variables (Vercel → Settings → Environments → Production)

| Name | Value | Notes |
|---|---|---|
| `APP_ENV` | `production` | |
| `SUPABASE_URL` | `https://<ref>.supabase.co` | no `/rest/v1` suffix |
| `SUPABASE_ANON_KEY` | `sb_publishable_…` | must be the publishable key; the app refuses accounts if it's a secret key |
| `SUPABASE_SERVICE_ROLE_KEY` | `sb_secret_…` | mark Sensitive |
| `ADMIN_EMAILS` | comma-separated emails | who can open `/admin` |
| `LLM_PROVIDER` | `anthropic` (or `mock` for labelled demo answers) | |
| `LLM_API_KEY` | Anthropic key | mark Sensitive; account needs credits |
| `LLM_MODEL` | `claude-haiku-5-5` (optional) | empty = `claude-opus-5-5` |
| `EMBEDDING_PROVIDER` | `voyage` | |
| `EMBEDDING_API_KEY` | Voyage key | mark Sensitive; needs a payment method on file |
| `OSM_USER_AGENT` | optional | defaults to a generic app name |

Changing a variable only takes effect on the next deploy: push, or Deployments → ⋯ → Redeploy.

## Supabase setup (once per project)
1. Run `supabase/migrations/0001` … `0005` in order in the SQL editor.
2. Authentication → Email: "Confirm email" off until an email sender (e.g. Resend) is configured.
3. Load documents: `scripts/ingest.py` from a machine with the keys in `.env`.

## After every deploy
1. `GET /api/health` → `"status": "ok"`, `"environment": "production"`, and `supabase`, `llm`, `embeddings`,
   `accounts`, `admins_configured` all `true`, `anon_key_misconfigured` `false`.
2. Scan a test photo on `/scan`: real result, no "Demo mode" banner.
3. Ask `/assistant` a question the documents cover: "Answered from N source(s)".
4. Open `/donations` and `/centres?place=421201`: both load.

## When something breaks
| Symptom | Likely cause | Fix |
|---|---|---|
| Scanner says "isn't set up correctly" | Anthropic key wrong or out of credits | re-paste `LLM_API_KEY`, check credits, redeploy |
| Assistant shows passages, not answers | LLM unavailable | as above; passages are the designed fallback |
| "Knowledge base isn't ready" | Supabase or Voyage settings missing | check the four settings, redeploy |
| Accounts "aren't switched on" | `SUPABASE_ANON_KEY` missing or is a secret key | use the `sb_publishable_` key |
| Recycling search slow, "map service is slow" | public OpenStreetMap servers overloaded | nothing to do; verified directory still works, map is retried after 5 minutes |
| "RELOOP is very busy today" | site-wide daily AI cap reached | raise caps in `reloop/services/ratelimit.py` if the traffic is genuine |
| Sign-ups fail for everyone | Supabase Auth per-IP limit (all requests come from Vercel) | raise limits in Supabase → Authentication → Rate Limits |

## Rolling back
Vercel → Deployments → open the last good production deployment → ⋯ → **Instant Rollback**. Or revert the
commit on GitHub and push. Database migrations only add tables, so older code keeps working against the newer
database.

## Backups and costs
- The Supabase free plan doesn't include downloadable backups. Before inviting real users at scale, move to a
  paid plan (daily backups) or export the data regularly.
- Anthropic and Voyage bill per use. Usage limits cap AI calls per visitor and per day (see docs/SECURITY.md).

## Open follow-ups
- Turn on GitHub Dependabot alerts (repo Settings → Code security).
- Add verified places to the recycling directory (`/admin/partners`), each with its source link.
- Configure an email sender in Supabase to enable email confirmation and password reset.
