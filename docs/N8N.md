# Voice calls to Google Sheet (n8n)

After every voice-helper call, ElevenLabs sends a short summary to n8n. n8n checks the message really came from
ElevenLabs, adds one row to a Google Sheet, and emails the team when the call needs a follow-up.

```
Call ends ──▶ ElevenLabs post-call webhook (signed) ──▶ n8n
                                                         ├─ check signature (reject anything not from ElevenLabs)
                                                         ├─ add / update a row in Google Sheet
                                                         └─ donation lead or safety concern? ──▶ email the team
```

**What is stored:** time, duration, item, lane, donation lead (yes/no), safety concern (yes/no), locality or PIN,
any question the helper couldn't answer, and ElevenLabs' short summary. **Never** the full transcript or audio.
Phone numbers and email addresses are removed if a caller says them anyway. Share the sheet only with the team.

Files: `n8n/reloop-voice-calls.json` (import this), `n8n/verify_and_build_row.js` (the checking code, for reading).
After editing the JS, run `.venv/Scripts/python scripts/build_n8n_workflow.py` to rebuild the JSON.

## 1. Google Sheet
Create a sheet named **RELOOP voice calls**. In row 1, type these headers exactly, one per column (A to L):

| A | B | C | D | E | F | G | H | I | J | K | L |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Call time (IST) | Conversation ID | Duration (seconds) | Call result | Item | Lane | Donation lead | Safety concern | Locality or PIN | Unanswered question | Summary | Needs follow-up |

## 2. Data collection in ElevenLabs
Agent → **Analysis** tab → **Data collection** → **Add data collection**, once per row:

| Name | Data type | Description |
|---|---|---|
| `item` | string | The main item the caller asked about, in a few plain words, e.g. "wooden chair". Empty if none. |
| `waste_lane` | string | The lane from RELOOP's classify_item tool result: wet, dry, reuse, textile, e-waste, hazardous, medical or unsure. Empty if the tool wasn't used. |
| `donation_lead` | boolean | True only if the classify_item result said the item can be donated (donation status "eligible") and the caller sounded interested in donating it. |
| `safety_concern` | boolean | True if the caller asked about hazardous or medical waste (batteries, chemicals, medicines, sharps) or described an emergency. |
| `locality` | string | The locality or 6-digit PIN code the caller mentioned. Never a name, phone number or full address. Empty if none. |
| `unanswered_question` | string | A question the helper couldn't answer because RELOOP's documents or directory didn't cover it. Empty if everything was answered. |

Save (and Publish if shown). Then check the agent's **Tools** list still shows all three tools.

## 3. n8n
1. n8n → **Workflows** → **Create workflow** → **⋯** (top right) → **Import from file** → choose `n8n/reloop-voice-calls.json`.
2. **Add row to Google Sheet** node: create a Google Sheets credential (sign in with Google), choose the **RELOOP voice calls** document and the sheet tab. Check "Column to match on" is **Conversation ID**.
3. **Email the team** node: create a Gmail credential and put the team's email address in **To**. (Or delete this node if you don't want emails.)
4. **ElevenLabs post-call webhook** node: copy the **Production URL**.
5. Keep n8n open. The secret comes in step 4.

## 4. ElevenLabs webhook
1. ElevenLabs → **Agents** → **Settings** (workspace settings for agents) → **Post-call webhook** → create a webhook with the n8n **Production URL**, authentication **HMAC**.
2. Copy the **webhook secret** ElevenLabs shows.
3. In n8n, open **Check signature + build row** and replace `PASTE_ELEVENLABS_WEBHOOK_SECRET_HERE` with that secret (keep the quotes). Don't put it anywhere else.
4. If you see per-agent settings, make sure the RELOOP agent uses this webhook with the **transcript** event.
5. In n8n, **Save** and switch the workflow to **Active**.

## 5. Test
Make a short call on `/talk` ("I have an old wooden chair", then "it works and it's clean"), hang up, and wait a minute.
- A new row should appear in the sheet, with Donation lead = Yes, and the team gets an email.
- n8n → **Executions** shows each run. A red run that says **Rejected** means the secret in the Code node doesn't match ElevenLabs.

## Notes
- ElevenLabs needs a 200 reply; the webhook answers straight away, so slow Google calls don't cause retries.
- If retries are switched on in ElevenLabs, the same call updates its row instead of adding a duplicate (matched on Conversation ID).
- Data collection is filled in by ElevenLabs' AI after the call, so treat the Yes/No columns as hints and check the summary.
