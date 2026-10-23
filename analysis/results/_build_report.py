"""Build the comprehensive engineering report PDF (ReportLab route)."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image, PageBreak, KeepTogether)
from PIL import Image as PILImage

OUT = 'docs/Vario_USB_FalseLift_ESP_IDF_Validation_Report.pdf'
FIG = 'analysis/results/'

styles = getSampleStyleSheet()
H1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName='Helvetica-Bold',
                    fontSize=15, textColor=HexColor('#1a3a5c'), spaceBefore=18,
                    spaceAfter=8, keepWithNext=1)
H2 = ParagraphStyle('H2', parent=styles['Heading2'], fontName='Helvetica-Bold',
                    fontSize=12, textColor=HexColor('#1a3a5c'), spaceBefore=12,
                    spaceAfter=6, keepWithNext=1)
BODY = ParagraphStyle('BODY', parent=styles['Normal'], fontName='Helvetica',
                      fontSize=9.5, leading=13.5, textColor=HexColor('#222222'),
                      spaceAfter=5)
CAP = ParagraphStyle('CAP', parent=BODY, fontSize=8, leading=10,
                     textColor=HexColor('#555555'), alignment=1, spaceAfter=10)
TITLE = ParagraphStyle('TITLE', parent=styles['Title'], fontName='Helvetica-Bold',
                       fontSize=21, leading=26, textColor=HexColor('#1a3a5c'),
                       spaceAfter=6)
SUB = ParagraphStyle('SUB', parent=BODY, fontSize=12, leading=16,
                     textColor=HexColor('#444444'), alignment=1)
SMALL = ParagraphStyle('SMALL', parent=BODY, fontSize=8, leading=11,
                       textColor=HexColor('#555555'))


def P(txt, s=BODY):
    return Paragraph(txt, s)


def fig(path, width=16.2*cm, caption=None):
    im = PILImage.open(path)
    w, h = im.size
    height = width * h / w
    els = [Image(path, width=width, height=height)]
    if caption:
        els.append(Paragraph(caption, CAP))
    return els


def tbl(data, colw, header=True, fontsize=8.5):
    t = Table(data, colWidths=colw, repeatRows=1 if header else 0)
    st = [('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
          ('FONTSIZE', (0, 0), (-1, -1), fontsize),
          ('TOPPADDING', (0, 0), (-1, -1), 4),
          ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
          ('LINEBELOW', (0, -1), (-1, -1), 1.0, HexColor('#000000'))]
    if header:
        st += [('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
               ('LINEABOVE', (0, 0), (-1, 0), 1.2, HexColor('#000000')),
               ('LINEBELOW', (0, 0), (-1, 0), 0.6, HexColor('#000000'))]
    t.setStyle(TableStyle(st))
    return t


def hdr_ftr(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(HexColor('#777777'))
    canvas.drawCentredString(w/2, h - 1.3*cm,
        'Vario USB - False-Lift Root Cause & ESP-IDF Firmware Corrections')
    canvas.line(2*cm, h - 1.5*cm, w - 2*cm, h - 1.5*cm)
    canvas.drawCentredString(w/2, 1.2*cm, 'Page %d' % doc.page)
    canvas.restoreState()


def first_page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setStrokeColor(HexColor('#1a3a5c'))
    canvas.setLineWidth(2)
    canvas.line(2*cm, h - 4.5*cm, w - 2*cm, h - 4.5*cm)
    canvas.line(2*cm, 4.5*cm, w - 2*cm, 4.5*cm)
    canvas.restoreState()


story = []
story.append(Spacer(1, 5.2*cm))
story.append(Paragraph('Vario USB', TITLE))
story.append(Paragraph('False-Lift Root-Cause Investigation,<br/>ESP-IDF Firmware Corrections & Hardware Validation', SUB))
story.append(Spacer(1, 0.9*cm))
story.append(Paragraph(
    'Raghav Malik &middot; Kimi Work engineering session &middot; 23 October 2026<br/>'
    'Hardware: ESP32-S3 dev board, 2x MS5611 (GY-63 clone) barometers, MPU6050 IMU<br/>'
    'Firmware: esp-idf/vario (ESP-IDF, Arduino-independent) &middot; Analysis: Python 3, analysis/ + filter_benchmark/', SUB))
story.append(Spacer(1, 0.6*cm))
story.append(Paragraph(
    'Companion documents: Vario_USB_Engineering_Report_Phases_1-5.pdf (offline filter benchmark), '
    'Vario_USB_Technical_Paper.pdf (research manuscript), docs/HANDOVER.md (state transfer), '
    'docs/defect_register.md (defect log), docs/project_history.md (chronology).', SMALL))
story.append(PageBreak())

# ---------------- 1 Executive summary ----------------
story.append(Paragraph('1. Executive summary', H1))
story.append(P(
    'Two clean elevator captures (1 to 14 floors, two full round trips each) exposed a sustained '
    'false-lift audio fault: while the elevator stood dead-still at the ground floor with the '
    'barometric altitude flat to +/-0.1 m, every estimator on both barometers reported '
    '+0.4-0.7 m/s of climb and beeped "lift" for up to 17 s. This report documents the '
    'root-cause investigation, the evidence exonerating the sensor, the compensation, the '
    'estimators, and the environmental hypotheses (temperature, door/piston pressure '
    'equalisation), and identifies the true cause: the <b>altitude reference pressure p0 was a '
    'running mean of the first 2000 samples (~50 s)</b>, which continued to move after the '
    'elevator reached the lower floor, manufacturing a steady apparent climb at '
    'd(alt)/d(p0) x dp0/dt ~= 0.084 m/Pa x 5 Pa/s ~= +0.45 m/s.'))
story.append(P(
    'A firmware-exact offline simulation (same compensation, same p0 semantics, same estimator '
    'math, same logged timestamps) reproduces the MCU-reported velocity during the false-lift '
    'window with a bias of -0.002 m/s (run 1) and -0.001 m/s (run 2) - essentially perfect. '
    'With a fixed reference the same replay yields -0.02 m/s and 0.00 m/s. The mechanism is '
    'proven beyond reasonable doubt.'))
story.append(P(
    'Three firmware corrections were implemented, built, flashed and bench-validated: '
    '(1) fixed ISA reference pressure (101325 Pa) replacing the moving p0 - removes the entire '
    'artifact class with zero risk to genuine climb detection, because estimator velocity is '
    'invariant to a constant altitude offset; '
    '(2) C03 steady-state gain cache eliminating a 200-iteration Riccati refit storm caused by '
    'the 20/40 ms baro sampling pattern (1330 us -> 38 us average per update, 35x); '
    '(3) enlarged diagnostic-line buffer so all ten per-estimator CPU pairs are reported.'))
story.append(P(
    'IMU-assisted suppression was evaluated and <b>rejected by evidence</b>: the IMU was silent '
    '(constant 1 g) throughout the artifact, making it indistinguishable from a genuine slow '
    'thermal climb - any acceleration-consistency veto capable of catching it would also veto '
    'real thermals, violating the design constraint that low acceleration must not imply zero '
    'vertical velocity.'))

# ---------------- 2 Scope & configuration ----------------
story.append(Paragraph('2. Scope, hardware and firmware configuration', H1))
story.append(Paragraph('2.1 As-built hardware (validated this session)', H2))
story.append(tbl([
    ['Item', 'Value'],
    ['MCU', 'ESP32-S3 @ 240 MHz (double-precision FPU absent; doubles emulated)'],
    ['Baro sid0', 'MS5611 GY-63 clone, Bus A (auto-probed), PROM[0]=0x0878, foam-covered'],
    ['Baro sid1', 'MS5611 GY-63 clone, Bus B, PROM[0]=0x0884, foam-covered'],
    ['IMU', 'MPU6050 @ 0x69, 100 Hz streamed, Madgwick attitude (beta=0.3)'],
    ['Sensor spacing', '25 mm vertical (increased from stacked); thermally isolated from laptop'],
    ['Audio output', 'Virtual: timestamped USB-serial V frames (ON/TONE/OFF), policy lift_on=+0.20, lift_off=+0.05 m/s'],
], [3.2*cm, 13*cm]))
story.append(Spacer(1, 6))
story.append(Paragraph('2.2 Firmware pipeline (esp-idf/vario)', H2))
story.append(P(
    'MS5611 read pipeline: pressure conversion started on tick N, ADC read on tick N+4 '
    '(>=20 ms; the GY-63 clones clock out zeros while converting instead of NAKing, so '
    'shorter windows produced ~33% d1=0 frames). Resulting rates: 40 Hz pressure + 10 Hz '
    'temperature per barometer, 100 Hz IMU, estimator bank runs per baro sample; FUS propagates '
    'on IMU at 100 Hz. The compensation chain (MS5611 second-order, analysis/common.py math, '
    'transcribed verbatim) converts d1/d2 to Pa, then altitude via the reference pressure.'))
story.append(Paragraph('2.3 Estimator bank (all run side-by-side on every baro sample)', H2))
story.append(tbl([
    ['ID', 'Architecture', 'Q', 'R', 'Notes'],
    ['D01', '2-state CV Kalman (kalman.py ref)', '1.0', '0.035', 'Fast/twitchy; lowest CPU'],
    ['C03', 'Steady-state-gain CV tracker (tracking.py ref)', '1.0', '0.035', 'Gains from 200-iter discrete Riccati'],
    ['S4', 'Fast/slow stacked, gated (stacked.py ref)', 'slow 0.3', 'slow 0.035', 'Corrected WP-B variant'],
    ['S5', 'Portable vario_core (portable filter)', '0.3', '0.035', 'gate 3.5 sigma, q_gain 2.0'],
    ['FUS', 'Baro+IMU fusion, Madgwick attitude', '0.3', '0.035', 'Async IMU predict / baro correct; bias tau 3 s'],
], [1.2*cm, 8.2*cm, 1.7*cm, 1.7*cm, 4.4*cm]))
story.append(Spacer(1, 6))

# ---------------- 3 Datasets ----------------
story.append(Paragraph('3. Datasets', H1))
story.append(tbl([
    ['Capture', 'Duration', 'Drops', 'Bad', 'Role'],
    ['20261023_221124_idf_elevator_2x (run 1)', '170.0 s', '0', '0', 'Elevator 1>14>1>14 (2 round trips) - primary evidence'],
    ['20261023_221420_idf_elevator_2x (run 2)', '167.8 s', '3', '0', 'Elevator, identical protocol - reproduction'],
    ['20261023_221109_idf_elevator_2x', '18 s', '-', '-', 'Aborted (dropouts) - excluded per protocol'],
    ['20261023_215709_idf_handtest3', '163 s', '7', '0', 'Static + hand moves + tosses (pre-fix firmware)'],
    ['20261023_234521_idf_p0fix_static', '75.3 s', '0', '0', 'Post-fix stationary validation'],
    ['20261023_234944_idf_bbuf_check', '20.2 s', '0', '0', 'Post-fix diagnostic buffer check'],
], [6.6*cm, 1.8*cm, 1.2*cm, 1.1*cm, 6.9*cm]))
story.append(Spacer(1, 4))
story.append(P(
    'B-line health counters throughout: abad=0, vnan=0, tx_ovf=0, zero I2C errors. '
    'Original recordings, sidecar JSON (PROM constants), analysis scripts and this report are '
    'committed to the repository; nothing was modified or re-derived.', SMALL))

story.append(PageBreak())
# ---------------- 4 Elevator results ----------------
story.append(Paragraph('4. Elevator results (pre-fix firmware)', H1))
story.append(P(
    'Leg detection on the compensated altitude (1 s smoothing, 0.5 m/s threshold) found four '
    'travel legs per run, reproducible to within 0.1 m/s between runs:'))
story.append(tbl([
    ['Leg', 'Run 1 (dH, rate)', 'Run 2 (dH, rate)'],
    ['1 descent', '-38.2 m, -1.59 m/s', '-38.2 m, -1.59 m/s'],
    ['2 ascent', '+38.2 m, +1.55 m/s', '+38.4 m, +1.55 m/s'],
    ['3 descent', '-38.3 m, -1.60 m/s', '-38.2 m, -1.60 m/s'],
    ['4 ascent', '+38.2 m, +1.56 m/s', '+38.3 m, +1.56 m/s'],
], [3*cm, 6.5*cm, 6.5*cm]))
story.append(Spacer(1, 4))
story.append(P(
    '1 to 14 floors = 38.2 m implies 2.94 m per floor. Both barometers agree within +/-0.2 m '
    'during travel. Audio behaviour with the lift-only policy (ON at v>=+0.20, OFF below '
    '+0.05): descents correctly silent; ascents tracked tightly - implied velocity median '
    '+1.64 m/s (D01) and +1.83-1.85 m/s (FUS) against true +1.55-1.56 m/s, with FUS running '
    'about +0.3 m/s hot near its tone saturation. The dwells between legs are the subject of '
    'Section 5.'))
for e in fig(FIG + 'fig1_elevator_run1.png', caption='Figure 1 - Run 1 overview: compensated altitude (both barometers) with detected legs, and audio ON events per estimator. Note the elevated audio activity at the floor-1 dwells (~35-50 s and ~95-118 s).'):
    story.append(e)
for e in fig(FIG + 'fig1_elevator_run2.png', caption='Figure 2 - Run 2 overview, identical protocol; the artifact repeats at the same phase of the run.'):
    story.append(e)

# ---------------- 5 False lift investigation ----------------
story.append(Paragraph('5. False-lift investigation', H1))
story.append(Paragraph('5.1 Symptom and the paradox that constrained it', H2))
story.append(P(
    'At the floor-1 dwell after the first descent (run 1: t=42.5-58 s absolute), D01-sid0 '
    'emitted 78 tone events implying +0.28/+0.45/+0.66 m/s (p10/p50/p90) for a continuous '
    '~16 s, and every other estimator on both sensors did the same. Yet the compensated '
    'altitude - reconstructed independently from the logged raw d1/d2 with the exact '
    'datasheet compensation - is flat to +/-0.1 m for the whole dwell. An honest constant-'
    'velocity Kalman filter cannot hold +0.45 m/s against a flat input; the firmware input '
    'must therefore differ from the reconstructed stream, or the reference itself moves.'))
story.append(Paragraph('5.2 Hypotheses examined and evidence', H2))
story.append(tbl([
    ['Hypothesis', 'Evidence', 'Verdict'],
    ['Clone temperature coefficient (dT/dt -> fake climb)',
     'd1 and d2 both move during the dwell but the second-order compensation cancels them: '
     'reconstructed compensated altitude flat; temperature was slowly FALLING (~0.008 C/s), '
     'which is the fake-sink direction for this clone family',
     'Ruled out'],
    ['Elevator door / piston effect / shaft pressure equalisation',
     'Would appear in the raw pressure stream; the compensated stream is flat within ~2 s '
     'of every stop, both sensors, both runs',
     'Ruled out for this artifact'],
    ['Estimator dynamics (lag/ringing after the descent)',
     'D01 replayed offline on the reconstructed stream returns v ~= 0.00 through every '
     'dwell; no lightly-damped mode can sustain +0.45 m/s for 15 s against flat input',
     'Ruled out'],
    ['Firmware processing (NaN, batching, timestamp gaps)',
     'vnan=0, abad=0, zero seq drops; logged timestamps are the same esp_timer values fed '
     'to the estimators',
     'Ruled out'],
    ['Moving reference pressure p0',
     'Firmware computed altitude against a running mean of the first 2000 pressure samples '
     '(~50 s); the descent placed the dwell inside that window, so p0 kept climbing toward '
     'the lower-floor pressure at ~5 Pa/s',
     'CONFIRMED (Section 5.3-5.4)'],
], [4.2*cm, 10.2*cm, 2.5*cm]))
story.append(Paragraph('5.3 Mechanism', H2))
story.append(P(
    'baro_proc_altitude() returned alt = 44330(1-(p/p0)^0.1903) with p0 = the cumulative '
    'mean of the first 2000 valid samples, frozen afterwards. During any motion inside that '
    'window the reference keeps moving: d(alt)/d(p0) = 44330 x 0.1903 x (p/p0)^0.1903 / p0, '
    'which evaluates to ~0.084 m/Pa near p ~= p0 ~= 100 kPa. At the floor-1 dwell, p0 rose '
    '~5 Pa/s toward the new-floor pressure (38 m of descent = ~455 Pa step), so the firmware '
    'altitude climbed at ~0.4-0.7 m/s while true altitude was flat. The beeping stops '
    'within ~2 s of sample 2000 (t=57.1 s run 1, 55.8 s run 2) - exactly when p0 freezes. '
    'The artifact is 100% inside the reference; the sensor data was telling the truth.'))
story.append(P(
    'The convention came from the offline benchmark (p0 = mean of first 2000 samples), where '
    'all captures were static - the mean converges to true pressure and the offset is '
    'constant, so velocity is unaffected. Eight prior test rounds never moved the sensor '
    'during the window; the "keep the board still for 60 s" capture protocol masked it '
    'completely. The offline convention is safe only when the first 50 s are static.'))
for e in fig(FIG + 'fig2_p0_mechanism.png', caption='Figure 3 - The moving reference. Top: measured pressure and the running-mean p0 (red); p0 freezes at sample 2000 (~50 s). Bottom: altitude against the fixed reference (true profile, ~380 m) versus against the moving p0 (what the estimators consumed, offset near 0 m); the orange band marks the floor-1 dwell where the moving reference climbs despite the elevator being stopped.'):
    story.append(e)
story.append(Paragraph('5.4 Proof by firmware-exact simulation', H2))
story.append(P(
    'The complete firmware chain was re-simulated offline on the logged raw frames: identical '
    'compensation, identical running-mean-then-freeze p0 semantics, D01 transcribed line-for-'
    'line from estimators.c (including the P=10I reset seeding), fed the logged timestamps. '
    'Comparing against the MCU tone-implied velocity:'))
story.append(tbl([
    ['Quantity (dwell@1 after descent 1)', 'Run 1', 'Run 2'],
    ['MCU tones, implied v p50', '+0.45 m/s', '+0.48 m/s'],
    ['Simulation with moving p0: p50 / bias vs MCU', '+0.44 / -0.002', '+0.48 / -0.001'],
    ['Simulation with fixed 101325 Pa ref: p50 / bias vs MCU', '-0.02 / -0.49', '+0.00 / -0.46'],
    ['False-lift ON-time, moving p0 (audio policy replay)', '16.5 s', '17.5 s'],
    ['False-lift ON-time, fixed reference', '0.0 s', '1.2 s'],
    ['Total ON-time per run, moving p0', '74.6 s', '72.0 s'],
    ['Total ON-time per run, fixed reference', '54.9 s', '52.9 s'],
], [8.6*cm, 4.1*cm, 4.1*cm]))
story.append(Spacer(1, 4))
story.append(P(
    'The moving-reference simulation matches the MCU to within 2 mm/s; the fixed reference '
    'eliminates 20 s of phantom beeping per run while preserving the ~49 s of genuine ascent '
    'lift (total ON 55 s vs 49 s expected). Both runs reproduce identically.'))
for e in fig(FIG + 'fig3_false_lift_dwell.png', caption='Figure 4 - The money plot. Dwell zoom: black dots are MCU-reported velocity (tone-implied, D01 sid0); the red trace is the offline replay fed the moving-reference input - it tracks the MCU through the entire false-lift episode; the green trace is the same replay with the fixed reference, sitting at zero throughout (post-fix behaviour).'):
    story.append(e)
story.append(Paragraph('5.5 Why IMU-based suppression was rejected', H2))
story.append(P(
    'The design constraint: steady thermal climbing produces almost no vertical acceleration, '
    'so no stationary-motion veto may be introduced. The dwell diagnostics show ax held a '
    'constant 1 g for the whole artifact - the false lift is IMU-indistinguishable from a '
    'genuine 0.45 m/s thermal. An acceleration-consistency check tight enough to catch the '
    'dwell would catch real thermals too; adaptive barometric confidence cannot help because '
    'the pressure measurements were clean and self-consistent (the error was in the '
    'reference, not the measurement). The only safe suppression class is a physically '
    'unmoving reference - which the fixed 101325 Pa p0 achieves exactly, with zero risk '
    'to genuine climb detection since estimator velocity is invariant to a constant '
    'altitude offset.'))

story.append(PageBreak())
# ---------------- 6 Firmware corrections ----------------
story.append(Paragraph('6. Firmware corrections and verification status', H1))
story.append(tbl([
    ['Fix', 'Validation', 'Status'],
    ['Fixed ISA reference 101325 Pa (baro_proc.c/h); p0 accumulator removed (-32 KB DRAM)',
     'Replay-validated on both elevator runs (bias -0.002/-0.001 m/s match, false lift 16.5/17.5 s -> 0.0/1.2 s); '
     'MCU-validated: 75 s stationary capture silent of sustained lift, no 50 s window',
     'Replay + MCU verified'],
    ['C03 steady-state gain cache (4 dt buckets, 1 ms quantisation)',
     'MCU-validated: 1330 us -> 38 us avg per update (35x); residual max 2676 us is the one-time first refit',
     'MCU verified'],
    ['B-line diagnostic buffer 512 -> 768 bytes',
     'MCU-validated: all 10 per-estimator CPU pairs present in every B-line (was data-dependent truncation)',
     'MCU verified'],
    ['Formal MCU-vs-Python replay equivalence on fixed reference',
     'Pending (task queued; benchmark reference convention uses a constant mean so velocities are unaffected by design)',
     'Not yet verified'],
], [6.2*cm, 8.6*cm, 2.1*cm], fontsize=8))
story.append(Spacer(1, 6))
for e in fig(FIG + 'fig4_on_time.png', width=15.5*cm, caption='Figure 5 - Audio-policy replay, both runs: false-lift ON-time at the floor-1 dwell (left) and total ON-time (right). The ~20 s/run reduction equals the phantom; the ~53-55 s remainder matches the ~49 s of genuine ascent plus ramp.'):
    story.append(e)

# ---------------- 7 Bench validation ----------------
story.append(Paragraph('7. Post-fix bench validation', H1))
story.append(P(
    'The corrected firmware was flashed and a 75 s stationary capture taken '
    '(idf_p0fix_static, 0 seq drops, 0 bad frames). Audio: only short 1-3 s threshold '
    'blips from the fast estimators (expected behaviour near the +0.20 threshold), spread '
    'uniformly across the run - no sustained episodes, and crucially no concentration in '
    'the first 50 s, confirming the moving-reference window is gone. von=3-15 across the '
    'run (startup transient only), vnan=0, abad=0.'))
for e in fig(FIG + 'fig6_bench_validation.png', caption='Figure 6 - Post-fix stationary validation: altitude (fixed reference, absolute) and audio activity. The 50 s warmup window visible in all pre-fix captures is absent.'):
    story.append(e)

# ---------------- 8 CPU ----------------
story.append(Paragraph('8. Per-estimator CPU cost on the ESP32-S3', H1))
story.append(P(
    'B-line accounting (avg/max us per update, ESP32-S3 @ 240 MHz, doubles emulated). '
    'x86 reference numbers from the offline benchmark (results/09_cpu_cost.csv, '
    'results/12_cpu.csv): D01 14.55 us, S4 18.97 us, S5 18.39 us.'))
story.append(tbl([
    ['Estimator', 'Pre-fix avg (elevator run 1)', 'Post-fix avg (bench)', 'x86 reference'],
    ['D01', '52 us', '52 us', '14.6 us'],
    ['C03', '1330 us  <- refit storm', '38 us', 'n/a'],
    ['S4', '94 us', '105 us', '19.0 us'],
    ['S5', '74 us', '98 us', '18.4 us'],
    ['FUS (baro side)', '45 us', '75 us', 'n/a'],
], [3.6*cm, 5*cm, 4.2*cm, 3.6*cm]))
story.append(Spacer(1, 4))
story.append(P(
    'The C03 refit storm: the baro dt is bimodal (20 ms with a 40 ms slot at every '
    'temperature conversion; 25% of samples at 40 ms, measured), C03 refits its steady-state '
    'gains whenever dt drifts >2%, and the 20<->40 ms ping-pong re-ran the 200-iteration '
    'Riccati refit on ~half of all updates. The cache keys gains by 1 ms-quantised dt (4 '
    'slots); each distinct dt refits exactly once. Tick budget: full estimator bank now '
    '~0.4 ms per 5 ms tick (mcyc ~270k cycles). FUS IMU-side propagation cost is not yet '
    'charged to any eid (known accounting gap).', SMALL))
for e in fig(FIG + 'fig5_cpu.png', width=13.5*cm, caption='Figure 7 - Per-estimator update cost before/after the C03 cache fix (log scale).'):
    story.append(e)

# ---------------- 9 Uncertainties ----------------
story.append(Paragraph('9. Remaining uncertainties and limitations', H1))
story.append(P(
    '1. Small residual dwell beeps (median +0.2 m/s, a few short events at the floor-14 '
    'and second floor-1 dwells) are present in both the moving- and fixed-reference '
    'simulations - genuine small estimator wobble, not the p0 artifact. A thermal second-'
    'order contribution (session-long ~0.01 C/s drift through the foam) is plausible but '
    'not separated. Bounded and minor.'))
story.append(P(
    '2. The p0 fix is validated for velocity behaviour; absolute altitude now reads vs ISA '
    'sea level (~380 m at the test site), which is correct and useful, but QNH-style '
    'field calibration is a future option, not a defect.'))
story.append(P(
    '3. The elevator is a proxy for flight. No real flight data exists yet; clone '
    'tempco behaviour in free air (fast adiabatic changes) remains characterised only '
    'on the bench. BMP581 + LSM6DSV16X breakouts are ordered to retire the clone-sensor '
    'risk class.'))
story.append(P(
    '4. Known open issues (parked): USB Serial/JTAG host stalls (random; recover by MCU '
    'restart before a capture), esp_timer racing ~70x during stalls (harmless to clean '
    'segments), FUS IMU-side CPU not charged to an eid. The MCU-vs-Python formal replay '
    'equivalence check on the fixed reference is queued.'))
story.append(P(
    '5. No estimator has been selected or frozen: D01/C03/S4/S5/FUS remain competing '
    'candidates side-by-side, per project constraint.'))

# ---------------- 10 Reproducibility ----------------
story.append(Paragraph('10. Reproducibility', H1))
story.append(tbl([
    ['Artifact', 'Location'],
    ['Report figures', 'analysis/results/_report_figs.py -> fig1-fig7 PNGs'],
    ['Forensic dwell analysis', 'analysis/results/_dwell_forensics.py'],
    ['p0 confirmation sim', 'analysis/results/_p0_confirm.py'],
    ['Elevator leg/audio analysis', 'analysis/results/_elev_analyze.py'],
    ['Raw captures + PROM sidecars', 'analysis/data/20261023_2211*/221420/234521/234944*'],
    ['Firmware (fixes in baro_proc.c/h, estimators.c, bench.c)', 'esp-idf/vario/'],
    ['Defect register / project history', 'docs/defect_register.md / docs/project_history.md'],
    ['Prior phase reports', 'docs/Vario_USB_Engineering_Report_Phases_1-5.pdf; docs/Vario_USB_Technical_Paper.pdf'],
], [6.5*cm, 10.4*cm]))
story.append(Spacer(1, 6))
story.append(P(
    'All numbers in this report are measured or simulated from the committed captures; '
    'scripts regenerate every figure and table from the raw CSV/JSON pairs.', SMALL))

doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=2.2*cm, bottomMargin=2*cm,
                        leftMargin=2*cm, rightMargin=2*cm,
                        title='Vario USB - False-Lift Root Cause & ESP-IDF Firmware Corrections',
                        author='Raghav Malik / Kimi Work')
doc.build(story, onFirstPage=first_page, onLaterPages=hdr_ftr)
print('PDF written:', OUT)
