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

ROW = "$('Check signature + build row').item.json"


def field(name: str) -> str:
    """A JS expression for one column of the row built by the Code node."""
    return f"{ROW}['{name}']"


# Slack is seen by the whole channel, so it never carries the caller's name or phone number.
SLACK_MESSAGE = (
    "=:recycle: *RELOOP voice call needs follow-up*\n"
    f"*Item:* {{{{ {field('Item')} || 'not recorded' }}}} (lane: {{{{ {field('Lane')} || 'n/a' }}}})\n"
    f"*Donation lead:* {{{{ {field('Donation lead')} }}}}   *Safety concern:* {{{{ {field('Safety concern')} }}}}\n"
    f"*Locality or PIN:* {{{{ {field('Locality or PIN')} || 'not given' }}}}\n"
    f"*Callback requested:* {{{{ {field('Contact consent')} === 'Yes' ? 'yes, contact details are in HubSpot' : 'no' }}}}\n"
    f"*Unanswered question:* {{{{ {field('Unanswered question')} || 'none' }}}}\n"
    f">{{{{ {field('Summary')} }}}}\n"
    f"_Conversation {{{{ {field('Conversation ID')} }}}}_"
)

HUBSPOT = "https://api.hubapi.com/crm/v3/objects"
IS_PIN = f"/^[1-9][0-9]{{5}}$/.test({field('Locality or PIN')})"
CONTACT_PROPERTIES = (
    f"{{ firstname: {field('Name')}, phone: {field('Phone')}, "
    f"zip: {IS_PIN} ? {field('Locality or PIN')} : undefined, "
    f"city: {IS_PIN} ? undefined : ({field('Locality or PIN')} || undefined) }}"
)
NOTE_BODY = (
    f"'<b>RELOOP voice call</b> (' + {field('Call time (IST)')} + ')<br>' + "
    f"'Item: ' + {field('Item')} + ' (lane: ' + {field('Lane')} + ')<br>' + "
    f"'Donation lead: ' + {field('Donation lead')} + ', safety concern: ' + {field('Safety concern')} + '<br>' + "
    f"'Locality or PIN: ' + {field('Locality or PIN')} + '<br>' + "
    f"'Unanswered question: ' + ({field('Unanswered question')} || 'none') + '<br><br>' + "
    f"{field('Summary')} + '<br><br>Conversation ' + {field('Conversation ID')}"
)


def if_node(node_id: str, name: str, position: list[int], conditions: list[dict]) -> dict:
    return {
        "id": node_id, "name": name, "type": "n8n-nodes-base.if", "typeVersion": 2, "position": position,
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose"},
                "conditions": conditions,
                "combinator": "and",
            },
            "options": {},
        },
    }


def hubspot_request(node_id: str, name: str, position: list[int], method: str, url: str, body: str) -> dict:
    """HubSpot API call using n8n's 'HubSpot App Token' credential (a HubSpot private app token)."""
    return {
        "id": node_id, "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": position,
        "parameters": {
            "method": method, "url": url,
            "authentication": "predefinedCredentialType", "nodeCredentialType": "hubspotAppToken",
            "sendBody": True, "specifyBody": "json", "jsonBody": "={{ JSON.stringify(" + body + ") }}",
            "options": {},
        },
    }


EXTRA_NODES = [
    {
        "id": "a1f0c6de-1111-4c4c-9a01-000000000006",
        "name": "Slack alert",
        "type": "n8n-nodes-base.slack",
        "typeVersion": 2.3,
        "onError": "continueRegularOutput",
        "position": [1040, 100],
        "parameters": {
            "authentication": "oAuth2",
            "select": "channel",
            "channelId": {"__rl": True, "mode": "list", "value": ""},
            "text": SLACK_MESSAGE,
            "otherOptions": {},
        },
    },
    if_node("a1f0c6de-1111-4c4c-9a01-000000000007", "Callback agreed?", [1040, 300], [
        {"id": "c0b1", "leftValue": "={{ " + field("Contact consent") + " }}", "rightValue": "Yes",
         "operator": {"type": "string", "operation": "equals"}},
        {"id": "c0b2", "leftValue": "={{ " + field("Phone") + " }}", "rightValue": "",
         "operator": {"type": "string", "operation": "notEmpty", "singleValue": True}},
    ]),
    hubspot_request("a1f0c6de-1111-4c4c-9a01-000000000008", "HubSpot: find contact by phone", [1300, 300], "POST",
                    HUBSPOT + "/contacts/search",
                    "{ filterGroups: [{ filters: [{ propertyName: 'phone', operator: 'EQ', value: " + field("Phone") + " }] }], "
                    "properties: ['firstname', 'phone'], limit: 1 }"),
    if_node("a1f0c6de-1111-4c4c-9a01-000000000009", "Already in HubSpot?", [1560, 300], [
        {"id": "c0c1", "leftValue": "={{ $json.total }}", "rightValue": 0, "operator": {"type": "number", "operation": "gt"}},
    ]),
    hubspot_request("a1f0c6de-1111-4c4c-9a01-000000000010", "HubSpot: update contact", [1820, 200], "PATCH",
                    "=" + HUBSPOT + "/contacts/{{ $json.results[0].id }}",
                    "{ properties: " + CONTACT_PROPERTIES + " }"),
    hubspot_request("a1f0c6de-1111-4c4c-9a01-000000000011", "HubSpot: create contact", [1820, 400], "POST",
                    HUBSPOT + "/contacts",
                    "{ properties: Object.assign(" + CONTACT_PROPERTIES + ", { lifecyclestage: 'lead' }) }"),
    hubspot_request("a1f0c6de-1111-4c4c-9a01-000000000012", "HubSpot: add call note", [2080, 300], "POST",
                    HUBSPOT + "/notes",
                    "{ properties: { hs_timestamp: new Date().toISOString(), hs_note_body: " + NOTE_BODY + " }, "
                    "associations: [{ to: { id: $json.id }, "
                    "types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 202 }] }] }"),  # 202 = note to contact
]


def link(target: str) -> dict:
    return {"node": target, "type": "main", "index": 0}


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
                # RAW: store text as-is, so "+91 98..." isn't read as a formula (#ERROR!).
                "options": {"cellFormat": "RAW"},
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
        *EXTRA_NODES,
    ],
    "connections": {
        "ElevenLabs post-call webhook": {"main": [[{"node": "Check signature + build row", "type": "main", "index": 0}]]},
        "Check signature + build row": {"main": [[{"node": "Add row to Google Sheet", "type": "main", "index": 0}]]},
        "Add row to Google Sheet": {"main": [[{"node": "Needs follow-up?", "type": "main", "index": 0}]]},
        "Needs follow-up?": {"main": [[link("Email the team")], []]},
        "Email the team": {"main": [[link("Slack alert")]]},
        "Slack alert": {"main": [[link("Callback agreed?")]]},
        "Callback agreed?": {"main": [[link("HubSpot: find contact by phone")], []]},
        "HubSpot: find contact by phone": {"main": [[link("Already in HubSpot?")]]},
        "Already in HubSpot?": {"main": [[link("HubSpot: update contact")], [link("HubSpot: create contact")]]},
        "HubSpot: update contact": {"main": [[link("HubSpot: add call note")]]},
        "HubSpot: create contact": {"main": [[link("HubSpot: add call note")]]},
    },
    "settings": {"executionOrder": "v1"},
    "pinData": {},
}

out = ROOT / "n8n" / "reloop-voice-calls.json"
out.write_text(json.dumps(workflow, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")

# Just the Slack + HubSpot boxes, for pasting onto an existing workflow's canvas (keeps its secret and logins).
extra_names = {n["name"] for n in EXTRA_NODES}
snippet = {
    "nodes": EXTRA_NODES,
    "connections": {k: v for k, v in workflow["connections"].items() if k in extra_names},
}
out = ROOT / "n8n" / "add-slack-hubspot-nodes.json"
out.write_text(json.dumps(snippet, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")

# ---------- Workflow 2: reel-script drafts on a schedule (internal, never public) ----------

DRAFT = "$('Ask RELOOP for a reel draft').item.json"
REEL_SLACK = (
    "=:clapper: *New reel draft to review*: {{ " + DRAFT + ".sheet_row['Topic'] }}\n"
    "*Status:* {{ " + DRAFT + ".sheet_row['Status'] }}\n"
    "*Hook:* {{ " + DRAFT + ".sheet_row['Hook'] }}\n"
    "{{ " + DRAFT + ".sheet_row['Review notes'] ? '*Review notes:*\n' + " + DRAFT + ".sheet_row['Review notes'] : '' }}\n"
    "Open the 'Reel drafts' sheet to check the facts against the sources, then film and post by hand."
)

reel_workflow = {
    "name": "RELOOP reel drafts (internal)",
    "nodes": [
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000001",
            "name": "Mon and Thu 9am",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [0, 0],
            "parameters": {"rule": {"interval": [{"field": "weeks", "triggerAtDay": [1, 4], "triggerAtHour": 9}]}},
        },
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000002",
            "name": "Ask RELOOP for a reel draft",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [260, 0],
            "parameters": {
                "method": "POST",
                "url": "https://reloop-india.vercel.app/api/internal/reel",
                # Header Auth credential: name X-Reloop-Internal-Key, value = INTERNAL_API_SECRET (pasted in n8n only).
                "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
                "sendBody": True, "specifyBody": "json", "jsonBody": "{}",
                "options": {"timeout": 120000, "response": {"response": {"neverError": True}}},
            },
        },
        if_node("b2e1d7aa-2222-4c4c-9a01-000000000003", "Draft made?", [520, 0], [
            {"id": "d0a1", "leftValue": "={{ ['draft', 'needs_fix'].includes($json.status) }}", "rightValue": "",
             "operator": {"type": "boolean", "operation": "true", "singleValue": True}},
        ]),
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000004",
            "name": "Take sheet row",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [780, -100],
            "parameters": {"mode": "runOnceForAllItems", "language": "javaScript",
                           "jsCode": "// The API returns a ready-made row for the 'Reel drafts' sheet.\n"
                                     "return [{ json: $input.first().json.sheet_row }];"},
        },
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000005",
            "name": "Add to Reel drafts sheet",
            "type": "n8n-nodes-base.googleSheets",
            "typeVersion": 4.5,
            "position": [1040, -100],
            "parameters": {
                "operation": "append",
                "documentId": {"__rl": True, "mode": "list", "value": ""},
                "sheetName": {"__rl": True, "mode": "list", "value": ""},
                "columns": {"mappingMode": "autoMapInputData", "value": {}},
                "options": {"cellFormat": "RAW"},
            },
        },
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000006",
            "name": "Tell the team",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2.3,
            "position": [1300, -100],
            "onError": "continueRegularOutput",
            "parameters": {"authentication": "oAuth2", "select": "channel",
                           "channelId": {"__rl": True, "mode": "list", "value": ""}, "text": REEL_SLACK, "otherOptions": {}},
        },
        {
            "id": "b2e1d7aa-2222-4c4c-9a01-000000000007",
            "name": "Report a problem",
            "type": "n8n-nodes-base.slack",
            "typeVersion": 2.3,
            "position": [780, 120],
            "onError": "continueRegularOutput",
            "parameters": {"authentication": "oAuth2", "select": "channel",
                           "channelId": {"__rl": True, "mode": "list", "value": ""},
                           "text": "=:warning: No reel draft this time ({{ $json.status || 'error' }}): {{ $json.message || 'no reply from RELOOP' }}",
                           "otherOptions": {}},
        },
    ],
    "connections": {
        "Mon and Thu 9am": {"main": [[link("Ask RELOOP for a reel draft")]]},
        "Ask RELOOP for a reel draft": {"main": [[link("Draft made?")]]},
        "Draft made?": {"main": [[link("Take sheet row")], [link("Report a problem")]]},
        "Take sheet row": {"main": [[link("Add to Reel drafts sheet")]]},
        "Add to Reel drafts sheet": {"main": [[link("Tell the team")]]},
    },
    "settings": {"executionOrder": "v1", "timezone": "Asia/Kolkata"},
    "pinData": {},
}
out = ROOT / "n8n" / "reloop-reel-drafts.json"
out.write_text(json.dumps(reel_workflow, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")
