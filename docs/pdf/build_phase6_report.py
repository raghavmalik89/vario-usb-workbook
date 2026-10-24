"""Build the Bench 6 (Phase 6) ESP-IDF filter benchmark PDF report.

Reuses docs/pdf/build_lib.py scaffolding. Content mirrors
filter_benchmark/reports/phase6_espidf_benchmark.md; figures are read from
filter_benchmark/bench6/figs/.

Repro: python docs/pdf/build_phase6_report.py
"""
from pathlib import Path

from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                PageBreak, KeepTogether)

import build_lib as lib

ROOT = Path(__file__).resolve().parents[2]
FIGS = ROOT / "filter_benchmark" / "bench6" / "figs"
OUT = ROOT / "filter_benchmark" / "reports" / "phase6_espidf_benchmark.pdf"

st = lib.styles()
FIGN = [0]
TABN = [0]


def fig(name, width_cm, caption):
    FIGN[0] += 1
    path = FIGS / name
    from PIL import Image as PILImage
    with PILImage.open(path) as im:
        w_px, h_px = im.size
    from reportlab.platypus import Image
    img = Image(str(path), width=width_cm * cm,
                height=width_cm * cm * h_px / w_px)
    return [img, lib.P(f"<b>Figure {FIGN[0]}.</b> {caption}", st["caption"])]


def tab(header, rows, widths, caption, center=None):
    TABN[0] += 1
    t = lib.three_line_table(header, rows, widths, center_cols=center)
    return KeepTogether([lib.P(f"<b>Table {TABN[0]}.</b> {caption}",
                               st["caption"]), t, Spacer(1, 8)])


def h1(x):
    return lib.P(x, st["h1"])


def h2(x):
    return lib.P(x, st["h2"])


def body(x):
    return lib.P(x, st["body"])


story = []

# ------------------------------------------------------------------ title ---
story.append(Spacer(1, 3.2 * cm))
story.append(lib.P("Bench 6 — ESP-IDF Filter Architecture Benchmark",
                   st["title"]))
story.append(lib.P("Phase 6 comparative study over the clean ESP-IDF captures "
                   "· 37 candidates · frozen configurations · corrected "
                   "reconstruction", st["subtitle"]))
story.append(Spacer(1, 10))
story.append(lib.P(
    "Hardware: 2× MS5611 GY-63 clones (foam-covered) + MPU6050, ESP32-S3 "
    "@ 240 MHz · firmware esp-idf/vario @ 8e79e68 · baro 40 Hz + 10 Hz temp, "
    "IMU 100 Hz", st["subtitle"]))
story.append(lib.P(
    "Status: complete frozen-configuration study with controls. "
    "<b>No estimator is selected or frozen.</b> "
    "This PDF is the DEF-014-corrected re-issue: the handtest reference-smoother "
    "boundary artifact is fixed and rankings are re-computed (§3.3, §6). "
    "Scripts: filter_benchmark/bench6/ (run6 → equiv6 → rate6 → tune6 → "
    "mcucpu6 → figures6); re-run on BMP581/LSM6DSV16X captures by registering "
    "the new stems in datasets.py.", st["subtitle"]))
story.append(PageBreak())

# -------------------------------------------------------------- objective ---
story.append(h1("1. Objective and datasets"))
story.append(body(
    "Re-evaluate the full filter trade space on the clean ESP-IDF recordings — "
    "29 standalone filters, stacked S1–S5, CV/Kalman references and IMU-fusion "
    "candidates — with the reconstruction defect DEF-001 corrected (fixed 101325 Pa "
    "ISA reference, firmware-exact compensation). This is a fresh comparative study, "
    "not a confirmation of previous rankings. Both barometers are evaluated "
    "independently throughout (the two clones differ; sid1 is consistently "
    "≈1.15–1.4× noisier). Corrupted captures are excluded from scoring and retained "
    "as documented fault-test data."))
story.append(tab(
    ["Capture", "Role", "Split", "Quality"],
    [["221124_idf_elevator_2x", "elevator run 1: 4 legs ±38.2 m, −1.72/+1.66 m/s", "train", "CLEAN"],
     ["221420_idf_elevator_2x", "elevator run 2 (same profile)", "validation", "CLEAN (3× 20 ms gaps)"],
     ["215709_idf_handtest3", "static + gentle slow moves; 'toss' was DEF-014 artifact", "train", "GOOD (7× 20 ms gaps)"],
     ["234521_idf_p0fix_static", "static 75.3 s", "validation", "CLEAN"],
     ["234944_idf_bbuf_check", "static 20.2 s", "validation", "CLEAN"],
     ["221109_idf_elevator_2x", "aborted capture", "excluded", "USB-stall dropouts (DEF-008)"],
     ["215027_idf_foam_static", "foam static", "excluded", "CORRUPTED: 3703 seq gaps / 6192 dup IMU ts"]],
    [4.1 * cm, 6.4 * cm, 2.0 * cm, 4.0 * cm],
    "Scoring datasets and quality verdicts (measured, not labelled).",
    center={2}))
story.append(body(
    "Controls: frozen configurations first; tuning is a separate leakage-controlled "
    "pass (train-select, validation-report); a sampling-rate control precedes all "
    "cross-chain comparisons; MCU-vs-replay equivalence precedes all replay-vs-firmware "
    "comparisons. Estimator output and virtual-audio behaviour are scored separately."))

story.append(h1("2. MCU equivalence and new firmware-chain findings"))
story.append(body(
    "<b>Formal equivalence (queued task): PASS for D01.</b> On the post-p0fix statics, "
    "with the era-correct chain (fixed 101325 Pa reference against the firmware's 10× "
    "pressure scale — DEF-011 — plus the boot d2 seed), the Python replay reproduces "
    "MCU tone velocities with steady-state bias ≤ 0.3 mm/s, p95 |error| = 1.0 mm/s and "
    "100 % audio ON/OFF transition agreement (24 and 37 transitions, both sids). C03 "
    "agrees to p95 71–105 mm/s (its gain-cache quantization). S4/S5/FUS emit no steady "
    "audio transitions on statics — a vacuous, honestly reported result."))
story.append(body(
    "<b>DEF-011 (new, major):</b> baro_proc.c::compensate_pa returns p01mbar·10, ten "
    "times the common.py scale. Under the moving-p0 firmware the ratio cancelled; the "
    "p0fix hardcoded 101325 Pa (common-line units) against the still-10× pressure, so "
    "post-fix firmware velocities are scaled by exactly 10^0.1903 = 1.5498 and absolute "
    "altitude is garbage (−23 725 m). Self-consistent within the firmware, so bench "
    "captures remain valid; equivalence replays must use the isa_fw10 chain."))
story.append(body(
    "<b>DEF-010 mechanism:</b> the boot d2 seed (prom[5]·256, 20 °C) steps the "
    "compensation at the first real T frame → startup audio flap (tones clamp at "
    "+6.67 m/s), amplified to a −1.5×10⁴ m/s transient by the DEF-011 scale; emulated "
    "by seed_d2=True, and startup (t &lt; 8 s) is always reported separately."))
story.append(body(
    "<b>Gate-decision chaos (pre-p0fix moving window only):</b> during the first 50 s "
    "of the elevator/handtest captures, S4/S5 (and mildly C03/FUS) replay tones diverge "
    "from MCU by seconds, while the plain Kalman D01 — the core of both stacks — matches "
    "to ~1 mm/s everywhere. The raw reconstruction is therefore right; the divergence "
    "lives in discontinuous gate latches amplifying sub-LSB micro-differences while the "
    "defective moving reference was active. It affects only old-firmware equivalence "
    "bookkeeping, never scoring (fixed-ISA), and vanishes with the frozen reference "
    "(frozen-era p95: D01 1.0–1.2 mm/s, S4 1.1–2.1 mm/s, S5 1.0–1.3 mm/s, all captures)."))
story.append(body(
    "<b>Asymmetric tone clamp (new observation):</b> implied v = (f−500)/450 with "
    "f ∈ [400, 3500] Hz represents v ∈ [−0.22, +6.67] m/s; the firmware suppresses "
    "tones below 400 Hz, so MCU tone streams are blind to strong sink. Replay audio "
    "metrics are the authoritative comparison for sink behaviour."))
story += fig("fig13_mcu_equivalence.png", 15.5,
             "Formal MCU equivalence (a), harness validation in the frozen-p0 era (b), "
             "and the DEF-011 pressure-scale defect (c).")

story.append(h1("3. Frozen-configuration results"))
story.append(h2("3.1 Static silence"))
story.append(tab(
    ["Candidate", "Phase 3/4 rest RMS", "Bench 6 rest RMS", "Δ"],
    [["B02_project_kalman", "0.096", "<b>0.0165</b>", "−83 %"],
     ["C02_AlphaBetaGamma", "0.021", "0.0217", "—"],
     ["C01_AlphaBeta", "0.026", "0.0282", "—"],
     ["S1_RobustAdaptiveKF", "0.044", "0.0346", "−21 %"],
     ["S5_LightGateKF", "0.045 [M]", "0.0369", "−18 %"],
     ["S4_FastSlowGated", "—", "0.0371", "—"],
     ["S2_DualTimescale", "0.084", "0.0373", "−56 %"],
     ["C03_CV_tracker", "0.048", "0.0485", "—"],
     ["D01_Kalman_CV", "0.101", "0.0567", "−44 %"],
     ["B02_Butter2", "2.55", "1.49 (rate artefact, §4)", "—"]],
    [4.6 * cm, 3.4 * cm, 3.6 * cm, 2.2 * cm],
    "Rest velocity RMS (m/s, medians). Phase 3/4 numbers were measured on the "
    "defective moving/session-mean reference — most of the apparent movement is the "
    "DEF-001 correction, not the filters.",
    center={1, 2, 3}))
story.append(body(
    "Audio false-latch on statics: 0 latches/h for the whole bank; the known "
    "chatterers remain A03_Holt (~5615/h), S3 (~4450/h), FUS_Q10 (~2273/h), E06 (111/h), "
    "D04 (55/h); unadaptive baselines B00/E01–E03 chatter at 6400–6700/h."))

story.append(h2("3.2 Elevator controlled motion (run 1, medians over sids)"))
story.append(tab(
    ["Candidate", "leg RMS", "leg bias", "rise [D]", "exit [D]", "dwell false s", "missed"],
    [["C03_CV_tracker", "0.089", "−0.006", "1.27", "6.53", "2.18", "0"],
     ["S2_DualTimescale", "0.091", "−0.005", "1.34", "4.44", "2.01", "0"],
     ["S4_FastSlowGated", "0.091", "−0.006", "1.34", "6.07", "2.15", "0"],
     ["E06_RobustAdapt", "0.092", "−0.005", "1.18", "6.80", "2.33", "0"],
     ["D01_Kalman_CV", "0.093", "−0.005", "1.26", "6.80", "2.27", "0"],
     ["S1_RobustAdaptiveKF", "0.097", "−0.005", "1.30", "5.18", "1.97", "0"],
     ["S5_LightGateKF", "0.098", "−0.005", "1.31", "6.28", "2.13", "0"],
     ["C01_AlphaBeta", "0.106", "−0.004", "1.67", "3.30", "2.21", "0"],
     ["FUS", "0.241", "−0.028", "1.77", "6.81", "4.95", "0"],
     ["B02_Butter2", "1.489", "−0.006", "n/m", "6.91", "19.9", "0"]],
    [4.3 * cm, 1.9 * cm, 1.9 * cm, 1.9 * cm, 1.9 * cm, 2.4 * cm, 1.7 * cm],
    "Sustained climb and descent track equally (|bias| ≤ 6 mm/s on ±1.7 m/s legs). "
    "The exit proxy is floored at ≈6.8 s by dwell wobble [D]. No filter missed any "
    "lift — elevator discrimination is saturated.",
    center={1, 2, 3, 4, 5, 6}))
story += fig("fig01_elevator_overview_run1.png", 16.0,
             "Run 1 overview: altitude with detected legs, bank velocity traces "
             "against the 1-s boxcar reference, and replay-audio ON episodes vs MCU "
             "V-frames.")
story += fig("fig03_zoom_panels_run1.png", 15.0,
             "Zoom panels: transition into lift, exit/floor stop, and dwell "
             "behaviour for representative candidates.")
story += fig("fig02_velocity_traces_all_run1.png", 16.2,
             "All 37 candidate velocity traces on run 1 (legs shaded; ±0.2 m/s "
             "audio thresholds dotted).")

story.append(h2("3.3 Handtest, virtual audio, and CPU"))
story.append(body(
    "Handtest (corrected reference, DEF-014): the zero-padded reference smoother had "
    "fabricated two phantom events (startup 0–3.8 s; toss 148.2–151.9 s, fake ≈4 m/s "
    "peak); the IMU refutes them (|a|−g ≤ 0.17 m/s² at 144–152 s — no toss). Event "
    "onset/toss metrics are withdrawn. The discriminative handtest metric is slow-block "
    "bias: B02 −0.014, C03 −0.030, E06 −0.032, D01 −0.037 m/s (tight); S4 −0.116, "
    "S5 −0.121, FUS −0.182; S2 +0.32 and S1 +0.63 m/s — both report climb through a "
    "slow descent (S1 audio ON 0.60–0.72 of the block — a slow-descent false-lift). "
    "Static-silence false latches (relative): S2 18/h, S1 166/h, bank ≈310–350/h, FUS "
    "629/h."))
story += fig("fig06_handtest_panel.png", 15.5,
             "Handtest3: altitude, IMU acceleration, bank velocity traces with "
             "slow-block shading (no events under corrected reference, DEF-014), and "
             "virtual-audio overlays.")
story.append(body(
    "Virtual audio, separately: dwell false-ON between legs 2.0–2.4 s/run across the "
    "viable family (FUS 4.95) — the post-p0fix residual of the DEF-001/007 mechanism "
    "(Phase-era ≈16.5 s/run on the defective reference). Replay-vs-MCU transition "
    "agreement (frozen era, ±30 ms window): D01 84 %, S4 43–75 %, S5 33–62 %, dominated "
    "by timing near the asymmetric tone clamp rather than state disagreement."))
story.append(tab(
    ["Estimator (on-target, post-p0fix)", "sid0 avg/max µs", "sid1 avg/max µs", "tick budget"],
    [["D01_Kalman_CV", "36 / 44", "27 / 37", "0.7 %"],
     ["FUS (baro side; DEF-009)", "33 / 37", "—", "0.7 %"],
     ["S5_LightGateKF", "77 / 80", "59 / 88", "1.6 %"],
     ["S4_FastSlowGated", "97 / 101", "69 / 82", "2.0 %"],
     ["C03_CV_tracker", "105 / 132", "78 / 102", "2.6 %"]],
    [6.2 * cm, 3.2 * cm, 3.2 * cm, 2.4 * cm],
    "MCU CPU from B-line telemetry during the clean captures (real pipeline, no "
    "synthetic timing). Pre-p0fix lines carry the C03 refit storm (~1329/2671 µs, "
    "DEF-002 historical evidence). Efficiency is not a differentiator.",
    center={1, 2, 3}))

story.append(h1("4. Sampling-rate control"))
story.append(body(
    "Decimating the clean streams to ≈25/20 Hz and 10 Hz: seconds-parameterized filters "
    "(D01, C03, S4, S5, FUS) are near-invariant (leg RMS 0.09→0.13–0.14 at 10 Hz, rise "
    "unchanged, exit inside the dwell-wobble floor). The fixed-coefficient B02_Butter2 "
    "does not transfer (leg RMS 1.49 m/s at 50 Hz vs 0.32 at 10 Hz) — its Phase 2–5 "
    "coefficients are wrong for the ESP-IDF rate; it is excluded from cross-chain "
    "comparisons. The ESP-IDF vs Arduino rate differences are therefore a non-issue for "
    "the Kalman/tracker/stacked families."))
story += fig("fig15_rate_control.png", 16.0,
             "Rate sensitivity: seconds-parameterized filters near-invariant; "
             "fixed-coefficient B02 does not transfer across rates.")

story.append(h1("5. Leakage-controlled tuning (NOT a freeze)"))
story.append(tab(
    ["Family", "Train pick", "Validation effect vs frozen"],
    [["D01_Kalman_CV", "q=0.3", "rest RMS 0.057→0.028, exit 6.8→3.8 s, rise 1.19→1.70 s"],
     ["S5_LightGateKF", "q=0.1", "rest RMS 0.037→0.025, exit 5.7→3.7 s, rise 1.33→1.65 s"],
     ["S4_FastSlowGated", "tau_fast=0.5", "mixed (exit better, rise/rms worse) — not recommended"],
     ["C03_CV_tracker", "frozen best", "all alternatives ≥ +18 % composite"]],
    [3.6 * cm, 2.4 * cm, 9.0 * cm],
    "Selection on train only (run1 + handtest3); every configuration reported on "
    "validation (run2 + statics). The train picks transfer — no leakage signature.")
)
story += fig("fig18_tuning_train_val.png", 16.0,
             "Tuning pass: train-side selection and train/validation rest-RMS for the "
             "frozen vs tuned configurations.")

story.append(h1("6. Rankings vs Phases 2–5 and failure modes"))
story.append(body(
    "Composite (7 metrics, percentile-normalized; slow-block |bias| replaces the "
    "phantom onset metric after DEF-014): <b>C03, C01, B02_project_kalman, E06, "
    "S2</b> top-5; S4 7th, S1 8th, D01 9th, S5 12th, FUS 21st. Per-metric leaders: rest "
    "noise B02_project_kalman / C02 / C01; response E06; exit C02/C01 (floored proxy); "
    "slow-block tracking B02/E06/C03/D01 (|bias| ≤ 0.04 m/s). "
    "<b>Interpretation flag: S2 is 5th despite its known freeze-trap defect</b> — the "
    "composite rewards its low static chatter; ranking position is not endorsement."))
story.append(body(
    "What changed and why: (1) D01's rest floor 0.101→0.057 m/s — the old number was the "
    "defective reference, not the filter. (2) S5's Phase-4 stand-out status does not "
    "survive corrected streams: the S1/S4/S5 cluster is tight (0.035–0.037) and S5's "
    "slow-block bias is mid-pack. (3) S1's defect is now quantified, not shifted: "
    "+0.63 m/s slow-descent false-lift — masked in the first analysis by the DEF-014 "
    "phantom onset metric. (4) C03 rises to the composite top — its Phase-2/3 weaknesses "
    "were firmware-era artefacts (DEF-002 CPU, DEF-001 false-lift), both fixed. "
    "(5) FUS shows no measurable benefit on vibration-free data; the fusion value "
    "proposition stays open for real-flight data. (6) B02's collapse is a rate artefact."))
story += fig("fig17_ranking_heatmap.png", 14.5,
             "Normalized metric ranks (rows sorted by composite) with raw medians.")
story += fig("fig14_failure_modes.png", 16.0,
             "Failure modes: S1 slow-descent false-lift (surfaced by the DEF-014 "
             "correction), S2 freeze-trap, startup flap (DEF-010), S3 gate chatter, "
             "slow-block behaviour.")

story.append(h1("7. Limitations and next phase"))
story.append(body(
    "No subsecond ground truth on the elevator: rise/exit are labelled proxies [D]; "
    "exit is floored at ≈6.8 s by dwell wobble. Handtest static window contains operator "
    "micro-movements; false-latch rates are relative rankings. Post-p0fix dynamic "
    "captures do not exist yet — S4/S5/FUS MCU audio equivalence on transitions is "
    "vacuous, not failed. Handtest3 has no strong events under the corrected reference "
    "(DEF-014); event-relative response latency is not measurable on the current "
    "captures. Fusion evaluation is baro-reference-bound. The two clones differ; all "
    "medians are reported over both sids."))
story.append(body(
    "<b>Next phase (BMP581 + LSM6DSV16X):</b> register the new captures in "
    "datasets.py and re-run the pipeline; the registry is the only sensor-specific "
    "file. The reference firmware for the current sensor set is archived at "
    "esp-idf/firmware_archive/vario_idf_MS5611x2_MPU6050_p0fix_r8e79e68_20261023/ "
    "(binaries + SHA-256 + README) for A/B flashing. <b>Hard gate: DEF-011 (10× "
    "pressure scale) must be fixed before any further physical validation, "
    "absolute-altitude comparison, or cross-sensor benchmark.</b> The top-5 MCU "
    "efficiency benchmark is deferred until the new sensors arrive (on-target CPU data "
    "shows processing is not the present bottleneck)."))

first, later = lib.header_footer("")
doc = SimpleDocTemplate(str(OUT), pagesize=lib.A4, topMargin=2.2 * cm,
                        bottomMargin=2.2 * cm, leftMargin=2.4 * cm,
                        rightMargin=2.4 * cm,
                        title="Bench 6 — ESP-IDF Filter Architecture Benchmark",
                        author="Raghav Malik")
doc.build(story, onFirstPage=first, onLaterPages=later)
print("wrote", OUT)
