/* tx.c — ring buffer + USB Serial/JTAG writer task (see tx.h). */
#include "tx.h"
#include "config.h"

#include <stdio.h>
#include <string.h>

#include "driver/usb_serial_jtag.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static uint8_t s_ring[TX_RING_BYTES];
static volatile uint32_t s_r_head;   /* write index (sampling task) */
static volatile uint32_t s_r_tail;   /* read index (tx task) */
static uint32_t s_highwater;
static uint32_t s_overflows;
static uint32_t s_last_e3_us;
static uint32_t s_seq;
static int s_in_overflow_emit;

/* keepalive meta lines (built once at boot, re-pushed periodically) */
static char s_meta[1024];
static size_t s_meta_len;

static void emitf(const char *fmt, ...);

static uint32_t ring_used(void)
{
    return (s_r_head + TX_RING_BYTES - s_r_tail) % TX_RING_BYTES;
}

static void ring_push(const char *buf, size_t len)
{
    /* one byte of slack distinguishes full from empty */
    uint32_t usable = (TX_RING_BYTES - 1) - ring_used();
    if (len > usable) {                   /* full: drop, count, rare E,3 */
        s_overflows++;
        uint32_t now = (uint32_t)esp_timer_get_time();
        if (!s_in_overflow_emit && now - s_last_e3_us > 200000 && usable > 32) {
            s_in_overflow_emit = 1;
            s_last_e3_us = now;
            emitf("E,%lu,%lu,3\n", (unsigned long)tx_next_seq(),
                  (unsigned long)now);
            s_in_overflow_emit = 0;
        }
        return;
    }
    uint32_t head = s_r_head;
    if (head + len <= TX_RING_BYTES) {
        memcpy(s_ring + head, buf, len);
    } else {
        size_t first = TX_RING_BYTES - head;
        memcpy(s_ring + head, buf, first);
        memcpy(s_ring, buf + first, len - first);
    }
    s_r_head = (head + len) % TX_RING_BYTES;
    uint32_t used = ring_used();
    if (used > s_highwater) s_highwater = used;
}

static void emitf(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (n >= (int)sizeof(buf)) n = sizeof(buf) - 1;
    ring_push(buf, (size_t)n);
}

void tx_init(void)
{
    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = 16384,
        .rx_buffer_size = 256,
    };
    usb_serial_jtag_driver_install(&cfg);
    s_r_head = s_r_tail = 0;
    s_highwater = 0;
    s_overflows = 0;
    s_seq = 0;
    s_last_e3_us = 0;
    s_meta_len = 0;
}

uint32_t tx_next_seq(void) { return s_seq++; }

void tx_p(uint32_t t_us, int sid, uint32_t d1)
{
    emitf("P,%lu,%lu,%d,%lu\n", (unsigned long)tx_next_seq(),
          (unsigned long)t_us, sid, (unsigned long)d1);
}

void tx_t(uint32_t t_us, int sid, uint32_t d2)
{
    emitf("T,%lu,%lu,%d,%lu\n", (unsigned long)tx_next_seq(),
          (unsigned long)t_us, sid, (unsigned long)d2);
}

void tx_i(uint32_t t_us, int16_t ax, int16_t ay, int16_t az,
          int16_t gx, int16_t gy, int16_t gz)
{
    emitf("I,%lu,%lu,%d,%d,%d,%d,%d,%d\n", (unsigned long)tx_next_seq(),
          (unsigned long)t_us, (int)ax, (int)ay, (int)az,
          (int)gx, (int)gy, (int)gz);
}

void tx_e(uint32_t t_us, int code)
{
    emitf("E,%lu,%lu,%d\n", (unsigned long)tx_next_seq(),
          (unsigned long)t_us, code);
}

void tx_v(uint32_t t_us, int eid, int event, int32_t val)
{
    emitf("V,%lu,%lu,%d,%d,%ld\n", (unsigned long)tx_next_seq(),
          (unsigned long)t_us, eid, event, (long)val);
}

void tx_b(const char *payload)
{
    emitf("B,%lu,%lu,%s\n", (unsigned long)tx_next_seq(),
          (unsigned long)esp_timer_get_time(), payload);
}

void tx_meta(const char *line)
{
    /* meta lines: no seq; appended to the keepalive block */
    size_t l = strlen(line);
    if (s_meta_len + l + 1 < sizeof(s_meta)) {
        memcpy(s_meta + s_meta_len, line, l);
        s_meta_len += l;
        s_meta[s_meta_len++] = '\n';
    }
    /* also push immediately (boot block) */
    ring_push(line, l);
    ring_push("\n", 1);
}

void tx_meta_keepalive(void)
{
    if (s_meta_len) ring_push(s_meta, s_meta_len);
}

uint32_t tx_overflow_count(void) { return s_overflows; }
uint32_t tx_ring_highwater(void) { return s_highwater; }

static void tx_task(void *arg)
{
    (void)arg;
    for (;;) {
        uint32_t head = s_r_head, tail = s_r_tail;
        if (head == tail) {
            vTaskDelay(pdMS_TO_TICKS(2));
            continue;
        }
        uint32_t avail = (head >= tail) ? (head - tail)
                                        : (TX_RING_BYTES - tail);
        if (avail > TX_CHUNK_BYTES) avail = TX_CHUNK_BYTES;
        int written = usb_serial_jtag_write_bytes(
            s_ring + tail, avail, pdMS_TO_TICKS(50));
        if (written > 0) {
            s_r_tail = (tail + (uint32_t)written) % TX_RING_BYTES;
        } else if (written < 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
        }
        /* written == 0: host not draining (or detached); data waits in
         * the ring — bounded wait above guarantees this task never wedges */
    }
}

void tx_start_task(void)
{
    xTaskCreatePinnedToCore(tx_task, "tx", 3072, NULL, 8, NULL, 0);
}
