"""Script 08 — Phase 3 audio evaluation (spec §3).

Separate configurable audio state machine (src/audio.py), IDENTICAL policy
for every candidate: lift-on +0.20, lift-off +0.05, no hold, actual replay
timestamps. Filter behaviour and audio behaviour are measured independently:
filters emit v; the machine emits latch events.

Outputs (per recording and sensor, before aggregation):
    results/08_audio_statics.csv    per stream: false triggers, per-hour
                                    rates, chatter, time latched ON
    results/08_audio_events.csv     per derived event: on-delay, beep-off
                                    delay, post-lift beeping, censoring
    results/08_audio_failures.csv   post-transient extremes (spec §5:
                                    never hidden — recorded as failures)
"""
from pathlib import Path
import csv
import json
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_common import CONFIG, ROOT, derive_events, replay, streams  # noqa: E402
import audio  # noqa: E402
from filters import FILTERS  # noqa: E402
from filters.stacked import STACKED  # noqa: E402

REGISTRY = dict(FILTERS)
REGISTRY.update(STACKED)
P3 = json.loads((ROOT / "config" / "phase3.json").read_text("utf-8"))
POLICY = P3["audio_policy"]
FAIL_V = P3["failure_threshold"]["post_transient_max_v"]
CENSOR_S = 8.0


def write_csv(rows, path):
    path = Path(path)
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in keys})


def main():
    names = list(P3["architectures"]) + P3["reference_baselines"]
    stat_rows, ev_rows, fail_rows = [], [], []

    for split in ("training", "validation"):
        for st in streams(split):
            events, _ = (derive_events(st["t"], st["alt"])
                         if st["kind"] == "motion" else (None, None))
            dur = st["t"][-1] - st["t"][0]
            for name in names:
                ov = dict(P3["architectures"].get(name, {}).get("params", {}))
                f = REGISTRY[name](**ov)
                t, v = replay.replay(f, t=st["t"], z=st["alt"])
                sm = audio.AudioStateMachine(
                    lift_on=POLICY["lift_on"], lift_off=POLICY["lift_off"],
                    hold_s=POLICY["hold_s"], min_on_s=POLICY["min_on_s"])
                states, tr = audio.apply_audio(t, v, sm)
                on_times = [tt for tt, s in tr if s == "on"]
                off_times = [tt for tt, s in tr if s == "off"]
                on_durs = [b - a for a, b in zip(on_times, off_times)]
                in_event_on = 0
                if events:
                    def in_ev(tt):
                        return any(a <= tt <= b for a, b in events)
                    in_event_on = sum(1 for tt in on_times if in_ev(tt))
                common = dict(filter=name, session=st["session"], sid=st["sid"],
                              kind=st["kind"], rate_hz=st["rate"], split=split)
                stat_rows.append(dict(common,
                    duration_s=round(dur, 2),
                    n_on=len(on_times),
                    n_on_in_events=in_event_on,
                    n_on_outside_events=len(on_times) - in_event_on,
                    on_transitions_per_hour=round(len(on_times) / dur * 3600, 1),
                    total_on_time_s=round(sum(on_durs), 2),
                    on_time_fraction=round(sum(on_durs) / dur, 4),
                    median_latch_s=(round(float(np.median(on_durs)), 3)
                                    if on_durs else 0.0)))

                if st["kind"] == "motion":
                    state_at = lambda tt: "on" if np.interp(  # noqa: E731
                        tt, t, [1.0 if s == "on" else 0.0 for s in states]
                        ) >= 0.5 else "off"
                    for (e0, e1) in events:
                        # on-delay: first ON at/after entry (proxy, derived ref)
                        future = [tt for tt in on_times if e0 - 1e-9 <= tt <= e1 + CENSOR_S]
                        was_on = state_at(e0) == "on"
                        on_delay = (round(future[0] - e0, 3) if future else np.nan)
                        # beep-off: ON at event end -> time to OFF (censored)
                        if was_on or future:
                            offs = [tt for tt in off_times if e1 - 1e-9 <= tt <= e1 + CENSOR_S]
                            beep_off = round(offs[0] - e1, 3) if offs else np.nan
                            censored = int(not offs)
                        else:
                            beep_off, censored = 0.0, 0
                        ev_rows.append(dict(common, t0=round(e0, 2),
                            t1=round(e1, 2), dur=round(e1 - e0, 2),
                            was_on_at_entry=int(was_on),
                            on_delay_s=on_delay,
                            beep_off_delay_s=beep_off,
                            beep_off_censored=censored))

                # post-transient failure check (spec §5): never hidden
                for tc in st["diag"].corrupt_t:
                    m = (t >= tc) & (t <= tc + 2.0)
                    if m.any():
                        mx = float(np.max(np.abs(v[m])))
                        if mx > FAIL_V:
                            fail_rows.append(dict(common,
                                t_transient=round(tc, 2),
                                max_abs_v_after=round(mx, 3),
                                failure="extreme output after rejected transient"))
            print(f"  {split}: {st['session']} sid{st['sid']} done", flush=True)

    write_csv(stat_rows, ROOT / "results" / "08_audio_statics.csv")
    write_csv(ev_rows, ROOT / "results" / "08_audio_events.csv")
    write_csv(fail_rows, ROOT / "results" / "08_audio_failures.csv")
    print(f"statics {len(stat_rows)} rows, events {len(ev_rows)} rows, "
          f"failures {len(fail_rows)} rows")


if __name__ == "__main__":
    main()
