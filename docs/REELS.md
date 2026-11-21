# Reel drafts (internal content pipeline)

Twice a week, n8n asks RELOOP for a short-video script (Instagram Reels / YouTube Shorts) about sorting one kind of
waste. The script lands in a Google Sheet for the team to check, film and post by hand. **Nothing is public and
nothing is posted automatically.** There is no web page for this: only a private API that needs a secret key.

```
n8n schedule (Mon + Thu 9am IST)
  → POST https://reloop-india.vercel.app/api/internal/reel   (header X-Reloop-Internal-Key)
       topic (rotates) → passages from the loaded official documents → Claude writes the script
       → Python checks → draft
  → Google Sheet "Reel drafts" (one row per draft)  → Slack: "New reel draft to review"
```

## What a draft contains
Title, spoken **hook**, on-screen hook, a **shot list** (4-7 shots: what to film, on-screen text, what to say, seconds),
caption, hashtags, safety note, **key facts each tied to a numbered source**, the sources, and review notes.

## Why it's safe to rely on
- **Facts come only from the loaded documents.** Every claim is listed with the passage it came from. If the documents
  don't cover a topic, no script is written ("Not written - no sources").
- **Checks after the AI** (in `reloop/services/reels.py`) flag, as "Needs fixing before filming": figures that aren't in
  the sources (%, kg, rupees), carbon or impact claims, links or phone numbers, suggestions to donate, reuse or sell
  hazardous or medical items, and facts pointing to sources that don't exist. "Never donate medicines" is allowed.
- **A person always reviews.** Check each key fact against its source, then fill in **Reviewer** and **Posted**.
- Demo mode (`LLM_PROVIDER=mock`) marks drafts "DEMO" and must never be posted.

## Topics
Used batteries, expired medicines, tube lights and CFL bulbs, four bins at home, wet waste, dry waste, sanitary waste,
old electronics, paint and pesticide containers, plastic at home. The schedule rotates through them. To add one, add a
`ReelTopic` to `TOPICS` in `reloop/services/reels.py`, with search questions worded like the official documents.
Ask for a specific topic by sending `{"topic": "batteries"}`; skip recent ones with `{"avoid": ["batteries"]}`.

## Setup
1. **Secret:** make a random value of 32+ characters
   (`.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(32))"`). Put it in Vercel as
   `INTERNAL_API_SECRET` (Production, Sensitive) and redeploy. `/api/health` then shows `"internal_api": true`.
2. **Sheet:** create **RELOOP reel drafts** with these headers in row 1 (A to Q):
   `Created (IST)`, `Topic`, `Lane`, `Status`, `Title`, `Hook`, `On-screen hook`, `Shot list`, `Total seconds`,
   `Caption`, `Hashtags`, `Safety note`, `Key facts`, `Sources`, `Review notes`, `Reviewer`, `Posted`.
3. **n8n:** Workflows → Create workflow → ⋯ → Import from file → `n8n/reloop-reel-drafts.json`.
   - **Ask RELOOP for a reel draft:** Credential → create **Header Auth**: Name `X-Reloop-Internal-Key`,
     Value = the secret.
   - **Add to Reel drafts sheet:** choose your Google Sheets login, the **RELOOP reel drafts** document and tab.
   - **Tell the team** and **Report a problem:** choose your Slack login and channel.
   - Save and switch the workflow **Active** (Publish if shown). Use **Execute workflow** once to test.

Each draft is one paid AI call (about 25 seconds). The API allows 20 per hour and 100 per day.
