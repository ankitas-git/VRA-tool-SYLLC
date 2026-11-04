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

1. **Vendors**: register the vendor.
2. **Documents**: the vendor is asked for security documents; upload them here (several files at once).
3. **Review**: check the uploaded documents against the SYLLC security questionnaire and see which questions they answer.
4. **Assess**: answer the risk questionnaire. The document request list updates from the inherent-risk answers, and the latest review's coverage is shown.
5. **History**: past assessments, including what evidence was outstanding when each was scored.
6. **Admin**: maintain the security questionnaire (password-protected).

## Configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables the AI document review. Without it, only the offline keyword scan is available. |
| `VRA_ADMIN_PASSWORD` | Password for the Admin page. Or set `admin_password` in `.streamlit/secrets.toml`. With neither, the Admin page stays locked. |
| `VRA_REVIEW_MODEL` | Model for the AI review (default `claude-opus-5-5`). |
| `VRA_REVIEW_EFFORT` | Reasoning effort for the AI review: `low`, `medium`, `high` (default), `xhigh`, `max`. |

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export VRA_ADMIN_PASSWORD='choose-a-strong-password'
streamlit run Home.py
```

## Questionnaire review

The SYLLC security questionnaire (67 questions in 13 sections) is stored in the database. It is seeded from `app/company_questionnaire.py` on first run; after that the **Admin** page is the source of truth:

- edit question text, section, order, keywords and reviewer guidance in place; add or delete questions; deactivate questions without deleting them
- export / import the whole questionnaire as CSV, or reset to the shipped default
- every change is recorded in a change log

The **Review** page compares a vendor's documents with the active questions and marks each one **Answered**, **Partially answered**, or **Not answered**, with what the documents say, verbatim evidence excerpts and their source document, what is still missing, and a follow-up request for the vendor.

- **AI review (Claude)**: reads each document. PDFs are sent as-is (scanned PDFs work), Word/Excel/CSV/TXT as extracted text, PNG/JPG through vision. Questions go in batches of 20 with the documents cached between batches. A question that asks the vendor to attach something only counts as answered if that item is among the uploads. Uploaded documents are sent to the Anthropic API.
- **Keyword scan (offline)**: finds where each question's keywords appear. It shows where a topic is mentioned, not whether the question is answered. Use it when no API key is available.
- Legacy `.doc` / `.xls` files can't be read; ask the vendor for PDF or `.docx` / `.xlsx`.
- Results are saved per vendor, and can be downloaded as CSV along with a Markdown follow-up request listing every question that isn't fully answered.

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
