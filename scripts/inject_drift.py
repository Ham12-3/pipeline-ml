"""Traffic generator.

--mode normal : send fresh in-distribution rows (drift should stay STABLE).
--mode drift  : shift one feature so the drift job's PSI crosses 0.2.

Run (server must be up) from repo root:
  python scripts/inject_drift.py --mode normal --n 400
  python scripts/inject_drift.py --mode drift  --n 400
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # repo root on path
from common import apply_drift, production_sample  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--mode", choices=["normal", "drift"], default="normal")
    ap.add_argument("--feature", type=int, default=0)
    ap.add_argument("--factor", type=float, default=1.8)
    ap.add_argument("--shift", type=float, default=2.0)
    ap.add_argument("--seed", type=int, default=999)
    args = ap.parse_args()

    X, _ = production_sample(args.n, seed=args.seed)
    if args.mode == "drift":
        X = apply_drift(X, args.feature, args.factor, args.shift)

    ok = err = 0
    for i, row in enumerate(X, 1):
        try:
            r = requests.post(f"{args.url}/predict",
                              json={"features": row.tolist()}, timeout=5)
            ok += r.status_code == 200
            err += r.status_code != 200
        except requests.RequestException:
            err += 1
        if i % 100 == 0:
            print(f"  sent {i}/{len(X)}  ok={ok} err={err}")

    print(f"Done ({args.mode}): ok={ok} err={err}")


if __name__ == "__main__":
    main()
