"""Script 07 — Phase 3 candidate run: S1/S2/S3 + reference baselines on every
session/stream of BOTH splits. Results reported per recording AND sensor
before any aggregation (spec §4).

Configs are FROZEN in config/phase3.json before this script runs; nothing
here tunes anything. Phase 2 results are not touched.
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import ROOT, derive_events, run_filter_on_stream, streams  # noqa: E402
from filters import FILTERS  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

REGISTRY = dict(FILTERS)
REGISTRY.update(STACKED)


def main():
    cfg = json.loads((ROOT / "config" / "phase3.json").read_text("utf-8"))
    names = list(cfg["architectures"]) + cfg["reference_baselines"]
    group = {**{n: n.split("_")[0] for n in cfg["architectures"]},
             **{n: "ref" for n in cfg["reference_baselines"]}}

    rows = []
    for split in ("training", "validation"):
        for st in streams(split):
            for name in names:
                ov = dict(cfg["architectures"].get(name, {}).get("params", {}))
                r = run_filter_on_stream(name, ov, st, registry=REGISTRY)
                r["group"] = group[name]
                r["split"] = split
                rows.append(r)
            print(f"  {split}: {st['session']} sid{st['sid']} done", flush=True)

    import csv
    out = ROOT / "results" / "07_phase3_all_streams.csv"
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})
    print(f"wrote {out} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
