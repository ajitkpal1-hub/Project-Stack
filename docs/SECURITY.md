# RELOOP AI security notes

Reviewed in Phase 9 (2026-11-15). This records what is protected, how, and the known gaps.
Tests for each point live in `tests/test_security.py`, `tests/test_donations.py`,
`tests/test_partners.py`, `tests/test_dashboards.py` and the browser journeys in `tests/e2e/`.

## Who can do what

| Action | Check on the server | Second line in the database |
|---|---|---|
| Read public listings / verified places | none needed | RLS: only `available`/`reserved` listings and `verified` places are visible to the public key |
| Create a listing | signed in, hazardous/medical words blocked | RLS: own `donor_id`, status must be `pending_review` |
| Approve / reject a listing or place | `ADMIN_EMAILS` check in `DonationService` / `PartnerService` | no update policy: only the service role can change status |
| Request an item | signed in, listing available, not your own, not twice | RLS: listing available, not own, unique per person |
| Approve / decline / complete | you own the listing | service role only |
| See a contact note | only the two sides of an approved request | `profiles` readable by owner only |
| Saved items | signed in | RLS: own rows only (read, add, delete) |
| Reports, knowledge documents, rate limits | admin check / server only | RLS on, no policies: service role only |

The service-role key is used only on the server, after the server's own check. The app refuses
to enable accounts if `SUPABASE_ANON_KEY` holds a secret key (it would switch off RLS).

## Web protections

- **Sessions**: Supabase tokens in an `HttpOnly`, `SameSite=Lax`, `Secure` (on HTTPS) cookie; checked
  with Supabase on each request (60-second cache), refreshed when expired, cleared when revoked.
  Signed-in pages send `Cache-Control: private, no-store`.
- **Forged forms (CSRF)**: every form that changes something carries a random token that must match a
  cookie. The scan, condition and assistant forms store nothing and are usage-limited instead.
- **Redirects**: `next=` only accepts paths on this site (`safe_next`).
- **Output**: Jinja autoescaping everywhere; the only trusted HTML is the escaped CSRF field. Links from
  data (source, website) are rendered only when they start with `http://` or `https://`.
- **Browser headers** (`reloop/security.py`): strict Content-Security-Policy (`script-src 'self'`: only our own
  `/js/scan.js`, no inline scripts, `connect-src 'none'`, no inline styles, images only from this site and the Supabase project), `frame-ancestors 'none'` and
  `X-Frame-Options: DENY` (no clickjacking), `nosniff`, `strict-origin-when-cross-origin`, HSTS on HTTPS.
- **Errors**: friendly pages for 403/404/500 with no stack traces; Supabase and AI error bodies are never
  shown or logged; secrets are never logged; `/api/health` reports yes/no flags only.

## Uploads

Photos are checked by their bytes (JPEG/PNG/WEBP only), capped at 4 MB, refused if they claim more than
40 megapixels (decompression-bomb guard, added in Phase 9), then re-encoded as JPEG, which drops all
metadata including GPS location. Scan photos are never stored; listing photos go to a private bucket and
are shown through one-hour signed links.

## Usage limits (`reloop/services/ratelimit.py`, migration 0005)

Per visitor (keyed hash of the IP address; raw IPs are never stored) and a site-wide daily cap:

| Action | Per visitor | Site-wide per day |
|---|---|---|
| AI scan | 20/hour, 60/day | 2000 |
| Assistant question | 30/hour, 100/day | 3000 |
| Report a problem | 10/hour | 1000 |
| Log in / sign up | 10 per 15 min, 40/day | none |

Counts live in Supabase so they hold across serverless instances; if the database is unreachable an
in-memory counter (per instance) takes over. Invalid uploads don't count.

## Known gaps and follow-ups

1. **Dependency audit not automated.** Turn on GitHub Dependabot alerts (repo Settings → Code security).
2. **Supabase Auth sees the server's IP**, not the visitor's, so Supabase's own per-IP auth limits are shared
   by all users. Our per-visitor limits run first; if sign-ups start failing at scale, raise the limits in
   Supabase (Authentication → Rate Limits) or move sign-in to the browser.
3. **Sign-up says when an email already has an account** (account enumeration). Accepted for clarity.
4. **No email confirmation or password reset** yet: both need an email sender (e.g. Resend) configured in Supabase.
5. **Admins are a list of emails** (`ADMIN_EMAILS`). Fine for a small team; move to roles if it grows.
6. **Static files** (CSS, fonts) are served by Vercel's CDN without the app's headers. They contain no user data.
