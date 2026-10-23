"""Generate the research-style technical paper PDF.

Output: docs/Vario_USB_Technical_Paper.pdf
Every number is read from the committed CSVs in filter_benchmark/results/
(the tables below are transcribed from them); figures are the committed PNGs.

Repro:  python docs/pdf/build_technical_paper.py
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

OUT = Path(__file__).resolve().parents[1] / "Vario_USB_Technical_Paper.pdf"
S = styles()
fig_no = [0]
tbl_no = [0]


def fig(name, width, caption):
    fig_no[0] += 1
    return figure(name, width, caption, fig_no[0], S)


def tbl(story, header, rows, widths, center=None, caption=None):
    if caption:
        tbl_no[0] += 1
        story.append(P(f"<b>Table {tbl_no[0]}.</b> {caption}", S["caption"]))
    story.append(three_line_table(header, rows, widths, center_cols=center))
    story.append(spacer(10))


story = []

# ------------------------------------------------------------ title block
story.append(Spacer(1, 2.2 * cm))
story.append(P("Vario USB: A Reproducible Bench Characterization of "
               "Barometric and Barometric-IMU Vertical-Velocity Estimation "
               "for a Low-Cost Variometer", S["title"]))
story.append(P("R. Malik (hardware, captures) with Kimi Work (analysis, "
               "benchmarking) · 2026-10-23", S["subtitle"]))
story.append(P("Repository: github.com/raghavmalik89/vario-usb-workbook · "
               "Commit series b3030bb–bc2f3f2", S["subtitle"]))
story.append(spacer(16))

# ---------------------------------------------------------------- abstract
story.append(P("Abstract", S["h1"]))
story.append(P(
    "We present a bench characterization of vertical-velocity (vario) "
    "estimation for a low-cost USB variometer built from two MS5611 "
    "barometric clones and an MPU6050 inertial measurement unit on an "
    "ESP32-S3. A causal, timestamp-driven replay engine re-runs 29 filter "
    "configurations over 22 committed captures (quiet and office statics, "
    "elevator rides, drops, tosses, controlled hand motion), with "
    "whole-session separation between tuning and validation, physically "
    "equivalent 45/90 Hz parameterizations, and all latency figures "
    "reported as derived proxies rather than ground truth. Measured "
    "findings: raw barometric differentiation is unusable "
    "(9.0–22.1 m/s RMS at rest), the pressure ADC word dominates sensor "
    "noise (2.56–2.89 Pa RMS, equivalent to 0.21–0.24 m of altitude), and "
    "a constant-velocity Kalman filter reaches a rest vertical-velocity "
    "floor of 0.10–0.11 m/s in a quiet house — seven times better than the "
    "same estimator in a drafty office (0.71–0.80 m/s), demonstrating that "
    "ambient pressure drafts, not the sensor, set the practical noise "
    "floor. Real-IMU fusion equals baro-only estimation at rest and on the "
    "elevator but degrades it 1.4–2.2x under tumble because a 6-DOF "
    "attitude estimator without magnetometer leaves gravity residuals of "
    "6.5–10.3 m/s²; simulation shows that with known attitude the same "
    "fusion architecture reduces climb-tracking error 50x and coasts "
    "through a 1 s barometer blackout at 0.034 m/s RMS. Audio-policy "
    "evaluation exposes a missed-lift defect (18.9–21.6% of lifts) in the "
    "otherwise most accurate robust-adaptive filter, and a freeze defect "
    "in a dual-timescale filter is root-caused to a self-referencing "
    "replace step. No final estimator is selected; retained candidates, "
    "limitations, and reproducibility references are given.", S["body"]))
story.append(PageBreak())

# ------------------------------------------------------------ 1 intro
story.append(P("1. Introduction", S["h1"]))
story.append(P(
    "A variometer is the central flight instrument of soaring: it reports "
    "vertical velocity so the pilot can centre thermals and detect sink. "
    "The core engineering tension is latency versus noise. Barometric "
    "altitude is available at tens of hertz with sub-metre resolution, but "
    "differentiating altitude to velocity amplifies noise roughly with "
    "bandwidth; any low-pass or estimator that suppresses noise also "
    "delays the onset and release of a lift, and pilots report release "
    "detection (exit from lift) as being at least as important as onset. "
    "Consumer variometers additionally contain IMUs, and open-source "
    "designs (e.g. har-in-air's ESP32 vario) fuse barometer and "
    "accelerometer; how much of that benefit survives on real low-cost "
    "hardware with consumer-grade IMUs is rarely quantified.", S["body"]))
story.append(P(
    "This paper documents a bench programme that treats the variometer as "
    "an estimation problem to be measured, not assumed. All experiments "
    "run on one physical rig whose raw captures are committed to version "
    "control, so every figure in this paper is reproducible from the "
    "repository by command-line invocation. The contributions are:", S["body"]))
for c in (
    "1) A causal replay engine that re-runs filters against recorded raw "
    "ADC streams with physically derived sample intervals, preserves "
    "corrupt frames and missing-sample events in diagnostics, and keeps "
    "sensor streams independent unless an explicit fusion algorithm is "
    "being evaluated (Section 3).",
    "2) A characterization of two GY-63 MS5611 clones and a genuine "
    "MPU6050 on one I2C rig, including clone scale bias and the "
    "dominance of the pressure ADC word in sensor noise (Section 4.1).",
    "3) A 29-filter comparison across five families (window smoothers, "
    "frequency-domain low-pass, trackers, Kalman variants, robust/gated "
    "estimators) with whole-session tuning/validation separation, "
    "physically equivalent 45/90 Hz parameterizations, and CPU-cost "
    "measurements relevant to an embedded target (Sections 4.3–4.4).",
    "4) A real-IMU fusion validation separating the Kalman core from the "
    "attitude estimator, showing that attitude quality — not the filter — "
    "is the fusion bottleneck on this hardware (Section 4.5), supported by "
    "a simulation ceiling with known attitude (Section 4.7).",
    "5) An audio-behaviour evaluation covering lift onset, exit-from-lift, "
    "false beeping, and a missed-lift defect in the most accurate filter "
    "(Section 4.4), plus fault-injection and C99-portability results "
    "(Section 4.6)."):
    story.append(P(c, S["body"]))
story.append(P(
    "Throughout, claims are tagged [M] measured, [S] simulated, [D] "
    "derived proxy, [H] hypothesis, or [U] unverified. No final estimator "
    "is selected in this paper; the programme deliberately ends at a "
    "shortlist with measured trade-offs.", S["body"]))

# ------------------------------------------------------------ 2 background
story.append(P("2. Background and Related Work", S["h1"]))
story.append(P("2.1 Barometric altimetry", S["h2"]))
story.append(P(
    "Barometric altitude follows from the pressure-altitude relation of "
    "the 1976 ICAO standard atmosphere as tabulated in the MS5611 "
    "datasheet [1]:", S["body"]))
story.append(formula("baro",
    r"h(p)=44330\left[1-\left(\frac{p}{p_0}\right)^{0.1903}\right]"))
story.append(P(
    "with p the measured pressure and p0 = 1013.25 hPa the sea-level "
    "reference. The MS5611-01BA03 is a 24-bit barometric module; at "
    "oversampling ratio (OSR) 4096 its datasheet RMS noise is 0.012 mbar "
    "typical [1]. Stochastic noise modelling for barometric altimeters is "
    "treated by Sabatini and Genovese [6]. Vertical velocity is the "
    "derivative of h; direct differencing is the trivial estimator and, "
    "as our measurements confirm (Section 4.3), the worst.", S["body"]))
story.append(P("2.2 Recursive estimation", S["h2"]))
story.append(P(
    "The classical framework is the Kalman filter [3]; Welch and Bishop "
    "give the standard formulation [4]. The workhorse model here is a "
    "two-state constant-velocity (CV) filter over altitude h and velocity "
    "v with process spectral density q and measurement variance r:", S["body"]))
story.append(formula("cv",
    r"F=[[1,\ dt],\ [0,\ 1]],\ \ "
    r"Q=q\,[[dt^{3}/3,\ dt^{2}/2],\ [dt^{2}/2,\ dt]],\ \ "
    r"H=[[1,\ 0]]"))
story.append(P(
    "In fusion mode each timestamped accelerometer sample propagates the "
    "state through the gravity-compensated Earth-vertical acceleration "
    "a_z - g:", S["body"]))
story.append(formula("fuse",
    r"x_{k+1}=F\,x_k+\left[dt^{2}/2,\ dt\right]^{T}(a_z-g),\ \ "
    r"a_z=\left(R(q_k)\,a_{meas}\right)_z"))
story.append(P("2.3 Attitude estimation", S["h2"]))
story.append(P(
    "Gravity compensation requires orientation. We use the gradient-"
    "descent IMU/MARG orientation filter of Madgwick, Harrison and "
    "Vaidyanathan [5], which fuses accelerometer and gyroscope at low "
    "computational cost suitable for microcontrollers; the quaternion "
    "update integrates gyro rates with a feedback term driving the "
    "measured direction of gravity toward the model direction:", S["body"]))
story.append(formula("madg",
    r"q_{k+1}=q_k+\frac{\Delta t}{2}\,q_k\otimes"
    r"\left[0,\ \omega_k-\hat{b}_k\right]"))
story.append(P(
    "The rig has no magnetometer, so yaw is unobservable in principle and "
    "pitch/roll are only as good as the acceleration reference — a "
    "limitation that Section 4.5 quantifies under tumble.", S["body"]))
story.append(P("2.4 Noise stability analysis", S["h2"]))
story.append(P(
    "Allan deviation [7] separates white noise from drift by averaging "
    "successive phase averages; we report it on detrended altitude at "
    "tau = 1 s and 10 s as a stability fingerprint of each capture:", S["body"]))
story.append(formula("allan",
    r"\sigma_y^{2}(\tau)=\frac{1}{2}"
    r"\left\langle\left(\bar{y}_{k+1}-\bar{y}_k\right)^{2}\right\rangle"))
story.append(P("2.5 Open-source practice", S["h2"]))
story.append(P(
    "The closest open references are har-in-air's ESP32 IMU/BARO/GPS "
    "variometer [8], which couples a Kalman altitude estimator with an "
    "IMU and is the de facto design pattern for DIY variometers, and "
    "Gallostra's AltitudeEstimation library [9]. Audio conventions "
    "(rising tone with climb rate, onset/exit thresholds) follow XCSoar's "
    "established glide-computer practice [10]. This paper differs from "
    "both in that every design claim is tied to a committed raw capture "
    "and a replayable metric rather than to field impressions.", S["body"]))

# ---------------------------------------------------------- 3 methodology
story.append(P("3. Methodology", S["h1"]))
story.append(P("3.1 Hardware rig", S["h2"]))
story.append(P(
    "One ESP32-S3 development board hosts two independent I2C buses. Bus A "
    "(GPIO4/5) carries an MPU6050 IMU at 0x69 and an MS5611 clone at 0x76; "
    "bus B (GPIO6/7) carries a second MS5611 clone at 0x77. The GY-63 "
    "modules are low-cost MS5611 breakouts from the same supplier batch; "
    "clone identity is verified by PROM CRC and PROM[0] words "
    "(0x0878 / 0x0884) [M]. The IMU is a genuine MPU6050 (WHO_AM_I 0x68). "
    "All orientation-sensitive firmware assumes the X-up mounting of the "
    "rig [M]. Table 1 summarizes the as-built.", S["body"]))
tbl(story,
    ["Device", "Bus", "Address", "Role", "Verified by"],
    [["MS5611 clone #1 (GY-63)", "A (GPIO4/5)", "0x76", "Barometer sid 0",
      "PROM[0]=0x0878, CRC ok"],
     ["MPU6050 (genuine)", "A (GPIO4/5)", "0x69", "IMU, 200 Hz accel+gyro",
      "WHO_AM_I=0x68"],
     ["MS5611 clone #2 (GY-63)", "B (GPIO6/7)", "0x77", "Barometer sid 1",
      "PROM[0]=0x0884, CRC ok"]],
    [4.4*cm, 2.6*cm, 1.8*cm, 4.4*cm, 4.0*cm],
    caption="As-built rig. A third barometer on a bit-banged bus C was "
            "probed during bring-up but is not part of the dataset.")

story.append(P("3.2 Capture protocol and dataset", S["h2"]))
story.append(P(
    "Captures are raw telemetry frames (P/T/E lines: pressure ADC, "
    "temperature ADC, error codes) with hardware timestamps, recorded over "
    "USB at 921600 baud using a fixed command-line tool. Twenty-two "
    "captures are committed: bench statics at two firmware generations "
    "(t001–t003), elevator and step-drop (t004), office statics plus "
    "elevator, drop, toss and controlled-move sessions (t005–t006), the "
    "same set with the IMU streamed at 200 Hz (t007), and a quiet-house "
    "static (t008). Data-quality diagnostics (sequence drops, corrupt "
    "frames) accompany every capture; the t005–t008 motion captures used "
    "here were clean (0 sequence drops at ingest). Capture metadata "
    "(OSR, rate, label) is stored in JSON sidecars next to each CSV, and "
    "the benchmark regenerates its reports from these files only.", S["body"]))

story.append(P("3.3 Causal replay engine", S["h2"]))
story.append(P(
    "The benchmark never re-simulates noise: it replays recorded ADC "
    "streams through each filter with sampling intervals derived from "
    "physical timestamps (never assumed nominal), handling irregular "
    "gaps, spikes and dropouts exactly where they occurred. Corrupt "
    "frames and missing-sample events are preserved in per-run "
    "diagnostics rather than silently dropped. Individual sensor streams "
    "are kept independent — the two barometers are never averaged — "
    "except when an explicitly defined fusion algorithm is under test, so "
    "that cross-sensor noise structure (shared chamber pressure vs "
    "independent electronics) remains observable in the results. An "
    "event detector derives lift events from the reference stream of each "
    "session; onset/release latencies are then computed per filter "
    "against those derived references and are reported as descriptive "
    "proxies [D], not ground-truth latency, because no capture contains a "
    "truth-grade vertical-velocity signal. A commercial reference vario "
    "(baseline B03) was planned but remained unavailable [U].", S["body"]))

story.append(P("3.4 Filters under test", S["h2"]))
story.append(P(
    "Twenty-nine configurations in five families are compared against "
    "three baselines: B00 raw differencing; B01 least-squares slope over a "
    "1 s window; B02 a literature-style project Kalman filter "
    "(q_h=0.05, q_v=0.5, auto-r). Family A: window smoothers (SMA, EMA, "
    "Holt, median, Hampel, robust EMA). Family B: frequency-domain "
    "low-pass (1-pole, 2nd-order Butterworth, 2nd-order Bessel, Savitzky-"
    "Golay). Family C: alpha-beta and alpha-beta-gamma trackers. Family "
    "D: Kalman variants (CV, CA, adaptive-R, innovation-gated). Family S: "
    "robust/gated estimators (S1 robust-adaptive, S1P persistence, S2 "
    "dual-timescale, S3 acceleration-aware, S4 fast/slow gated, S5 light-"
    "gate). All filters run from a single command-line entry point; "
    "every configuration and run is reproducible from the repository.", S["body"]))

story.append(P("3.5 Tuning, validation, and metrics", S["h2"]))
story.append(P(
    "Per-filter tuning was fit on training sessions only and reported "
    "against held-out validation sessions (whole-session separation). "
    "Static metrics: detrended altitude noise, drift range and Allan "
    "deviation, and Kalman-filter rest vertical-velocity RMS. Motion "
    "metrics: onset/release latency proxies, false-latch rate, and "
    "event-level audio behaviour (Section 4.4). Rate comparisons use "
    "physically equivalent parameterizations wherever possible (e.g. "
    "time-constant-matched EMA, bandwidth-matched low-pass).", S["body"]))

# ------------------------------------------------------------- 4 results
story.append(P("4. Results", S["h1"]))
story.append(P("4.1 Static noise and drift: the draft effect", S["h2"]))
story.append(P(
    "Table 2 condenses the cross-generation static characterization "
    "(results/21_static_compare.csv). Two findings stand out. First, the "
    "pressure ADC word dominates: per-sample pressure noise corresponds "
    "to 0.40–0.46 m detrended altitude, while the temperature ADC word "
    "contributes 0.2–0.5 Pa — an earlier hypothesis that temperature-ADC "
    "noise materially limits altitude was refuted [M]. Second, the quiet-"
    "house capture t008 drifts 1.25–1.38 m over 60 s, essentially "
    "matching the office statics t005/t006 (1.19–1.65 m), while the t007 "
    "office static — recorded beside an open-window draught — drifts "
    "9.2–9.8 m, roughly 7x more. The Kalman rest vertical-velocity RMS "
    "follows the same split: 0.10–0.11 m/s on the quiet captures versus "
    "0.71–0.80 m/s on the draughty one. The dominant limiter on practical "
    "vario noise is ambient pressure disturbance, not the sensor [M].", S["body"]))
tbl(story,
    ["Capture", "OSR/rate", "r_est (m²)", "Alt. noise (m)",
     "Drift range (m)", "ADEV 1s/10s (m)", "KF rest v-RMS (m/s)"],
    [["t005 office", "4096 @ 45 Hz", "0.0328–0.0367", "0.43–0.44",
      "1.34–1.65", "0.39–0.40", "0.120–0.131"],
     ["t006 office", "2048 @ 90 Hz", "0.0269–0.0312", "0.41–0.42",
      "1.19–1.28", "0.27–0.29", "0.104–0.107"],
     ["t007 office (draft)", "2048 @ 90 Hz +IMU", "0.0379–0.0463",
      "0.44–0.46", "9.21–9.76", "0.41–0.51", "0.713–0.796"],
     ["t008 quiet house", "2048 @ 90 Hz +IMU", "0.0261–0.0326",
      "0.40–0.42", "1.25–1.38", "0.27–0.30", "0.105–0.112"]],
    [2.9*cm, 2.9*cm, 2.2*cm, 2.4*cm, 2.4*cm, 2.5*cm, 2.6*cm],
    center={1, 2, 3, 4, 5, 6},
    caption="Static characterization across capture generations "
            "(per-sid ranges, both barometers; exploratory KF q=10 with "
            "per-capture r). Source: results/21_static_compare.csv [M].")
story += fig("fig_static_drift.png", 14.5,
             "Detrended altitude over the four 60 s statics. t007 (orange) "
             "shows the 7x larger draft-driven excursion; t005/t006/t008 "
             "overlay within ~0.4 m of each other.",)
story += fig("fig_static_kf.png", 14.5,
             "Kalman vertical velocity at rest: quiet captures sit at the "
             "0.10–0.11 m/s floor while the draughty t007 sits at "
             "0.71–0.80 m/s — the environment, not the estimator, sets "
             "the floor.")
story.append(P(
    "Allan deviation (Figure 3) is consistent with this reading: every "
    "capture shares a short-tau floor of 0.25–0.35 m, and only t007 rises "
    "with averaging time, the signature of a slowly varying disturbance "
    "(draft) rather than sensor white noise [M][D].", S["body"]))
story += fig("fig_static_allan.png", 14.0,
             "Allan deviation of detrended altitude. Quiet statics are "
             "flat or falling with tau; the draughty t007 rises, "
             "indicating non-stationary environmental disturbance.")

story.append(P("4.2 IMU health at rest", S["h2"]))
story.append(P(
    "The MPU6050 is genuine but consumer-grade: at rest it reports "
    "|a| = 10.055 m/s² (10.077 m/s² in t008) against 9.807 expected — a "
    "+2.5–2.8% clone-scale bias — while gyro offset norms (51.7–55.8 dps "
    "across sessions) are large but stable, and 1-sigma accel noise at "
    "rest is 0.013 m/s² [M]. Rest accel bias was estimated to 0.0014 m/s² "
    "residual norm by the fusion estimator under a rest gate. Madgwick "
    "gravity-direction error at rest is 0.011 rad, rising to 0.14 rad on "
    "the smooth elevator and 3.4–10.3 rad-equivalent residuals (as "
    "gravity-norm deviation) under tumble (Section 4.5).", S["body"]))

story.append(P("4.3 Filter benchmark", S["h2"]))
story.append(P(
    "Across both rates, the 1-pole and 2nd-order low-pass family is "
    "uniformly poor at rest (0.34–5.18 m/s RMS; the 2nd-order filters "
    "ring after transients), window smoothers trade noise for heavy "
    "latency, and the recursive estimators dominate. Table 3 gives the "
    "rate comparison on the static metric for representative filters "
    "(results/06_rate_comparison.csv); doubling rate with physically "
    "equivalent parameterization leaves the ordering unchanged and "
    "marginally improves the Kalman rest floor (0.101 to 0.087 m/s for "
    "the CV filter).", S["body"]))
tbl(story,
    ["Filter", "Family", "Rest v-RMS 45 Hz (m/s)", "Rest v-RMS 90 Hz (m/s)"],
    [["B00 diff", "baseline", "9.02", "21.5"],
     ["B01 regression (1 s)", "baseline", "0.159", "0.155"],
     ["A01 SMA (1 s)", "A", "0.250", "0.396"],
     ["A02 EMA (tau=1 s)", "A", "0.190", "0.175"],
     ["B02 Butterworth-2", "B", "2.54", "3.73"],
     ["C01 alpha-beta", "C", "0.026", "0.025"],
     ["C03 CV tracker", "C", "0.047", "0.056"],
     ["D01 Kalman CV", "D", "0.101", "0.087"],
     ["D04 Kalman adapt-R", "D", "0.122", "0.097"]],
    [4.6*cm, 2.2*cm, 4.4*cm, 4.4*cm], center={1, 2, 3},
    caption="Static rest vertical-velocity RMS, representative filters "
            "(t001 statics; 06_rate_comparison.csv) [M].")
story.append(P(
    "The retained Phase-4 candidates are summarized in Table 4 "
    "(results/12_estimator_summary.csv, 12_cpu.csv). Two defects shape "
    "the shortlist. First, the dual-timescale S2 froze permanently on "
    "its first sustained event: root cause [M] was the replace step "
    "writing the fast-track state from a prediction that itself consumed "
    "the fast-track state (self-reference), fixed by saturating the "
    "correction to a bounded deviation from prediction; S2 was "
    "disqualified. Second, S1 — the best rest performer — misses 18.9% "
    "of validation lifts under the common audio policy (Section 4.4). "
    "S5 matches S1's rest accuracy at 2.7x lower CPU; S4 is the fastest "
    "on release; C03 is the cheapest but false-latches and has a "
    "validation missed-lift rate of 2.7%.", S["body"]))
tbl(story,
    ["Estimator", "Rest RMS train (m/s)", "Onset proxy val (s)",
     "Release proxy val (s)", "CPU (us/sample)"],
    [["C03 CV tracker", "0.048", "1.29", "2.18", "7.1"],
     ["D01 Kalman CV", "0.096", "-2.35", "2.11", "16.0"],
     ["S1 Robust-adaptive", "0.045", "0.14", "4.95", "50.7"],
     ["S1P Persistence", "0.045", "0.14", "1.90", "50.4"],
     ["S4 Fast/slow gated", "0.085", "0.04", "1.43", "19.0"],
     ["S5 Light-gate", "0.046", "0.12", "4.23", "18.4"]],
    [4.0*cm, 3.4*cm, 3.2*cm, 3.2*cm, 2.6*cm], center={1, 2, 3, 4},
    caption="Retained candidates: rest accuracy (training statics), "
            "derived onset/release latency proxies (validation), and "
            "measured CPU cost. Negative onset proxy for D01 is a proxy "
            "artifact (output leads the derived reference).")
story += fig("fig_p4_estimator_comparison.png", 15.0,
             "Phase-4 candidates on rest-RMS versus release proxy: the "
             "accuracy/latency/CPU trade space. S2 excluded (freeze "
             "defect).")
story += fig("fig_p4_s2_freeze_event.png", 14.5,
             "The S2 freeze defect: fast-track state locked at its "
             "pre-event value while the slow track continued — traced to "
             "a self-referencing replace step.")

story.append(P("4.4 Audio behaviour: onset, exit-from-lift, and defects", S["h2"]))
story.append(P(
    "Each estimator drives a common audio state machine with per-filter "
    "tuned thresholds (lift-on, lift-off, strong-lift), hysteresis and a "
    "persistence gate; the evaluation counts missed lifts, false-on time, "
    "onset delay and exit delay per event against derived references "
    "(results/13_policy_comparison.csv, validation split, tuned+safety "
    "variant, Table 5). The exit-from-lift requirement is explicitly "
    "measured: XCSoar-style conventions expect prompt silencing when lift "
    "ends [10], and continuous-beeping suppression is part of the policy "
    "score. S1/S1P pay for their rest accuracy with the worst lift "
    "detection (18.9–21.6% missed) — an unacceptable defect for a "
    "soaring instrument — while S4/S5/D01 detect all validation lifts. "
    "Transient stress tests (results/08_audio_failures.csv) further show "
    "estimators emitting extreme outputs after rejected transients "
    "(up to 16.2 m/s for S3 on the 90 Hz drop capture), which the audio "
    "persistence gate is designed to absorb.", S["body"]))
tbl(story,
    ["Estimator", "Missed-lift rate", "Onset delay med (s)",
     "Exit delay med (s)", "False-on per hr (train)"],
    [["C03 CV tracker", "0.027", "0.77", "0.82", "0"],
     ["D01 Kalman CV", "0.0", "0.70", "0.79", "60"],
     ["S1 Robust-adaptive", "0.189", "1.54", "1.00", "60"],
     ["S1P Persistence", "0.216", "1.42", "1.08", "60"],
     ["S4 Fast/slow gated", "0.0", "1.08", "1.44", "60"],
     ["S5 Light-gate", "0.0", "0.90", "0.98", "60"]],
    [4.0*cm, 2.6*cm, 3.3*cm, 3.0*cm, 3.3*cm], center={1, 2, 3, 4},
    caption="Audio-policy evaluation, validation split. Missed-lift "
            "defect of S1/S1P is the key discriminator; false-on rates "
            "are from the training split (statics).")

story.append(P("4.5 Real-IMU fusion", S["h2"]))
story.append(P(
    "Fusion was validated against the real t007/t008 captures "
    "(results/17_real_imu_fusion.csv, 22_t008_fusion.csv): Madgwick "
    "attitude at beta=0.3 from 200 Hz IMU samples, accel bias estimated "
    "only under a rest gate, Kalman core as in Section 2.2. At rest the "
    "fusion output is numerically identical to baro-only (t008: 0.1085 "
    "vs 0.1086 m/s; zero reinitializations) [M] — the IMU adds nothing "
    "when the rig is still, as it should. On the elevator the two are "
    "within 4% (1.39 vs 1.33 m/s session RMS). Under tumble, fusion is "
    "1.4–2.2x worse than baro-only (Table 6): the attitude error, visible "
    "as gravity-residual norm 6.5–10.3 m/s² during drop/toss, injects "
    "false vertical acceleration. The bottleneck is therefore the 6-DOF "
    "attitude estimator without magnetometer — not the Kalman core "
    "[M][D].", S["body"]))
tbl(story,
    ["Session", "Rest/behaviour", "v-RMS baro-only (m/s)",
     "v-RMS fusion (m/s)", "Gravity residual (m/s²)"],
    [["t008 quiet static", "rest", "0.1085", "0.1086", "0.011 rad"],
     ["t007 bench static", "rest (drafty)", "0.756", "0.756", "0.011 rad"],
     ["t007 elevator 2x", "smooth motion", "1.334", "1.393", "0.137 rad"],
     ["t007 drop", "tumble", "1.245", "2.077", "6.53"],
     ["t007 drop2", "tumble", "1.511", "2.678", "8.21"],
     ["t007 toss", "tumble", "1.361", "2.972", "10.29"],
     ["t007 ControledMove2", "jerk + tumble", "1.685", "2.205", "3.41"]],
    [3.6*cm, 3.0*cm, 3.2*cm, 3.1*cm, 3.1*cm], center={1, 2, 3, 4},
    caption="Real-IMU fusion vs baro-only (sid 0; sid 1 within 5%). "
            "Fusion is neutral at rest, equal on smooth motion, and "
            "harmful under tumble — the attitude-limited regime.")
story += fig("fig_p5_real_fusion.png", 15.0,
             "Fusion versus baro-only on the t007 drop and elevator: the "
             "fused track diverges exactly where attitude error grows.")

story.append(P("4.6 Portability and fault handling", S["h2"]))
story.append(P(
    "The Kalman core is portable: a C99 implementation matches the "
    "Python reference to 2.0e-08 m/s worst-case across 12 irregular-"
    "sampling, spike, gap and reversal vectors in double precision, and "
    "passes looser float tolerances; it compiles for the Xtensa ESP32-S3 "
    "target (results/15_portable_equivalence.csv) [M]. Fault injection "
    "(results/09_fault_recovery.csv) validates innovation gating at "
    "3.5 sigma plus a loss-of-track reinitializer (8 consecutive "
    "&gt;5 sigma innovations trigger reacquisition): after a sustained "
    "sensor fault the estimator recovers within one event window without "
    "latching. The shortest-arc attitude warm start (quaternion from "
    "accelerometer tilt) shipped after closed-loop replays showed cold-"
    "start attitude transients contaminating the first seconds of fusion; "
    "trigonometric forms were abandoned as convention-treacherous on the "
    "X-up rig in favour of a vector form.", S["body"]))

story.append(P("4.7 Simulated fusion ceiling", S["h2"]))
story.append(P(
    "To separate architecture from hardware, the identical fusion "
    "pipeline was run on simulated streams with known attitude "
    "(results/14_fusion_simulated.csv) [S]. With attitude given, fusion "
    "cuts climb-tracking RMS error from 0.499 to 0.0095 m/s (50x), "
    "coasts through a 1 s barometer blackout at 0.034 m/s RMS versus "
    "1.70 m/s baro-only, and bounds a single-sample 8 m pressure spike to "
    "1.50 m/s peak velocity error. The architecture is sound; the "
    "hardware attitude estimate is what stands between the bench rig and "
    "these numbers [S][D].", S["body"]))

# ------------------------------------------------------------ 5 discussion
story.append(P("5. Discussion", S["h1"]))
story.append(P(
    "Three measured results reorganize the design space. First, the "
    "quiet-static floor of 0.10–0.11 m/s rest vertical-velocity RMS — "
    "reached by a plain CV Kalman with per-capture r — is already at the "
    "level pilots describe as 'quiet', and it was reached without any "
    "fusion. The 7x degradation caused by a room draft shows the "
    "deployment environment dominates; a filter tuned on a draughty bench "
    "would be over-smoothed for the air. Second, IMU fusion as "
    "implemented is an attitude problem in disguise: with a 6-DOF IMU and "
    "no magnetometer, gravity residuals during tumble exceed the signal "
    "by an order of magnitude, so fusion helps exactly where attitude is "
    "good (rest, smooth motion) and hurts where attitude fails. "
    "Confidence-gated fusion — applying IMU propagation only when "
    "attitude error is bounded — is the natural next step, and the "
    "simulation ceiling quantifies the payoff (Section 4.7). Third, "
    "accuracy and audio behaviour diverge: the estimator with the best "
    "rest RMS misses nearly one lift in five, so filter selection must "
    "be driven by the policy metrics of Table 5, not by RMS alone.", S["body"]))
story.append(P(
    "The XCTracer-style architecture (fast IMU-predict/baro-correct "
    "Kalman with a slow baro-only confidence channel) remains a "
    "candidate, supported by the fusion results here, but its "
    "implementation details are not assumed without evidence and no "
    "estimator is frozen: further hardware testing and comparative "
    "measurements are planned before selection, per the programme "
    "constraint.", S["body"]))

# ----------------------------------------------------------- 6 limitations
story.append(P("6. Limitations", S["h1"]))
for l in (
    "All latency figures are derived proxies against derived event "
    "references [D]; no capture contains ground-truth vertical velocity, "
    "and the planned commercial reference vario (B03) was unavailable [U].",
    "The IMU is a genuine but low-grade MPU6050 with +2.5–2.8% accel "
    "scale bias and 52–56 dps gyro offsets; results characterize this "
    "unit, and a different IMU would shift the fusion conclusions.",
    "Both barometers are clones from one supplier batch; clone-to-clone "
    "variance beyond this pair is unmeasured.",
    "Bench motion (drops, tosses, elevator) is a proxy for thermal-lift "
    "flying; no real in-flight captures exist yet, and drop/toss dynamics "
    "exceed any soaring regime, which is why fusion looks worse on them "
    "than it likely would be in air [H].",
    "The KF q value used in the static characterization (q=10) is "
    "exploratory; q discrimination requires motion-session tuning and "
    "held-out validation, not statics.",
    "The USB capture path itself was implicated in a host-side freeze "
    "during long sessions; the MCU-side root cause is unverified [U].",
    "Audio-policy thresholds were tuned on bench events; pilot-in-the-"
    "loop validation is outstanding [U]."):
    story.append(P("• " + l, S["body"]))

# ---------------------------------------------------------- 7 conclusions
story.append(P("7. Conclusions", S["h1"]))
story.append(P(
    "On committed raw captures and a causal replay engine, this bench "
    "programme measured, rather than assumed, the noise floor, the "
    "filter trade space, the audio behaviour, and the real-IMU fusion "
    "value of a dual-barometer ESP32-S3 variometer. A plain CV Kalman "
    "filter reaches a 0.10–0.11 m/s rest floor in a quiet environment; "
    "ambient drafts, not the MS5611 clones, set the practical limit. IMU "
    "fusion is neutral at rest and on smooth motion but attitude-limited "
    "under tumble, with a quantified 50x ceiling if attitude is known. "
    "Three stacked-filter candidates (S5 light-gate, S4 fast/slow gated, "
    "D01 CV Kalman as the simple reference) are retained with measured "
    "trade-offs; S1/S1P are retained only if their missed-lift defect is "
    "resolved. All data, scripts, and result tables are committed and "
    "reproducible from the repository. The next engineering step is "
    "adaptive attitude-trust gating of the IMU fusion path, validated on "
    "controlled-motion captures, followed by real thermal-lift flight "
    "captures for final estimator selection.", S["body"]))

# ----------------------------------------------------------- references
story.append(P("References", S["h1"]))
refs = [
    "TE Connectivity. MS5611-01BA03 Barometric Pressure Sensor Module "
    "(Datasheet).",
    "InvenSense. MPU-6050 Six-Axis MEMS MotionTracking Device "
    "(Datasheet).",
    "Kalman, R. E. (1960). A new approach to linear filtering and "
    "prediction problems. Transactions of the ASME — Journal of Basic "
    "Engineering, 82(Series D), 35–45.",
    "Welch, G., &amp; Bishop, G. (2006). An Introduction to the Kalman "
    "Filter (Technical Report 95-041). University of North Carolina at "
    "Chapel Hill, Department of Computer Science.",
    "Madgwick, S. O. H., Harrison, A. J. L., &amp; Vaidyanathan, R. "
    "(2010). Estimation of IMU and MARG orientation using a gradient "
    "descent algorithm. Proceedings of the IEEE International Conference "
    "on Rehabilitation Robotics (ICORR), 1–7.",
    "Sabatini, A. M., &amp; Genovese, V. (2014). A stochastic approach "
    "to noise modeling for barometric altimeters. Sensors, 14(9).",
    "Riley, W. (2008). Handbook of Frequency Stability Analysis. NIST "
    "Special Publication 1065, National Institute of Standards and "
    "Technology.",
    "har-inair. ESP32_IMU_BARO_GPS_VARIO — open-source ESP32 variometer "
    "firmware. GitHub repository (referenced in docs/HANDOVER.md).",
    "Gallostra, J. (juangallostra). AltitudeEstimation — Kalman-based "
    "altitude/velocity estimation library. GitHub repository (referenced "
    "in docs/HANDOVER.md).",
    "XCSoar. XCSoar — the open-source glide computer. https://xcsoar.org "
    "(vario audio conventions).",
]
for i, r in enumerate(refs, 1):
    story.append(P(f"[{i}] {r}", S["ref"]))
story.append(spacer(10))
story.append(P(
    "Reproducibility: all captures in analysis/data/, all metrics in "
    "filter_benchmark/results/*.csv, all figures in "
    "filter_benchmark/results/*.png, and the generators of both this "
    "paper and the companion engineering report in docs/pdf/. Build with "
    "python docs/pdf/build_technical_paper.py.", S["caption"]))

# ------------------------------------------------------------------ build
doc = SimpleDocTemplate(
    str(OUT), pagesize=A4,
    leftMargin=2.2 * cm, rightMargin=2.2 * cm,
    topMargin=2.3 * cm, bottomMargin=2.1 * cm,
    title="Vario USB: Bench Characterization of Barometric-IMU "
          "Vertical-Velocity Estimation",
    author="R. Malik with Kimi Work")
first, later = header_footer(
    "Vario USB — Technical Paper · 2026-10-23")
doc.build(story, onFirstPage=first, onLaterPages=later)
print(f"wrote {OUT}")
