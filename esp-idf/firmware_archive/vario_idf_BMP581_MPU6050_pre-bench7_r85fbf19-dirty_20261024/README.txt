vario_idf firmware archive — BMP581 bring-up build (pre-Bench 7)
================================================================
Base commit : 85fbf19 (+ working-tree BMP581 integration, dirty)
Built/flashed: 2026-10-24, verified on rig (board 90:da:72:73:79:e0)

Contents:
  vario_idf.bin       app image (0x10000)
  bootloader.bin      (0x0)
  partition-table.bin (0x8000)
  sdkconfig           build config snapshot

Flash:
  python -m esptool --chip esp32s3 -b 460800 --before default-reset     --after hard-reset write-flash --flash-mode dio --flash-size 2MB     --flash-freq 80m 0x0 bootloader.bin 0x8000 partition-table.bin     0x10000 vario_idf.bin

Rig config (from #C meta, readback-verified):
  BMP581 on Bus B @0x47 (chipid 0x50, rev 0x32), OSR p=x16 t=x2,
  ODR 40 Hz (osr_cfg=0x61, odr_cfg=0xc5), IIR bypass,
  on-chip compensated: pressure Pa = raw24/64, temp C = raw24/65536.
  MPU6050 on Bus A @0x68. Estimators e0..e4 = D01, C03, S4, S5, FUS @ sid0.
  Baro cadence read every 5th 5 ms tick — drdy on this part is NOT
  cleared by data-register reads, so drdy polling emits stale repeats
  (see idf_bmp581_bringup capture, documented fault dataset).
  DEF-011 fixed in baro_proc (scale = p01mbar*10/1000*100).

Verified: analysis/data/20261024_230014_idf_bmp581_bringup2.{csv,json}
  40.0 Hz P frames, dt exactly 25 ms, 98% fresh values,
  96.854 kPa / 379.1 m / 20.9 C, 0 drops, 0 errors.
