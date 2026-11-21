"""Build n8n/reloop-voice-calls.json from n8n/verify_and_build_row.js.

Run after editing the JS:  .venv/Scripts/python scripts/build_n8n_workflow.py
The workflow never contains secrets: the webhook secret is pasted into n8n by hand.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = (ROOT / "n8n" / "verify_and_build_row.js").read_text(encoding="utf-8")

ALERT_MESSAGE = """=A RELOOP voice call needs a look.

Time: {{ $json['Call time (IST)'] }}
Item: {{ $json['Item'] }}  (lane: {{ $json['Lane'] }})
Donation lead: {{ $json['Donation lead'] }}
Safety concern: {{ $json['Safety concern'] }}
Locality or PIN: {{ $json['Locality or PIN'] }}
Callback: {{ $json['Contact consent'] === 'Yes' ? $json['Name'] + ', ' + $json['Phone'] : 'not requested' }}

Summary: {{ $json['Summary'] }}

Conversation ID: {{ $json['Conversation ID'] }} (find the full call in ElevenLabs -> Agents -> Conversations).
"""

workflow = {
    "name": "RELOOP voice calls to Google Sheet",
    "nodes": [
        {
            "id": "a1f0c6de-1111-4c4c-9a01-000000000001",
            "name": "ElevenLabs post-call webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [0, 0],
            "webhookId": "5d0f7c2e-reloop-voice-calls",
            "parameters": {
                "httpMethod": "POST",
                "path": "reloop-voice-calls",
                "responseMode": "onReceived",
                "options": {"rawBody": True},
            },
        },
        {
            "id": "a1f0c6de-1111-4c4c-9a01-000000000002",
            "name": "Check signature + build row",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [260, 0],
            "parameters": {"mode": "runOnceForAllItems", "language": "javaScript", "jsCode": CODE},
        },
        {
            "id": "a1f0c6de-1111-4c4c-9a01-000000000003",
            "name": "Add row to Google Sheet",
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.5,
            "position": [520, 0],
            "parameters": {
                "operation": "appendOrUpdate",
                "documentId": {"__rl": True, "mode": "list", "value": ""},
                "sheetName": {"__rl": True, "mode": "list", "value": ""},
                "columns": {"mappingMode": "autoMapInputData", "value": {}, "matchingColumns": ["Conversation ID"]},
                "options": {},
            },
        },
        {
            "id": "a1f0c6de-1111-4c4c-9a01-000000000004",
            "name": "Needs follow-up?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [780, 0],
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                    "conditions": [{
                        "id": "c0a1",
                        "leftValue": "={{ $('Check signature + build row').item.json['Needs follow-up'] }}",
                        "rightValue": "Yes",
                        "operator": {"type": "string", "operation": "equals"},
                    }],
                    "combinator": "and",
                },
                "options": {},
            },
        },
        {
            "id": "a1f0c6de-1111-4c4c-9a01-000000000005",
            "name": "Email the team",
            "type": "n8n-nodes-base.gmail",
            "typeVersion": 2.1,
            "position": [1040, -100],
            "parameters": {
                "sendTo": "",
                "subject": "=RELOOP voice call to follow up: {{ $('Check signature + build row').item.json['Item'] || 'a call' }}",
                "emailType": "text",
                "message": ALERT_MESSAGE.replace("$json[", "$('Check signature + build row').item.json["),
                "options": {"appendAttribution": False},
            },
        },
    ],
    "connections": {
        "ElevenLabs post-call webhook": {"main": [[{"node": "Check signature + build row", "type": "main", "index": 0}]]},
        "Check signature + build row": {"main": [[{"node": "Add row to Google Sheet", "type": "main", "index": 0}]]},
        "Add row to Google Sheet": {"main": [[{"node": "Needs follow-up?", "type": "main", "index": 0}]]},
        "Needs follow-up?": {"main": [[{"node": "Email the team", "type": "main", "index": 0}], []]},
    },
    "settings": {"executionOrder": "v1"},
    "pinData": {},
}

out = ROOT / "n8n" / "reloop-voice-calls.json"
out.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")
