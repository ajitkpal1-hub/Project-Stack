"""The n8n workflow file stays in sync with its script and never carries a secret."""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / "n8n" / "reloop-voice-calls.json"
SCRIPT = ROOT / "n8n" / "verify_and_build_row.js"


def test_workflow_matches_script(tmp_path):
    before = WORKFLOW.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_n8n_workflow.py")], check=True, capture_output=True)
    assert WORKFLOW.read_text(encoding="utf-8") == before, "run scripts/build_n8n_workflow.py and commit the result"


def test_workflow_has_no_secret_and_checks_signature():
    w = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    code = next(n for n in w["nodes"] if n["type"] == "n8n-nodes-base.code")["parameters"]["jsCode"]
    assert "const WEBHOOK_SECRET = 'PASTE_ELEVENLABS_WEBHOOK_SECRET_HERE';" in code
    assert "timingSafeEqual" in code and "elevenlabs-signature" in code
    assert not re.search(r"(wsec_|sk_|whsec_)[A-Za-z0-9]{8,}", WORKFLOW.read_text(encoding="utf-8"))
    hook = next(n for n in w["nodes"] if n["type"] == "n8n-nodes-base.webhook")["parameters"]
    assert hook["options"]["rawBody"] is True and hook["httpMethod"] == "POST"


def test_sheet_row_never_includes_transcript():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "data.transcript" not in code  # only the summary and collected fields, never the full transcript
    assert "[number removed]" in code and "[email removed]" in code


def test_contact_details_only_with_consent():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "const callerName = consent === 'Yes'" in code
    assert "const callerPhone = consent === 'Yes'" in code
    assert "'Phone': callerPhone" in code and "'Contact consent': consent" in code


def test_slack_never_carries_contact_details():
    w = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    text = next(n for n in w["nodes"] if n["name"] == "Slack alert")["parameters"]["text"]
    assert "['Phone']" not in text and "['Name']" not in text
    assert "details are in HubSpot" in text


def test_hubspot_only_after_consent():
    w = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    conn = w["connections"]
    assert conn["Callback agreed?"]["main"][0][0]["node"] == "HubSpot: find contact by phone"
    assert conn["Callback agreed?"]["main"][1] == []  # no consent: nothing goes to HubSpot
    gate = next(n for n in w["nodes"] if n["name"] == "Callback agreed?")["parameters"]["conditions"]["conditions"]
    assert {c["rightValue"] for c in gate} >= {"Yes"} and any(c["operator"]["operation"] == "notEmpty" for c in gate)
    hubspot = [n for n in w["nodes"] if n["name"].startswith("HubSpot")]
    assert len(hubspot) == 4 and all(n["parameters"]["nodeCredentialType"] == "hubspotAppToken" for n in hubspot)
    assert all(n["parameters"]["url"].lstrip("=").startswith("https://api.hubapi.com/") for n in hubspot)


def test_paste_in_snippet_matches_workflow():
    snippet = json.loads((ROOT / "n8n" / "add-slack-hubspot-nodes.json").read_text(encoding="utf-8"))
    w = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    names = {n["name"] for n in snippet["nodes"]}
    assert names == {"Slack alert", "Callback agreed?", "HubSpot: find contact by phone", "Already in HubSpot?",
                     "HubSpot: update contact", "HubSpot: create contact", "HubSpot: add call note"}
    assert all(n in w["nodes"] for n in snippet["nodes"])
    assert snippet["connections"]["Slack alert"]["main"][0][0]["node"] == "Callback agreed?"


def test_chain_runs_after_the_email():
    conn = json.loads(WORKFLOW.read_text(encoding="utf-8"))["connections"]
    assert conn["Needs follow-up?"]["main"][0] == [{"node": "Email the team", "type": "main", "index": 0}]
    assert conn["Email the team"]["main"][0][0]["node"] == "Slack alert"


def test_sheet_stores_phone_as_text():
    w = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    sheet = next(n for n in w["nodes"] if n["type"] == "n8n-nodes-base.googleSheets")
    assert sheet["parameters"]["options"]["cellFormat"] == "RAW"  # "+91 ..." would otherwise become a formula error


def test_phone_never_starts_with_plus():
    code = SCRIPT.read_text(encoding="utf-8")
    assert "'91 ' + local" in code and "'+91 '" not in code


def test_reel_workflow_is_scheduled_and_carries_no_secret():
    path = ROOT / "n8n" / "reloop-reel-drafts.json"
    w = json.loads(path.read_text(encoding="utf-8"))
    trigger = next(n for n in w["nodes"] if n["type"] == "n8n-nodes-base.scheduleTrigger")
    assert trigger["parameters"]["rule"]["interval"][0]["triggerAtDay"] == [1, 4]  # Monday and Thursday
    assert w["settings"]["timezone"] == "Asia/Kolkata"
    call = next(n for n in w["nodes"] if n["name"] == "Ask RELOOP for a reel draft")["parameters"]
    assert call["url"] == "https://reloop-india.vercel.app/api/internal/reel" and call["genericAuthType"] == "httpHeaderAuth"
    assert "X-Reloop-Internal-Key" not in json.dumps(call)  # the header and secret live in an n8n credential
    assert w["connections"]["Draft made?"]["main"][1][0]["node"] == "Report a problem"


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def test_n8n_expressions_have_no_backslashes():
    # n8n's expression parser rejected a backslash escape inside {{ }} with "invalid syntax" (Slack message, 2026-11-21).
    for name in ("reloop-voice-calls.json", "reloop-reel-drafts.json"):
        w = json.loads((ROOT / "n8n" / name).read_text(encoding="utf-8"))
        for n in w["nodes"]:
            if n["type"] == "n8n-nodes-base.code":
                continue  # plain JavaScript, not an expression
            for text in _strings(n["parameters"]):
                for expr in re.findall(r"\{\{(.*?)\}\}", text, flags=re.DOTALL):
                    assert "\\" not in expr, (name, n["name"], expr[:80])
