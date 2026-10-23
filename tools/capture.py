#!/usr/bin/env python3
"""
capture.py - Vario USB bench rig serial logger.

Reads protocol v1 text frames from the ESP32-S3 (see docs/serial_protocol.md)
and writes a wide-format CSV plus a JSON sidecar with calibration + run stats.

Usage:
    python capture.py --port COM7 --label t001_bench_60s
    python capture.py --auto --baud 921600 --duration 60
    python capture.py --auto --label t002_elevator_run1

CSV columns (wide format, empty fields where not applicable):
    seq,t_us,type,sid,d1,d2,ax,ay,az,gx,gy,gz,eid,ev,val,note
    (eid/ev/val carry V virtual-audio events; note carries B benchmark stats)

Output: analysis/data/<YYYYMMDD_HHMMSS>_<label>.csv (+ .json sidecar)
Ctrl+C stops cleanly and still writes the sidecar with stats.
"""
import argparse
import csv
import json
import queue
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial not found. Install with:  pip install pyserial")

COLS = ["seq", "t_us", "type", "sid", "d1", "d2", "ax", "ay", "az", "gx", "gy", "gz",
        "eid", "ev", "val", "note"]

RE_DATA = re.compile(r"^(?P<type>[PTIEVBN]),(?P<seq>\d+),(?P<t_us>\d+)(?:,(?P<rest>.*))?$")
RE_K = re.compile(r"^#K,(?P<sid>\d+),(?P<vals>\d+(?:,\d+)*)$")
RE_H = re.compile(r"^#H,(?P<name>.+),(?P<ver>.+)$")
RE_C = re.compile(r"^#C,(?P<kv>.*)$")


def auto_port() -> str:
    """Pick the most likely COM port: USB CDC / ESP32 JTAG descriptions."""
    prefs = []
    for p in list_ports.comports():
        desc = f"{p.description} {p.hwid}".lower()
        if any(k in desc for k in ("usb serial", "jtag", "esp32", "usb cdc", "acm")):
            prefs.append(p.device)
    if not prefs:
        avail = [p.device for p in list_ports.comports()]
        sys.exit(f"No USB-serial port found. Available: {avail or '(none)'}")
    return sorted(prefs)[0]


def parse_line(raw: str):
    """Return ('row', list) | ('meta', key, value) | ('bad', reason, raw)."""
    line = raw.strip()
    if not line:
        return None
    if line.startswith("#"):
        m = RE_K.match(line)
        if m:
            return ("meta", f"prom_{m.group('sid')}", m.group("vals"))
        m = RE_H.match(line)
        if m:
            return ("meta", "firmware", f"{m.group('name')} {m.group('ver')}")
        m = RE_C.match(line)
        if m:
            return ("meta", "config", m.group("kv"))
        return ("meta", "other", line)
    m = RE_DATA.match(line)
    if not m:
        return ("bad", "unparseable", line)
    typ, seq, t_us = m.group("type"), int(m.group("seq")), int(m.group("t_us"))
    rest = (m.group("rest") or "").split(",")
    row = {c: "" for c in COLS}
    row.update(seq=seq, t_us=t_us, type=typ)
    try:
        if typ == "P":
            row["sid"], row["d1"] = int(rest[0]), int(rest[1])
        elif typ == "T":
            row["sid"], row["d2"] = int(rest[0]), int(rest[1])
        elif typ == "I":
            for k, v in zip(["ax", "ay", "az", "gx", "gy", "gz"], rest):
                row[k] = int(v)
        elif typ == "E":
            row["sid"] = rest[0]  # error code parked in sid column
        elif typ == "V":        # virtual audio event: eid, ev, val
            row["eid"], row["ev"], row["val"] = int(rest[0]), int(rest[1]), int(rest[2])
        elif typ == "B":        # benchmark stats blob -> note column
            row["note"] = ",".join(rest)
    except (IndexError, ValueError):
        return ("bad", "field-error", line)
    return ("row", row)


def reader_thread(ser, q, stop):
    """Chunked reads + incremental line splitting.

    ser.readline() is a per-byte Python loop and caps the drain rate at
    ~8 KB/s — far below the firmware's ~12 KB/s full-rate stream (measured:
    it filled the device TX ring and cost 469 dropped frames in one run).
    Blocking chunked reads lift the host ceiling by an order of magnitude.
    """
    buf = b""
    while not stop.is_set():
        try:
            data = ser.read(4096)
        except serial.SerialException as e:
            q.put(("bad", f"serial-error: {e}", ""))
            stop.set()
            return
        if not data:
            continue
        buf += data
        while b"\n" in buf:
            raw, buf = buf.split(b"\n", 1)
            q.put(parse_line(raw.decode("utf-8", errors="replace")))
    if buf:
        q.put(parse_line(buf.decode("utf-8", errors="replace")))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="COM port (default: auto-detect)")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--label", default="run", help="run label, e.g. t001_bench")
    ap.add_argument("--duration", type=float, default=0, help="seconds (0 = until Ctrl+C)")
    ap.add_argument("--outdir", default=str(Path(__file__).resolve().parent.parent
                                            / "analysis" / "data"))
    args = ap.parse_args()

    port = args.port or auto_port()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = outdir / f"{stamp}_{args.label}.csv"
    json_path = csv_path.with_suffix(".json")

    print(f"Opening {port} @ {args.baud} ...")
    ser = serial.Serial(port, args.baud, timeout=0.2, write_timeout=1)
    time.sleep(2.0)  # let the board reset / USB CDC settle
    ser.reset_input_buffer()
    try:
        ser.write(b"G")   # firmware stream-start handshake (vario-idf >= 0.1.0)
    except serial.SerialException:
        pass

    meta = {"label": args.label, "started_utc": datetime.now(timezone.utc).isoformat(),
            "port": port, "baud": args.baud, "csv": csv_path.name}
    stats = {"lines_written": 0, "bad_lines": 0, "seq_drops": 0,
             "bytes_read": 0, "errors": {}}
    last_seq = None
    t_start = time.monotonic()
    t_last = t_start
    last_count = 0

    stop = threading.Event()
    q = queue.Queue()
    rt = threading.Thread(target=reader_thread, args=(ser, q, stop), daemon=True)
    rt.start()

    print(f"Logging to {csv_path}  (Ctrl+C to stop)")
    try:
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            while not stop.is_set():
                try:
                    item = q.get(timeout=0.25)
                except queue.Empty:
                    item = None
                if item:
                    kind = item[0]
                    if kind == "row":
                        row = item[1]
                        if last_seq is not None and row["seq"] > last_seq + 1:
                            stats["seq_drops"] += row["seq"] - last_seq - 1
                        last_seq = row["seq"]
                        if row["type"] == "E":
                            stats["errors"][row["sid"]] = stats["errors"].get(row["sid"], 0) + 1
                        w.writerow(row)
                        stats["lines_written"] += 1
                    elif kind == "meta":
                        meta.setdefault("device", {})[item[1]] = item[2]
                    elif kind == "bad":
                        stats["bad_lines"] += 1
                now = time.monotonic()
                if now - t_last >= 1.0:
                    rate = (stats["lines_written"] - last_count) / (now - t_last)
                    print(f"  {stats['lines_written']:>8} lines | "
                          f"{rate:6.0f} lines/s | drops {stats['seq_drops']} | "
                          f"bad {stats['bad_lines']}", flush=True)
                    t_last, last_count = now, stats["lines_written"]
                if args.duration and now - t_start >= args.duration:
                    break
    except KeyboardInterrupt:
        print("\nStopping (Ctrl+C) ...")
    finally:
        stop.set()
        rt.join(timeout=1.0)
        ser.close()

    elapsed = time.monotonic() - t_start
    stats["elapsed_s"] = round(elapsed, 2)
    meta["stats"] = stats
    json_path.write_text(json.dumps(meta, indent=2))
    print(f"\nDone: {stats['lines_written']} lines in {elapsed:.1f}s "
          f"({stats['lines_written']/max(elapsed,1e-9):.0f} lines/s), "
          f"{stats['seq_drops']} seq drops, {stats['bad_lines']} bad lines")
    print(f"CSV:  {csv_path}")
    print(f"Meta: {json_path}")


if __name__ == "__main__":
    main()
