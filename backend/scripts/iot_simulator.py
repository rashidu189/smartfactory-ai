"""External IoT device / gateway simulator for SmartFactory AI.

Sends synthetic sensor telemetry to the real ingestion endpoint, exactly like a line gateway would.

  python scripts/iot_simulator.py --url https://<your-cloud-run-url> --key sfk_... [--interval 5] [--degrade L03-PRS-01]

Each tick sends one reading per machine (timestamp = now, UTC). --degrade makes one machine drift
(vibration and temperature rise) so you can watch its failure risk climb on the Machine health page
after the model scores new data. Uses only the Python standard library.
"""
import argparse
import json
import random
import time
import urllib.request
from datetime import datetime, timezone

MACHINES = ["L01-CNV-01", "L01-FIL-01", "L02-PRS-01", "L02-PKG-01", "L03-PRS-01", "L03-CNC-01",
            "L03-CNV-01", "L04-MLD-01", "L04-PRS-01", "L05-INJ-01", "L05-CNV-01", "L05-PKG-01"]


def reading(machine: str, drift: float) -> dict:
    return {"machine_id": machine, "ts": datetime.now(timezone.utc).isoformat(),
            "temperature_c": round(62 + random.gauss(0, 1.2) + 8 * drift, 2),
            "vibration_mm_s": round(2.2 + random.gauss(0, 0.22) + 3.5 * drift, 3),
            "current_a": round(15 + random.gauss(0, 0.5), 2),
            "pressure_bar": round(6 + random.gauss(0, 0.12), 3),
            "rpm": round(1480 + random.gauss(0, 12), 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Base URL of the app, e.g. https://smartfactory-ai-xxxx.a.run.app")
    ap.add_argument("--key", required=True, help="Integration API key with the 'iot' scope")
    ap.add_argument("--interval", type=float, default=5.0, help="Seconds between batches")
    ap.add_argument("--ticks", type=int, default=0, help="Stop after N batches (0 = run until Ctrl+C)")
    ap.add_argument("--degrade", default="", help="Machine code that slowly degrades")
    a = ap.parse_args()
    endpoint = a.url.rstrip("/") + "/api/integrations/iot/telemetry"
    n = 0
    while True:
        n += 1
        drift = min(1.0, n / 60)
        batch = [reading(m, drift if m == a.degrade else 0.0) for m in MACHINES]
        req = urllib.request.Request(endpoint, data=json.dumps(batch).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "X-API-Key": a.key})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print(f"[{n}] {r.status} {r.read().decode()}")
        except urllib.error.HTTPError as e:
            print(f"[{n}] HTTP {e.code}: {e.read().decode()[:200]}")
        except urllib.error.URLError as e:
            print(f"[{n}] connection error: {e.reason}")
        if a.ticks and n >= a.ticks:
            break
        time.sleep(a.interval)


if __name__ == "__main__":
    main()
