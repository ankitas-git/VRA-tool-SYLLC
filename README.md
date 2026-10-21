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

SQLite data lives in `data/vra.db`.

## Scoring

- **Inherent** — weighted answers on data sensitivity, volume, system access, criticality, subprocessors.
- **Control** — assurance, encryption, identity, incident response, privacy terms, BCP.
- **Residual** — inherent reduced by control strength (`inherent × (1 − 0.75 × control/5)`).
- **Tiers** — Low &lt; 2, Moderate 2–3, High 3–4, Critical ≥ 4. Review cadence is 36 / 24 / 12 / 6 months.

Change questions in `app/questionnaire.py` and the formula in `app/scoring.py`.
