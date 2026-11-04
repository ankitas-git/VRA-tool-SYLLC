# VRA-tool-SYLLC

Local app for automating vendor risk assessments: register vendors, answer inherent-risk and control questions, score residual risk, and track when to reassess.

## Run

```bash
cd ~/Projects/VRA-tool-SYLLC
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run Home.py
```

SQLite data lives in `data/vra.db`. Uploaded documents are stored under `data/documents/<vendor_id>/` (git-ignored).

## Workflow

1. **Vendors** — register the vendor.
2. **Documents** — the vendor is asked for security documents; upload them here.
3. **Assess** — answer the questionnaire. The document request list updates live from the inherent-risk answers, and you can upload missing documents in place.
4. **History** — review past assessments, including what evidence was outstanding when each was scored.

## Security documents

- **Requested set** — every vendor: SOC 2 Type II report and information security policy. More are added by risk: incident response plan (internal data or more sensitive), DPA (PII or more sensitive), pen test summary and security questionnaire (PII or production access), BCP/DR plan (core or mission-critical), cyber insurance (regulated data or admin access).
- **Validation** — allowed types are PDF, Word, Excel, CSV, TXT, PNG and JPG, up to 25 MB. The file's leading bytes must match its extension. Filenames are sanitized and a SHA-256 hash is recorded.
- **Expiry** — taken from the issue date plus the document type's validity (for example SOC 2 is 12 months, ISO 27001 is 36 months, a DPA does not expire), or set by hand. Documents show as Current, Expiring soon (within 30 days), or Expired; expired ones count as outstanding.
- **Unverified claims** — a control answer of 4 or above with no current supporting document is flagged, e.g. "SOC 2 Type II current" with no SOC 2 report or ISO certificate on file. Scores are not changed; flags are recorded with the assessment.

## Scoring

- **Inherent** — weighted answers on data sensitivity, volume, system access, criticality, subprocessors.
- **Control** — assurance, encryption, identity, incident response, privacy terms, BCP.
- **Residual** — inherent reduced by control strength (`inherent × (1 − 0.75 × control/5)`).
- **Tiers** — Low &lt; 2, Moderate 2–3, High 3–4, Critical ≥ 4. Review cadence is 36 / 24 / 12 / 6 months.

Change questions in `app/questionnaire.py`, the formula in `app/scoring.py`, and document types, request rules and evidence mappings in `app/documents.py`.
