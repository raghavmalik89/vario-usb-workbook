/* ms5611.h — minimal MS5611 driver over the ESP-IDF i2c_master bus.
 * Streams raw 24-bit ADC values; PROM stays readable for #K meta + CRC.
 */
#ifndef MS5611_H
#define MS5611_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/i2c_master.h"

typedef struct {
    i2c_master_dev_handle_t dev;
    uint8_t addr;
    uint16_t prom[8];   /* word0 factory, 1..6 C1..C6, 7 CRC */
    bool ok;
} ms5611_t;

esp_err_t ms5611_init(ms5611_t *b, i2c_master_bus_handle_t bus, uint8_t addr);
esp_err_t ms5611_start_conv(const ms5611_t *b, uint8_t osr_cmd);
esp_err_t ms5611_read_adc(const ms5611_t *b, uint32_t *adc24);
bool ms5611_prom_crc_ok(const ms5611_t *b);
uint8_t ms5611_crc_computed(const ms5611_t *b);
uint8_t ms5611_crc_stored(const ms5611_t *b);

#endif
