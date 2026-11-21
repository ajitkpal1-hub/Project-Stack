// RELOOP: check that this message really came from ElevenLabs, then build one row for the Google Sheet.
// This is the code inside the "Check signature + build row" node of n8n/reloop-voice-calls.json.
// Paste the ElevenLabs webhook secret below ONLY inside n8n. Never commit it to the repo.

const crypto = require('crypto');
const WEBHOOK_SECRET = 'PASTE_ELEVENLABS_WEBHOOK_SECRET_HERE';
const MAX_AGE_SECONDS = 30 * 60; // ElevenLabs' own SDK accepts messages up to 30 minutes old

if (WEBHOOK_SECRET.startsWith('PASTE_')) {
  throw new Error('Paste the ElevenLabs webhook secret into this node first.');
}

// 1. The exact bytes ElevenLabs sent (the Webhook node has "Raw Body" switched on).
const first = $input.first();
const headers = first.json.headers || {};
let raw;
try {
  raw = (await this.helpers.getBinaryDataBuffer(0, 'data')).toString('utf8');
} catch (e) {
  throw new Error('No raw body found. In the Webhook node, open Options and switch on "Raw Body".');
}

// 2. Signature header looks like: t=<timestamp>,v0=<hex HMAC-SHA256 of "<timestamp>.<raw body>">
const sigHeader = String(headers['elevenlabs-signature'] || '');
let timestamp = '';
let signature = '';
for (const part of sigHeader.split(',')) {
  const p = part.trim();
  if (p.startsWith('t=')) timestamp = p.slice(2);
  if (p.startsWith('v0=')) signature = p;
}
if (!timestamp || !signature) throw new Error('Rejected: missing ElevenLabs-Signature header.');

const expected = 'v0=' + crypto.createHmac('sha256', WEBHOOK_SECRET).update(`${timestamp}.${raw}`).digest('hex');
const a = Buffer.from(signature);
const b = Buffer.from(expected);
if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
  throw new Error('Rejected: signature does not match. Check the secret in this node.');
}
let sentAt = Number(timestamp);
if (sentAt > 1e12) sentAt = sentAt / 1000; // tolerate milliseconds
if (!Number.isFinite(sentAt) || Date.now() / 1000 - sentAt > MAX_AGE_SECONDS) {
  throw new Error('Rejected: message is too old.');
}

// 3. Only finished-call summaries go to the sheet (audio and failed-call events are ignored).
const payload = JSON.parse(raw);
if (payload.type !== 'post_call_transcription') return [];

const data = payload.data || {};
const meta = data.metadata || {};
const analysis = data.analysis || {};
const collected = analysis.data_collection_results || {};

// Data collection results can be keyed by the item's name ("item") or by an internal ID (items made in the
// ElevenLabs analysis library), and can arrive as an object or a list. Find each item by its name, any ID
// field, or the start of the description we gave it in docs/N8N.md.
const DESCRIPTION_STARTS = {
  item: 'the main item the caller asked about',
  waste_lane: "the lane from reloop's classify_item",
  donation_lead: 'true only if the classify_item result',
  safety_concern: 'true if the caller asked about hazardous',
  locality: 'the locality or 6-digit pin code',
  unanswered_question: "a question the helper couldn't answer",
  contact_consent: 'true only if the caller clearly agreed',
  caller_name: "the caller's first name",
  caller_phone: "the caller's phone number",
  customer_name: 'the full name of the customer',
};
const entries = (Array.isArray(collected) ? collected.map((e, i) => [String(i), e]) : Object.entries(collected))
  .map(([k, v]) => {
    const labels = [k];
    if (v && typeof v === 'object') {
      for (const f of ['data_collection_id', 'name', 'id', 'key', 'identifier']) if (typeof v[f] === 'string') labels.push(v[f]);
    }
    const schema = (v && typeof v === 'object' && v.json_schema) || {};
    return { labels: labels.map((s) => s.toLowerCase()), description: String(schema.description || '').toLowerCase(), v };
  });
const pick = (key) => {
  const start = DESCRIPTION_STARTS[key];
  const hit = entries.find((e) => e.labels.includes(key))
    || (start && entries.find((e) => e.description.startsWith(start)));
  if (!hit) return '';
  let v = hit.v;
  if (v && typeof v === 'object') v = v.value ?? v.result ?? '';
  if (v === null || v === undefined || String(v).toLowerCase() === 'null') return '';
  return v;
};
const yes = (key) => {
  const v = pick(key);
  return v === true || String(v).toLowerCase() === 'true' ? 'Yes' : 'No';
};

// Contact details are kept only when the caller agreed to a callback, and only in their own columns.
const consent = yes('contact_consent');
const cleanPhone = (v) => {
  const digits = String(v || '').replace(/[^\d+]/g, '');
  const local = digits.replace(/^(\+?91)/, '');
  return /^[6-9]\d{9}$/.test(local) ? '+91 ' + local : (digits.length >= 8 ? digits : '');
};
const callerName = consent === 'Yes' ? String(pick('caller_name') || pick('customer_name') || '').slice(0, 60) : '';
const callerPhone = consent === 'Yes' ? cleanPhone(pick('caller_phone')) : '';

// Privacy: the summary and other text columns never carry phone numbers or emails (PIN codes, 6 digits, stay).
const scrub = (text) => String(text || '')
  .replace(/(\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}/g, '[number removed]')
  .replace(/[^\s@]+@[^\s@]+\.[^\s@]+/g, '[email removed]')
  .slice(0, 1000);

const started = meta.start_time_unix_secs ? new Date(meta.start_time_unix_secs * 1000) : new Date();
const donationLead = yes('donation_lead');
const safetyConcern = yes('safety_concern');

return [{
  json: {
    'Call time (IST)': started.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }),
    'Conversation ID': data.conversation_id || '',
    'Duration (seconds)': meta.call_duration_secs ?? '',
    'Call result': analysis.call_successful || '',
    'Item': scrub(pick('item')),
    'Lane': scrub(pick('waste_lane')),
    'Donation lead': donationLead,
    'Safety concern': safetyConcern,
    'Locality or PIN': scrub(pick('locality')),
    'Unanswered question': scrub(pick('unanswered_question')),
    'Summary': scrub(analysis.transcript_summary),
    'Needs follow-up': donationLead === 'Yes' || safetyConcern === 'Yes' || callerPhone ? 'Yes' : 'No',
    'Name': callerName,
    'Phone': callerPhone,
    'Contact consent': consent,
    // Diagnostic: how ElevenLabs labelled each collected item (labels and value types only, never values).
    // Handy if columns ever come through empty again. Needs a 'Debug' column in the sheet (or n8n ignores it).
    'Debug': 'v3 | ' + (Array.isArray(collected) ? 'list' : typeof collected) + ' | ' + entries.map((e) =>
      e.labels.join('/') + ':' + (e.v && typeof e.v === 'object' ? 'obj{' + Object.keys(e.v).join(',') + '}' : typeof e.v)
      + (e.description ? '~' + e.description.slice(0, 25) : '')).join(' ; ').slice(0, 1500),
  },
}];
