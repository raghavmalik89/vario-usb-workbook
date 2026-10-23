"""Generate the comprehensive engineering report PDF (Phases 1-5 + t008).

Output: docs/Vario_USB_Engineering_Report_Phases_1-5.pdf
Source of every number: filter_benchmark/results/*.csv and the phase
reports; figures are the committed PNGs in filter_benchmark/results/.

Repro:  python docs/pdf/build_engineering_report.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_lib import (P, RESULTS, formula, header_footer, spacer, styles,
                       three_line_table, figure)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer)

OUT = Path(__file__).resolve().parents[1] / "Vario_USB_Engineering_Report_Phases_1-5.pdf"
S = styles()
fig_no = [0]


def fig(name, width, caption):
    fig_no[0] += 1
    return figure(name, width, caption, fig_no[0], S)


def tbl(no_caption_story, header, rows, widths, center=None, caption=None):
    if caption:
        no_caption_story.append(P(f"<b>Table {tbl.n}.</b> {caption}",
                                  S["caption"]))
        tbl.n += 1
    no_caption_story.append(three_line_table(header, rows, widths,
                                             center_cols=center))
    no_caption_story.append(spacer(10))


tbl.n = 1
story = []

# ---------------------------------------------------------------- cover
story.append(Spacer(1, 4.5 * cm))
story.append(P("Vario USB Bench Programme", S["title"]))
story.append(P("Comprehensive Engineering Report — Phases 1–5 "
               "and the t008 Quiet-House Static Validation", S["subtitle"]))
story.append(Spacer(1, 0.8 * cm))
story.append(P("Dual-barometer + IMU variometer benchmark on an ESP32-S3 rig: "
               "hardware, datasets, causal replay methodology, 29-filter "
               "comparison, audio behaviour, fault analysis, real-IMU fusion, "
               "and cross-generation static noise characterization.",
               S["subtitle"]))
story.append(Spacer(1, 1.6 * cm))
for line in ("Author: R. Malik (hardware, captures) with Kimi Work (analysis)",
             "Repository: github.com/raghavmalik89/vario-usb-workbook",
             "Date: 2026-10-23 · Commit series b3030bb–bc2f3f2",
             "Evidence labels: [M] measured · [S] simulated · [D] derived proxy "
             "· [H] hypothesis · [U] unverified"):
    story.append(P(line, S["subtitle"]))
story.append(PageBreak())

# ---------------------------------------------------------------- exec
story.append(P("Executive summary", S["h1"]))
story.append(P(
    "This report consolidates a five-phase bench programme that took a "
    "variometer sensor rig from first wiring to a validated real-IMU fusion "
    "pipeline with a fully reproducible filter benchmark. Principal measured "
    "results:", S["body"]))
for b in (
    "The two GY-63 MS5611 clones share a per-sample pressure noise floor of "
    "2.6–2.9 Pa (≈0.21–0.24 m altitude) at OSR2048/90 Hz, ~2–3× the "
    "datasheet typical; a quiet-house static (t008) proves this floor is "
    "sensor-intrinsic, while the office capture (t007) shows 7× more slow "
    "drift (9.2 m vs 1.3 m range) caused by room-pressure draft [M].",
    "A baro-only constant-velocity Kalman filter at an exploratory q=10 with "
    "measured r reaches a rest velocity noise floor of 0.10–0.11 m/s RMS on "
    "quiet statics across three firmware generations [M].",
    "Of 29 standalone filters benchmarked causally, robust/adaptive Kalman "
    "variants (S1/S5) dominate the rest-noise/transient-rejection trade; "
    "S5 matches S1 at ~1/3 CPU [M]. The fastest exit-from-lift is S4 "
    "(median release proxy 1.43 s) [D].",
    "The S2 dual-timescale filter froze permanently after landing "
    "transients — root-caused to a plausibility pre-clean that replaced "
    "deviating samples with its own prediction; the saturation fix "
    "(never replace, always move toward the sample) eliminates the trap [M].",
    "Real-IMU fusion (Phase 5): with an exact attitude warm-start and "
    "loss-of-track reinitialization, the fused estimator equals baro-only at "
    "rest and on elevator motion, and degrades gracefully on drop/toss — "
    "the limiter is 6-DOF attitude quality under tumble (6.5–10.3 m/s² "
    "gravity residual), not the Kalman filter [M].",
    "A portable C99 core reproduces the Python reference estimator within "
    "2.0e-08 m/s (double build) and cross-compiles for ESP32-S3 [M/S].",
    "No final estimator is selected or frozen in this report, per programme "
    "instruction; q=10 is an exploratory operating point only."):
    story.append(P("• " + b, S["body"]))
story.append(PageBreak())

# ---------------------------------------------------------------- 1 system
story.append(P("1. System overview", S["h1"]))
story.append(P("1.1 Hardware as-built", S["h2"]))
story.append(P(
    "The bench rig is an ESP32-S3 with two GY-63 modules (MS5611 barometric "
    "clones) on separate I²C buses and one GY-521 (MPU6050 IMU). Clone #1 has "
    "CSB pulled low and answers at 0x76 on bus A (GPIO4/5) together with the "
    "MPU6050 at 0x69 (AD0 tied high, WHO_AM_I=0x68, genuine die). Clone #2 — "
    "the unit under test — answers at 0x77 on bus B (GPIO6/7). A third "
    "barometer position (bit-banged bus C, GPIO15/16) exists on the schematic "
    "but is not populated. PROM[0] reads 0x0878 (bus A) and 0x0884 (bus B). "
    "The rig is mounted X-up: at rest the dominant specific-force component is "
    "ax ≈ +1 g, so no analysis may assume az is the gravity axis [M].",
    S["body"]))
tbl(story,
    ["Module", "Bus", "Address", "Role / notes"],
    [["GY-63 #1 (MS5611 clone)", "A (GPIO4/5)", "0x76", "CSB pulled low; sid 0"],
     ["GY-521 (MPU6050)", "A (GPIO4/5)", "0x69", "genuine; ±8 g / ±500 dps; DLPF 44 Hz"],
     ["GY-63 #2 (MS5611 clone)", "B (GPIO6/7)", "0x77", "unit under test; sid 1"],
     ["GY-63 #3 (optional)", "C (GPIO15/16)", "—", "not populated"]],
    [4.6 * cm, 2.6 * cm, 2.0 * cm, 6.8 * cm],
    caption="Bench rig hardware as-built [M].")
story.append(P("1.2 Firmware generations", S["h2"]))
tbl(story,
    ["Generation", "Version", "Stream", "Role"],
    [["t001", "0.1.3", "baro only", "bring-up, noise floor (T-001)"],
     ["t002", "0.2.2", "baro + 200 Hz IMU", "IMU path validation (T-002/T-004)"],
     ["t003", "0.3.1", "dual baro lockstep 45 Hz", "dual-sensor study (T-003)"],
     ["t005", "0.5.3", "dual baro 50 Hz", "OSR4096 motion set (T-005)"],
     ["t006", "0.6.0", "dual baro measured 90 Hz", "OSR2048 high-rate set"],
     ["t007/t008", "0.7.0", "dual baro 90 Hz + IMU 200 Hz",
      "real-IMU fusion dataset (OSR2048)"]],
    [2.6 * cm, 1.8 * cm, 5.4 * cm, 6.2 * cm],
    caption="Firmware generations. All speak serial protocol v1 over USB-CDC "
            "at 921600 baud: boot legend, per-device health check, PROM dump, "
            "raw frames only — no on-MCU filtering.")
story.append(P(
    "Every frame carries a sequence number and a physical MCU timestamp "
    "(esp_timer_get_time); the offline pipeline derives all sampling "
    "intervals from these timestamps, never from USB receipt time. A JSON "
    "sidecar per capture carries firmware config and PROM words; offline "
    "temperature/pressure compensation is impossible without it.", S["body"]))
story.append(P("1.3 Capture and analysis pipeline", S["h2"]))
story.append(P(
    "Captures are taken with <font face='Courier'>tools/capture.py</font> "
    "(COM5 @ 921600). The benchmark replay engine feeds identical "
    "chronological (sample, physical-timestamp) pairs to every filter; "
    "corrupt frames are band-filtered and counted, sequence gaps are "
    "preserved in diagnostics, and the filters experience true variable dt. "
    "The two barometers are replayed as independent streams unless an "
    "explicitly defined fusion algorithm is being evaluated. Operational "
    "lessons (serial-monitor port locks, CDC non-reset behaviour, meta-on-"
    "attach timing, label reuse) are recorded in docs/HANDOVER.md.", S["body"]))

# ---------------------------------------------------------------- 2 data
story.append(P("2. Datasets", S["h1"]))
story.append(P(
    "22 recordings are committed under analysis/data/ (CSV + JSON sidecar), "
    "spanning statics, elevator rides, step drops, toss-and-catch and "
    "controlled hand motion across firmware generations t001–t008. Session "
    "types come from operator labels — naming, not independent evidence. "
    "The machine-generated quality verdict for every run is in "
    "filter_benchmark/reports/data_quality_report.md; the summary is "
    "reproducible via scripts/02_validate_data.py.", S["body"]))
tbl(story,
    ["Dataset", "Statics", "Elevator", "Drop", "Toss", "Controlled", "IMU"],
    [["t001–t002", "3", "—", "—", "—", "—", "t002 only"],
     ["t003 dual", "1", "—", "—", "—", "—", "—"],
     ["t004", "—", "2", "1", "—", "—", "yes"],
     ["t005 OSR4096", "1", "1", "1", "1", "1", "—"],
     ["t006 OSR2048", "1", "—", "1", "—", "1", "—"],
     ["t007 OSR2048+IMU", "1", "1", "2", "1", "1", "yes"],
     ["t008 quiet static", "1", "—", "—", "—", "—", "yes"]],
    [3.4 * cm, 1.9 * cm, 1.9 * cm, 1.5 * cm, 1.5 * cm, 2.2 * cm, 1.8 * cm],
    center={1, 2, 3, 4, 5, 6},
    caption="Recording inventory by session class (counts of captures).")
story.append(P(
    "Data-quality highlights [M]: the t008 quiet static is clean (one 1-frame "
    "sequence gap). Motion sessions from t007 lose 3.5–9 % of sample time to "
    "3–12 simultaneous freezes of both barometers and the IMU (0.32–0.66 s "
    "each) — the coincidence across all three streams pins the cause to "
    "whole-loop USB/serial backpressure, not I2C. These freezes double as "
    "accidental blackout-coast test intervals. Drop/toss impacts saturate the "
    "±8 g accelerometer for &lt;1 % of IMU samples (noted, expected at "
    "impacts). One t004 elevator capture lacks its sidecar and is excluded "
    "from all compensated analysis.", S["body"]))
story.append(P("2.1 Reference channels", S["h2"]))
story.append(P(
    "No capture contains GPS, a reference-vario output stream, or "
    "ground-truth event tags. All event timings reported below are "
    "descriptive proxies against derived references (1-s Gaussian-smoothed "
    "barometric derivative with strong-motion gating), never physical "
    "latency. The spec-mandated B03 reference-vario baseline is therefore "
    "Unavailable in every recording and is reported as such [U].", S["body"]))

# ---------------------------------------------------------------- 3 method
story.append(P("3. Benchmark methodology", S["h1"]))
story.append(P("3.1 Causal replay and evidence labels", S["h2"]))
story.append(P(
    "Filters are evaluated by causal replay on physical timestamps with "
    "whole-session tuning/validation separation (9 training + 5 validation "
    "sessions in Phases 2–4; multiple sids per session are not independent "
    "samples). Every number carries an evidence label: [M] measured on bench "
    "captures, [S] simulated on seeded synthetic streams, [D] derived proxy "
    "against a derived reference, [H] hypothesis/design default, [U] "
    "unverified. Per-filter tuning was fit on training sessions only and "
    "reported against held-out validation sessions; every tested "
    "configuration is preserved in results/ (nothing discarded).", S["body"]))
story.append(P("3.2 Estimator model", S["h2"]))
story.append(P(
    "The core estimator is a timestamp-driven asynchronous Kalman filter "
    "over state x = [h, v] (constant-velocity model) with IMU propagation "
    "extending the state usage in fusion mode:", S["body"]))
story.append(formula("cv",
    r"F=[[1,\ dt],\ [0,\ 1]],\ \ "
    r"Q=q\,[[dt^{3}/3,\ dt^{2}/2],\ [dt^{2}/2,\ dt]],\ \ "
    r"H=[[1,\ 0]]"))
story.append(P(
    "with process spectral density q and measurement variance r. In fusion "
    "mode (Phase 5) each timestamped 3-axis accel sample propagates the state "
    "through gravity-compensated Earth-vertical acceleration and each baro "
    "sample corrects it; accel bias is estimated only under a rest gate "
    "(|v| &lt; 0.5 m/s and |a_comp| &lt; 1 m/s², clamped to ±2 m/s²). "
    "Innovation gating (3.5σ) plus a loss-of-track reinitializer (8 "
    "consecutive &gt;5σ innovations ⇒ reacquire from the measurement) "
    "protect against transients. Altitude comes from the MS5611 second-order "
    "temperature-compensated conversion and the ISA troposphere relation "
    "h = 44330·(1−(p/p₀)^0.1903) with p₀ from the first ~40 s of a session.",
    S["body"]))
story.append(P("3.3 Audio evaluation", S["h2"]))
story.append(P(
    "Audio behaviour is measured through a separate state machine "
    "(src/audio.py) so filter and audio defects are independently "
    "attributable. The common policy across Phases 2–4 is lift-on +0.20 m/s, "
    "lift-off +0.05 m/s; Phase 4 adds a generic fault veto (5-of-5 streak "
    "detector) and a max_on valve. False-ON rates are per-hour on statics; "
    "exit-from-lift is first-class (an ON-at-event-end with no OFF within "
    "8 s is censored and counted, never dropped); continuous beeping under "
    "sustained faults is measured as ON-fraction with and without the veto.",
    S["body"]))
story.append(PageBreak())

# ---------------------------------------------------------------- 4 phase 1-2
story.append(P("4. Phase 1–2: baselines and the 29-filter standalone benchmark", S["h1"]))
story.append(P(
    "Phase 1 delivered the dataset inventory and the machine-checked quality "
    "report. Phase 2's mandate was correctness and comparability, not "
    "selection: all baselines and all standalone filters (Groups A smoothing, "
    "B classical, C trackers, D Kalman variants, E adaptive) were run on "
    "identical streams with default and tuned configurations (unit tests "
    "11/11; 29 filters registered; 667 individual-filter rows).", S["body"]))
tbl(story,
    ["Baseline", "Static rest RMS [m/s]", "Motion RMS [m/s]",
     "Onset proxy [s]", "Release proxy [s]", "False latches"],
    [["B00 raw diff-quota", "9.140", "11.630", "−2.905", "7.940", "1"],
     ["B01 regression slope", "0.159", "1.277", "−1.965", "4.765", "7"],
     ["B02 project Kalman [M]", "0.096", "0.563", "−0.100", "4.885", "1"],
     ["B03 reference vario", "n/a — Unavailable in all recordings [U]", "", "", "", ""]],
    [3.6 * cm, 3.0 * cm, 2.7 * cm, 2.6 * cm, 2.7 * cm, 2.0 * cm],
    center={1, 2, 3, 4, 5},
    caption="Baselines B00–B03 at defaults, session medians [M]; proxies [D].")
story.append(P(
    "Representative standalone results at default configurations (session "
    "medians; full 26-row table in reports/phase2_demonstration.md): "
    "alpha-beta trackers C01/C02 are quietest at rest (0.026/0.021 m/s) but "
    "blind at onset (proxy 1.2–1.4 s); the CV Kalman D01 reaches 0.101 m/s "
    "rest with onset proxy −0.31 s; robust/adaptive variants D04/D06 and "
    "E06 improve motion handling (0.58–0.92 m/s motion RMS); windowed "
    "smoothers (SMA/Median/Hampel) trade 1.3–2.4 m/s motion RMS for "
    "0.25–0.49 m/s rest noise; fixed high-order low-passes (Butterworth/Bessel) "
    "ring badly at rest (2.5–3.4 m/s) — the classic pressure-smoothing trap "
    "the background research warns about [M][D].", S["body"]))
story.append(P("4.1 Per-filter tuning and held-out validation", S["h2"]))
story.append(P(
    "Each filter was tuned on training sessions (rank-based multi-objective "
    "score: static RMS, motion RMS, onset proxy, false latches) and "
    "validated held-out. Tuned configurations improved motion RMS for most "
    "filters (e.g. A02 EMA 0.85→0.58 m/s, C02 ABG 0.63→0.22 m/s) while "
    "validation onsets stayed consistent — no filter was tuned to the "
    "validation split [M].", S["body"]))
story.append(P("4.2 Rate comparison and its correction", S["h2"]))
story.append(P(
    "A Phase 2 table appeared to show 1.4–1.6× higher rest noise at 90 Hz "
    "than 45 Hz for windowed smoothers. Phase 3 audited this: trailing "
    "windows are parameterised in seconds, for which rate cancels exactly "
    "(v(t) = (z(t)−z(t−W))/W); synthetic controls show no rate effect, and "
    "decimating the t006 static 90→45 Hz changes SMA rest RMS by only 1.6 %. "
    "The apparent effect was firmware noise colour (OSR4096 vs OSR2048; "
    "increment lag-1 correlation −0.28 vs −0.47) — a session-pair "
    "confounder, not a rate effect [M]. The Phase 2 numbers stand; the "
    "interpretation is corrected here.", S["body"]))

# ---------------------------------------------------------------- 5 phase 3
story.append(P("5. Phase 3: stacked candidates and audio behaviour", S["h1"]))
story.append(P(
    "Three stacked architectures were frozen before any held-out run "
    "(configs in config/phase3.json with per-parameter provenance): "
    "S1_RobustAdaptiveKF (Hampel pre-clean + adaptive-gain CV Kalman), "
    "S2_DualTimescale (fast EMA + slow gated KF with persistence exit), "
    "S3_AccelerationAwareKF (3-state [h,v,a] KF with fault detection). "
    "Reference baselines B02/C03/D01 ran with frozen configs for "
    "comparability.", S["body"]))
tbl(story,
    ["Filter", "Rest RMS [m/s]", "Onset proxy [s]", "Beep-off proxy [s]",
     "False ON/hr", "ON outside events"],
    [["S1_RobustAdaptiveKF", "0.045", "0.14", "2.06", "60", "1.0"],
     ["S2_DualTimescale", "0.081", "−0.27", "0.00*", "120", "2.0"],
     ["S3_AccelerationAwareKF", "0.334", "−3.90", "0.27", "13260", "221"],
     ["B02_project_kalman", "0.092", "−0.02", "1.76", "480", "8.0"],
     ["C03_CV_tracker", "0.048", "1.29", "0.96", "0", "0.0"],
     ["D01_Kalman_CV", "0.096", "−2.35", "0.92", "120", "2.0"]],
    [4.1 * cm, 2.4 * cm, 2.4 * cm, 2.5 * cm, 1.9 * cm, 2.4 * cm],
    center={1, 2, 3, 4, 5},
    caption="Phase 3 estimator + audio results [M] (train statics; val "
            "proxies [D]). *S2's 0.00 s applies only to the 42 % of events "
            "where it exited at all — on the other 57 % its persistence latch "
            "held ON past the window (the freeze trap, §6.1).")
story.append(P(
    "Seeded synthetic fault injection (spike / burst / gap / reversal; "
    "recorded-failure threshold 1.0 m/s) showed S1/S2 rejecting all four "
    "transients while C03 and D01 recorded failures on the burst scenario "
    "(2.99/3.00 m/s) and baro-only S3 failed all four [S]. CPU cost (host "
    "Python, relative is the portable quantity): S1 42.9 µs/update (2.95× "
    "D01) due to its sliding Hampel window; S2 16.6 µs (1.14×); C03 6.6 µs "
    "(0.45×) [M].", S["body"]))
story.append(P("5.1 Recorded failures (never hidden)", S["h2"]))
story.append(P(
    "S3 chatters audio at ~13 000 ON/hour on statics — its baro-only "
    "acceleration state excites the velocity output — and reaches 16.2 m/s "
    "post-transient on corrupt frames; S1 has one marginal 1.04 m/s "
    "excursion; D01/C03 record excursions on the same transients. All ten "
    "failure rows are preserved in results/08_audio_failures.csv [M].", S["body"]))
story.append(PageBreak())


# ---------------------------------------------------------------- 6 phase 4
story.append(P("6. Phase 4: corrected metrics, safety mechanisms, C core", S["h1"]))
story.append(P("6.1 The S2 freeze trap — root cause and fix-by-design [M]", S["h2"]))
story.append(P(
    "Corrected per-event accounting (873 events) exposed 31 censored "
    "beep-offs on S2 — audio that never exited after an event, 17 lift / 13 "
    "sink / 1 weak. Root cause: S2's plausibility pre-clean computed each "
    "incoming sample's innovation against the fast branch's own prediction "
    "and, beyond max_dev, replaced the sample with the prediction. Under the "
    "sustained deceleration of a landing, the real signal departs from the "
    "prediction faster than the prediction follows; once the gap exceeded "
    "max_dev, every real sample was discarded (median 2017 rejected samples "
    "on censored events), the filter consumed only its own output, and (h,v) "
    "froze at a wrong value — median tail v = 0.449 m/s with audio pinned ON "
    "to end of capture.", S["body"]))
story += fig("fig_p4_s2_freeze_event.png", 13.5,
             "The identical drop-session stream through frozen S2 (top) and "
             "the saturation-fixed S4 (bottom). S2 freezes after the landing "
             "transient and never exits; S4 recovers and exits each event "
             "normally [M].")
story.append(P(
    "Fix applied in all subsequent filters: saturate, never replace — "
    "zc = h_pred + sign(dev)·max_dev. The filter always moves toward the real "
    "signal at max_dev per sample and can never become self-referential; "
    "S4_FastSlowGated has zero censored events on identical input. S2/S3 are "
    "frozen untouched as defect references so Phase 3 stays reproducible.", S["body"]))
story.append(P("6.2 Retained candidates (Phase 4)", S["h2"]))
tbl(story,
    ["Filter", "Rest RMS [m/s]", "Missed lifts (val)", "Censored",
     "Release proxy [s]", "Onset proxy [s]", "CPU µs"],
    [["S5_LightGateKF", "0.045", "0.0%", "0", "4.23", "0.12", "18.4"],
     ["S4_FastSlowGated", "0.085", "0.0%", "0", "1.43", "0.04", "19.0"],
     ["S1_RobustAdaptiveKF", "0.045", "17.8–21.6%", "2→0†", "4.95", "0.14", "50.7"],
     ["C03_CV_tracker (ref)", "0.048", "2.2–2.7%", "0", "2.18", "1.29", "7.0"],
     ["D01_Kalman_CV (ref)", "0.096", "0.0%", "0", "2.11", "−2.35", "16.0"]],
    [4.0 * cm, 2.2 * cm, 2.4 * cm, 1.8 * cm, 2.3 * cm, 2.2 * cm, 1.6 * cm],
    center={1, 2, 3, 4, 5, 6},
    caption="Phase 4 estimator comparison, frozen configs, common audio "
            "policy [M]; proxies [D]. †S1's two policy-level censored events "
            "are removed by the tuned+safety policy. S1's missed-lift rate is "
            "a real estimator defect (its adaptive gate rejects genuine "
            "onsets), flagged as its known weakness.")
story.append(P(
    "S5 delivers S1-class robustness in constant time (no sliding window) at "
    "~1/3 the CPU; S4 is the fastest exit-from-lift with zero missed lifts. "
    "S1P (persistence added to S1) was rejected on validation evidence. "
    "Audio-policy tuning on training sessions only (576 policies; mostly "
    "lift_on 0.15 / lift_off 0.03 + min_on 0.15) halved the worst false-ON "
    "rate (120→60/hr) and transferred to validation without degradation; the "
    "safety baseline (max_on 10 s + fault veto) removes the two remaining "
    "censored events. With the veto, sustained-fault audio ON-fraction is "
    "0.000 for every candidate (without it: 0.63–0.97) [M][S].", S["body"]))
story.append(P("6.3 Synthetic fusion interface and portable C core", S["h2"]))
story.append(P(
    "The baro/IMU fusion interface (async IMU-predict / baro-correct, "
    "gravity compensation with Earth z-down convention a_z = f_z + g, "
    "rest-gated accel-bias estimation, baro-only fallback) was verified on "
    "seeded synthetic IMU only [S]: climb-rate RMS error 0.499 → 0.009 m/s "
    "with known attitude, and 0.034 vs 1.699 m/s during a 1 s baro blackout. "
    "Recorded synthetic failures: fusion is slightly worse than baro-only at "
    "rest (0.031 vs 0.012 m/s — injected IMU noise has nothing to cancel), "
    "and an 8 m baro spike produces 1.50 m/s post-spike velocity. No fusion "
    "claim was made for real IMU data until Phase 5.", S["body"]))
story.append(P(
    "The portable C99 core (portable/vario_core/, no heap, timestamp-driven, "
    "estimator and audio modules independent) reproduces the Python "
    "reference on 12/12 test vectors: double build max |Δv| = 2.0e-08 m/s "
    "(tolerance 1e-6), float build 5.1e-05 m/s (tolerance 1e-3); it builds "
    "with MSVC on host and xtensa-esp-elf-gcc for ESP32-S3 in float and "
    "double variants [M/S]. Host runner timing reads 0.000 µs on most "
    "vectors (clock() resolution); CPU numbers therefore come from the "
    "Python benchmark, and on-target timing remains future work.", S["body"]))

# ---------------------------------------------------------------- 7 phase 5
story.append(P("7. Phase 5: real-IMU fusion", S["h1"]))
story.append(P("7.1 Noise decomposition [M]", S["h2"]))
story.append(P(
    "Direct decomposition of the compensated-altitude noise on the t007 "
    "static (holding one ADC channel constant at a time) shows the pressure "
    "ADC d1 dominates: 2.56–2.89 Pa lag-1 per sample (0.21–0.24 m), while "
    "the clone's temperature channel d2 contributes only ~0.2–0.5 Pa. This "
    "refutes the earlier working hypothesis that d2 was a major noise "
    "injector (scripts/18_noise_decompose.py). Median-filtering d2 over ±2.5 s "
    "before compensation changes total noise by &lt;2 % (kept: physically "
    "right, costs nothing). The same decomposition applied to earlier phases' "
    "streams: their tuned q/r absorbed this same d1 noise.", S["body"]))
story.append(P("7.2 Clone calibration [M]", S["h2"]))
story.append(P(
    "The MPU6050 clone reads |a| = 10.055 m/s² at rest — a +2.5 % scale "
    "error (t008: +2.8 %). The scale factor is a per-device constant taken "
    "from the clean static and applied to all sessions; per-session estimates "
    "are fragile because slow controlled hand motion keeps |a| inside any "
    "plausible band (this poisoned one session's estimate to 9.567). The gyro "
    "carries a large but stable offset (≈51.7–55.8 °/s norm, mostly x), "
    "removed by capture-start rest-window subtraction.", S["body"]))
story.append(P("7.3 Attitude warm start and fault recovery [M]", S["h2"]))
story.append(P(
    "The 6-DOF Madgwick estimator (β=0.3) is healthy on real data: 0.011 m/s² "
    "rest gravity residual after convergence, verified against synthetic "
    "controls. But starting from identity quaternion needs ~5 s to acquire "
    "the rig's tilt, and the leaked ~2.2 m/s² mean vertical acceleration "
    "integrated the fused KF's velocity to 14 m/s; the innovation gate then "
    "rejected every measurement for the rest of the session while the fault "
    "flag — previously a display-only latch — left the filter coasting at a "
    "runaway state. Two fixes in src/: (1) quat_from_accel_tilt, an exact "
    "shortest-arc warm start from the first accel sample (az(0) ≈ 0.02 m/s²; "
    "roll/pitch trigonometric forms were abandoned after both the plain and "
    "conjugated variants left 0.2–0.6 m/s² residual on this X-up rig); "
    "(2) loss-of-track reinitialization (8 consecutive &gt;5σ innovations ⇒ "
    "reacquire from the measurement, counted in n_reinit).", S["body"]))
story += fig("fig_p5_real_fusion.png", 14.5,
             "Phase 5 fused (red) vs baro-only (grey) velocity on the t007 "
             "static (top) and elevator (bottom), exploratory q=10 with "
             "measured r. At rest the traces coincide; on the elevator the "
             "fused track matches baro-only with slightly lower peaks [M].")
story.append(P("7.4 Fusion verdict on real captures [M]", S["h2"]))
tbl(story,
    ["Session", "Baro-only rest v-RMS [m/s]", "Fusion rest v-RMS [m/s]",
     "Madgwick |az| [m/s²]", "Fusion gates/reinit"],
    [["t007 benchstatic", "0.35–0.76", "0.35–0.76", "0.011", "19–31 / 1–2"],
     ["t007 elevator_2x", "1.33", "1.39", "0.137", "8–12 / 0"],
     ["t007 ControledMove2", "1.14–1.19", "1.43–1.47", "3.41", "329–363 / 13–15"],
     ["t007 drop / drop2 / toss", "1.08–1.64", "1.80–3.00", "6.5–10.3",
      "308–688 / 13–42"]],
    [4.4 * cm, 3.2 * cm, 3.2 * cm, 2.6 * cm, 2.8 * cm],
    center={1, 2, 3, 4},
    caption="Real-IMU fusion vs baro-only at rest-masked segments, "
            "exploratory q=10 [M]. The pattern is monotone in attitude error: "
            "fusion is identical at rest, equal on the elevator, worse under "
            "hand motion, clearly worse under tumble.")
story.append(P(
    "The q sweep on statics is a flat plateau (drift-removed rest v-RMS "
    "0.407–0.447 m/s across q = 0.3…100, spread 10 %) — the metric has no "
    "power to discriminate q on office statics — while small q reinit-cycles "
    "on motion (q=1: 11 reinit in 34 s on drop). Exploratory operating point "
    "q = 10 is a documented judgement call, mid-range and motion-vetted; "
    "r = 0.042 m² (t007) is measured [M]. No estimator is selected or frozen.",
    S["body"]))

# ---------------------------------------------------------------- 8 t008
story.append(P("8. t008 quiet-house static validation", S["h1"]))
story.append(P(
    "t008_quiet_static (60 s, same rig and firmware 0.7.0 as t007, quiet "
    "house, one 1-frame sequence gap) isolates the environment's contribution "
    "to the earlier statics. Cross-generation comparison "
    "(scripts/21_static_compare.py):", S["body"]))
tbl(story,
    ["Capture", "OSR / rate", "Detrended noise [m]", "Drift range [m]",
     "Allan σ(1 s) [m]", "Allan σ(10 s) [m]", "KF rest v-RMS [m/s]"],
    [["t005 office", "4096 / 45 Hz", "0.43", "1.3–1.7", "0.39–0.40", "0.40", "0.12–0.13"],
     ["t006 office", "2048 / 90 Hz", "0.41", "1.2–1.3", "0.27–0.29", "0.27–0.29", "0.10–0.11"],
     ["t007 office", "2048 / 90 Hz", "0.44–0.46", "9.2–9.8", "0.41", "0.48–0.51", "0.71–0.80"],
     ["t008 QUIET", "2048 / 90 Hz", "0.40–0.42", "1.3–1.4", "0.27–0.30", "0.28–0.30", "0.10–0.11"]],
    [2.5 * cm, 2.4 * cm, 2.7 * cm, 2.4 * cm, 2.4 * cm, 2.5 * cm, 2.7 * cm],
    center={1, 2, 3, 4, 5, 6},
    caption="Cross-phase static comparison, both sids [M]. The quiet house "
            "removes 7× of slow drift and halves mid-τ Allan deviation vs the "
            "t007 office session; the per-sample noise floor is unchanged — "
            "it is sensor-intrinsic.")
story += fig("fig_static_drift.png", 14.5,
             "Altitude relative to session mean for four static captures. "
             "The t007 office trace (red) wanders −8.5 m; all others stay "
             "within ±1 m [M].")
story += fig("fig_static_allan.png", 12.5,
             "Overlapping Allan deviation of compensated altitude (sid mean; "
             "faint dots: individual sids). All captures share the short-τ "
             "white-noise floor; only the t007 office trace rises with τ — "
             "random-walk room draft [M].")
story.append(P(
    "Consequences. (1) The KF rest noise floor of 0.10–0.11 m/s is a robust "
    "cross-generation measurement of what a quiet MS5611-clone static "
    "supports — earlier office numbers conflated sensor noise with draft. "
    "(2) The t007-derived r = 0.042 m² was inflated by draft leakage into "
    "the 1-s detrend estimator; the quiet-static value is 0.026–0.033 m². "
    "(3) Fusion on t008 equals baro-only at rest (0.1085 vs 0.1086 m/s) with "
    "zero reinitializations — the Phase-5 machinery reproduces on fresh data. "
    "(4) IMU run-to-run consistency between t007 and t008 (scale +2.5/+2.8 %, "
    "gyro offset norm 51.7/55.8 °/s, Madgwick residual 0.011 m/s² both) "
    "confirms calibration stability across power cycles [M].", S["body"]))

# ---------------------------------------------------------------- 9 register
story.append(PageBreak())
story.append(P("9. Failure and correction register", S["h1"]))
tbl(story,
    ["#", "Defect / correction", "Evidence", "Status"],
    [["F1", "S2 freeze trap: plausibility pre-clean replaced deviating "
            "samples with own prediction → permanent freeze after landings "
            "(31 censored beep-offs)", "results/11_s2_censoring.csv [M]",
      "Root-caused; saturation fix in S4/S5; S2 frozen as defect ref"],
     ["F2", "Fusion divergence: identity-q0 attitude transient leaked 2.2 "
            "m/s² into fused KF → v ran to 14 m/s, gate froze filter; fault "
            "flag was display-only", "scripts/20_fusion_trace.py [M]",
      "Fixed: shortest-arc warm start + loss-of-track reinit"],
     ["F3", "45-vs-90 Hz rate interpretation in Phase 2 was a session-pair "
            "confounder (firmware noise colour), not a rate effect", "Phase 3 "
      "audit controls [M][S]", "Corrected; Phase 2 numbers unchanged"],
     ["F4", "d2 temperature-channel noise hypothesized as major altitude-noise "
            "injector", "scripts/18_noise_decompose.py [M]",
      "Refuted: d1 pressure ADC dominates (2.6–2.9 Pa vs 0.2–0.5 Pa)"],
     ["F5", "MS5611 compensation scale: a hand-derivation with /2^6 is wrong "
            "by ~500×", "analysis/common.py [M]", "Documented; common.py is "
      "the ground truth (final scale /2^15)"],
     ["F6", "Per-session g_cal estimation poisoned by slow hand motion "
            "(9.567 m/s²)", "script 17 motion rows [M]",
      "Fixed: per-device constant from clean static"],
     ["F7", "S3 audio chatter ~13k ON/hr + 16.2 m/s post-transient; S4/S5 "
            "1.3–2.0 m/s excursions on corrupt frames", "08_audio_failures.csv, "
      "11_events_corrected.csv [M]", "Recorded, unfixed by design"],
     ["F8", "S1 adaptive gate rejects genuine onsets (17.8–21.6 % missed "
            "lifts on validation)", "results/12_*.csv [M]",
      "Recorded as S1's known defect"],
     ["F9", "USB whole-loop freezes (0.32–0.66 s) in t007 motion sessions",
            "quality report + script 21 gap audit [M]",
      "Documented; MCU pacing work pending; harmless to analysis"]],
    [0.9 * cm, 7.2 * cm, 4.4 * cm, 4.4 * cm],
    caption="Defects and corrections across phases. Nothing was silently "
            "fixed or discarded; frozen defect references keep every failure "
            "reproducible.")

# ---------------------------------------------------------------- 10 limits
story.append(P("10. Limitations, uncertainty, reproducibility", S["h1"]))
for b in (
    "<b>No ground truth.</b> Onset/release/audio timings are derived proxies "
    "[D] against smoothed references; negative onset proxies mean a filter "
    "anticipated the derived reference, not physical reality. No confidence "
    "intervals are claimed; session medians are descriptive, and multiple "
    "sids per session are not independent samples.",
    "<b>Environmental confounders.</b> Office statics are draft-dominated "
    "(t007: 9 m range); only t008 is pressure-quiet. Cross-capture "
    "comparisons therefore report drift-free metrics wherever discrimination "
    "matters. Clones vary per unit: the two GY-63s differ ~1.8× in rest "
    "noise on some captures, so per-sid evaluation is mandatory and "
    "dual-barometer averaging would import the noisier sensor's errors.",
    "<b>Motion envelope.</b> Drop/toss/elevator/controlled-move approximate "
    "the flight-relevant envelope partially; no real thermal-lift capture "
    "exists yet. Impact saturation at ±8 g limits drop/toss accel fidelity.",
    "<b>Fusion limits.</b> 6-DOF attitude (no magnetometer) degrades under "
    "tumble (6.5–10.3 m/s² gravity residual) — the measured fusion ceiling. "
    "q=10 is exploratory; the static sweep cannot discriminate q. Synthetic "
    "fusion failures (rest regression, 8 m spike excursion) are recorded.",
    "<b>Reproducibility.</b> Every number traces to a row in results/; "
    "figures regenerate from the same CSVs; all capture data and firmware "
    "configs are committed; test suite 47/47 (scripts/run_tests.py). "
    "Host CPU numbers are relative-cost indicators; on-target ESP32 timing "
    "is pending. GitHub pushes from this machine are intermittently blocked "
    "by the network; commits are always local-safe first."):
    story.append(P("• " + b, S["body"]))

# ---------------------------------------------------------------- appendix
story.append(P("Appendix A — Reproduction", S["h1"]))
story.append(P(
    "Repo: github.com/raghavmalik89/vario-usb-workbook. Captures: "
    "analysis/data/*.csv + .json sidecars. Benchmark: filter_benchmark/ "
    "(scripts 01–22, results/, reports/, config/, src/, tests/, portable/). "
    "Regenerate, in order:", S["body"]))
story.append(P(
    "python scripts/run_tests.py            # 47/47 unit + regression\n"
    "python scripts/02_validate_data.py     # data quality report (22 runs)\n"
    "python -u scripts/03_run_baselines.py  # B00-B03\n"
    "python -u scripts/04_run_individual_filters.py\n"
    "python -u scripts/05_tune_parameters.py A B C D E\n"
    "python -u scripts/07_phase3_candidates.py\n"
    "python -u scripts/08_audio_evaluation.py\n"
    "python -u scripts/09_fault_and_cost.py\n"
    "python -u scripts/11_audio_events_v2.py\n"
    "python -u scripts/12_estimator_comparison.py\n"
    "python -u scripts/13_audio_policy_tuning.py\n"
    "python -u scripts/14_imu_fusion_sim.py # synthetic fusion\n"
    "python -u scripts/15_portable_core.py  # C core equivalence\n"
    "python -u scripts/17_real_imu_fusion.py# t007 real-IMU fusion\n"
    "python -u scripts/18_noise_decompose.py# d1/d2 noise split\n"
    "python -u scripts/21_static_compare.py # cross-phase statics + t008\n"
    "python -u scripts/22_t008_fusion.py    # t008 fusion check",
    S["code"]))
story.append(P(
    "Document generators (this PDF and the companion technical paper): "
    "docs/pdf/build_engineering_report.py, docs/pdf/build_technical_paper.py "
    "with shared helpers in docs/pdf/build_lib.py. Source reports for each "
    "phase: filter_benchmark/reports/phase2_demonstration.md, "
    "phase3_engineering_report.md, phase4_final_report.md, "
    "phase5_real_fusion.md, data_quality_report.md, dataset_inventory.md; "
    "programme handover: docs/HANDOVER.md.", S["body"]))

# ---------------------------------------------------------------- build
first, later = header_footer(
    "Vario USB — Engineering Report Phases 1–5 (2026-10-23)")
doc = SimpleDocTemplate(str(OUT), pagesize=A4,
                        topMargin=2.4 * cm, bottomMargin=2.2 * cm,
                        leftMargin=2.4 * cm, rightMargin=2.4 * cm,
                        title="Vario USB Engineering Report Phases 1-5",
                        author="R. Malik / Kimi Work",
                        subject="Dual-barometer + IMU variometer benchmark")
doc.build(story, onFirstPage=first, onLaterPages=later)
print(f"wrote {OUT} ({len(story)} flowables)")
