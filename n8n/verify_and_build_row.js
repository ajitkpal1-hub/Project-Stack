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

// Data collection results may arrive as a plain value or as { value: ... }.
const pick = (key) => {
  const v = collected[key];
  if (v === null || v === undefined) return '';
  if (typeof v === 'object') return v.value ?? '';
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
  },
}];
