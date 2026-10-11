"""Generate SYNTHETIC demo production data. Not real factory results.

Period 1 (sample_production.csv, 2026-09-28 → 2026-10-11):
  * Line 03 degrades in the second week (press failure: downtime, low output, more defects).
  * Line 01 still meets target overall, but bearing-overheating stops build up in the last days
    (early-warning / predictive-maintenance signal).
  * Line 04 night shift (B) has a higher defect rate than day shift (shift pattern).
  * Line 05 has a moderately high defect rate.
Period 2 (sample_production_after.csv, 2026-10-12 → 2026-10-25): after corrective actions —
  Line 03 press repaired, Line 01 bearing replaced, Line 04 night-shift retraining; Line 05 unchanged.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "data"
LINES = {
    "Line 01": ("Bottle Cap A", 1200),
    "Line 02": ("Bottle Cap B", 1100),
    "Line 03": ("Pump Housing", 900),
    "Line 04": ("Valve Seal", 1000),
    "Line 05": ("Spray Nozzle", 950),
}
REASONS = ["Changeover", "Material shortage", "Minor stops", "Planned maintenance"]
HEADER = ["date", "line", "shift", "product", "target_output", "actual_output", "inspected_units",
          "defective_units", "downtime_minutes", "downtime_reason"]


def make(start: date, days: int, period: int, seed: int) -> list[list]:
    random.seed(seed)
    rows = []
    for d in range(days):
        day = start + timedelta(days=d)
        for line, (product, target) in LINES.items():
            for shift in ("A", "B"):
                downtime = random.choice([10, 15, 20, 25, 30, 35])
                reason = random.choice(REASONS)
                defect_p = random.uniform(0.010, 0.022)
                loss = random.uniform(0.02, 0.08)
                if period == 1:
                    if line == "Line 03" and d >= 7:
                        downtime = random.choice([70, 85, 95, 110, 130])
                        reason = "Mechanical failure - press"
                        defect_p = random.uniform(0.045, 0.065)
                        loss = random.uniform(0.26, 0.38)
                    if line == "Line 01" and d >= 9:
                        downtime = 20 + (d - 8) * 14 + random.choice([0, 5, 10])
                        reason = "Bearing overheating" if shift == "A" or d >= 11 else reason
                    if line == "Line 04" and shift == "B":
                        defect_p = random.uniform(0.032, 0.045)
                else:
                    if line == "Line 03" and d < 2:   # ramp-up after the press repair
                        loss = random.uniform(0.10, 0.15)
                    if line == "Line 04" and shift == "B":
                        defect_p = random.uniform(0.018, 0.026)
                if line == "Line 05":
                    defect_p = random.uniform(0.030, 0.042)
                actual = int(target * (1 - loss) * (1 - downtime / 480 * 0.4))
                defective = int(round(actual * defect_p))
                rows.append([day.isoformat(), line, shift, product, target, actual, actual,
                             defective, downtime, reason])
    return rows


def write(name: str, rows: list[list]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / name).open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT_DIR / name}")


if __name__ == "__main__":
    write("sample_production.csv", make(date(2026, 9, 28), 14, 1, 2026))
    write("sample_production_after.csv", make(date(2026, 10, 12), 14, 2, 2027))
