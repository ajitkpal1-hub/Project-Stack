# Knowledge base documents

Put the official documents the disposal assistant may answer from in this folder (PDF, TXT or MD),
and describe each one in `manifest.toml`. Then run:

```bash
.venv/Scripts/python scripts/ingest.py --dry-run   # check text extraction, no cost
.venv/Scripts/python scripts/ingest.py             # embed and store in Supabase
```

Rules:
- Only official or documented sources (government rules, CPCB/MPCB guidance, municipal instructions, NGO acceptance policies).
- Record the real title, publisher, date and download link. Never invent them.
- Scanned PDFs without a text layer need OCR first; the script reports them.
- Re-running is safe: an unchanged file is replaced, not duplicated. A changed file is stored as a new version, so archive the old one (admin tools arrive in Phase 8).
