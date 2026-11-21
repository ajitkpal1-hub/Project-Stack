# Voice agent (ElevenLabs)

RELOOP's voice helper answers household questions by voice: which bin, can it be donated, where to drop it.
ElevenLabs does the listening and speaking. **RELOOP gives every answer**: the agent calls three RELOOP tools
and speaks what they return. It never answers waste questions from its own knowledge.

```
Caller ──voice──▶ ElevenLabs agent ──POST + X-Reloop-Voice-Key──▶ reloop-india.vercel.app/api/voice/…
                                   ◀──── JSON with a "say" line ────
```

| Tool | RELOOP endpoint | Use it for |
|---|---|---|
| `ask_official_guidance` | `POST /api/voice/ask` | Rules and "how do I dispose of…" questions. Answers come only from the loaded official documents. |
| `classify_item` | `POST /api/voice/classify` | "I have a … what do I do with it?" Bin, safety, and whether it can be donated. |
| `find_centres` | `POST /api/voice/centres` | "Where can I drop it near …?" Verified places first. Map places are marked unchecked. |

## 1. Turn the tools on in RELOOP (once)

1. Create a random secret of 32 or more characters:
   `.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Vercel → Project → Settings → Environment Variables → Production: add `VOICE_TOOL_SECRET` with that value and mark it **Sensitive**.
   For local testing, add the same line to `.env`.
3. Redeploy (Deployments → ⋯ → Redeploy).
4. Check that `https://reloop-india.vercel.app/api/health` shows `"voice_tools": true`.

Keep the secret out of chat, email and screenshots. If it leaks, make a new one and update it in both Vercel and ElevenLabs.

## 2. Create the agent (ElevenLabs dashboard)

ElevenLabs → **Agents** → **Create agent** → start from a blank agent. Name: `RELOOP voice helper`.

### First message
> Namaste! I'm the RELOOP voice helper. I can tell you which bin something goes in, whether it can be donated, and where to drop it in Thakurli, Dombivli and Kalyan. This call is handled by our voice partner ElevenLabs. What would you like to get rid of today?

### System prompt
Paste this as it is:

```
You are the RELOOP voice helper. RELOOP helps households in India sort waste, reuse and donate. The pilot area is Thakurli, Dombivli and Kalyan in Maharashtra.

HOW YOU ANSWER
- You do not know waste rules yourself. Every fact you give must come from a tool result in this conversation. If no tool has answered, you don't know yet.
- Each tool result has a "say" field. Speak its meaning in short, natural sentences. You may shorten it, but never add facts, places, phone numbers, rules, percentages or promises that are not in the result.
- When you need a tool, call it straight away in the same turn. Never say you will look something up and then stop without calling the tool.
- Tool inputs must be in English. If the caller speaks Hindi or Marathi, translate their words into simple English for the tool, then answer in the caller's language. Say that the official guidance is in English and you are summarising it.

WHICH TOOL
- The caller describes an item they want to get rid of → classify_item.
- The caller asks about rules, a type of waste, or "how do I dispose of…" → ask_official_guidance.
- The caller asks where to take something → find_centres. Ask for their locality or 6-digit PIN code first if they haven't given it.

DONATION AND CONDITION
- Never say an item can be donated unless the latest classify_item result has donation status "eligible".
- If the result's ask_caller list has a question, ask it. When the caller answers about condition, call classify_item again with the same description and condition set to exactly one of:
  works_clean (it works and is clean), needs_repair (it needs a small fix or clean-up), broken (broken or worn out), not_sure.
- Only use the condition the caller actually told you. Never assume an item works or is clean.
- Medicines, syringes, batteries, chemicals and other hazardous items can never be donated, whatever the caller says.
- To donate or list an item, people use the Donate page on the RELOOP website. You cannot create listings, book pickups or contact anyone.

HONESTY
- If a result says the documents don't cover something, say so plainly and suggest the local municipal office. Do not fill the gap.
- If a result's "demo" is true, say it is a demonstration answer.
- Places marked "verified": false were not checked by RELOOP. Always tell the caller to call ahead.
- If a tool fails or says it is busy, apologise and suggest the RELOOP website: reloop-india.vercel.app.

PRIVACY AND SAFETY
- Ask for contact details only when a follow-up from the RELOOP team would help: the caller wants help donating an item, asked about hazardous or medical waste, or you couldn't answer their question. Then say: "If you'd like, our team can call you back about this. May I take your first name and phone number? We'll only use them to follow up on this request." Take them only if the caller agrees. If they say no, carry on without them.
- Read the phone number back once to confirm it, then don't repeat it again.
- Never ask for a full address, email or ID numbers. A locality or PIN code is enough.
- Never pass names or phone numbers to the RELOOP tools.
- If someone describes an emergency (fire, chemical spill, someone hurt, swallowed medicine), tell them to call 112 straight away and stop giving waste advice.
- Stay on household waste, reuse, recycling and donation. Politely decline anything else.

STYLE
- Warm, simple, short. Two or three sentences at a time, then let the caller speak.
```

### Language
In the agent's language settings choose English as the default and add Hindi and Marathi if you want them.
The tools still take English (see the prompt).

### Model
Pick any LLM the dashboard offers. A fast, low-cost one is enough, because RELOOP does the thinking and the agent only routes and speaks.

## 3. Add the three tools

For each one: agent → **Agent** section → **Add Tool** → Tool type **Webhook**.

All three share these settings:
- **Method:** `POST`
- **Headers:** add a header named `X-Reloop-Voice-Key`, choose type **Secret**, then **Create New Secret** and paste your `VOICE_TOOL_SECRET`.
  Create the secret once and reuse it for the other two tools.
- **Body content type:** JSON
- If you see a timeout setting, use **30 seconds**. Classification takes about 6–11 seconds.
- Optional: turn on a **tool call sound** so callers don't hear silence while RELOOP thinks.

### Tool 1: `ask_official_guidance`
- **URL:** `https://reloop-india.vercel.app/api/voice/ask`
- **Description:** `Answers questions about waste rules and how to dispose of things, using only RELOOP's loaded official documents. Use it for general questions such as "how do I dispose of batteries" or "what counts as wet waste".`
- **Body parameters:**

| Identifier | Type | Required | Description (value type: LLM Prompt) |
|---|---|---|---|
| `question` | string | yes | The caller's question as one clear English sentence, under 500 characters. No names, phone numbers or addresses. |

### Tool 2: `classify_item`
- **URL:** `https://reloop-india.vercel.app/api/voice/classify`
- **Description:** `Works out which bin an item goes in, safety warnings, what to do with it, and whether it can be donated. Call it again with a condition after the caller says whether the item works and is clean.`
- **Body parameters:**

| Identifier | Type | Required | Description (value type: LLM Prompt) |
|---|---|---|---|
| `description` | string | yes | The item in the caller's own words, in simple English, under 300 characters, e.g. "old wooden study table, one leg loose". Include the material and any battery, plug or liquid they mention. No personal details. |
| `condition` | string | no | Only if the caller has said it: one of `works_clean`, `needs_repair`, `broken`, `not_sure`. Otherwise leave it empty. |

### Tool 3: `find_centres`
- **URL:** `https://reloop-india.vercel.app/api/voice/centres`
- **Description:** `Finds places to drop off waste, recyclables or donations near a locality or PIN code. RELOOP-verified places come first; map places are marked not verified.`
- **Body parameters:**

| Identifier | Type | Required | Description (value type: LLM Prompt) |
|---|---|---|---|
| `place` | string | yes | Locality name or 6-digit PIN code, e.g. "Dombivli East" or "421201". |
| `material` | string | no | One of `wet`, `dry`, `reuse`, `textile`, `e-waste`, `hazardous`, `medical`. Use the lane from a classify_item result when there is one. Otherwise leave it empty. |

## 4. Security and privacy settings
- **Security → Allowlist:** add `reloop-india.vercel.app` (and `project-stack-wheat.vercel.app` if you still use it), so the widget only works on your site.
- **Privacy / data retention:** keep transcripts only as long as you need them. Turn off audio recording if you don't need it.
- **Spending:** set a usage or credit limit in your ElevenLabs workspace. RELOOP also caps voice tool calls (300 an hour, 1,500 a day).

## 5. Test in the dashboard
Use the agent's **Test** / call button and try these:

| Say | Expect |
|---|---|
| "I have an old wooden chair." | Reuse lane. It asks whether it works and is clean. It does not promise donation yet. |
| "Yes, it works and it's clean." | Calls the tool again with `works_clean`. It can be donated; use the Donate page. |
| "I have some expired cough syrup. It's sealed and clean." | Medical waste. Never donated, whatever the condition. |
| "How do I dispose of old batteries?" | Answers from the documents, or says plainly that they don't cover it. |
| "Where can I drop e-waste near 421201?" | Verified places, or says it has none yet. Any map places come with "call ahead". |
| "What's the weather today?" | Politely declines. |
| A tool with the wrong secret | RELOOP refuses (401) and the agent apologises and suggests the website. |

## 6. The website page (/talk)
The widget appears only on `/talk` ("Talk" in the menu). How it is set up:
- **Agent ID:** `ELEVENLABS_AGENT_ID` in `reloop/config.py` (public, not a secret). Set the env var to override it, or set it to empty to switch the widget off.
- **Pinned widget:** `@elevenlabs/convai-widget-embed` version `0.24.1` from unpkg, checked with a Subresource Integrity hash (`VOICE_WIDGET_*` in `reloop/security.py`).
  To upgrade, download the new `dist/index.js`, read the changelog, recompute the sha384 hash, update both values, and test a call on `/talk`.
- **Security policy:** only `/talk` gets the wider policy (the widget file, ElevenLabs `api`/`api.us`/`livekit` hosts, `blob:` worklets, inline styles, microphone).
  Every other page keeps the strict policy with no microphone. The widget's fingerprinting telemetry ping and its Google Fonts import stay blocked.
- **Allowlist:** the agent's Security → Allowlist must include the site's domain, or the widget can't connect.
- **Privacy:** the widget includes FingerprintJS (device details used by ElevenLabs to prevent misuse). The page says so, next to the voice-processing notice.

Checked 2026-11-21 in Edge: the widget loads with no blocked requests, and a call connects (`wss://api.us.elevenlabs.io/v1/convai/conversation`) and the agent speaks.

## 7. Next
- **n8n (Phase C):** a post-call webhook that saves each call's summary and alerts the team about donation leads and safety questions.
