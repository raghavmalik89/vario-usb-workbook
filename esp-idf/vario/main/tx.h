/* tx.h — data link: protocol v1 frames into a ring, drained to USB Serial/JTAG.
 *
 * Design goals (task: "serial logging must not interfere with real-time
 * processing"):
 *  - the sampling task never blocks on USB: it formats into a small stack
 *    buffer and pushes into a large ring; when the ring is full the frame
 *    is dropped and counted (protocol E,3 at most once per 200 ms)
 *  - a dedicated task owns the USB write side; the driver call has a
 *    bounded wait so a detached host can never wedge the system
 *  - integer-only formatting: no float printf in the data path
 *  - meta lines (#...) have no seq; data lines carry the global seq
 */
#ifndef TX_H
#define TX_H

#include <stdint.h>
#include <stdarg.h>

void tx_init(void);
void tx_start_task(void);

/* Global protocol-v1 sequence counter (data lines only). */
uint32_t tx_next_seq(void);

/* Data frame emitters (integer fields only). */
void tx_p(uint32_t t_us, int sid, uint32_t d1);
void tx_t(uint32_t t_us, int sid, uint32_t d2);
void tx_i(uint32_t t_us, int16_t ax, int16_t ay, int16_t az,
          int16_t gx, int16_t gy, int16_t gz);
void tx_e(uint32_t t_us, int code);
void tx_v(uint32_t t_us, int eid, int event, int32_t val);   /* V frame */
void tx_b(const char *payload);                              /* B frame */

/* Meta lines, emitted at boot and re-emitted every 5 s (meta-on-attach:
 * the USB Serial/JTAG driver exposes no DTR, so keepalive meta guarantees
 * a host attaching at any time receives #H/#K/#C without a reset). */
void tx_meta(const char *line);
void tx_meta_keepalive(void);

/* Stats for the B line. */
uint32_t tx_overflow_count(void);
uint32_t tx_ring_highwater(void);

#endif
