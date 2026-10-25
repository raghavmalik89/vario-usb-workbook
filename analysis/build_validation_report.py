"""Build reports/Vario_BMP581_LSM6DSV16X_Engineering_Validation.pdf (v2).
Three-regime structure: static / hand+shake / elevator, across three sensor
generations, plus integrated cross-regime filter comparison.
Reuses: dataset integrity CSV, elevator analysis package, Bench 7/6 results,
handshake_regime_analysis.py outputs. No benchmark recomputation.
"""
import csv
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image, PageBreak, KeepTogether)

OUT = 'reports/Vario_BMP581_LSM6DSV16X_Engineering_Validation.pdf'
PKG = 'analysis/external/elevator_225610'
os.makedirs('reports', exist_ok=True)

INK = HexColor('#1a2733')
GREY = HexColor('#5a6a75')
LIGHT = HexColor('#f2f4f6')

styles = getSampleStyleSheet()
styles.add(ParagraphStyle('BodyJ', parent=styles['Normal'], fontName='Helvetica',
                          fontSize=9.5, leading=13.5, alignment=TA_JUSTIFY,
                          textColor=HexColor('#333333'), spaceAfter=5))
styles.add(ParagraphStyle('H1x', parent=styles['Heading1'], fontName='Helvetica-Bold',
                          fontSize=15, leading=19, textColor=INK, spaceBefore=14,
                          spaceAfter=7, keepWithNext=1))
styles.add(ParagraphStyle('H2x', parent=styles['Heading2'], fontName='Helvetica-Bold',
                          fontSize=11.5, leading=15, textColor=INK, spaceBefore=10,
                          spaceAfter=5, keepWithNext=1))
styles.add(ParagraphStyle('Cap', parent=styles['Normal'], fontName='Helvetica-Oblique',
                          fontSize=8.5, leading=11, textColor=GREY, spaceBefore=3,
                          spaceAfter=10, alignment=TA_CENTER))
styles.add(ParagraphStyle('TabCap', parent=styles['Normal'], fontName='Helvetica-Bold',
                          fontSize=9, leading=12, textColor=INK, spaceBefore=8,
                          spaceAfter=3, keepWithNext=1))
styles.add(ParagraphStyle('Cell', parent=styles['Normal'], fontName='Helvetica',
                          fontSize=8, leading=10.5))
styles.add(ParagraphStyle('CellB', parent=styles['Normal'], fontName='Helvetica-Bold',
                          fontSize=8, leading=10.5))
styles.add(ParagraphStyle('Bull', parent=styles['BodyJ'], leftIndent=14,
                          bulletIndent=4, spaceAfter=3))
BULL = '\u2022'


def P(txt, st='BodyJ'):
    return Paragraph(txt, styles[st])


def cap(txt):
    return Paragraph(txt, styles['Cap'])


def tcap(txt):
    return Paragraph(txt, styles['TabCap'])


def tbl(data, colw):
    rows = []
    for i, row in enumerate(data):
        st = 'CellB' if i == 0 else 'Cell'
        rows.append([Paragraph(str(c), styles[st]) for c in row])
    t = Table(rows, colWidths=colw, repeatRows=1)
    t.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 1.2, INK),
        ('LINEBELOW', (0, 0), (-1, 0), 0.6, INK),
        ('LINEBELOW', (0, -1), (-1, -1), 1.2, INK),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), LIGHT]),
    ]))
    return t


def fig(path, w=16.2*cm, caption=''):
    from PIL import Image as PILImage
    iw, ih = PILImage.open(path).size
    h = w * ih / iw
    return [Image(path, width=w, height=h), cap(caption)]


def readcsv(p):
    with open(p, newline='') as f:
        return list(csv.DictReader(f))


def f2(x, nd=2):
    return f'{float(x):.{nd}f}'


def pa_mean(path, t_lo, t_hi):
    """mean pressure Pa (d1/64) within device-time window."""
    ts, ps = [], []
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            if r['type'] != 'P':
                continue
            try:
                t = int(r['t_us'])
                ps.append(int(r['d1']) / 64.0)
                ts.append(t)
            except (ValueError, TypeError):
                pass
    t0 = ts[0]
    sel = [p for t, p in zip(ts, ps) if t_lo <= (t - t0) / 1e6 <= t_hi]
    return sum(sel) / len(sel) if sel else float('nan')


def alt(p_pa):
    return 44330.0 * (1.0 - (p_pa / 101325.0) ** 0.1903)


CW = A4[0] - 5*cm
story = []

# ---------------- static-regime comparison figure ----------------
fig_a, axes = plt.subplots(1, 2, figsize=(10, 3.6))
gens = ['MS5611\n+MPU6050', 'BMP581\n+MPU6050', 'BMP581\n+LSM6DSV16X']
p_lo = [0.42, 0.18, 0.19]
p_mid = [0.45, 0.20, 0.23]
p_hi = [0.48, 0.22, 0.31]
axes[0].bar(gens, p_mid, color=['#8fa3b0', '#5b7a94', '#2f4f6f'],
            width=0.55, yerr=[[m - l for m, l in zip(p_mid, p_lo)],
                              [h - m for h, m in zip(p_hi, p_mid)]],
            capsize=4)
axes[0].set_ylabel('pressure noise (Pa RMS)')
axes[0].set_title('Barometer static noise by generation')
g_lo = [0.4, 0.4, 0.030]
g_mid = [0.5, 0.5, 0.033]
g_hi = [0.9, 0.9, 0.036]
axes[1].bar(gens, g_mid, color=['#8fa3b0', '#5b7a94', '#2f4f6f'],
            width=0.55, yerr=[[m - l for m, l in zip(g_mid, g_lo)],
                              [h - m for h, m in zip(g_hi, g_mid)]],
            capsize=4)
axes[1].set_ylabel('gyro noise (dps)')
axes[1].set_title('IMU gyro noise by generation')
for ax in axes:
    ax.grid(axis='y', alpha=0.3)
    ax.tick_params(labelsize=8)
fig_a.tight_layout()
fig_a.savefig('analysis/output/fig_static_noise_by_generation.png', dpi=150)
plt.close(fig_a)

# static drift from new-era statics
drift_rows = []
for tag, nm in [('20261025_204257_idf_bmp581LSM6DS_static1', 'static1 (96 s)'),
                ('20261025_210221_idf_bmp581LSM6DS_static2', 'static2 (102 s)')]:
    p = f'analysis/data/{tag}.csv'
    if os.path.exists(p):
        a = pa_mean(p, 5, 15)
        b = pa_mean(p, -15, -1)
        drift_rows.append([nm, f'{alt(a):.1f}', f'{alt(b):.1f}',
                           f'{(alt(b) - alt(a)) * 100:.1f}'])

# ---------------- cover ----------------
story.append(Spacer(1, 3.6*cm))
story.append(Paragraph('Vario USB — BMP581 + LSM6DSV16X',
             ParagraphStyle('T1', fontName='Helvetica-Bold', fontSize=23, leading=28,
                            textColor=INK, alignment=TA_CENTER)))
story.append(Spacer(1, 0.5*cm))
story.append(Paragraph('Consolidated Variometer Engineering Validation Report',
             ParagraphStyle('T2', fontName='Helvetica', fontSize=15, leading=20,
                            textColor=GREY, alignment=TA_CENTER)))
story.append(Spacer(1, 0.25*cm))
story.append(Paragraph('Three-regime edition: static — hand/shake — elevator, across three sensor generations',
             ParagraphStyle('T3', fontName='Helvetica-Oblique', fontSize=10.5, leading=14,
                            textColor=GREY, alignment=TA_CENTER)))
story.append(Spacer(1, 1.8*cm))
cover_rows = [
    ['Platform', 'ESP32-S3 @ 240 MHz, ESP-IDF firmware "vario-idf 0.2.0"'],
    ['Barometer', 'Bosch BMP581, I2C bus B (GPIO6/7) @ 0x47, ODR 40 Hz, IIR bypass'],
    ['IMU', 'ST LSM6DSV16X, I2C bus A (GPIO4/5) @ 0x6B, 100 kHz (DEF-020 fix), 240 Hz, +-8 g / +-500 dps'],
    ['Estimators (frozen configs)', 'D01 (CV Kalman), C03 (CV Tracker), S4 (Fast/Slow), S5 (Light Gate), FUS (baro+IMU fusion)'],
    ['Virtual audio policy', 'lift_on +0.20 / lift_off +0.05 m/s, tone 500 + 450*v Hz'],
    ['Principal benchmark', '20261025_225610_idf_bmp581LSM6DS_elevator_2x (180 s, four legs 14->1->14->1->14)'],
    ['Regime coverage', 'Static: 3 generations; hand: MS5611/BMP581/BMP581+LSM; shake: MS5611-era + gap (4 new-era shake captures announced, not yet in workspace)'],
    ['Report date / status', '2026-10-25 (rev. 2) — engineering study, no estimator selected or frozen'],
]
ct = Table([[Paragraph(a, styles['CellB']), Paragraph(b, styles['Cell'])]
            for a, b in cover_rows], colWidths=[4.6*cm, CW-4.6*cm])
ct.setStyle(TableStyle([
    ('LINEABOVE', (0, 0), (-1, 0), 1.2, INK),
    ('LINEBELOW', (0, 0), (-1, 0), 0.6, INK),
    ('LINEBELOW', (0, -1), (-1, -1), 1.2, INK),
    ('TOPPADDING', (0, 0), (-1, -1), 5),
    ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
]))
story.append(ct)
story.append(Spacer(1, 1.4*cm))
story.append(Paragraph(
    'All quantitative statements are either directly measured from recorded telemetry, '
    'pressure-derived reference estimates, or reproduced from the cited frozen-configuration '
    'benchmark phases. Pressure-derived timings are relative comparisons, not absolute '
    'ground-truth latency measurements; no independent ground truth exists in any recording.',
    styles['Cap']))
story.append(PageBreak())

# ---------------- 1 executive summary ----------------
story.append(P('1&nbsp;&nbsp;Executive summary and key findings', 'H1x'))
story.append(P(
    'This report consolidates the Vario USB measurement and benchmark record through the first '
    'fully-validated BMP581 + LSM6DSV16X acquisition, structured as three complementary test '
    'regimes — static sensitivity/stability, hand/shake responsiveness/robustness, and elevator '
    'sustained-motion accuracy — each compared across the three sensor generations '
    '(MS5611+MPU6050, BMP581+MPU6050, BMP581+LSM6DSV16X).'))
for b in [
    '<b>Acquisition integrity is established.</b> The principal elevator recording is flawless: '
    'zero sequence drops, zero malformed lines, zero I2C errors, IMU 100.006 Hz (max gap 11.9 ms, '
    'zero stale frames), baro 40.006 Hz, host/device clock agreement within 0.2 s.',
    '<b>DEF-020 was root-caused and fixed.</b> The ~25 s mid-session IMU death traced to bus A at '
    '400 kHz with only weak (~45 kOhm) internal pull-ups. At 100 kHz: zero IMU errors across 60 s '
    '+ 90 s verification, 100.0 Hz streaming, 0.0 % stale. Note: clean elevator acquisition does '
    'not mean zero errors under all breadboard handling — the 120 s hand test still shows 80 brief '
    'E1 frames (~0.7/s, masked 2.4 %); wiring robustness remains a breadboard-level caveat.',
    '<b>Static regime:</b> baro noise improved 0.42-0.48 Pa (MS5611) to 0.18-0.31 Pa (BMP581, '
    'both IMU eras); gyro noise improved ~0.5 dps to 0.033 dps. Zero false audio ON episodes in '
    'any post-fix static across all candidates (37 configurations, Bench 7).',
    '<b>Hand/shake regime:</b> on the 120 s BMP581+LSM6DSV16X hand test (14 deliberate moves), '
    'D01/C03/S4/S5 each produced exactly 14 audio episodes (zero missed, zero extra); FUS produced '
    '22 (8 extra, 16 brief) with tone peaks to 6.65 m/s — IMU-aided overshoot/chatter under '
    'vigorous motion. Historical hand tests show the same cluster ordering (S1P fastest onset, '
    'D01/C03 mid, all release within ~1 s).',
    '<b>Elevator regime:</b> baro-only estimators are effectively tied — D01/C03 lead audio alert '
    'timing (~0.35-0.45 s after pressure-derived threshold), S4/S5 lag 0.1-0.35 s, plateau '
    'velocities within 0.01 m/s mean of reference; zero false audio on descents/dwells. FUS is '
    'materially worse: +0.20 m/s sustained-climb bias, ~1 s late start, ~5-6 s ON-extension after '
    'floor stops — reproduced on two IMU generations, so it is a fusion-configuration property.',
    '<b>CPU correction vs rev. 1:</b> C03 is cheaper in Python replay (55 vs 131 us/update), but '
    '<b>D01 is cheaper on-target</b> (36/44 us avg/max vs C03 105/132 us). Efficiency is not a '
    'selector either way (worst case 2.6 % of the 5 ms tick).',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText=BULL))
story.append(P(
    'Overall: the hardware path is validated end-to-end. The frozen baro-only cluster '
    '(D01/C03/S4/S5) leads in every regime measured; FUS needs a stop-state / gravity-'
    'compensation review and vibration-rich data before any further fusion complexity. Real-'
    'flight recording remains the decisive open validation. No estimator is selected or frozen.'))

# ---------------- 2 hardware & firmware ----------------
story.append(P('2&nbsp;&nbsp;Hardware and firmware configuration', 'H1x'))
story.append(tcap('Table 1 — Hardware and firmware configuration of record'))
story.append(tbl([
    ['Item', 'Configuration'],
    ['MCU', 'ESP32-S3 (dual-core, 240 MHz), firmware vario-idf 0.2.0, 5 ms sens tick'],
    ['Baro path', 'BMP581 @ 0x47 on bus B (GPIO6/7), 400 kHz, OSR x16 (P) / x2 (T), ODR 40 Hz, IIR bypass, on-chip compensation: Pa = raw24/64'],
    ['IMU path', 'LSM6DSV16X @ 0x6B on bus A (GPIO4/5), 100 kHz (DEF-020 fix; was 400 kHz), ODR 240 Hz, +-8 g / +-500 dps, BDU on, single 14-byte burst read 0x20-0x2D'],
    ['IMU robustness', '3-attempt bounded retry per ST call; runtime recovery FSM (200 ms solid failure -> 100 ms sparse probing; bus reset + reconfigure every 2 s; E-code 3; imu_rec counter)'],
    ['Estimators', 'e0..e4 = D01, C03, S4, S5, FUS, side-by-side per baro sample, frozen configurations (no tuning since Phase 6)'],
    ['Virtual audio', 'Timestamped V frames: ev=1 ON / ev=2 OFF (val = ON duration ms) / ev=3 pitch; policy lift_on +0.20, lift_off +0.05 m/s; tone = 500 + 450*v Hz'],
    ['Telemetry', 'USB-serial CDC @ 921600: P (baro 40 Hz), I (IMU 100 Hz), T (10 Hz), V (audio events), B (5 s diagnostics), E (errors); TX ring 240 KB'],
    ['Legacy rigs', 'MS5611 GY-63 clones x2 (foam-covered) + MPU6050 (Phases 2-6); BMP581 + MPU6050 (Bench 7); gravity axis changed from +X (MPU mount) to -Z (LSM mount)'],
], [3.4*cm, CW-3.4*cm]))
story.append(Spacer(1, 6))

# ---------------- 3 methodology & inventory ----------------
story.append(P('3&nbsp;&nbsp;Test methodology and dataset inventory', 'H1x'))
story.append(P(
    'Methodology follows the programme convention: every frame carries a device timestamp '
    '(esp_timer, 1 us) and a sequence number; all rates are measured from device timestamps, '
    'never assumed. Altitude is ISA pressure-derived (apparent altitude proxy, not surveyed '
    'height). Motion events are detected from a 2 s Savitzky-Golay smoothed pressure-derived '
    'velocity crossing +-0.30 m/s; all onset/exit timings are relative comparisons against this '
    'shared reference — the reference itself has group delay, so absolute sub-second response is '
    'never claimed. Independent ground truth (GPS, optical, elevator controller log) is '
    'unavailable in all recordings. E1/E2 error frames, IMU stale intervals and recovery windows '
    'are masked out of IMU-dependent (FUS) analysis with a +-0.5 s recovery margin; barometric '
    'measurements in the same captures are preserved. Repeated #H/#C metadata blocks during '
    'streaming are an intentional 5 s keepalive, not faults. Shake-test responses to deliberate '
    'vigorous motion are genuine responses, not false alerts, unless contradicted by a motion '
    'reference.'))
story.append(tcap('Table 2 — Dataset inventory and integrity (device-measured). 66 captures in '
                  'analysis/data; representative and flagged rows shown.'))
integ = readcsv('analysis/output/report_dataset_integrity.csv')
keep = [r for r in integ if any(k in r['capture'] for k in [
    '231354_idf_bmp581_static', '233753_idf_bmp581_handtest1',
    '235054_idf_bmp581_elevator', 'static0', 'static1', 'static2',
    'handtest1_120s', 'elevator_2x_200s', 'fixcheck60s', 'fixcheck90s',
    'lsm6dsv_bringup', 'lsm6dsv_bringup9', 't004_elevator_f14',
    't005_ControledMove', 't005_toss', 't006_benchstatic', 'handtest3',
]) and not any(k in r['capture'] for k in ['bringup2', 'bringup3', 'bringup4',
    'bringup5', 'bringup6', 'bringup7', 'bringup8'])]
rows = [['Capture (suffix)', 'Span s', 'P frm', 'I frm', 'E1', 'E2', 'Stale %']]
for r in keep:
    nm = r['capture'].replace('2026', '26').replace('_idf_', ' ')
    rows.append([nm, r['device_span_s'], r['P_frames'], r['I_frames'] or '-',
                 r['E1'], r['E2'], r['imu_stale_pct'] or '-'])
story.append(tbl(rows, [6.6*cm, 1.5*cm, 1.6*cm, 1.6*cm, 1.5*cm, 1.5*cm, 1.9*cm]))
story.append(cap('Table 2 — Full 66-capture table: analysis/output/report_dataset_integrity.csv. '
                 'The operator-reported shake captures of 21:29, 21:35, 21:44 and 22:09 (2026-10-25) '
                 'are announced but NOT present in analysis/data at build time — they are an identified '
                 'data gap (Section 6), not silently excluded.'))
story.append(P(
    'Known exclusions: t004_elevator_run1 lacks a JSON sidecar (PROM constants missing) and is '
    'analysis-excluded; static0 is retained as the DEF-020 fault dataset; bringup1-9 are retained '
    'as DEF-017/018 evidence. Host-side USB backlog affected the Bench 7 elevator capture '
    '(f = 1.11) and static0 (29 s host pause); device-time analysis is unaffected. The 22:56:10 '
    'elevator capture has f = 0.999 (180.33 s host vs 180.11 s device).'))

story.append(PageBreak())

# ---------------- 4 data quality ----------------
story.append(P('4&nbsp;&nbsp;Data quality, interruptions and exclusion masks', 'H1x'))
story.append(P(
    'Three fault classes are tracked per capture: (i) E1/E2/E3 frames — IMU status/burst read '
    'failures and recovery events; (ii) IMU stale reuse — consecutive identical six-axis frames, '
    'the firmware\'s no-data fallback; (iii) host-side backlog — device span exceeding host '
    'elapsed, detected via sidecar stats and TX-ring high-water.'))
story.append(tcap('Table 3 — Fault-class summary by acquisition era'))
story.append(tbl([
    ['Era', 'Captures', 'E1 total', 'E2 total', 'Worst stale %', 'Disposition'],
    ['MS5611 + MPU6050 (Ph 2-6)', '38', '523', '0', '0.16', 'healthy; E1 bursts during development flashes only'],
    ['BMP581 + MPU6050 (Bench 7)', '4', '0', '0', '0.01', 'clean'],
    ['LSM bring-up pre-fix', '9', '6301', '739', '12.35', 'DEF-017/018 evidence (400 kHz + weak pull-ups)'],
    ['static0 (fault dataset)', '1', '15318', '193', '2.12', 'DEF-020 runtime wedge at 25.15 s; IMU dead, baro intact'],
    ['Post-fix 100 kHz era', '6', '80', '0', '0.46', 'elevator/statics clean; handtest1_120s has 80 brief E1 (~0.7/s) during active breadboard handling'],
], [3.6*cm, 1.7*cm, 1.8*cm, 1.8*cm, 2.1*cm, CW-10.0*cm]))
story.append(Spacer(1, 4))
story.append(P(
    '<b>Exclusion policy and sizes.</b> IMU-dependent analysis masks: every +-0.5 s window around '
    'an E1/E2 frame; all recovery intervals (E3 to first fresh sample); stale runs longer than 5 '
    'frames plus a 0.5 s margin. Applied: handtest1_120s masks 2.84 s (2.4 %, one interval after '
    'merging overlaps); all other post-fix captures mask 0.0-0.3 %. Barometric channels are never '
    'masked. The 22:56:10 elevator capture requires no masking at all.'))
story.append(P(
    '<b>Hardware reliability qualification.</b> The clean elevator/statics demonstrate the fix '
    'under stationary rig conditions. The residual ~0.7 E1/s during the hand test correlates with '
    'active handling of a breadboard rig (connector/contact micro-motion); it is masked for '
    'analysis and does not affect barometric data, but it means zero-error operation is not yet '
    'proven under vigorous handling. This is a wiring/build robustness caveat, not a regression.'))

# ---------------- 5 static regime ----------------
story.append(P('5&nbsp;&nbsp;Regime A — Static conditions: sensitivity and stability', 'H1x'))
story.append(P(
    'Statics expose what a vario must do when nothing happens: minimum sensor noise, estimator '
    'velocity stability, slow drift, and absolute audio silence. This regime is the only one '
    'that measures false-activation behaviour with a true zero-motion reference (the rig at '
    'rest), and the only one in which gyro bias/noise can be characterised cleanly.'))
story.extend(fig('analysis/output/fig_static_noise_by_generation.png', w=16.2*cm,
                 caption='Figure 1 — Static noise by sensor generation. Barometer: MS5611 clones 0.42-0.48 Pa RMS; '
                         'BMP581 0.18-0.31 Pa (no dependence on IMU era). Gyro: MPU6050 ~0.4-0.9 dps; LSM6DSV16X 0.033 dps.'))
story.append(tcap('Table 4 — Cross-generation static comparison'))
story.append(tbl([
    ['Quantity', 'MS5611 + MPU6050', 'BMP581 + MPU6050', 'BMP581 + LSM6DSV16X'],
    ['Pressure noise (Pa RMS)', '0.42-0.48', '0.18-0.22', '0.19-0.31'],
    ['Altitude equivalent', '3.4-3.9 cm', '1.5-1.9 cm', '1.5-2.5 cm'],
    ['Estimator velocity noise (static)', 'best 6.3-6.5 mm/s (S1P/S2/S4/S5)', '6.3-6.7 mm/s (S1P/S2/S4/S5/FUS); D01/C03 8.4 mm/s', 'floor-dwell altitude std 1.9-3.2 cm'],
    ['Gyro noise / bias', '~0.4-0.9 dps / small', '~0.4-0.9 dps / small', '0.033 dps / ~0.05-0.12 dps'],
    ['Gravity magnitude check', '1.000 g (foam rig)', '1.000 g', '0.9989-0.9994 g (gravity on -Z axis, new mount)'],
    ['False audio ON (static)', 'pre-DEF-001: moving-reference defect; post-fix: 0', '0 in 90 s (all 37 candidates, Bench 7)', '0 in static0/1/2 + fixchecks (all 5 deployed)'],
], [4.2*cm, (CW-4.2*cm)/3, (CW-4.2*cm)/3, (CW-4.2*cm)/3]))
story.append(Spacer(1, 4))
story.append(tcap('Table 5 — Slow drift, new-era statics (mean apparent altitude, first vs last 10 s)'))
story.append(tbl([['Capture', 'Start alt (m)', 'End alt (m)', 'Drift (cm)']] + drift_rows,
                 [5.2*cm, 3.4*cm, 3.4*cm, CW-12.0*cm]))
story.append(cap('Table 5 — Drift is ordinary ambient pressure change over ~100 s (centimetre-level), not '
                 'sensor fault; the elevator run returned to the starting floor within -0.245 m after two round trips.'))
story.append(P(
    '<b>What static reveals that other regimes cannot:</b> the false-alarm floor (with zero '
    'motion there is no ambiguity about what constitutes a false ON), the noise floor each '
    'filter architecture imposes on its velocity output, and clean IMU bias/noise for fusion '
    'tuning. The ranking implication: S1P/S2/S4/S5-class low-noise architectures hold a small '
    'static-velocity-noise advantage over D01/C03 (6.3-6.5 vs 8.4 mm/s — D01/C03\'s R=0.035 '
    'dominates sensor noise); FUS is competitive at rest (6.7 mm/s) because its IMU aiding is '
    'near-neutral when nothing moves.'))

# ---------------- 6 hand/shake regime ----------------
story.append(P('6&nbsp;&nbsp;Regime B — Hand movement and shake: responsiveness and robustness', 'H1x'))
story.append(P(
    'Hand and shake tests expose the responsiveness/robustness corner: onset and release '
    'timing on repeated lifts/drops, behaviour across rapid direction changes, and chatter '
    'susceptibility under vigorous shaking. They are also the only regime so far that '
    'exercises the IMU under real motion — the fusion value proposition lives or dies here. '
    'No independent motion reference exists, so timings remain relative and deliberate-shake '
    'responses are genuine responses, not false alerts.'))
story.append(P(
    '<b>New-era hand test (BMP581 + LSM6DSV16X, 120 s, 14 deliberate vertical moves by '
    'protocol).</b> Table 6 gives the firmware-reported virtual-audio episodes per estimator '
    '(V frames; 80 brief E1 frames and one stale run masked for the FUS evaluation, 2.4 % of '
    'the record; barometric data retained throughout).'))
hs = readcsv('analysis/output/handshake_lsm_audio_summary.csv')
rows = [['Filter', 'Episodes', 'Startup (t<10 s)', 'Total ON s', 'Mean dur s', 'Max dur s',
         'Brief <1.5 s', 'Tone peak m/s', 'Mean episode peak m/s']]
for r in hs:
    rows.append([r['estimator'], r['episodes'], r['startup_episodes_t0_10s'],
                 f2(r['total_on_s']), f2(r['mean_dur_s']), f2(r['max_dur_s']),
                 r['brief_lt_1p5s'], f2(r['tone_peak_mps']), f2(r['tone_mean_peak_mps'])])
story.append(tcap('Table 6 — Audio episodes per estimator, handtest1_120s (14 deliberate moves)'))
story.append(tbl(rows, [1.7*cm, 1.6*cm, 2.1*cm, 1.8*cm, 1.8*cm, 1.7*cm, 1.7*cm, 1.9*cm, CW-15.3*cm]))
story.append(cap('Table 6 — All four baro-only estimators: exactly 14 episodes (one per deliberate move; zero '
                 'missed, zero extra). FUS: 22 episodes (8 extra, 16 brief <1.5 s) and tone peaks of 6.65 m/s '
                 'against 1.44-1.55 m/s for baro-only — IMU-aided overshoot/chatter under vigorous motion. '
                 'No startup false ONs in the first 10 s for any estimator in this capture.'))
story.extend(fig('analysis/output/fig_handshake_audio_timeline.png', w=16.2*cm,
                 caption='Figure 2 — Audio ON episodes per estimator over the 120 s hand test. The four baro-only '
                         'tracks are near-identical; FUS fragments into brief repeated episodes.'))
story.append(tcap('Table 7 — Historical hand-test audio behaviour (Bench 7, BMP581 + MPU6050, 17 detected events + 1 slow block)'))
story.append(tbl([
    ['Candidate', 'Onset med (s)', 'Release med (s)', 'Slow-block audio ON frac', 'Slow bias (m/s)', 'Static RMS in-test'],
    ['D01/C03', '2.10', '1.00', '0.431', '+0.031', '0.0057'],
    ['S1P', '-0.91', '0.33', '0.146', '-0.097', '0.0036'],
    ['S4', '2.20', '0.58', '0.438', '-0.015', '0.0037'],
    ['S5', '2.25', '0.43', '0.426', '+0.011', '0.0037'],
], [3.0*cm, 2.4*cm, 2.4*cm, 3.6*cm, 2.4*cm, CW-13.8*cm]))
story.append(cap('Table 7 — Onset/release relative to the pressure-derived reference. The slow block '
                 '(61.9-129.8 s) is the thermalling-regime proxy: S1P tracks it without latching audio '
                 '(ON frac 0.146) while D01/C03/S4/S5 hold audio ON ~43 % of the block — a deliberate '
                 'design trade (chatter immunity vs slow-motion persistence), not a defect.'))
story.append(P(
    '<b>Shake subtests.</b> MS5611-era toss and drop captures (t005_toss 45 s, t006/t007 drops) '
    'provided the historical shake evidence used in Phases 4-6 failure-mode analysis: all '
    'leading candidates recovered without latch-up after tosses and drops; S3 showed its '
    'documented dwell-wobble failure and S2 its freeze-trap behaviour (both retained as labelled '
    'defect references). <b>Data gap:</b> the four new-era shake captures recorded at 21:29, '
    '21:35, 21:44 and 22:09 on 2026-10-25 are not present in the workspace at build time, so a '
    'quantitative new-generation shake comparison (FUS tone overshoot under vigorous shaking, '
    'recovery after impact) cannot yet be tabulated. They are the first priority for the next '
    'analysis pass; nothing in this section silently assumes them.'))
story.append(P(
    '<b>Fault tolerance, reported separately.</b> Communication-layer faults during this regime '
    'are wiring/build related (DEF-017/020 class): 80 brief E1 frames during active handling vs '
    'zero during stationary captures, all absorbed by retry/stale-reuse, none reaching the '
    'estimators as corrupt data. They degrade gracefully and are masked for evaluation; they are '
    'not estimator robustness and should not be scored as such.'))
story.append(P(
    '<b>What hand/shake reveals that other regimes cannot:</b> onset/release speed on real '
    'abrupt motion, chatter susceptibility (brief-episode counts), IMU-aided behaviour under '
    'motion — the only evidence bearing on the fusion value proposition — and graceful-fault '
    'behaviour under handling.'))

story.append(PageBreak())

# ---------------- 7 elevator regime ----------------
story.append(P('7&nbsp;&nbsp;Regime C — Elevator: accuracy and sustained-motion behaviour', 'H1x'))
story.append(P(
    'The elevator is the controlled sustained-motion reference: four ~39.4 m legs at '
    '-1.736/-1.738 and +1.670/+1.669 m/s with stationary dwells at both ends. It is the only '
    'regime that measures sustained-velocity bias, plateau tracking error, stop settling and '
    'floor-dwell silence at realistic vario speeds.'))
story.append(P(
    'Recording 20261025_225610_idf_bmp581LSM6DS_elevator_2x_200s: 18,012 IMU frames (100.006 Hz, '
    'max interval 11.9 ms, zero stale), 7,205 baro frames (40.006 Hz, max 27.2 ms), 695 V frames, '
    'no TX overflow, max sensor tick 6.65 ms (budget 10.5 ms), all B windows vnan=0 / vfault=0. '
    'Host 180.33 s vs device 180.11 s — no backlog. File name says 200 s; device span 180.1 s.'))
legs = readcsv(f'{PKG}/elevator_225610_leg_metrics.csv')
rows = [['Leg', 'Direction', 'Start s', 'Stop s', 'Duration s', 'Plateau mean m/s', 'Plateau std', 'Step m']]
for r in legs:
    rows.append([r['leg'], r['direction'], f2(r['start_s'], 1), f2(r['stop_s'], 1),
                 f2(r['duration_s'], 1), f2(r['plateau_mean_mps'], 3), f2(r['plateau_std_mps'], 3),
                 f2(r['endpoint_height_m'], 1)])
story.append(tcap('Table 8 — Measured legs (pressure-derived reference, +-0.30 m/s threshold)'))
story.append(tbl(rows, [1.0*cm, 2.0*cm, 1.8*cm, 1.8*cm, 2.0*cm, 3.0*cm, 2.2*cm, CW-13.8*cm]))
story.append(cap('Table 8 — Leg-to-leg repeatability: plateau means agree within 0.004 m/s, durations within 0.43 s.'))
story.extend(fig(f'{PKG}/elevator_225610_altitude_legs.png',
                 caption='Figure 3 — Four floor-to-floor legs, ISA-derived altitude.'))
story.extend(fig(f'{PKG}/elevator_225610_velocity_reference.png',
                 caption='Figure 4 — Pressure-derived vertical-velocity reference (2 s Savitzky-Golay). Shared by all timing comparisons.'))
dwells = readcsv(f'{PKG}/elevator_225610_floor_dwell_metrics.csv')
rows = [['Floor dwell', 'Window s', 'Mean h (m)', 'h std (m)', 'Noise Pa RMS']]
for r in dwells:
    rows.append([r['floor'], f"{f2(r['start_s'],0)}-{f2(r['end_s'],0)}", f2(r['mean_h_m'],2),
                 f2(r['std_h_m'],3), f2(r['noise_pa'],3)])
story.append(tcap('Table 9 — Stationary floor dwells'))
story.append(tbl(rows, [3.2*cm, 2.6*cm, 2.6*cm, 2.2*cm, CW-10.6*cm]))
story.append(cap('Table 9 — Altitude std 1.9-3.2 cm during dwells; noise 0.187-0.219 Pa RMS.'))
story.append(P(
    '<b>Transitions.</b> IMU specific-force projection shows clean acceleration/deceleration '
    'events at every leg start and stop (Figure 7), independently confirming the motion '
    'timeline. Settling after floor stops: baro-only estimators return below 0.05 m/s residual '
    'within ~2-3 s; FUS takes 5-6 s (its audio hangs correspondingly longer).'))

story.append(PageBreak())

story.append(tcap('Table 10 — Virtual-audio episodes, 22:56:10 elevator (relative to pressure-derived threshold)'))
aud = readcsv(f'{PKG}/elevator_225610_audio_events_summary.csv')
rows = [['Filter', 'Ascent', 'ON s', 'OFF s', 'ON dur s', 'ON lag s', 'OFF lag s']]
for r in aud:
    rows.append([r['filter'], r['ascent'], f2(r['on_s'],2), f2(r['off_s'],2),
                 f2(r['on_duration_s'],2), f2(r['on_lag_to_pressure_threshold_s'],2),
                 f2(r['off_lag_to_pressure_threshold_s'],2)])
story.append(tbl(rows, [1.9*cm, 1.4*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.8*cm, CW-11.8*cm]))
story.append(cap('Table 10 — Two intended ON episodes per estimator, exclusively on ascents; zero extra episodes '
                 'on descents or dwells. OFF lag includes policy hysteresis and reference group delay — relative only.'))
story.extend(fig(f'{PKG}/elevator_225610_audio_gates.png',
                 caption='Figure 5 — Audio ON/OFF episodes for all five estimators against the motion reference.'))
tv = readcsv(f'{PKG}/elevator_225610_tone_velocity_metrics.csv')
rows = [['Filter', 'Ascent', 'Tone mean m/s', 'Ref mean m/s', 'Mean diff m/s', 'MAE m/s']]
for r in tv:
    rows.append([r['filter'], r['ascent'], f2(r['tone_derived_mean_mps'],3),
                 f2(r['pressure_ref_mean_mps'],3), f2(r['mean_difference_mps'],3),
                 f2(r['MAE_mps'],3)])
story.append(tcap('Table 11 — Tone-coded plateau velocity vs pressure reference'))
story.append(tbl(rows, [1.9*cm, 1.4*cm, 2.6*cm, 2.6*cm, 2.6*cm, CW-11.1*cm]))
story.append(cap('Table 11 — Baro-only agrees with the reference to 0.011 m/s mean (MAE 0.057-0.072); '
                 'FUS reads +0.20 m/s high on both ascents.'))
story.extend(fig(f'{PKG}/elevator_225610_tone_velocity_vs_pressure.png',
                 caption='Figure 6 — Tone-derived velocity vs pressure proxy, both ascents. FUS plateau sits ~12 % high.'))
story.append(P(
    '<b>The FUS +0.20 m/s bias, stated objectively.</b> The same-signed bias (+0.20 ascent / '
    '-0.25 descent in Bench 7, +0.201/+0.205 in the 22:56 tone reconstruction) appears on two '
    'different IMUs (MPU6050 and LSM6DSV16X), two baro sensors (MS5611 and BMP581) and both '
    'elevator buildings. Acquisition-layer defects are therefore excluded by replication. The '
    'bias is present only while IMU aiding is active during sustained acceleration, scales with '
    'the motion direction, and co-occurs with the late start and long exit: it is a property of '
    'the fusion configuration (plausibly the gravity-compensation/convergence state and the '
    'accel weighting during near-constant-velocity legs), not of any sensor. Hypotheses and '
    'possible improvements are in Section 12; no firmware change was made.'))
story.extend(fig(f'{PKG}/elevator_225610_imu_acceleration.png',
                 caption='Figure 7 — IMU specific-force projection (rest axis) vs pressure proxy: clean accel/decel '
                         'events at every transition, independently confirming the motion timeline.'))
story.append(P(
    '<b>What the elevator reveals that other regimes cannot:</b> sustained-velocity bias and '
    'plateau accuracy (impossible to judge from seconds-long hand moves), stop settling and '
    'OFF-delay discipline at realistic speeds, and dwell silence over minute-scale windows.'))

# ---------------- 8 integrated cross-regime ----------------
story.append(P('8&nbsp;&nbsp;Integrated cross-regime filter comparison', 'H1x'))
story.append(P(
    'M = measured (this report / cited benchmarks); Q = qualitative judgement. Blank = no '
    'reliable measurement available. Values are regime-representative, not single-capture noise.'))
story.append(tcap('Table 12 — Cross-regime summary, five deployed estimators'))
story.append(tbl([
    ['Criterion', 'D01', 'C03', 'S4', 'S5', 'FUS'],
    ['Static velocity noise (mm/s RMS)', '8.4 M', '8.4 M', '6.5 M', '6.3 M', '6.7 M'],
    ['False audio in static', '0 M', '0 M', '0 M', '0 M', '0 M (startup ONs seen on some captures) M'],
    ['Hand onset vs D01 (s)', '0 (ref) M', '0 M', '+0.1-0.15 Q', '+0.1-0.15 Q', 'fragmented; extra episodes M'],
    ['Hand missed/extra episodes (14 moves)', '0/0 M', '0/0 M', '0/0 M', '0/0 M', '0/8 M'],
    ['Shake robustness (new era)', 'no capture yet', 'no capture yet', 'no capture yet', 'no capture yet', 'no capture yet — gap'],
    ['Slow-block audio ON frac (Bench 7)', '0.43 M', '0.43 M', '0.44 M', '0.43 M', 'n/a'],
    ['Elevator rise vs D01 (s)', '0 (ref) M', '0 M', '+0.10-0.12 M', '+0.15-0.25 M', '+0.40-0.73 M'],
    ['Elevator plateau mean error (m/s)', '-0.004 M', '-0.011 M', '-0.008 M', '-0.007 M', '+0.201 M'],
    ['Elevator OFF lag vs D01 (s)', '0 (ref) M', '0 M', '+0.25-0.33 M', '+0.25-0.33 M', '+5.5-5.7 M'],
    ['Fault tolerance (masked E1, handling)', 'unaffected M', 'unaffected M', 'unaffected M', 'unaffected M', 'unaffected after masking M'],
    ['CPU: on-target avg/max (us)', '36/44 M', '105/132 M', '97/101 M', '77/80 M', '33/37 M (baro side)'],
    ['CPU: Python replay (us/update)', '131 M', '55 M', '-', '-', '-'],
], [4.6*cm] + [(CW-4.6*cm)/5]*5))
story.append(cap('Table 12 — D01 and C03 are one architecture (algebraically near-identical after gain '
                 'settling; Section 9). "Shake robustness (new era)" is an identified data gap — the four '
                 'announced shake captures are not in the workspace at build time.'))
story.append(P(
    '<b>No winner is selected.</b> The measured evidence says: in every regime so far, the '
    'baro-only cluster matches or beats FUS; within the cluster, D01/C03 trade a slightly '
    'higher static noise floor for the fastest alerts and simplest structure, S4/S5 trade '
    'alert latency for a lower static floor. Which trade matters is a flight-data question.'))

# ---------------- 9 equivalence + cpu ----------------
story.append(P('9&nbsp;&nbsp;MCU replay equivalence and CPU cost', 'H1x'))
story.append(tcap('Table 13 — MCU vs Python-replay audio equivalence (Bench 7)'))
story.append(tbl([
    ['Estimator', 'Elevator episodes MCU/py', 'Handtest episodes', 'max |dT_on|', 'max |dT_off|'],
    ['D01', '2 / 2', '16 / 16', '0.000 s', '0.000 s'],
    ['C03', '2 / 2', '16 / 16', '0.025 s', '0.025 s'],
    ['S4', '2 / 2', '16 / 16', '0.000 s', '0.000-0.075 s'],
    ['S5', '2 / 2', '16 / 16', '0.000 s', '0.000 s'],
    ['FUS', '4 / 4', '19 / 19', '0.075 s', '0.100 s'],
], [2.4*cm, 4.4*cm, 3.2*cm, 2.2*cm, CW-12.2*cm]))
story.append(cap('Table 13 — Replay reproduces every MCU episode within 1-4 baro samples. FUS\'s two extra '
                 'start-up ON episodes (t = 5-12 s) are genuine estimator behaviour, reproduced in replay.'))
story.append(P(
    'The D01/C03 identical timestamps are mathematical, not a wiring defect: C03 is the '
    'steady-state-gain CV tracker of the same model D01\'s time-varying Kalman converges to; '
    'max |dv| is 0.087-0.151 m/s only during abrupt hand motion. Ranking consequence: D01 and '
    'C03 are one architecture — the choice between them is an implementation-cost choice, and '
    'the cost picture is platform-dependent: <b>C03 is 2.4x cheaper in Python replay (55 vs '
    '131 us/update), while D01 is ~3x cheaper on-target (36/44 vs 105/132 us avg/max)</b>. '
    'Either way the worst case is 2.6 % of the 5 ms tick — efficiency is not a selector.'))
story.append(tcap('Table 14 — On-target CPU cost (ESP32-S3 240 MHz, medians from B-line telemetry, post-DEF-002 build)'))
story.append(tbl([
    ['Estimator', 'sid0 avg/max us', 'sid1 avg/max us', 'Tick budget share'],
    ['D01 (cheapest on-target)', '36 / 44', '27 / 37', '0.7 %'],
    ['FUS (baro side; IMU side uncharged — DEF-009)', '33 / 37', '-', '0.7 %'],
    ['S5', '77 / 80', '59 / 88', '1.6 %'],
    ['S4', '97 / 101', '69 / 82', '2.0 %'],
    ['C03 (cheapest in replay)', '105 / 132', '78 / 102', '2.6 %'],
], [5.2*cm, 5.6*cm, 3.4*cm, CW-14.2*cm]))
story.append(cap('Table 14 — Host-replay costs for all 37 candidates: filter_benchmark/results/63_cpu_host.csv.'))

story.append(PageBreak())

# ---------------- 10 historical comparison ----------------
story.append(P('10&nbsp;&nbsp;Historical filter-benchmark comparison (Phases 2-7)', 'H1x'))
story.append(P(
    'Phase 6 (MS5611 + MPU6050, 37 frozen candidates, corrected DEF-014 scoring) composite '
    'top-5: <b>C03, C01, B02_project_kalman, E06, S2</b>; S4 7th, S1 8th, D01 9th, S5 12th, FUS '
    '21st (FUS_Q10 20th). Phase-to-phase changes were driven by defect fixes, not filter drift: '
    'D01\'s rest floor "improved" 0.101 -> 0.057 m/s once the moving-reference defect (DEF-001) '
    'stopped being attributed to it; C03\'s refit storm (DEF-002) fix removed its Phase-2/3 CPU '
    'penalty; S1\'s real +0.63 m/s slow-descent bias (a thermalling-regime false-lift) was '
    'exposed only after the phantom-event scoring artifact (DEF-014) was removed. S2 ranks 5th '
    'despite its documented freeze-trap architecture defect — ranking position is not endorsement.'))
story.append(tcap('Table 15 — Bench 7 (BMP581 + MPU6050) sustained-motion results, median over legs'))
story.append(tbl([
    ['Candidate', 'Rise (s)', 'Exit (s)', 'Leg RMS (m/s)', 'Ascent bias', 'Descent bias'],
    ['C03 / D01', '1.26', '3.89', '0.068', '+0.001', '-0.008'],
    ['S1P', '1.31', '2.11', '0.068', '+0.001', '-0.006'],
    ['S4', '1.36', '2.11', '0.072', '+0.001', '-0.008'],
    ['S5', '1.36', '3.08', '0.069', '+0.001', '-0.007'],
    ['S2 (defect ref)', '1.36', '2.11', '0.072', '+0.001', '-0.008'],
    ['S3 (defect ref)', '0.53', '6.61', '0.139', '-0.001', '+0.016'],
    ['FUS', '1.80', '7.44', '0.243', '+0.201', '-0.250'],
    ['FUS_Q10 (exploratory)', '1.14', '4.43', '0.105', '+0.061', '-0.091'],
], [3.6*cm, 1.8*cm, 1.8*cm, 2.6*cm, 2.2*cm, CW-11.0*cm]))
story.append(cap('Table 15 — Audio correctness: every baro-only candidate 0 missed lifts, 0 false audio '
                 'seconds; FUS added 2 start-up false ONs and ~5-6 s ON-extensions after top-floor stops.'))
story.append(P(
    '<b>Cross-generation stability of conclusions.</b> (1) The baro-only cluster\'s relative '
    'ordering replicates on BMP581+LSM6DSV16X data — the ranking is hardware-independent. '
    '(2) FUS\'s bias/late-start/long-exit pattern reproduces within ~0.05 m/s on different IMU '
    'hardware — the problem is fusion configuration, not the MPU6050. (3) The DEF-020 fix removed '
    'the only acquisition-layer objection to the new hardware; no ranking-level change is '
    'attributable to sensor swaps for baro-only candidates.'))

# ---------------- 11 audio & pilot ----------------
story.append(P('11&nbsp;&nbsp;Audio behaviour and pilot experience', 'H1x'))
for b in [
    'Static: absolute silence from all candidates in every post-fix static — the false-lift '
    'defect class (DEF-001) stays fixed; FUS start-up ONs seen on some historical captures did '
    'not recur in the new-era statics/handtest.',
    'Hand moves: all four baro-only candidates announce every deliberate move once (14/14) with '
    'clean single episodes (mean 1.43-1.51 s, matching the motion); S4/S5 are fractionally more '
    'chatter-prone historically (Table 7 slow block). FUS fragments (22 episodes, 16 brief) and '
    'over-pitches (6.65 m/s peaks) — it would feel nervous and exaggerated in the hand.',
    'Elevator: prompt climb announcement (D01/C03 0.35-0.45 s after threshold; S4/S5 up to ~0.6 s), '
    'accurate tone through the leg, shut-off 1.4-2.0 s after floor arrival for baro-only; FUS '
    'hangs 5-6 s — the single most pilot-visible defect on this dataset.',
    'Tone fidelity: baro-only tone tracks sustained climb within ~0.01 m/s mean; FUS over-pitches '
    '~12 %.',
    'The 5 s metadata keepalive never produces audio artifacts (V frames are estimator-driven only).',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText=BULL))

# ---------------- 12 FUS limitations ----------------
story.append(P('12&nbsp;&nbsp;FUS limitations and possible improvements', 'H1x'))
story.append(P(
    '<b>Measured, across all three regimes.</b> Static: 0 false ONs in the new era, 6.7 mm/s '
    'velocity noise (competitive). Hand/shake: 8 extra episodes in 14 moves, 16 brief, tone '
    'overshoot to 6.65 m/s (baro-only 1.44-1.55). Elevator: +0.20/-0.25 m/s sustained bias, '
    '3.6x leg RMS, slowest rise, ~7 s exit, 5-6 s post-stop audio extension; two start-up false '
    'ONs historically (attitude/bias convergence, t = 5-12 s). FUS_Q10 (labelled exploratory, '
    'Phase 5) improves every elevator column but remains worse than all baro-only candidates.'))
story.append(P(
    '<b>Plausible causes (hypotheses, unvalidated — no firmware changes made).</b> (i) Gravity-'
    'compensation/attitude state converges slowly from cold start and drifts during long '
    'constant-velocity legs, folding specific-force error into climb rate (matches the bias sign '
    'reversal between climb and descent, and the cold-start false ONs); (ii) IMU-aided state is '
    'not faded when the baro innovation says the air is clean — in vibration-free data the '
    'accelerometer adds only bias, so fusion should degrade to baro-only but the current gains '
    'keep trusting it (matches hand-test overshoot); (iii) the audio OFF path reads the fused '
    'state without a dwell-stable floor (matches the post-stop extension). The decisive '
    'experiment is vibration-rich data (flight or the pending shake captures): hypothesis (ii) '
    'predicts FUS should at least match baro-only in turbulence; if it does not, the fusion '
    'structure itself needs rework (adaptive gain scheduling, baro-innovation gating, explicit '
    'stationary reset).'))

# ---------------- 13 conclusions ----------------
story.append(P('13&nbsp;&nbsp;Conclusions, recommendations and next validation steps', 'H1x'))
for b in [
    '<b>Acquisition layer: validated</b> (40.006 / 100.006 Hz, zero errors on the principal '
    'benchmarks). Keep Bus A at 100 kHz; external 2.2 kOhm pull-ups are optional future '
    'headroom. Breadboard handling still produces ~0.7 brief E1/s — a wiring-robustness caveat, '
    'not a regression.',
    '<b>Baro-only cluster: still leading, still frozen.</b> D01/C03 fastest alerts; S4/S5 lowest '
    'static floor; all four effectively tied on elevator accuracy and perfectly clean on hand '
    'moves and statics. Carry all four into flight evaluation; do not down-select yet.',
    '<b>D01 vs C03:</b> one architecture; C03 wins in Python replay, D01 wins on-target. Decision '
    'can wait for flight data.',
    '<b>FUS: hold.</b> No new fusion complexity; first run the shake captures (data gap) and a '
    'stop-state review. Current evidence says fusion harms quiet-air performance in every regime '
    'measured.',
    '<b>Next steps, in order:</b> (1) supply/copy the 21:29/21:35/21:44/22:09 shake captures and '
    'run the regime-B shake comparison; (2) Bench 8 frozen-config replay over the new-era hand + '
    'elevator captures; (3) real-flight recording with the same protocol; (4) only then consider '
    'leakage-controlled tuning.',
    '<b>Standing limitations:</b> no independent ground truth in any recording; all sub-second '
    'timings are pressure-proxy-relative; static/hand/elevator data cannot certify flight '
    'behaviour; new-generation shake data missing; S2 retained as labelled defect reference; '
    'no estimator is frozen by this report.',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText=BULL))
story.append(Spacer(1, 8))
story.append(P(
    'Reproducibility: dataset integrity — analysis/report_collect_integrity.py; hand/shake audio '
    'analysis — analysis/handshake_regime_analysis.py; elevator analysis package — '
    'analysis/external/elevator_225610/; frozen-config benchmarks — filter_benchmark/results/ and '
    'filter_benchmark/reports/; this PDF — analysis/build_validation_report.py; firmware of '
    'record — esp-idf/vario/ @ local commit dee9c1a (not pushed).', 'Cap'))


def hf(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2.5*cm, h - 1.5*cm,
                      'Vario USB — BMP581 + LSM6DSV16X Engineering Validation (three-regime edition)')
    canvas.drawRightString(w - 2.5*cm, h - 1.5*cm, '2026-10-25')
    canvas.setStrokeColor(HexColor('#c8d0d6'))
    canvas.setLineWidth(0.5)
    canvas.line(2.5*cm, h - 1.7*cm, w - 2.5*cm, h - 1.7*cm)
    canvas.drawCentredString(w / 2, 1.4*cm, f'Page {doc.page}')
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=2.3*cm, bottomMargin=2.2*cm,
                        leftMargin=2.5*cm, rightMargin=2.5*cm,
                        title='Vario USB BMP581+LSM6DSV16X Engineering Validation (three-regime)',
                        author='Vario USB project')
doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=hf)
print('built', OUT)
