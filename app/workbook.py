"""Read and write questionnaires in the layout of SYLLC's scoring workbook.

Workbook layout ("Questionnaire" sheet, header in row 1):
    A Control Area | B NIST Function | C Question | D Response |
    E Weight (standard is 30%) | F Actual Score | G Possible Score
with F = IF(D="Satisfactory", 1*E, 0), G = E, and a "Results" sheet that
divides SUMIFs of F by SUMIFs of G per NIST function and control area.
"""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional

from app.company_questionnaire import NIST_FUNCTIONS
from app.questionnaire_scoring import RESPONSES, SATISFACTORY

HEADERS = [
    "Control Area",
    "NIST Function",
    "Question",
    "Response",
    "Weight (standard is 30%)",
    "Actual Score",
    "Possible Score",
    "Document review",
    "Notes",
]


class WorkbookError(ValueError):
    pass


def _find_header(ws) -> tuple:
    """Locate the header row and the columns we need (case-insensitive)."""
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 20)):
        names = {str(c.value).strip().lower(): c.column for c in row if c.value not in (None, "")}
        q_col = names.get("question")
        if not q_col:
            continue
        cols = {"text": q_col}
        for key, label in (("section", "control area"), ("nist_function", "nist function"), ("response", "response")):
            if label in names:
                cols[key] = names[label]
        weight = next((c for n, c in names.items() if n.startswith("weight")), None)
        if weight:
            cols["weight"] = weight
        return row[0].row, cols
    raise WorkbookError("No header row with a 'Question' column was found.")


def read_questionnaire(data: bytes) -> List[Dict[str, Any]]:
    """Questions from a workbook in the scoring-workbook layout.

    Uses the "Questionnaire" sheet if present, otherwise the first sheet with
    a 'Question' header. Rows without question text are skipped. A blank weight
    is 0 (not scored), as in the workbook. Responses are returned when present.
    """
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:
        raise WorkbookError(f"Could not open the workbook: {exc}") from exc
    sheets = [wb["Questionnaire"]] if "Questionnaire" in wb.sheetnames else wb.worksheets
    last_err: Optional[Exception] = None
    for ws in sheets:
        try:
            header_row, cols = _find_header(ws)
        except WorkbookError as exc:
            last_err = exc
            continue
        if "section" not in cols:
            raise WorkbookError("The 'Control Area' column is missing.")
        rows = []
        for r in ws.iter_rows(min_row=header_row + 1):
            get = lambda key: r[cols[key] - 1].value if key in cols else None  # noqa: E731
            text = get("text")
            if text is None or not str(text).strip():
                continue
            weight = get("weight")
            nist = str(get("nist_function") or "").strip()
            if nist and nist.lower() not in {f.lower() for f in NIST_FUNCTIONS}:
                raise WorkbookError(f"Row {r[0].row}: unknown NIST function '{nist}'.")
            response = str(get("response") or "").strip()
            rows.append(
                {
                    "section": str(get("section") or "").strip() or "General",
                    "nist_function": nist,
                    "text": str(text).strip(),
                    "weight": weight if weight not in (None, "") else 0,
                    "response": response if response in RESPONSES else "",
                }
            )
        if not rows:
            raise WorkbookError("The workbook has no questions.")
        return rows
    raise last_err or WorkbookError("The workbook has no sheets.")


def write_scored_workbook(title: str, items: List[Dict[str, Any]]) -> bytes:
    """Build a workbook like SYLLC's, with live formulas, from scored items.

    Each item needs: control_area, nist_function, question, response, weight;
    optional review_status and note.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    results = wb.active
    results.title = "Results"
    q = wb.create_sheet("Questionnaire")

    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="D9E1F2")
    q.append(HEADERS)
    for c in q[1]:
        c.font = bold
        c.fill = head_fill
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, it in enumerate(items, start=2):
        q.append(
            [
                it["control_area"],
                it["nist_function"] or None,
                it["question"],
                it["response"],
                it["weight"],
                f'=IF(D{i}="{SATISFACTORY}",1*E{i},0)',
                f"=E{i}",
                it.get("review_status") or None,
                it.get("note") or None,
            ]
        )
    last = len(items) + 1
    total = last + 1
    q.cell(total, 5, "Total").font = bold
    q.cell(total, 6, f"=SUM(F2:F{last})").font = bold
    q.cell(total, 7, f"=SUM(G2:G{last})").font = bold
    dv = DataValidation(type="list", formula1=f'"{",".join(RESPONSES)}"', allow_blank=True)
    q.add_data_validation(dv)
    dv.add(f"D2:D{max(last, 2)}")
    for col, width in zip("ABCDEFGHI", (30, 14, 80, 16, 12, 12, 12, 20, 60)):
        q.column_dimensions[col].width = width
    for row in q.iter_rows(min_row=2, max_row=last):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    q.freeze_panes = "A2"

    # Results sheet, mirroring the workbook's layout.
    results.merge_cells("A1:F1")
    results.merge_cells("A2:F2")
    results.merge_cells("A3:F3")
    results["A1"] = title
    results["A1"].font = Font(bold=True, size=14)
    results["A2"] = "Overall Score"
    results["A2"].font = bold
    results["A3"] = f"=IFERROR(Questionnaire!F{total}/Questionnaire!G{total},0)"
    results["A3"].number_format = "0.0%"
    results["A3"].font = Font(bold=True, size=16)
    results.merge_cells("B5:C5")
    results.merge_cells("E5:F5")
    results["B5"] = "Score By NIST Function"
    results["E5"] = "Score By Control Area"
    results["B5"].font = results["E5"].font = bold

    def ratio(col: str, ref: str) -> str:
        return (
            f"=IFERROR(SUMIF(Questionnaire!{col}:{col},{ref},Questionnaire!F:F)"
            f"/SUMIF(Questionnaire!{col}:{col},{ref},Questionnaire!G:G),\"n/a\")"
        )

    for r, fn in enumerate(NIST_FUNCTIONS, start=6):
        results.cell(r, 2, fn)
        c = results.cell(r, 3, ratio("B", f"Results!B{r}"))
        c.number_format = "0.0%"
    areas = list(dict.fromkeys(it["control_area"] for it in items))
    for r, area in enumerate(areas, start=6):
        results.cell(r, 5, area)
        c = results.cell(r, 6, ratio("A", f"Results!E{r}"))
        c.number_format = "0.0%"
    for col, width in zip("ABCDEF", (4, 18, 12, 4, 42, 12)):
        results.column_dimensions[col].width = width

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
