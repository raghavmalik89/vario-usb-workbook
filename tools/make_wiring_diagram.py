#!/usr/bin/env python3
"""Regenerate docs/test_rig_wiring.png — ESP32-S3 test rig wiring diagram."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

C_3V3, C_GND = "#c0392b", "#222222"
C_SCL_A, C_SDA_A = "#1a5276", "#5dade2"
C_SCL_B, C_SDA_B = "#1e8449", "#7dcea0"
C_SCL_C, C_SDA_C = "#b9770e", "#f0b27a"
C_OPT = "#7f8c8d"

fig, ax = plt.subplots(figsize=(12.5, 7.2), dpi=160)
ax.set_xlim(0, 13); ax.set_ylim(0, 8)
ax.axis("off")

def box(x, y, w, h, title, lines, dashed=False, tcolor="black"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06",
                       fc="#f8f9f9", ec="#34495e", lw=1.4, ls="--" if dashed else "-")
    ax.add_patch(p)
    ax.text(x + w/2, y + h - 0.22, title, ha="center", va="center",
            fontsize=9.5, fontweight="bold", color=tcolor)
    for i, ln in enumerate(lines):
        ax.text(x + 0.18, y + h - 0.55 - i*0.30, ln, ha="left", va="center", fontsize=7.6)

# ---------------- ESP32-S3 (left) ----------------
esp_lines = [
    "USB-C  ->  PC  (capture.py)",
    "",
    "I2C Bus A (hardware I2C0)",
    "  SCL = GPIO5      SDA = GPIO4",
    "I2C Bus B (hardware I2C1)",
    "  SCL = GPIO7      SDA = GPIO6",
    "I2C Bus C (bit-banged, optional)",
    "  SCL = GPIO16     SDA = GPIO15",
    "IMU INT (optional) = GPIO10",
]
box(0.4, 2.1, 3.6, 3.9, "ESP32-S3-DevKitC-1", esp_lines)
ESP_R = 4.0  # right edge of ESP box

# ---------------- Sensors (right) ----------------
box(8.4, 6.05, 4.2, 1.35, "GY-63 #1  (MS5611)", ["addr 0x77  -  Bus A", "VCC GND SCL SDA"], tcolor=C_SCL_A)
box(8.4, 4.35, 4.2, 1.50, "GY-521  (MPU6050)", ["addr 0x68  -  Bus A", "VCC GND SCL SDA AD0 INT", "AD0 -> GND,  INT -> GPIO10 (opt.)"], tcolor=C_SCL_A)
box(8.4, 2.65, 4.2, 1.35, "GY-63 #2  (MS5611)", ["addr 0x77  -  Bus B", "VCC GND SCL SDA"], tcolor=C_SCL_B)
box(8.4, 0.95, 4.2, 1.35, "GY-63 #3  (MS5611)", ["addr 0x77  -  Bus C (soft)", "optional - noise / redundancy"], dashed=True, tcolor=C_SCL_C)
SEN_L = 8.4  # left edge of sensor boxes

# ---------------- Power rails ----------------
ax.plot([0.9, 12.4], [7.85, 7.85], color=C_3V3, lw=2.4)
ax.text(0.55, 7.85, "3V3", fontsize=9, color=C_3V3, fontweight="bold", va="center")
ax.plot([0.9, 12.4], [0.35, 0.35], color=C_GND, lw=2.4)
ax.text(0.55, 0.35, "GND", fontsize=9, color=C_GND, fontweight="bold", va="center")

def rail_tap(x, y_pin, rail_y, color):
    ax.plot([x, x], [y_pin, rail_y], color=color, lw=1.3)
    ax.plot([x - 0.07, x + 0.07], [rail_y, rail_y], color=color, lw=2.6)

# taps: (sensor box left edge x, pin y, box top or bottom)
for x, ytop in [(9.2, 7.40), (10.6, 5.85), (9.2, 4.00), (10.6, 2.30)]:
    rail_tap(x, ytop, 7.85, C_3V3)          # 3V3 down into box top
for x, ybot in [(9.2, 6.05), (10.6, 4.35), (9.2, 2.65), (10.6, 0.95)]:
    rail_tap(x, ybot, 0.35, C_GND)          # GND up into box bottom

# ---------------- Signal wiring ----------------
def wire(points, color, lw=1.8, ls="-"):
    xs = [p[0] for p in points]; ys = [p[1] for p in points]
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, solid_capstyle="round")

# Bus A: GPIO5 SCL (y4.95) -> MS1 SCL, MPU SCL
wire([(ESP_R, 4.95), (5.3, 4.95), (5.3, 6.72), (SEN_L, 6.72)], C_SCL_A)
wire([(5.3, 4.95), (5.3, 5.05), (6.6, 5.05), (6.6, 5.15), (SEN_L, 5.15)], C_SCL_A)
ax.text(4.15, 5.06, "SCL_A  GPIO5", fontsize=7.3, color=C_SCL_A)

# Bus A: GPIO4 SDA (y4.55) -> MS1 SDA, MPU SDA
wire([(ESP_R, 4.55), (4.6, 4.55), (4.6, 6.42), (SEN_L, 6.42)], C_SDA_A)
wire([(4.6, 4.55), (4.6, 4.85), (7.5, 4.85), (7.5, 4.90), (SEN_L, 4.90)], C_SDA_A)
ax.text(4.15, 4.36, "SDA_A  GPIO4", fontsize=7.3, color=C_SDA_A)

# Bus B: GPIO7 SCL -> MS2 SCL ; GPIO6 SDA -> MS2 SDA
wire([(ESP_R, 4.15), (5.9, 4.15), (5.9, 3.32), (SEN_L, 3.32)], C_SCL_B)
ax.text(4.15, 4.22, "SCL_B  GPIO7", fontsize=7.3, color=C_SCL_B)
wire([(ESP_R, 3.75), (7.0, 3.75), (7.0, 3.02), (SEN_L, 3.02)], C_SDA_B)
ax.text(4.15, 3.56, "SDA_B  GPIO6", fontsize=7.3, color=C_SDA_B)

# Bus C (soft, dashed): GPIO16 SCL -> MS3 ; GPIO15 SDA -> MS3
wire([(ESP_R, 3.35), (6.3, 3.35), (6.3, 1.62), (SEN_L, 1.62)], C_SCL_C, ls="--")
ax.text(4.15, 3.42, "SCL_C  GPIO16 (soft)", fontsize=7.3, color=C_SCL_C)
wire([(ESP_R, 2.95), (7.2, 2.95), (7.2, 1.32), (SEN_L, 1.32)], C_SDA_C, ls="--")
ax.text(4.15, 2.76, "SDA_C  GPIO15 (soft)", fontsize=7.3, color=C_SDA_C)

# INT optional (dashed grey)
wire([(ESP_R, 2.55), (7.9, 2.55), (7.9, 4.62), (SEN_L, 4.62)], C_OPT, lw=1.3, ls=":")
ax.text(7.95, 3.4, "INT\nGPIO10", fontsize=6.8, color=C_OPT, ha="left")

# ---------------- Notes ----------------
notes = (
    "MS5611 x3 all ship at addr 0x77 - they CANNOT share a bus. Split across A/B/C.\n"
    "MPU6050 (0x68) does not collide with MS5611, so it shares Bus A.\n"
    "All modules run at 3.3 V logic. Avoid ESP32-S3 strapping pins 0/3/45/46 and USB pins 19/20."
)
ax.text(0.4, 1.55, notes, fontsize=7.6, va="top", color="#34495e",
        bbox=dict(fc="#fef9e7", ec="#b9770e", lw=0.8, boxstyle="round,pad=0.4"))

ax.set_title("Vario USB - bench test rig: ESP32-S3 + 3x GY-63 (MS5611) + MPU6050",
             fontsize=12, fontweight="bold", pad=10)

from pathlib import Path
out = Path(__file__).resolve().parent.parent / "docs" / "test_rig_wiring.png"
fig.savefig(out, bbox_inches="tight")
print("wrote", out)
