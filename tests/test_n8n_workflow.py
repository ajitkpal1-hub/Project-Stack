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
