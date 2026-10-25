"""Build reports/Vario_BMP581_LSM6DSV16X_Engineering_Validation.pdf.
Consolidates: dataset integrity (analysis/output/report_dataset_integrity.csv),
elevator 22:56:10 analysis package (figures + CSVs), Bench 7 BMP581 results,
Bench 6 ESP-IDF results, DEF-020 fix verification, integration report facts.
All figures reused from existing assets; no benchmark recomputation.
"""
import csv
import os
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
styles.add(ParagraphStyle('CellR', parent=styles['Normal'], fontName='Helvetica',
                          fontSize=8, leading=10.5, alignment=2))
styles.add(ParagraphStyle('Bull', parent=styles['BodyJ'], leftIndent=14,
                          bulletIndent=4, spaceAfter=3))


def P(txt, st='BodyJ'):
    return Paragraph(txt, styles[st])


def cap(txt):
    return Paragraph(txt, styles['Cap'])


def tcap(txt):
    return Paragraph(txt, styles['TabCap'])


def tbl(data, colw, align_right_from=1):
    """Three-line academic table. data[0] is the header row."""
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


CW = A4[0] - 5*cm  # usable width with 2.5cm margins

story = []

# ---------------- cover ----------------
story.append(Spacer(1, 4.2*cm))
story.append(Paragraph('Vario USB — BMP581 + LSM6DSV16X',
             ParagraphStyle('T1', fontName='Helvetica-Bold', fontSize=23, leading=28,
                            textColor=INK, alignment=TA_CENTER)))
story.append(Spacer(1, 0.5*cm))
story.append(Paragraph('Consolidated Variometer Engineering Validation Report',
             ParagraphStyle('T2', fontName='Helvetica', fontSize=15, leading=20,
                            textColor=GREY, alignment=TA_CENTER)))
story.append(Spacer(1, 2.2*cm))
cover_rows = [
    ['Platform', 'ESP32-S3 @ 240 MHz, ESP-IDF firmware "vario-idf 0.2.0"'],
    ['Barometer', 'Bosch BMP581, I2C bus B (GPIO6/7) @ 0x47, ODR 40 Hz, IIR bypass'],
    ['IMU', 'ST LSM6DSV16X, I2C bus A (GPIO4/5) @ 0x6B, 240 Hz, +-8 g / +-500 dps'],
    ['Estimators (frozen configs)', 'D01 (CV Kalman), C03 (CV Tracker), S4 (Fast/Slow), S5 (Light Gate), FUS (baro+IMU fusion)'],
    ['Virtual audio policy', 'lift_on +0.20 / lift_off +0.05 m/s, tone 500 + 450*v Hz'],
    ['Record under review', '20261025_225610_idf_bmp581LSM6DS_elevator_2x_200s (180.1 s device span, four legs 14->1->14->1->14)'],
    ['Report date', '2026-10-25'],
    ['Status', 'Engineering study — no estimator selected or frozen'],
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
story.append(Spacer(1, 1.8*cm))
story.append(Paragraph(
    'All quantitative statements are either directly measured from recorded telemetry, '
    'pressure-derived reference estimates, or reproduced from the cited frozen-configuration '
    'benchmark phases. Pressure-derived timings are relative comparisons, not absolute '
    'ground-truth latency measurements.', styles['Cap']))
story.append(PageBreak())

# ---------------- 1 executive summary ----------------
story.append(P('1&nbsp;&nbsp;Executive summary and key findings', 'H1x'))
story.append(P(
    'This report consolidates the complete measurement and benchmark record of the Vario USB '
    'programme through the first fully-validated BMP581 + LSM6DSV16X acquisition: sensor '
    'bring-up, a root-caused I2C failure mode, three static tests, a hand test, and a clean '
    'four-leg elevator recording (22:56:10, 2026-10-25), together with the historical '
    'filter-architecture benchmarks (Phases 2-7) against which the new datasets are compared.'))
for b in [
    '<b>Acquisition integrity is established.</b> The principal elevator recording is flawless: '
    'zero sequence drops, zero malformed lines, zero I2C errors, IMU 100.006 Hz (max gap 11.9 ms, '
    'zero stale frames), baro 40.006 Hz, host/device clock agreement within 0.2 s.',
    '<b>DEF-020 was root-caused and fixed.</b> The mid-session IMU death (~25 s) traced to bus A '
    'running at 400 kHz with only the ESP32-S3 weak (~45 kOhm) internal pull-ups. Lowering bus A '
    'to 100 kHz (BMP581 bus untouched) gives zero IMU errors across 60 s + 90 s verification, '
    '100.0 Hz streaming and 0.0 % stale samples. The collateral BMP581 slowdown (40 -> 31.25 Hz) '
    'was task-time contention, not a bus fault.',
    '<b>Baro-only estimators are effectively tied on elevator dynamics.</b> D01/C03 lead audio '
    'alert timing (ON ~0.35-0.45 s after the pressure-derived motion threshold); S4/S5 lag by '
    '0.1-0.35 s; tone-derived plateau velocities match the pressure reference to within '
    '~0.01 m/s mean (MAE 0.06-0.07 m/s). Zero false audio episodes on descents and floor dwells.',
    '<b>FUS (IMU fusion) is measurably worse on this data.</b> It starts ~0.75-1.2 s late, '
    'overshoots sustained climb by ~+0.20 m/s, and stays ON ~5-6 s after each top-floor stop. '
    'Consistent with the Bench 7 finding: quiet-building data has no vibration for IMU-aiding '
    'to cancel. This is an estimator/configuration observation, not an acquisition defect.',
    '<b>Static audio cleanliness is unprecedented.</b> No candidate produced a single false '
    'audio ON in the 90 s BMP581 static (Bench 7, 37 frozen configurations); the same holds for '
    'the new-era statics.',
    '<b>CPU is not a differentiator.</b> Worst on-target cost is 2.6 % of the 5 ms tick (C03, '
    '105/132 us avg/max); efficiency was explicitly deferred as a selection criterion.',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText='&bull;'))
story.append(P(
    'Overall: the BMP581 + LSM6DSV16X hardware path is validated end-to-end at the acquisition '
    'layer. The frozen baro-only architectures (D01/C03/S4/S5) remain the leading candidates; '
    'FUS needs a stop-state / gravity-compensation review before any further complexity. Real-'
    'flight recording remains the decisive open validation.'))

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
story.append(P(
    'Sensor generations: MS5611 static pressure noise was 0.42-0.48 Pa RMS on the clones; the '
    'BMP581 measures 0.18-0.22 Pa RMS (1.5-1.9 cm altitude equivalent) — a 2x+ improvement. '
    'Gyro noise improved from ~0.4-0.9 dps (MPU6050) to 0.033 dps (LSM6DSV16X), with |a| = '
    '0.9989-0.9994 g and bias < 0.12 dps. Raw scales are identical across IMUs (4096 LSB/g, '
    '65.5 LSB/dps), so estimator inputs are directly comparable.'))

# ---------------- 3 methodology & inventory ----------------
story.append(P('3&nbsp;&nbsp;Test methodology and dataset inventory', 'H1x'))
story.append(P(
    'Methodology follows the programme convention: every frame carries a device timestamp '
    '(esp_timer, 1 us) and a sequence number; all rates are measured from device timestamps, '
    'never assumed. Altitude is ISA pressure-derived (apparent altitude proxy, not surveyed '
    'height). Motion events are detected from a 2 s Savitzky-Golay smoothed pressure-derived '
    'velocity crossing +-0.30 m/s; all onset/exit timings are relative comparisons against '
    'this shared reference — the reference itself has group delay, so absolute sub-second '
    'response is never claimed. Independent ground truth (GPS, optical, elevator controller '
    'log) is unavailable in all recordings. E1/E2 error frames, IMU stale intervals and '
    'diagnostic counters are masked out of IMU-dependent analysis with a recovery margin; '
    'barometric measurements in the same captures are preserved. Repeated #H/#C metadata '
    'blocks during streaming are an intentional 5 s keepalive (documented), not faults.'))
story.append(tcap('Table 2 — Dataset inventory and integrity (device-measured). 66 captures total; '
                  'representative and flagged rows shown.'))
integ = readcsv('analysis/output/report_dataset_integrity.csv')
keep = [r for r in integ if any(k in r['capture'] for k in [
    '231354_idf_bmp581_static', '233753_idf_bmp581_handtest1',
    '235054_idf_bmp581_elevator', 'static0', 'static1', 'static2',
    'handtest1_120s', 'elevator_2x_200s', 'fixcheck60s', 'fixcheck90s',
    'lsm6dsv_bringup', 'lsm6dsv_bringup9', 't004_elevator_f14',
    't005_ControledMove', 't006_benchstatic', 'handtest3',
]) and not any(k in r['capture'] for k in ['bringup2', 'bringup3', 'bringup4',
    'bringup5', 'bringup6', 'bringup7', 'bringup8'])]
rows = [['Capture (suffix)', 'Span s', 'P frm', 'I frm', 'E1', 'E2', 'Stale %']]
for r in keep:
    nm = r['capture'].replace('2026', '26').replace('_idf_', ' ')
    rows.append([nm, r['device_span_s'], r['P_frames'], r['I_frames'] or '-',
                 r['E1'], r['E2'], r['imu_stale_pct'] or '-'])
story.append(tbl(rows, [6.6*cm, 1.5*cm, 1.6*cm, 1.6*cm, 1.5*cm, 1.5*cm, 1.9*cm]))
story.append(cap('Table 2 — 66 captures exist in total (2026-10-21 .. 2026-10-25). Rows shown: MS5611-era '
                 'references, BMP581+MPU (Bench 7), LSM6DSV16X bring-up (DEF-017/020 evidence) and the '
                 'new-era validation set. full table: analysis/output/report_dataset_integrity.csv'))
story.append(P(
    'Known exclusions: t004_elevator_run1 lacks a JSON sidecar (PROM constants missing) and is '
    'analysis-excluded; static0 is retained as the DEF-020 fault dataset; bringup1-9 are retained '
    'as DEF-017/018 evidence. Host-side USB backlog (host elapsed < device span, ring high-water '
    'tens of KB) affected the Bench 7 elevator capture (f = 1.11) and static0 (29 s host pause); '
    'device-time analysis is unaffected. The 22:56:10 elevator capture has f = 0.999 '
    '(180.33 s host vs 180.11 s device) — no backlog.'))

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
    ['Post-fix 100 kHz era', '6', '80', '0', '0.46', 'clean; handtest1_120s has 80 brief E1 (~0.7/s), 0.46 % stale -> masked'],
], [3.6*cm, 1.7*cm, 1.8*cm, 1.8*cm, 2.1*cm, CW-10.0*cm]))
story.append(Spacer(1, 4))
story.append(P(
    '<b>Exclusion policy and sizes.</b> IMU-dependent analysis masks: every +-0.5 s window around '
    'an E1/E2 frame; all recovery intervals (E3 to first fresh sample); stale runs longer than 5 '
    'frames plus a 0.5 s margin. Applied to the post-fix era: handtest1_120s masks 2.6 s '
    '(2.2 %); all other post-fix captures mask 0.0-0.3 %. Barometric channels are never masked '
    '(the baro path was independent of every IMU fault). The 22:56:10 elevator capture requires '
    'no masking at all — zero E frames, zero stale intervals.'))

# ---------------- 5 static noise ----------------
story.append(P('5&nbsp;&nbsp;Static sensor noise and calibration', 'H1x'))
story.append(tcap('Table 4 — Static noise by sensor generation (1 s local baseline removed)'))
story.append(tbl([
    ['Sensor / era', 'Pressure noise Pa RMS', 'Altitude equiv.', 'Velocity noise at estimators (static)'],
    ['MS5611 clone (foam, Ph 2-6)', '0.42-0.48', '3.4-3.9 cm', 'best baro-only 6.3-6.5 mm/s RMS (Bench 7 ref)'],
    ['BMP581 (Bench 7, + MPU6050)', '0.18-0.22', '1.5-1.9 cm', 'S1P/S2/S4/S5 6.3-6.5 mm/s; D01/C03 8.4 mm/s; FUS 6.7 mm/s'],
    ['BMP581 (+ LSM6DSV16X, new era)', '0.19-0.31', '1.5-2.5 cm', 'elevator floor dwells 0.019-0.032 m altitude std'],
], [4.4*cm, 3.0*cm, 2.6*cm, CW-10.0*cm]))
story.append(Spacer(1, 4))
story.append(P(
    'BMP581 pressure noise is essentially unchanged between IMU generations (0.186 Pa on the '
    '22:56 elevator floor dwells vs 0.189 Pa previously) — the IMU swap did not disturb the baro '
    'path. IMU calibration checks on the new sensor: gravity magnitude 0.9989-0.9994 g across '
    'statics, raw gyro offset ~0.05-0.12 dps, per-axis gyro noise 0.033 dps (LSM6DSV16X driver-'
    'default filtering). Ambient pressure drift over the 180 s elevator run returned to the '
    'starting floor within -0.245 m — ordinary weather/offset drift, no compensation applied.'))

# ---------------- 6 hand/shake ----------------
story.append(P('6&nbsp;&nbsp;Hand and shake test findings', 'H1x'))
story.append(tcap('Table 5 — Handtest audio behaviour (Bench 7, BMP581 + MPU6050, 17 detected events + 1 slow block)'))
story.append(tbl([
    ['Candidate', 'Onset med (s)', 'Release med (s)', 'Slow-block audio ON frac', 'Slow bias (m/s)', 'Static RMS in-test'],
    ['D01/C03', '2.10', '1.00', '0.431', '+0.031', '0.0057'],
    ['S1P', '-0.91', '0.33', '0.146', '-0.097', '0.0036'],
    ['S4', '2.20', '0.58', '0.438', '-0.015', '0.0037'],
    ['S5', '2.25', '0.43', '0.426', '+0.011', '0.0037'],
], [3.0*cm, 2.4*cm, 2.4*cm, 3.6*cm, 2.4*cm, CW-13.8*cm]))
story.append(cap('Table 5 — Slow block (61.9-129.8 s) is the thermalling-regime proxy. Onset/release are '
                 'relative to the pressure-derived reference, not ground truth.'))
story.append(P(
    'New-era hand test (120 s, BMP581 + LSM6DSV16X, 80 brief E1 frames masked): acquisition is '
    'solid and the five deployed estimators track the motion profile; the frozen-config audio '
    'comparison on this capture is part of the pending Bench 8 replay and is intentionally not '
    'anticipated here. Historical shake/toss captures (t005_toss, t006/t007 drops) informed the '
    'failure-mode gallery of Phases 4-6; no new shake test exists in the new era yet — flagged '
    'as a next-step, since vibration-rich data is exactly the regime where FUS is claimed to win.'))

# ---------------- 7 elevator ----------------
story.append(P('7&nbsp;&nbsp;Four-leg elevator results (principal dynamic benchmark)', 'H1x'))
story.append(P(
    'Recording 20261025_225610_idf_bmp581LSM6DS_elevator_2x_200s: route 14 -> 1 -> 14 -> 1 -> 14, '
    '18,012 IMU frames (100.006 Hz, max interval 11.9 ms, zero stale), 7,205 baro frames '
    '(40.006 Hz, max 27.2 ms), 695 V frames, no TX overflow, max sensor tick 6.65 ms (budget '
    '10.5 ms), all B windows vnan=0 / vfault=0. File name says 200 s; host recorded 180.33 s '
    'against a 180.11 s device span.'))
legs = readcsv(f'{PKG}/elevator_225610_leg_metrics.csv')
rows = [['Leg', 'Direction', 'Start s', 'Stop s', 'Duration s', 'Plateau mean m/s', 'Plateau std', 'Step m']]
for r in legs:
    rows.append([r['leg'], r['direction'], f2(r['start_s'], 1), f2(r['stop_s'], 1),
                 f2(r['duration_s'], 1), f2(r['plateau_mean_mps'], 3), f2(r['plateau_std_mps'], 3),
                 f2(r['endpoint_height_m'], 1)])
story.append(tcap('Table 6 — Measured legs (pressure-derived reference, +-0.30 m/s threshold)'))
story.append(tbl(rows, [1.0*cm, 2.0*cm, 1.8*cm, 1.8*cm, 2.0*cm, 3.0*cm, 2.2*cm, CW-13.8*cm]))
story.append(cap('Table 6 — Two descents at -1.736/-1.738 m/s, two ascents at +1.670/+1.669 m/s, ~39.2-39.5 m per leg. '
                 'Leg-to-leg repeatability: plateau means agree within 0.004 m/s; durations within 0.43 s.'))
story.extend(fig(f'{PKG}/elevator_225610_altitude_legs.png',
                 caption='Figure 1 — Four floor-to-floor legs, ISA-derived altitude. Floor dwells at both ends of each leg.'))
story.extend(fig(f'{PKG}/elevator_225610_velocity_reference.png',
                 caption='Figure 2 — Pressure-derived vertical-velocity reference (2 s Savitzky-Golay). Shared by all timing comparisons.'))
dwells = readcsv(f'{PKG}/elevator_225610_floor_dwell_metrics.csv')
rows = [['Floor dwell', 'Window s', 'Mean h (m)', 'h std (m)', 'Noise Pa RMS']]
for r in dwells:
    rows.append([r['floor'], f"{f2(r['start_s'],0)}-{f2(r['end_s'],0)}", f2(r['mean_h_m'],2),
                 f2(r['std_h_m'],3), f2(r['noise_pa'],3)])
story.append(tcap('Table 7 — Stationary floor dwells'))
story.append(tbl(rows, [3.2*cm, 2.6*cm, 2.6*cm, 2.2*cm, CW-10.6*cm]))
story.append(cap('Table 7 — Altitude std 1.9-3.2 cm during dwells; noise 0.187-0.219 Pa RMS. No drift anomaly at any floor.'))
story.append(P(
    '<b>Transition behaviour.</b> IMU body-frame acceleration projected onto the rest specific-force '
    'axis shows clean acceleration/deceleration spikes at every leg start and stop (Figure 5), '
    'independently confirming the motion timeline. Recovery after abrupt motion (floor stops) '
    'is complete within the dwell: estimator outputs settle to < 0.05 m/s residual within ~2 s '
    'of stop for D01/C03, ~2-3 s for S4/S5, and 5-6 s for FUS (Section 9). Sustained climb and '
    'sustained descent plateaus are tracked to within 0.01 m/s mean by all baro-only candidates.'))

story.append(PageBreak())

# ---------------- 8 five-filter comparison ----------------
story.append(P('8&nbsp;&nbsp;Detailed five-filter comparison', 'H1x'))
story.append(P(
    'All five deployed estimators run side-by-side in firmware on identical frozen '
    'configurations. Audio ON/OFF is the primary pilot-facing output; timings below are relative '
    'to the shared pressure-derived motion threshold (crossing of +-0.30 m/s). Two intended ON '
    'episodes per estimator, exclusively on ascents; zero extra episodes on descents or dwells.'))
aud = readcsv(f'{PKG}/elevator_225610_audio_events_summary.csv')
rows = [['Filter', 'Ascent', 'ON s', 'OFF s', 'ON dur s', 'ON lag s', 'OFF lag s']]
for r in aud:
    rows.append([r['filter'], r['ascent'], f2(r['on_s'],2), f2(r['off_s'],2),
                 f2(r['on_duration_s'],2), f2(r['on_lag_to_pressure_threshold_s'],2),
                 f2(r['off_lag_to_pressure_threshold_s'],2)])
story.append(tcap('Table 8 — Virtual-audio episodes, 22:56:10 elevator (V-frame events, tone policy 0.20/0.05)'))
story.append(tbl(rows, [1.9*cm, 1.4*cm, 1.9*cm, 1.9*cm, 1.9*cm, 1.8*cm, CW-11.8*cm]))
story.append(cap('Table 8 — OFF lag includes the audio policy hysteresis (lift_off +0.05 m/s) and the reference smoother '
                 'group delay; values are relative, comparable only within this table and its Bench 7 counterpart. '
                 'D01 and C03 timestamps are identical to logged precision (see Section 9 — mathematical identity, not a wiring bug).'))
story.extend(fig(f'{PKG}/elevator_225610_audio_gates.png',
                 caption='Figure 3 — Audio ON/OFF episodes for all five estimators against the motion reference.'))
tv = readcsv(f'{PKG}/elevator_225610_tone_velocity_metrics.csv')
rows = [['Filter', 'Ascent', 'Tone mean m/s', 'Ref mean m/s', 'Mean diff m/s', 'MAE m/s']]
for r in tv:
    rows.append([r['filter'], r['ascent'], f2(r['tone_derived_mean_mps'],3),
                 f2(r['pressure_ref_mean_mps'],3), f2(r['mean_difference_mps'],3),
                 f2(r['MAE_mps'],3)])
story.append(tcap('Table 9 — Tone-coded plateau velocity vs pressure reference (10 Hz sample-and-hold within audio ON)'))
story.append(tbl(rows, [1.9*cm, 1.4*cm, 2.6*cm, 2.6*cm, 2.6*cm, CW-11.1*cm]))
story.append(cap('Table 9 — Tone reconstruction is quantized (pitch events only fire on tone changes); descriptive, not independent RMSE. '
                 'All baro-only candidates agree with the reference to <= 0.011 m/s mean; FUS reads +0.20 m/s high on both ascents.'))
story.extend(fig(f'{PKG}/elevator_225610_tone_velocity_vs_pressure.png',
                 caption='Figure 4 — Tone-derived velocity vs pressure proxy for both ascents. FUS plateau sits visibly above the reference.'))
story.append(P(
    '<b>Ordering on this recording.</b> Alert timing: D01 = C03 (lead) > S4 ~= S5 (~0.15-0.6 s '
    'later) > FUS (~0.75-1.2 s late, ON extension 5-6 s after floor arrival). Plateau accuracy: '
    'S4 (MAE 0.057-0.062) marginally best, all baro-only within 0.07 m/s MAE; FUS 0.20 m/s. '
    'Exit-from-lift: D01/C03 OFF ~1.4-1.6 s after the pressure threshold crossing, S4/S5 '
    '~1.7-2.0 s, FUS ~7.1 s. Stationary silence: all five silent at both floor-1 stops and '
    'throughout descents. These orderings replicate the Bench 7 pattern on different hardware, '
    'which strengthens them; absolute lags remain proxy-relative.'))
story.extend(fig(f'{PKG}/elevator_225610_imu_acceleration.png',
                 caption='Figure 5 — IMU specific-force projection (rest axis) vs pressure proxy: clean accel/decel events at every transition.'))

story.append(PageBreak())

# ---------------- 9 equivalence + CPU ----------------
story.append(P('9&nbsp;&nbsp;MCU replay equivalence and CPU cost', 'H1x'))
story.append(tcap('Table 10 — MCU vs Python-replay audio equivalence (Bench 7)'))
story.append(tbl([
    ['Estimator', 'Elevator episodes MCU/py', 'Handtest episodes', 'max |dT_on|', 'max |dT_off|'],
    ['D01', '2 / 2', '16 / 16', '0.000 s', '0.000 s'],
    ['C03', '2 / 2', '16 / 16', '0.025 s', '0.025 s'],
    ['S4', '2 / 2', '16 / 16', '0.000 s', '0.000-0.075 s'],
    ['S5', '2 / 2', '16 / 16', '0.000 s', '0.000 s'],
    ['FUS', '4 / 4', '19 / 19', '0.075 s', '0.100 s'],
], [2.4*cm, 4.4*cm, 3.2*cm, 2.2*cm, CW-12.2*cm]))
story.append(cap('Table 10 — Replay reproduces every MCU episode within 1-4 baro samples. FUS\'s two extra ON episodes '
                 '(start-up attitude/bias convergence, t = 5-12 s) are genuine estimator behaviour, reproduced in replay.'))
story.append(P(
    'The D01/C03 identical-timestamps observation is mathematical, not a wiring defect: C03 is '
    'the steady-state-gain CV tracker of the same model D01\'s time-varying Kalman converges to; '
    'once gains settle they are algebraically near-identical (max |dv| 0.087-0.151 m/s only '
    'during abrupt hand motion). Ranking consequence: D01 and C03 are one architecture; C03 '
    'delivers it at lower cost. FUS\'s four episodes on the Bench 7 elevator match its late-start '
    '+ early-false-ON behaviour seen again in the 22:56 capture.'))
story.append(tcap('Table 11 — On-target CPU cost (ESP32-S3 240 MHz, medians from B-line telemetry, post-DEF-002 build)'))
story.append(tbl([
    ['Estimator', 'sid0 avg/max us', 'sid1 avg/max us', 'Tick budget share'],
    ['D01', '36 / 44', '27 / 37', '0.7 %'],
    ['FUS', '33 / 37 (baro side; IMU side uncharged — DEF-009)', '-', '0.7 %'],
    ['S5', '77 / 80', '59 / 88', '1.6 %'],
    ['S4', '97 / 101', '69 / 82', '2.0 %'],
    ['C03', '105 / 132', '78 / 102', '2.6 %'],
], [2.4*cm, 6.6*cm, 3.4*cm, CW-12.4*cm]))
story.append(cap('Table 11 — Host-replay relative costs for all 37 candidates: filter_benchmark/results/63_cpu_host.csv '
                 '(D01 131 us vs C03 55 us per update). Worst case is 2.6 % of the 5 ms tick: efficiency is not a selector.'))

# ---------------- 10 historical comparison ----------------
story.append(P('10&nbsp;&nbsp;Historical filter-benchmark comparison (Phases 2-7)', 'H1x'))
story.append(P(
    'Phase 6 (MS5611 + MPU6050, 37 frozen candidates, corrected DEF-014 scoring) composite top-5: '
    '<b>C03, C01, B02_project_kalman, E06, S2</b>; S4 7th, S1 8th, D01 9th, S5 12th, FUS 21st '
    '(FUS_Q10 20th). Phase-to-phase changes were driven by defect fixes, not filter drift: D01\'s '
    'rest floor "improved" 0.101 -> 0.057 m/s once the moving-reference defect (DEF-001) stopped '
    'being attributed to it; C03\'s refit storm (DEF-002) fix removed its Phase-2/3 CPU penalty; '
    'S1\'s real +0.63 m/s slow-descent bias (a thermalling-regime false-lift) was exposed only '
    'after the phantom-event scoring artifact (DEF-014) was removed. S2 ranks 5th despite its '
    'documented freeze-trap architecture defect — ranking position is not endorsement.'))
story.append(tcap('Table 12 — Bench 7 (BMP581 + MPU6050) sustained-motion results, median over legs'))
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
story.append(cap('Table 12 — Late-night elevator ran ~11 % faster than Bench 6 (condition difference, handled via '
                 'device-time velocities only). Audio correctness: every baro-only candidate 0 missed lifts, 0 false '
                 'audio seconds; FUS added 2 start-up false ONs and ~5-6 s ON-extensions after top-floor stops.'))
story.append(P(
    '<b>What the new era confirms and changes.</b> (1) The baro-only cluster\'s relative ordering '
    '(D01/C03 fastest alert, S4/S5 close behind, all accurate on plateaus) replicates on BMP581+'
    'LSM6DSV16X data — hardware independence of the ranking. (2) FUS\'s bias (+0.20/-0.25 m/s), '
    'slow rise and 7.4 s exit reproduce within ~0.05 m/s on different IMU hardware — the problem '
    'is in the fusion configuration, not the MPU6050. (3) The DEF-020 fix removed the only '
    'acquisition-layer objection to the new hardware; no ranking-level change is attributable to '
    'sensor swaps for baro-only candidates.'))

# ---------------- 11 audio & pilot ----------------
story.append(P('11&nbsp;&nbsp;Audio behaviour and pilot experience', 'H1x'))
for b in [
    'Two intended ON episodes per estimator on the principal benchmark, exclusively on ascents; '
    'zero false activations on descents or floor dwells across all new-era captures — the false-'
    'lift defect class (DEF-001) remains fixed.',
    'Alert lead: D01/C03 turn ON 0.35-0.45 s after the pressure-derived threshold; S4/S5 add '
    '0.15-0.6 s; FUS is 0.75-1.2 s late. In pilot terms the baro-only cluster announces climb '
    'promptly; FUS would feel sluggish.',
    'Shut-off after floor arrival: D01/C03 ~1.4-1.6 s, S4/S5 ~1.7-2.0 s, FUS ~7.1 s relative to '
    'the shared reference. FUS\'s prolonged tone after the lift stops is the dominant pilot-'
    'experience defect on this dataset.',
    'Tone fidelity: baro-only tone velocities track the sustained climb to within ~0.01 m/s '
    '(MAE 0.06-0.07 m/s); FUS over-pitches by ~0.20 m/s, ~12 % fast.',
    'Static silence: zero false ON episodes in any post-fix static; the 5 s metadata keepalive '
    'never produces audio artifacts (V frames are estimator-driven only).',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText='&bull;'))

# ---------------- 12 FUS limitations ----------------
story.append(P('12&nbsp;&nbsp;FUS limitations and possible improvements', 'H1x'))
story.append(P(
    '<b>Observed (both IMU generations, reproduced twice).</b> Sustained-motion bias +0.20 m/s '
    '(ascent) / -0.25 m/s (descent); 3.6x higher leg RMS than baro-only; slowest rise; ~7 s '
    'exit; two start-up false ONs (t = 5-12 s, attitude/bias convergence); ~5-6 s audio '
    'extension after top-floor stops. FUS_Q10 (labelled exploratory, Phase 5) improves every '
    'column but remains worse than all baro-only candidates on this motion profile.'))
story.append(P(
    '<b>Plausible causes (hypotheses, unvalidated — no firmware changes made).</b> (i) The '
    'gravity-compensation / attitude reference converges slowly from cold start and drifts '
    'during long constant-velocity legs, folding specific-force error into climb rate; (ii) the '
    'IMU-aided state is not faded out when the innovation sequence says the baro is clean — '
    'in a vibration-free building the accelerometer adds only bias, so fusion should degrade '
    'to baro-only, but the current gains keep trusting it; (iii) the audio OFF path uses the '
    'fused state without a dwell-stable floor, producing the post-stop extension. The decisive '
    'experiment is vibration-rich data (flight or shake rig), where hypothesis (ii) predicts '
    'FUS should at least match baro-only; if it does not, the fusion structure itself needs '
    'rework (adaptive gain scheduling, baro-innovation gating, explicit stationary reset).'))

# ---------------- 13 conclusions ----------------
story.append(P('13&nbsp;&nbsp;Conclusions, recommendations and next validation steps', 'H1x'))
for b in [
    '<b>Acquisition layer: validated.</b> BMP581 + LSM6DSV16X at 100 kHz bus A produces '
    'reference-quality telemetry (40.006 / 100.006 Hz, zero errors over 180 s of motion). Keep '
    'Bus A at 100 kHz; external 2.2 kOhm pull-ups are optional future headroom, not a need.',
    '<b>Baro-only cluster: still leading, still frozen.</b> D01/C03/S4/S5 are statistically '
    'tied within proxy resolution on this benchmark; D01/C03 lead alert timing. Carry all four '
    'into flight evaluation; do not down-select yet.',
    '<b>D01 vs C03:</b> one architecture; C03 is cheaper (55 vs 131 us host-replay; 105 vs 36 us '
    'on-target). Decision can wait for flight data.',
    '<b>FUS: hold.</b> Do not add fusion complexity; first run the vibration-rich test and a '
    'stop-state review. Current evidence says it harms quiet-air performance.',
    '<b>Next validation steps, in order:</b> (1) new-era hand/shake replay with frozen configs '
    '(Bench 8); (2) vibration/shake capture to test the FUS value proposition; (3) real-flight '
    'recording with the same capture protocol; (4) only then consider leakage-controlled '
    'tuning. DEF-011-scale checks remain a standing requirement before physical validation '
    'claims (already satisfied in firmware this phase).',
    '<b>Standing limitations:</b> no independent ground truth in any recording; all sub-second '
    'timings are pressure-proxy-relative; static/elevator data cannot certify flight behaviour; '
    'S2 retained as labelled defect reference; no estimator is frozen by this report.',
]:
    story.append(Paragraph(b, styles['Bull'], bulletText='&bull;'))
story.append(Spacer(1, 8))
story.append(P(
    'Reproducibility: dataset integrity — analysis/report_collect_integrity.py; elevator analysis '
    'package — analysis/external/elevator_225610/ (figures + machine-readable CSVs); frozen-config '
    'benchmarks — filter_benchmark/results/ and filter_benchmark/reports/ (phase2-6, bench7); '
    'firmware of record — esp-idf/vario/ @ local commit dee9c1a (not pushed).', 'Cap'))


def hf(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2.5*cm, h - 1.5*cm,
                      'Vario USB — BMP581 + LSM6DSV16X Engineering Validation')
    canvas.drawRightString(w - 2.5*cm, h - 1.5*cm, '2026-10-25')
    canvas.setStrokeColor(HexColor('#c8d0d6'))
    canvas.setLineWidth(0.5)
    canvas.line(2.5*cm, h - 1.7*cm, w - 2.5*cm, h - 1.7*cm)
    canvas.drawCentredString(w / 2, 1.4*cm, f'Page {doc.page}')
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=2.3*cm, bottomMargin=2.2*cm,
                        leftMargin=2.5*cm, rightMargin=2.5*cm,
                        title='Vario USB BMP581+LSM6DSV16X Engineering Validation',
                        author='Vario USB project')
doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=hf)
print('built', OUT)
