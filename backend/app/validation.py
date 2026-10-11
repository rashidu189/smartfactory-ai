"""File parsing and validation for uploaded production data.

All numeric checks happen here so the KPI layer can trust its input.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

REQUIRED_COLUMNS = [
    "date",
    "line",
    "target_output",
    "actual_output",
    "inspected_units",
    "defective_units",
    "downtime_minutes",
]
OPTIONAL_COLUMNS = ["shift", "product", "downtime_reason"]
NUMERIC_COLUMNS = [
    "target_output",
    "actual_output",
    "inspected_units",
    "defective_units",
    "downtime_minutes",
]

# Common header variants mapped to the canonical name.
ALIASES = {
    "production_line": "line",
    "line_id": "line",
    "target": "target_output",
    "planned_output": "target_output",
    "actual": "actual_output",
    "output": "actual_output",
    "inspected": "inspected_units",
    "defects": "defective_units",
    "defective": "defective_units",
    "downtime": "downtime_minutes",
    "downtime_min": "downtime_minutes",
}

MAX_ROWS = 50_000
MAX_BYTES = 10 * 1024 * 1024


class ValidationError(Exception):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


@dataclass
class ValidationResult:
    df: pd.DataFrame
    warnings: list[str] = field(default_factory=list)


def _normalise_header(name: str) -> str:
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(key, key)


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    if len(content) == 0:
        raise ValidationError("The file is empty.")
    if len(content) > MAX_BYTES:
        raise ValidationError("The file is larger than 10 MB. Please upload a smaller extract.")
    name = (filename or "").lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(content))
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return pd.read_excel(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 - surface parser errors to the user
        raise ValidationError(f"Could not read the file: {exc}") from exc
    raise ValidationError("Unsupported file type. Upload a .csv or .xlsx file.")


def validate(df: pd.DataFrame) -> ValidationResult:
    warnings: list[str] = []
    df = df.rename(columns={c: _normalise_header(c) for c in df.columns})
    df = df.dropna(how="all")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValidationError(
            "Missing required column(s): " + ", ".join(missing),
            [f"Required columns: {', '.join(REQUIRED_COLUMNS)}",
             f"Optional columns: {', '.join(OPTIONAL_COLUMNS)}"],
        )
    if df.empty:
        raise ValidationError("The file has headers but no data rows.")
    if len(df) > MAX_ROWS:
        raise ValidationError(f"Too many rows ({len(df)}). The prototype accepts up to {MAX_ROWS}.")

    errors: list[str] = []

    # Dates
    parsed = pd.to_datetime(df["date"], errors="coerce")
    bad_dates = df.index[parsed.isna()].tolist()
    if bad_dates:
        errors.append(f"Invalid or empty date in row(s): {_rows(bad_dates)}")
    df["date"] = parsed.dt.date

    # Line ids
    df["line"] = df["line"].astype(str).str.strip()
    blank_lines = df.index[(df["line"] == "") | (df["line"].str.lower() == "nan")].tolist()
    if blank_lines:
        errors.append(f"Empty line identifier in row(s): {_rows(blank_lines)}")

    # Numerics
    for col in NUMERIC_COLUMNS:
        num = pd.to_numeric(df[col], errors="coerce")
        bad = df.index[num.isna()].tolist()
        if bad:
            errors.append(f"'{col}' is not a number in row(s): {_rows(bad)}")
        neg = df.index[num < 0].tolist()
        if neg:
            errors.append(f"'{col}' is negative in row(s): {_rows(neg)}")
        df[col] = num

    if errors:
        raise ValidationError("The file has data problems that must be fixed.", errors)

    over = df.index[df["defective_units"] > df["inspected_units"]].tolist()
    if over:
        raise ValidationError(
            "Defective units cannot exceed inspected units.",
            [f"Row(s): {_rows(over)}"],
        )
    zero_target = df.index[df["target_output"] == 0].tolist()
    if zero_target:
        warnings.append(f"Target output is 0 in row(s) {_rows(zero_target)}; excluded from target achievement.")
    long_downtime = df.index[df["downtime_minutes"] > 24 * 60].tolist()
    if long_downtime:
        warnings.append(f"Downtime above 24 h in row(s) {_rows(long_downtime)}; please check units are minutes.")

    for col in OPTIONAL_COLUMNS:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()
        else:
            df[col] = ""

    keep = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    df = df[keep].reset_index(drop=True)
    return ValidationResult(df=df, warnings=warnings)


def _rows(idx: list[int], limit: int = 8) -> str:
    # +2: header is row 1 and pandas is 0-based, so this matches spreadsheet row numbers.
    shown = [str(i + 2) for i in idx[:limit]]
    more = f" (+{len(idx) - limit} more)" if len(idx) > limit else ""
    return ", ".join(shown) + more
