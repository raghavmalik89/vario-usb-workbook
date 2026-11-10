"""Generate the two website publication PDFs.

Outputs (reports/publication/):
  - A_Flying_Breadboard_Product_Development.pdf
  - Flight_Data_Filter_Validation_Report.pdf

Figure sources: reports/flight/*.png (committed, verified — copied into
docs/pdf/figs so build_lib.figure can locate them) and a logger block
diagram generated here from the DataLogger repository hardware table.

All quantitative content in the flight report is taken verbatim from
reports/flight_benchmark_report.md (workbook commit 53907ab) and
analysis/flight/flight_metrics.json; nothing is recomputed.

Repro:  python docs/pdf/build_publication_reports.py
"""
import shutil
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_lib import (P, FIGCACHE, formula, header_footer, spacer, styles,
                       three_line_table, figure)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (PageBreak, Paragraph, SimpleDocTemplate, Spacer)

ROOT = Path(__file__).resolve().parents[2]
FLIGHT_FIGS = ROOT / "reports" / "flight"
OUTDIR = ROOT / "reports" / "publication"
OUTDIR.mkdir(exist_ok=True)

REPORT1_PDF = OUTDIR / "A_Flying_Breadboard_Product_Development.pdf"
REPORT2_PDF = OUTDIR / "Flight_Data_Filter_Validation_Report.pdf"
S = styles()

# ---------------------------------------------------------------- figures
FLIGHT_PNGS = [
    "fig1_overview.png", "fig2_overlay.png", "fig3_transitions.png",
    "fig4_quiet.png", "fig5_audio.png",
    "linkedin_flying_the_breadboard.png",
]


def stage_figures():
    for name in FLIGHT_PNGS:
        src = FLIGHT_FIGS / name
        dst = FIGCACHE / f"pub_{name}"
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)


def make_logger_diagram():
    """Block diagram of the breadboard flight logger (hardware table of the
    ESP32-S3-Display-DataLogger repository README)."""
    png = FIGCACHE / "pub_logger_block_diagram.png"
    fig, ax = plt.subplots(figsize=(11.6, 6.4), dpi=300)
    ax.set_xlim(0, 116)
    ax.set_ylim(0, 64)
    ax.axis("off")

    ACCENT, INK, GREY = "#1F3864", "#333333", "#666666"
    BOX, FILL, SENS = "#d9e2f3", "#eef3fb", "#e8f0e8"

    def box(x, y, w, h, title, lines, fc=FILL, ec=ACCENT, tfs=10.2, lfs=8.4,
            title_color=ACCENT):
        ax.add_patch(FancyBboxPatch((x, y), w, h,
                     boxstyle="round,pad=0.6,rounding_size=1.2",
                     fc=fc, ec=ec, lw=1.2))
        ty = y + h - 3.6
        ax.text(x + w / 2, ty, title, ha="center", va="center",
                fontsize=tfs, fontweight="bold", color=title_color)
        for i, ln in enumerate(lines):
            ax.text(x + w / 2, ty - 4.2 - i * 3.4, ln, ha="center",
                    va="center", fontsize=lfs, color=INK)

    def arrow(x0, y0, x1, y1, label=None, ls="-"):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1),
                     arrowstyle="-|>", mutation_scale=13,
                     color=GREY, lw=1.3, linestyle=ls))
        if label:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 1.6, label,
                    ha="center", fontsize=7.6, color=GREY,
                    bbox=dict(fc="white", ec="none", pad=0.6))

    # --- sensors (left) ---
    box(2, 46, 26, 14, "BMP581 barometer",
        ["breakout · I²C 0x47 (chip ID 0x50)", "40 Hz · on-chip compensated", "Pa = raw24 / 64"], fc=SENS)
    box(2, 28, 26, 14, "QMI8658C IMU",
        ["onboard · I²C 0x6B", "bus fault root-caused at", "HW level — baro-only flight"], fc=SENS)
    box(2, 10, 26, 14, "Passive piezo buzzer",
        ["GPIO16 · LEDC PWM", "vario tone 400–3500 Hz", "(implemented, unverified audio)"], fc=SENS)

    # --- bus ---
    ax.add_patch(FancyBboxPatch((31.5, 42), 3.2, 16,
                 boxstyle="round,pad=0.3", fc=BOX, ec=ACCENT, lw=1.1))
    ax.text(33.1, 50, "I²C 100 kHz\nSDA·47 / SCL·48", rotation=90,
            ha="center", va="center", fontsize=7.8, color=INK)

    # --- MCU (centre) ---
    ax.add_patch(FancyBboxPatch((38, 20), 40, 38,
                 boxstyle="round,pad=0.8,rounding_size=1.6",
                 fc="#f7f9fd", ec=ACCENT, lw=1.6))
    ax.text(58, 54.2, "Waveshare ESP32-S3-LCD-1.9  (~ US$13)",
            ha="center", fontsize=11.5, fontweight="bold", color=ACCENT)
    ax.text(58, 50.6, "ESP32-S3R8 · 240 MHz dual-core · 16 MB flash · 8 MB octal PSRAM",
            ha="center", fontsize=8, color=GREY)
    box(40, 36.5, 35.5, 10.5, "Acquisition", ["40 Hz timestamped baro (+IMU when present)"], fc="white")
    box(40, 25, 35.5, 10.5, "Filter bank — frozen configs",
        ["C03 · D01 · S4 · S5  (host-verified vs", "Python reference, worst err 2.6e-6 m/s)"], fc="white")
    box(40, 13.2, 35.5, 8.6, "Audio + GUI",
        ["audio hysteresis +0.20 / -0.05 m/s", "3-screen LCD GUI"], fc="white")

    # --- outputs (right) ---
    box(84, 47, 30, 12, "microSD card",
        ["SDMMC 1-bit — flight recording", "B @ 40 Hz + V @ 20 Hz"], fc=SENS)
    box(84, 33, 30, 12, "USB stream @ 921600 baud",
        ["sequence-checked text protocol", "-> existing bench capture tool"], fc=SENS)
    box(84, 19, 30, 12, "LCD 320×170 (3 screens)",
        ["status / graph / vario readout", "REC indicator"], fc=SENS)

    # arrows
    arrow(28, 53, 31.5, 53)                    # BMP -> bus
    arrow(28, 35, 31.5, 47, ls=":")            # IMU -> bus (deferred)
    arrow(34.7, 50, 38, 50)                    # bus -> MCU
    arrow(78, 52, 84, 53)                      # MCU -> SD
    arrow(78, 44, 84, 39)                      # MCU -> USB
    arrow(78, 34, 84, 25)                       # MCU -> LCD
    arrow(28, 17, 38, 26)                      # buzzer -> MCU
    ax.text(32.5, 17.5, "GPIO16", fontsize=7.2, color=GREY, rotation=24)

    # bottom band
    ax.add_patch(FancyBboxPatch((2, 1.5), 112, 6,
                 boxstyle="round,pad=0.5,rounding_size=1.2",
                 fc="#f5f5f5", ec="#bbbbbb", lw=1.0))
    ax.text(58, 4.5, "Breadboard + jumper assembly — battery-powered for flight · every connection re-verified with the "
                     "onboard probe app (I²C scan + chip-ID, LCD diagnostics, buzzer sweep) · rough-handling checks "
                     "before flight · no custom PCB, enclosure or extra processor at this stage",
            ha="center", va="center", fontsize=8, color=INK, wrap=True)

    fig.tight_layout(pad=0.4)
    fig.savefig(png, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png


# ------------------------------------------------------------ build utils
def fig_flow(name, width, caption, counter):
    """figure() returns [Image, caption] — extend, don't append."""
    counter[0] += 1
    return figure(name, width, caption, counter[0], S)


def tbl_flow(story, header, rows, widths, counter, center=None, caption=None):
    if caption:
        counter[0] += 1
        story.append(P(f"<b>Table {counter[0]}.</b> {caption}", S["caption"]))
    story.append(three_line_table(header, rows, widths, center_cols=center))
    story.append(spacer(10))


def build(story, out_path, title, subtitle_lines):
    doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                            leftMargin=2.3 * cm, rightMargin=2.3 * cm,
                            topMargin=2.4 * cm, bottomMargin=2.2 * cm,
                            title=title, author="R. Malik")
    first, later = header_footer(title)
    cover = [Spacer(1, 4.0 * cm),
             P(title, S["title"])]
    for ln in subtitle_lines:
        cover.append(P(ln, S["subtitle"]))
    cover.append(Spacer(1, 1.2 * cm))
    for ln in ("R. Malik · Vario project engineering programme",
               "Sources: vario-usb-workbook (commit 53907ab, corrected "
               "flight benchmark) · ESP32-S3-Display-DataLogger repository",
               "Companion article: "
               + ("From Flight Data to Filter Decisions"
                  if "Breadboard" in title
                  else "A Flying Breadboard — A Product Development Story"),
               "Date: 2026-11-10 · Website publication handoff"):

        cover.append(P(ln, S["subtitle"]))
    cover.append(PageBreak())
    doc.build(cover + story, onFirstPage=first, onLaterPages=later)
    print("wrote", out_path)


# ================================================================ REPORT 1
def report1():
    fig_no, tbl_no = [0], [0]
    story = []

    story.append(P("1 · The product, and the question we could not answer "
                   "on the bench", S["h1"]))
    story.append(P(
        "The product under development is a small pressure-sensor variometer "
        "for paragliding: a device that reads a barometric pressure sensor, "
        "estimates vertical speed in real time, and tells the pilot — "
        "acoustically — when the wing is climbing in lift or sinking out. The "
        "engineering requirement sounds simple: <b>report vertical speed as "
        "early as possible, without false alarms and without chattering at the "
        "pilot when the air is neutral.</b>", S["body"]))
    story.append(P(
        "By the time this story begins, the programme had already produced a "
        "working bench infrastructure: an ESP32-S3 test rig with two "
        "barometers and an IMU, a causal-replay filter benchmark, frozen "
        "configurations for a bank of candidate estimators, an audio policy, "
        "and a defect register documenting how earlier conclusions were "
        "corrected when the evidence changed. The bench told us a lot. It could "
        "not tell us the one thing that mattered next: <b>how does the system "
        "behave in real air?</b>", S["body"]))
    story.append(P(
        "All of our motion evidence was proxy evidence. Elevator rides imitate "
        "slow, clean altitude changes; hand shakes imitate vibration; static "
        "sessions imitate standing on launch. None of them reproduce the actual "
        "operating environment — a paraglider climbing in a turbulent thermal "
        "at +2 m/s, slicing through sink, flying in air that changes character "
        "every few seconds. Filter tuning, audio-threshold selection and "
        "sensor validation carried an open risk of being optimized for the "
        "bench rather than for the sky. Closing that gap required <b>real "
        "flight measurements</b> — raw pressure from the actual sensor, "
        "recorded on an actual flight, at the full sample rate the algorithms "
        "run at.", S["body"]))

    story.append(P("2 · Why we needed a temporary data logger", S["h1"]))
    story.append(P(
        "The bench rig was never designed to fly: it streams over USB to a "
        "host computer at 921 600 baud, is powered from the USB port, and "
        "lives on a desk. The options were weighed directly:", S["body"]))
    tbl_flow(story,
             ["Option", "Verdict"],
             [["Fly the bench rig with a laptop",
               "Rejected — no practical way to host a laptop in flight; USB "
               "link and power both fail."],
              ["Buy a consumer GPS / barometer logger",
               "Rejected — low-rate position/altitude logs; no synchronized "
               "40 Hz raw pressure stream, no estimator state, no integrity "
               "guarantees aligned with our processing chain."],
              ["Phone barometer apps",
               "Rejected for the same reason: no raw-stream access, no "
               "integrity guarantees, no alignment with our processing chain."],
              ["Build a small temporary logger",
               "<b>Selected.</b> Same BMP581 sensor already validated on the "
               "bench, same estimator bank, battery-powered, logging to SD "
               "card, cheap and fast."]],
             [5.6 * cm, 10.0 * cm], tbl_no, caption="Alternatives considered "
             "for obtaining real flight pressure data.")
    story.append(P(
        "The logger was explicitly a <b>supporting development tool, not a "
        "product</b>. Its job was to reduce one specific uncertainty: what does "
        "the pressure stream actually look like in flight, and what do our "
        "frozen algorithms do with it? Everything about its design follows from "
        "treating it as disposable tooling.", S["body"]))

    story.append(P("3 · Hardware selection: the cheapest thing that removes "
                   "the uncertainty", S["h1"]))
    story.append(P(
        "The selection logic was deliberately inverted from a product design. "
        "Instead of asking “what should the final hardware be?”, we asked "
        "“what is the cheapest, fastest assembly that records the same "
        "pressure stream our product senses, at the same rate, with verifiable "
        "integrity?”", S["body"]))
    tbl_flow(story,
             ["Item", "Choice", "Rationale"],
             [["MCU + display",
               "Waveshare ESP32-S3-LCD-1.9 dev board, ~ US$13",
               "Integrated ESP32-S3 (240 MHz, 16 MB flash, 8 MB octal PSRAM), "
               "LCD for field status, USB for bench streaming — nothing else "
               "to integrate at board level."],
              ["Barometer",
               "BMP581 breakout (I²C 0x47)",
               "The exact sensor already validated in the bench programme "
               "(40 Hz cadence read, on-chip compensation Pa = raw24/64). "
               "Flight data directly comparable to every earlier capture."],
              ["IMU",
               "Onboard QMI8658C; ST LSM6DSV16X breakout kept, not fitted",
               "Motion context if needed, without blocking the barometer path."],
              ["Audio",
               "Passive piezo buzzer (GPIO16, LEDC PWM)",
               "In-flight acoustic behaviour identical in kind to the "
               "product's virtual audio."],
              ["Storage",
               "microSD via onboard SDMMC slot",
               "Self-contained recording independent of any host link."],
              ["Assembly",
               "Breadboard and jumper wiring",
               "Fast, fully re-wirable, inspectable. The flight would last "
               "minutes; the tooling did not need to survive a season."]],
             [2.5 * cm, 5.3 * cm, 7.8 * cm], tbl_no,
             caption="Hardware bill of the temporary flight logger.")
    story.append(P(
        "<b>Why no custom PCB?</b> A PCB is an investment in a design freeze. "
        "At this stage we did not know what the flight would teach us — that "
        "is the point of the exercise. Layout, fabrication and rework would add "
        "weeks and cost without reducing any of the uncertainty the flight was "
        "meant to resolve.", S["body"]))
    story.append(P(
        "<b>Why no enclosure?</b> The logger needed to survive one experiment "
        "on a cushioned harness, not a production lifetime. A 3D-printed shell "
        "is a product decision; the tooling version needs zip ties and foam.", S["body"]))
    story.append(P(
        "<b>Why no more powerful processor?</b> Measurement, not computation, "
        "was the bottleneck. Earlier phases had already measured on-target CPU "
        "cost for the full estimator bank at well under 3% of the real-time "
        "tick. The ESP32-S3 was vastly more compute than the logging task "
        "required; a bigger processor would have added nothing but board cost "
        "and power draw.", S["body"]))
    story.extend(fig_flow("pub_logger_block_diagram.png", 15.8,
                          "Block diagram of the breadboard flight logger: "
                          "sensor set, shared I²C bus, ESP32-S3 processing "
                          "chain and recording outputs, drawn from the "
                          "hardware table of the DataLogger repository.",
                          fig_no))

    story.append(P("4 · Assembly, and trusting nothing you have not poked",
                   S["h1"]))
    story.append(P(
        "The system was assembled on a breadboard: board, BMP581 breakout and "
        "buzzer on a shared I²C bus, SD card in the onboard slot. Breadboard "
        "construction under vibration is exactly as fragile as it sounds, so "
        "<b>verifiability was designed in rather than assumed</b>:", S["body"]))
    for b in [
        "A <b>probe-mode firmware</b> build was kept as the first-class "
        "diagnostic: on demand it runs an I²C scan with WHO_AM_I / CHIP_ID "
        "disambiguation (the BMP581 answers chip ID 0x50), draws a "
        "labelled-corner LCD diagnostic frame, and sweeps the buzzer.",
        "<b>Connection testing was repeated, not assumed</b> — after assembly "
        "changes and before flight, the scan/ID path re-verified every device "
        "on the bus.",
        "<b>Rough-handling checks</b> stood in for flight vibration: the "
        "assembled unit was shaken and tapped while the stream ran, watching "
        "for dropouts, I²C wedges or SD write stalls — the failure modes that "
        "would silently corrupt a flight recording.",
        "The honest-status convention from the bench programme carried over: "
        "every feature is labelled <i>verified on hardware</i>, "
        "<i>implemented but unverified</i>, or <i>deferred</i>. The buzzer "
        "tone, for example, shipped as “implemented, not acoustically "
        "verified” until it was heard working — a small habit that prevents "
        "bench confidence from masquerading as flight readiness."]:
        story.append(P("•  " + b, S["body"]))

    story.append(P("5 · Four days of AI-assisted integration — built on "
                   "verified foundations", S["h1"]))
    story.append(P(
        "The full logger firmware — 40 Hz timestamped acquisition, the "
        "four-estimator filter bank, three-screen GUI, audio state machine, "
        "USB streaming protocol and SD recording path — came together in "
        "<b>approximately four days of AI-assisted development</b>. The speed "
        "is real, but the sentence needs its second half: <b>it was fast "
        "because it was almost entirely recombination of previously verified "
        "engineering work</b>, and every reused piece had been earned earlier:", S["body"]))
    for b in [
        "The <b>filter bank</b> (C03, D01, S4, S5) was not rewritten. The "
        "frozen, benchmark-validated Python references were ported to C and "
        "<b>host-verified against the Python originals to a worst error of "
        "2.6e-6 m/s</b> before any flight.",
        "The <b>BMP581 driver</b> came from the workbook's validated bring-up "
        "(0x47, cadence read at 40 Hz, on-chip compensation).",
        "The <b>USB streaming protocol</b> (sequence counters, handshake, meta "
        "frames) was lifted from the bench capture toolchain, so the flight "
        "recorder spoke exactly the language the existing analysis pipeline "
        "parsed.",
        "The earlier programme's discipline — frozen configurations, defect "
        "register, replay verification — meant the new tool inherited a test "
        "culture, not just code."]:
        story.append(P("•  " + b, S["body"]))
    story.append(P(
        "AI compressed the implementation phase dramatically. It did not "
        "compress the verification phase, and it did not make engineering "
        "judgment optional. Two examples from the same four days:", S["body"]))
    story.append(P(
        "The LCD refused to render correctly through several rounds of "
        "“obvious” fixes; the actual root causes were a missing COLMOD "
        "(pixel-format) command in the panel init sequence, an active-low "
        "backlight polarity inversion, and an LSB-first font bit order. Each "
        "was found by instrumented diagnosis, not by accepting the first "
        "plausible patch.", S["body"]))
    story.append(P(
        "The onboard IMU initially appeared dead. Rather than accept that or "
        "blame the driver, the investigation walked the whole chain — "
        "driver, bus speed, bit-banged access, reset sequences — before "
        "attributing the fault at the hardware level. The logger flew "
        "barometer-only, and the decision was <i>evidence-based</i>, not "
        "convenience-based.", S["body"]))
    story.append(P(
        "The pattern worth keeping: <b>AI makes the first draft cheap; "
        "engineering verification makes it true.</b> The faster "
        "implementation becomes, the more the value of an experienced "
        "engineer shifts to deciding what to build, what to trust, and what "
        "must be proven before the result is believed.", S["body"]))

    story.append(P("6 · The flight", S["h1"]))
    story.append(P(
        "The assembled breadboard logger — display board, barometer breakout, "
        "buzzer, microSD card — flew on a real paragliding flight. In-flight "
        "photographs of the unit under the harness are held as externally "
        "supplied assets (see the asset manifest) and will accompany the "
        "website article.", S["body"]))
    story.append(P("The recording it brought back exceeded what the bench "
                   "could ever provide:", S["body"]))
    for b in [
        "<b>761.65 seconds</b> of device time — launch, sustained thermalling "
        "between 900 and 990 m, and landing rollout.",
        "<b>30,467 barometric samples at 40.0 Hz</b> with zero sequence gaps, "
        "duplicates, malformed lines or timestamp discontinuities.",
        "A coherent flight profile: climb-out from ~927 m at launch, repeated "
        "thermal climbs and transitions, flare, and a quiet landing rollout."]:
        story.append(P("•  " + b, S["body"]))
    story.extend(fig_flow("pub_linkedin_flying_the_breadboard.png", 16.0,
                          "Final approach, landing and rollout of the flight "
                          "(t = 588–668 s): four frozen variometer filters "
                          "replayed offline on the recorded BMP581 stream, "
                          "against the pressure-derived reference and the "
                          "+0.20 m/s audio threshold. The steep sink burst, "
                          "flare and quiet rollout visible here are the data "
                          "no bench test could produce. Verified plot, "
                          "reports/flight/linkedin_flying_the_breadboard.png.",
                          fig_no))
    story.append(P(
        "One afternoon of real air produced more decision-relevant "
        "information than the preceding weeks of proxy testing: what the "
        "pressure stream actually looks like at thermal onsets, how much lag "
        "the filters really exhibit against the pressure-derived reference "
        "(about <b>0.6–0.7 s</b>, after a correction to the analysis that had "
        "initially reported ~2.1 s — see the companion article), how the "
        "audio policy behaves in turbulent, near-threshold air, and which "
        "responsiveness-versus-smoothness trade-off actually matters to a "
        "pilot.", S["body"]))

    story.append(P("7 · What the breadboard bought us", S["h1"]))
    story.append(P(
        "The logger answered the flight-data question for the cost of a "
        "US$13 board, a breakout sensor, a handful of jumpers and about four "
        "days of work. Concretely, it:", S["body"]))
    for b in [
        "<b>Eliminated the largest open uncertainty</b> in the programme — "
        "whether bench-derived filter behaviour survives contact with real "
        "air. It does, and now we know quantitatively where and by how much "
        "the bench was right.",
        "<b>Upgraded the filter discussion from rankings to trade-offs</b> — "
        "on flight data the candidates differentiate on quietness, chatter "
        "and transient fidelity, not on correctness. That is a design "
        "conversation, not a bug hunt.",
        "<b>Validated the sensor and recording chain end-to-end</b> — the "
        "BMP581 at 40 Hz with zero integrity defects over 12.7 flight-"
        "minutes, and the SD recording path under real vibration.",
        "<b>Told us what to build next</b> — IMU + GPS in the flight "
        "recorder, multiple estimators logged simultaneously, and a quiet-"
        "soaring flight to firm up the quietness metrics. Requirements "
        "discovered from evidence, not assumed."]:
        story.append(P("•  " + b, S["body"]))

    story.append(P("8 · Lessons", S["h1"]))
    for b in [
        "<b>Engineering judgment decides what deserves to be built.</b> The "
        "custom PCB, the enclosure and the bigger processor were all "
        "reasonable products — and all wrong tools for this question. The "
        "discipline is in matching the investment to the uncertainty: spend "
        "on what reduces risk, defer what does not.",
        "<b>Rapid feedback beats speculative perfection.</b> Four days of "
        "tooling plus one flight replaced an unbound amount of bench "
        "extrapolation. A rough answer to the right question is worth more "
        "than a precise answer to the wrong one.",
        "<b>AI reduces implementation time; it does not eliminate "
        "verification.</b> It changed what the engineer's day looks like — "
        "more deciding, diagnosing and checking; less typing — but the "
        "record of what is verified, and the responsibility for it, stays "
        "human.",
        "<b>A breadboard can fly.</b> Not elegantly, not forever — but long "
        "enough to turn a guess into a measurement. That is often all a "
        "development tool needs to do."]:
        story.append(P("•  " + b, S["body"]))

    story.append(spacer(6))
    story.append(P("Sources and evidence trail", S["h2"]))
    for b in [
        "ESP32-S3-Display-DataLogger repository (github.com/raghavmalik89): "
        "hardware table, pinout, probe-mode diagnostics, filter-port "
        "verification (worst error 2.6e-6 m/s), module status matrix.",
        "vario-usb-workbook repository (github.com/raghavmalik89): bench rig, "
        "filter benchmark phases, BMP581 bring-up, USB protocol, on-target "
        "CPU measurements, flight benchmark at commit 53907ab.",
        "Companion article: <i>From Flight Data to Filter Decisions</i> — "
        "the corrected flight benchmark and all quantitative filter findings "
        "referenced above.",
        "In-flight photographs: externally supplied assets (owner to "
        "provide; see asset manifest)."]:
        story.append(P("•  " + b, S["body"]))

    build(story, REPORT1_PDF, "A Flying Breadboard",
          ["A Product Development Story",
           "How a US$13 display board, a barometric breakout and four days of "
           "AI-assisted integration replaced weeks of guessing about how a "
           "variometer behaves in real air."])


# ================================================================ REPORT 2
def report2():
    fig_no, tbl_no = [0], [0]
    story = []

    story.append(P("1 · Executive summary", S["h1"]))
    story.append(P(
        "The first real paragliding flight recording from the project's "
        "temporary breadboard logger is of <b>excellent integrity</b>: "
        "761.65 s of device time, 30,467 barometer samples at 40.0 Hz and "
        "15,169 vario samples at 19.9 Hz, with zero sequence gaps, "
        "duplicates, malformed lines or timestamp discontinuities.", S["body"]))
    for b in [
        "<b>The bench pipeline is flight-faithful.</b> The bench Python C03 "
        "reproduces the device-recorded C03 to <b>3.3 mm/s RMS</b> — the "
        "filter-versus-filter comparison is apples-to-apples.",
        "<b>Effective tracking lag is 0.57–0.70 s</b> on real thermal "
        "transitions. This report corrects an erroneous ~2.1 s figure from "
        "the first version of the analysis (§5.3).",
        "All four filters track the flight well; the differences are "
        "<b>matters of degree, not kind</b>. S4/S5 are measurably quieter "
        "(60 vs 67 mm/s RMS; 114 vs 137 mm/s p95) and chatter less (71/80 "
        "vs 93/96 audio episodes); C03/D01 have measurably better transient "
        "shape after delay compensation (134 vs 197–211 mm/s fast-motion "
        "RMS error) and slightly lower overshoot.",
        "On this dataset the evidence supports <b>S4 as the airborne "
        "default for the next flight</b>, with C03 retained as the verified "
        "reference. This is a measured-evidence-based recommendation, not a "
        "universal verdict — §7 states exactly what evidence would reverse "
        "it."]:
        story.append(P("•  " + b, S["body"]))

    story.append(P("2 · Recording setup and sensor configuration", S["h1"]))
    story.append(P(
        "The recording was made by the temporary ESP32-S3 flight logger "
        "described in the companion article: a Waveshare ESP32-S3-LCD-1.9 "
        "board with a BMP581 barometric breakout, logging to microSD during a "
        "paragliding flight. Sensor configuration, as validated during "
        "bring-up and unchanged for the flight:", S["body"]))
    for b in [
        "<b>BMP581</b> on the shared I²C bus at 0x47 (chip ID 0x50), "
        "oversampling ×16 pressure / ×2 temperature, ODR 40 Hz, on-chip IIR "
        "bypass, cadence read; on-chip compensated output Pa = raw24/64.",
        "One session marker (<i>S,1</i>) at file start; boot-persistent "
        "sequence counters; record types B (barometer) and V (vario).",
        "Recording firmware logged the <b>C03 estimator only</b> in V frames; "
        "D01, S4 and S5 are evaluated by offline replay on the recorded B "
        "stream (§4).",
        "<b>No IMU data</b> exists in this recording (§8)."]:
        story.append(P("•  " + b, S["body"]))
    story.append(P(
        "Pressure-to-altitude conversion throughout is the ISA model below, "
        "spot-verified against the logger's own altitude field (e.g. raw "
        "5,803,000 -> 90,671.9 Pa -> 927.1 m, matching the recorded 927,204 mm "
        "within 8 mm; median offset across the file 7.6 mm).", S["body"]))
    story.append(spacer(4))
    story.append(formula("isa", r"z = 44330\left(1-(p/101325)^{0.1903}\right)\ \mathrm{[m]}"))

    story.append(P("3 · Measurement integrity", S["h1"]))
    tbl_flow(story,
             ["Item", "Value"],
             [["Recording span (device timestamps)", "<b>761.65 s</b> (12 min 41.6 s)"],
              ["Barometer (B) rows", "<b>30,467</b>"],
              ["Barometer rate", "<b>40.00 Hz</b> (dt median 24.991 ms, p99 25.106 ms, max 25.421 ms)"],
              ["Vario (V) rows", "15,169"],
              ["Vario rate", "19.92 Hz (dt median 50.004 ms)"],
              ["B / V sequence integrity", "<b>zero gaps, zero duplicates</b>"],
              ["Malformed lines", "<b>0</b> of 45,637"],
              ["B timestamps", "strictly monotonic; no gaps > 100 ms"],
              ["Session markers", "exactly one (S,1,793567662,1,1) — one continuous session"],
              ["Filters in V rows", "C03 only"],
              ["IMU rows", "none"],
              ["End of file", "normal data rows; last V row 15 ms after last B row — no truncation"]],
             [6.4 * cm, 9.2 * cm], tbl_no,
             caption="Integrity audit of LOG00001 (device-side facts).")
    story.append(P(
        "The profile is a coherent paragliding sortie (fig. 1): launch and "
        "initial climb near t = 0 from ~927 m, sustained thermalling with "
        "altitude excursions between 900 and 990 m, and a landing rollout at "
        "~917 m from t ~ 655 s onward — the flat quiet tail used for the "
        "noise metrics of §5.", S["body"]))
    story.append(P(
        "<i>Recording-side observation (no impact on this analysis):</i> "
        "the filename LOG00001(2).CSV and non-zero boot counters suggest "
        "filename reuse across reboots; whether the SD firmware rotates, "
        "appends or overwrites on collision could not be confirmed from this "
        "repository. The analyzed file is complete and self-consistent; a "
        "filename-allocation audit is queued for the recording-firmware "
        "owner.", S["body"]))
    story.extend(fig_flow("pub_fig1_overview.png", 16.2,
                          "Full-flight altitude (top) and vertical-speed "
                          "history with all four filters and the audio "
                          "thresholds (bottom). Verified plot, "
                          "reports/flight/fig1_overview.png.", fig_no))

    story.append(P("4 · Methodology: replay, reference, and metric hygiene",
                   S["h1"]))
    story.append(P(
        "<b>Replay.</b> All four filters were replayed on the recorded B "
        "stream at real device timestamps (dt from consecutive differences), "
        "deterministic causal updates, using the frozen, previously validated "
        "Python implementations: <b>C03</b> — CV Tracker, q = 1.0, r = 0.035; "
        "<b>D01</b> — CV Kalman, q = 1.0, r = 0.035; <b>S4</b> — fast/slow "
        "gated architecture, frozen P4 parameters; <b>S5</b> — robust CV "
        "Kalman (light gate), frozen P4 parameters. Audio policy: ON at "
        "v &gt; +0.20 m/s, OFF at v &lt; +0.05 m/s, applied identically to "
        "each replayed output and to the device-recorded C03.", S["body"]))
    story.append(P(
        "<b>Reference.</b> The pressure-derived reference velocity is a "
        "two-stage Savitzky–Golay filter (81-tap on altitude -> gradient -> "
        "41-tap on velocity). The SG window is symmetric about its centre, so "
        "the filter is <b>zero-phase</b> and the reference is already "
        "time-aligned.", S["body"]))
    story.append(P(
        "<b>Pipeline verification.</b> Replaying C03 and aligning against the "
        "device's own V values gives best agreement at -1 B-sample (-25 ms — "
        "one 20 Hz V-sample quantization, consistent with causal filtering) "
        "with <b>3.3 mm/s RMS</b> excluding the first 5 s (shared "
        "initialization transient; worst single deviation 1.40 m/s at "
        "t = 0.075 s). Audio episodes: 93 replayed vs 94 recorded — agreement "
        "within one episode over 12.7 minutes.", S["body"]))
    story.append(P("<b>Metric hygiene</b> — two rules that keep the numbers "
                   "honest:", S["body"]))
    story.append(P(
        "1. <b>Delay and shape error are measured separately.</b> Raw "
        "cross-correlation lag on detected transitions (|ref| &gt; 0.5 m/s "
        "sustained >= 3 s; 46 detected, 44 retained after rejecting windows "
        "whose xcorr peak fell on the edge) gives the effective tracking lag; "
        "overshoot and settling are then computed against a "
        "<b>delay-compensated</b> reference so they measure shape, not "
        "delay.", S["body"]))
    story.append(P(
        "2. <b>Settling/overshoot windows are capped at the next transition "
        "start</b> — thermalling transitions are often only 5–10 s apart, and "
        "an uncapped 8 s window would integrate the next thermal burst.", S["body"]))

    story.append(P("5 · Quantitative comparison", S["h1"]))
    story.append(P(
        "All values measured as described above. “Delay” is the effective "
        "cross-correlation lag on real thermal transitions against the aligned "
        "pressure-derived reference — a proxy for tracking responsiveness. "
        "Treat absolute values with the caveats of §8.", S["body"]))
    tbl_flow(story,
             ["Metric", "C03", "D01", "S4", "S5"],
             [["Quiet RMS (mm/s), 37 s coverage", "67.2", "67.1", "<b>59.8</b>", "<b>59.5</b>"],
              ["Quiet p95 |v| (mm/s)", "137.4", "137.1", "<b>113.9</b>", "112.9"],
              ["Transition delay median (s)", "<b>0.600</b>", "<b>0.575</b>", "0.700", "0.625"],
              ["Transition delay p75 (s)", "0.625", "0.625", "0.750", "0.675"],
              ["Overshoot median, delay-comp (m/s)", "<b>0.277</b>", "0.290", "0.349", "0.361"],
              ["Settling median, delay-comp (s)", "<b>7.98</b>", "8.27", "9.46", "9.71"],
              ["Fast-motion RMS error, raw (m/s)", "0.642", "<b>0.640</b>", "0.732", "0.703"],
              ["Fast-motion RMS error, delay-comp (m/s)", "<b>0.134</b>", "0.145", "0.197", "0.211"],
              ["Fast-motion bias (mm/s)", "2.2", "2.2", "-5.9", "-5.8"],
              ["Output jerk RMS (m/s² per s)", "1.034", "1.085", "<b>0.894</b>", "0.945"],
              ["Audio episodes (+0.20 / -0.05)", "93", "96", "<b>71</b>", "80"],
              ["Audio ON time (s) / duty", "278.5 / 36.6%", "278.8 / 36.6%", "279.7 / 36.7%", "<b>273.5 / 35.9%</b>"],
              ["Mean episode duration (s)", "2.99", "2.90", "<b>3.94</b>", "3.42"],
              ["Proxy false triggers (ON >= 2 s while |ref| &lt; 0.15)", "0", "0", "0", "0"]],
             [6.6 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm, 2.5 * cm], tbl_no,
             center={1, 2, 3, 4},
             caption="Four-filter comparison on the LOG00001 flight "
                     "recording (frozen configurations, 40 Hz replay, "
                     "corrected reference alignment). Bold = best in row.")
    story.extend(fig_flow("pub_fig2_overlay.png", 16.2,
                          "All four filters replayed on identical BMP581 "
                          "pressure input, full flight. The outputs are "
                          "nearly coincident — the differences are matters of "
                          "degree. Verified plot, reports/flight/fig2_overlay.png.",
                          fig_no))

    story.append(P("5.1 · Reading the table", S["h2"]))
    story.append(P(
        "<b>Quietness (fig. 5):</b> S4/S5 are ~16% lower in RMS and ~18% lower "
        "in p95 than C03/D01 in the quiet segments — the largest robust "
        "difference in the study. But quiet coverage is 37 s of landing "
        "rollout only; there is no long quiet-soaring stretch in this "
        "flight.", S["body"]))
    story.append(P(
        "<b>Transient shape (fig. 3):</b> C03/D01 win the delay-compensated "
        "fast-motion error (134–145 vs 197–211 mm/s), overshoot (0.28–0.29 vs "
        "0.35–0.36 m/s) and settling (8.0–8.3 vs 9.5–9.7 s).", S["body"]))
    story.extend(fig_flow("pub_fig3_transitions.png", 15.2,
                          "Three zoomed climb/sink transition windows "
                          "(shaded), showing onset, tracking and exit "
                          "behaviour per filter against the aligned "
                          "reference. Verified plot, "
                          "reports/flight/fig3_transitions.png.", fig_no))
    story.append(P(
        "<b>Chatter (fig. 4):</b> total audio ON-time is nearly identical "
        "across filters (274–280 s of 761 s ~ 36% duty) — all four capture "
        "essentially the same lift. The difference is how that time is broken "
        "up: C03/D01 produce 93–96 short episodes, S4 71 longer ones, S5 80. "
        "With zero proxy false triggers for every filter, the extra episodes "
        "are mostly re-entries around the +0.20 threshold in turbulent, "
        "near-threshold air — not demonstrably wrong, but audible.", S["body"]))
    story.extend(fig_flow("pub_fig5_audio.png", 16.2,
                          "Audio ON-episode timelines per filter versus "
                          "device-recorded C03, over the reference velocity. "
                          "Episode patterns track the same thermal bands; "
                          "S4/S5 group them into fewer, longer episodes. "
                          "Verified plot, reports/flight/fig5_audio.png.",
                          fig_no))
    story.append(P(
        "<b>Delay:</b> all four respond in ~0.6–0.7 s. C03/D01 are "
        "marginally faster (0.58–0.60 s) than S5 (0.63 s) and S4 (0.70 s). "
        "Proportionally the spread is larger than it first appears (S4 ~17% "
        "slower than D01), but in absolute terms all four sit in the same "
        "responsiveness class.", S["body"]))
    story.append(P(
        "<b>Smoothness:</b> S4 has the lowest output jerk (0.894 vs "
        "1.03–1.09), consistent with its gating architecture suppressing "
        "small-scale velocity jitter. C03 and D01 are nearly identical on "
        "every metric, as expected from their shared q/r heritage — the "
        "practical field on this flight is {C03/D01} vs {S4, S5}.", S["body"]))
    story.extend(fig_flow("pub_fig4_quiet.png", 16.2,
                          "Left: landing-rollout quiet segment (37 s total). "
                          "Right: per-filter velocity-distribution histograms "
                          "in the quiet segments — the measurable basis for "
                          "the quietness ranking. Verified plot, "
                          "reports/flight/fig4_quiet.png.", fig_no))
    story.append(P(
        "<b>The responsiveness–smoothness trade-off in one line:</b> C03/D01 "
        "give crisper transients; S4/S5 give quieter output and calmer audio "
        "with slightly softer transient fidelity. Neither class is wrong; "
        "they weight the same measured trade differently.", S["body"]))

    story.append(P("5.2 · Corrected response-lag methodology — why ~2.1 s was "
                   "wrong", S["h2"]))
    story.append(P(
        "The first published version of this analysis reported an effective "
        "lag of ~2.1 s. <b>That value was invalid</b>, for a subtle and "
        "instructive reason.", S["body"]))
    story.append(P(
        "The pressure-derived reference uses a <b>centred (symmetric) "
        "Savitzky–Golay filter</b>. A symmetric SG filter is zero-phase: it "
        "has no group delay to correct. The erroneous run applied a "
        "“group-delay correction” of SG_LAG = 60 samples — a rule that holds "
        "for <i>causal/trailing</i> windows, not for a centred one — "
        "shifting the reference 1.5 s <b>beyond</b> truth. Every "
        "delay-conflated metric inherited exactly that 1.5 s inflation: "
        "filters appeared to lag ~2.1 s when the true lag was ~0.6 s, a "
        "discrepancy confirmed independently by cross-correlation.", S["body"]))
    story.append(P(
        "This revision removes the shift (the corrected script carries a "
        "comment recording the mistake so it is not reintroduced). The "
        "shape-only metrics — delay-compensated overshoot, settling and "
        "fast-motion error — were essentially unaffected, as they should "
        "be. <b>The corrected lag of 0.57–0.70 s is a pressure-derived, "
        "internally consistent estimate of effective tracking "
        "responsiveness.</b> It is not an independently verified physical "
        "response time: with no independent vertical-speed ground truth "
        "(§8), it should be read as “how far each filter trails the best "
        "pressure-only estimate of truth”, not as truth itself.", S["body"]))

    story.append(P("5.3 · Audio threshold behaviour", S["h2"]))
    story.append(P(
        "The +0.20 / -0.05 m/s hysteresis policy behaves on flight data "
        "exactly as designed in the virtual-audio bench work. In turbulent "
        "air near threshold, output hovering around +0.20 m/s produces "
        "clusters of short re-entry episodes (C03/D01) versus fewer, longer "
        "sustained episodes (S4's gating extends mean episode length to "
        "3.9 s). Episode patterns track the same thermal bands across all "
        "four filters, total ON-time is equal, and the proxy false-trigger "
        "screen (ON >= 2 s while the reference is below 0.15 m/s in magnitude) "
        "finds <b>zero</b> violations for every filter. The practical "
        "interpretation: the threshold itself is not generating false lift "
        "indications on this flight; the remaining design lever is how "
        "calmly the threshold is approached — a filter property, not a policy "
        "property.", S["body"]))

    story.append(P("6 · Ranking on this dataset, and the recommended "
                   "default", S["h1"]))
    tbl_flow(story,
             ["Rank", "Filter", "Basis"],
             [["1", "S4",
               "Quietest-class noise, fewest audio episodes, lowest jerk, zero "
               "proxy false triggers; costs are real but bounded (+0.1 s "
               "onset delay, +0.07 m/s median overshoot, +0.06–0.13 m/s "
               "delay-compensated fast-motion error). Best overall "
               "pilot-experience metrics."],
              ["2", "S5",
               "Statistically tied with S4 on quietness; middling chatter; "
               "better fast-motion shape than S4 but worse than C03/D01."],
              ["3", "C03",
               "Best transient fidelity and fastest settling; verified "
               "identical to device firmware; noticeably chattier audio and "
               "noisier quiet output."],
              ["4", "D01",
               "Same behaviour as C03 within measurement noise; no measured "
               "advantage over C03 on this data."]],
             [1.4 * cm, 1.8 * cm, 12.4 * cm], tbl_no, center={0, 1},
             caption="Real-world paragliding ranking — conditional on this "
                     "single flight.")
    story.append(P(
        "<b>Recommended default for the next flight: S4</b>, with C03 "
        "retained as the verified reference implementation. A pilot "
        "prioritizing crisp lift onset over audio calm would rationally pick "
        "C03 instead — both choices are defensible on this data.", S["body"]))
    story.append(P(
        "<b>What would reverse this recommendation:</b> (a) a flight with "
        "long quiet soaring stretches confirming or refuting that the quiet "
        "advantage generalizes beyond landing rollout; or (b) GPS reference "
        "data showing S4's gating misses or delays weak-but-flyable lift "
        "onsets. Either result feeds back before anything is frozen — this "
        "remains a design-space investigation, not a selection.", S["body"]))

    story.append(P("7 · Limitations", S["h1"]))
    for b in [
        "<b>No independent ground truth.</b> No GPS, video or pilot-log "
        "timestamps. All response/error figures use the pressure-derived SG "
        "reference — internally consistent proxies, not truth. The corrected "
        "lag in particular must not be cited as an independently verified "
        "physical response time.",
        "<b>Single flight.</b> One air mass, one pilot, one day. Rankings "
        "are conditional on this dataset.",
        "<b>No IMU data.</b> FUS (baro+IMU fusion) is unevaluable on flight "
        "data; no attitude/acceleration context exists for interpreting "
        "filter behaviour; all fusion gains from bench tests remain "
        "unvalidated in flight.",
        "<b>Limited quiet coverage.</b> The quiet metrics rest on 37 s of "
        "landing rollout; there is no long soaring-quiet stretch in this "
        "flight.",
        "<b>Launch/landing times are inferred</b> from the data, not logged.",
        "<b>Replay scope.</b> D01/S4/S5 were evaluated by offline replay; the "
        "recording firmware logged C03 only. On-target CPU/timing for the "
        "other estimators stands from previous bench phases.",
        "<b>Recording-firmware filename behaviour unverified</b> (§3 "
        "observation)."]:
        story.append(P("•  " + b, S["body"]))

    story.append(P("8 · Next validation experiments", S["h1"]))
    for b in [
        "<b>Log multiple estimators to SD</b> — interleaved V frames for "
        "D01/S4/S5 remove the replay-verification step entirely and give "
        "on-device comparison.",
        "<b>Add IMU + GPS</b> to flight recordings — enables FUS evaluation, "
        "an independent velocity reference, and launch/landing annotation.",
        "<b>A quiet-soaring flight</b> — 20+ minutes of straight-glide/"
        "soaring to firm up the quietness ranking beyond rollout data.",
        "<b>Repeat with S4 airborne</b> to test the §6 recommendation "
        "against weak-lift onsets.",
        "<b>SD filename-rotation audit</b> of the recording firmware (§3)."]:
        story.append(P("•  " + b, S["body"]))

    story.append(spacer(6))
    story.append(P("Reproducibility", S["h2"]))
    for b in [
        "Dataset copy: analysis/flight/LOG00001_flight.csv",
        "Analysis: analysis/flight/flight_analysis.py -> flight_metrics.json + "
        "replay_series.npz; figures: analysis/flight/flight_plots.py -> "
        "reports/flight/",
        "Filter implementations: filter_benchmark/src/filters/ (frozen, "
        "previously validated); workbook revision: commit 53907ab "
        "(corrected reference alignment)",
        "Recording hardware and flight context: companion article <i>A "
        "Flying Breadboard</i> and the ESP32-S3-Display-DataLogger "
        "repository."]:
        story.append(P("•  " + b, S["body"]))

    build(story, REPORT2_PDF, "From Flight Data to Filter Decisions",
          ["A corrected, evidence-based comparison of four frozen variometer "
           "filters on the first real paragliding flight recording.",
           "Dataset LOG00001 · workbook commit 53907ab · November 2026"])


if __name__ == "__main__":
    stage_figures()
    make_logger_diagram()
    report1()
    report2()
