/* ms5611.c */
#include "ms5611.h"
#include "config.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define MS5611_RESET      0x1E
#define MS5611_PROM_READ  0xA0
#define MS5611_ADC_READ   0x00

static uint8_t crc4(const uint16_t *prom_in)  /* datasheet CRC-4 over 128 bits */
{
    /* standard MS5611 driver form: CRC nibble of word 7 zeroed before the
     * division; result XORed with 0x0F (application-note convention) */
    uint16_t p[8];
    memcpy(p, prom_in, sizeof(p));
    p[7] = 0xFF00 & p[7];
    uint16_t n_rem = 0;
    for (int cnt = 0; cnt <= 15; cnt++) {
        if (cnt % 2 == 1) n_rem ^= (p[cnt >> 1] & 0x00FF);
        else n_rem ^= (p[cnt >> 1] >> 8);
        for (int n_bit = 8; n_bit > 0; n_bit--) {
            n_rem = (n_rem & 0x8000) ? (uint16_t)((n_rem << 1) ^ 0x3000)
                                     : (uint16_t)(n_rem << 1);
        }
    }
    n_rem = 0x000F & (n_rem >> 12);
    return (uint8_t)(n_rem ^ 0x0F);
}

esp_err_t ms5611_init(ms5611_t *b, i2c_master_bus_handle_t bus, uint8_t addr)
{
    memset(b, 0, sizeof(*b));
    b->addr = addr;
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &dev, &b->dev);
    if (err != ESP_OK) return err;

    /* GY-63 clones sometimes don't respond to the first reset/PROM burst
     * right after power-up (bench: ~3 of 5 boots after a flash, all-zero
     * PROM).  Retry the whole reset+read cycle before declaring dead. */
    for (int attempt = 0; attempt < 4; attempt++) {
        uint8_t cmd = MS5611_RESET;
        err = i2c_master_transmit(b->dev, &cmd, 1,
                                  pdMS_TO_TICKS(I2C_TIMEOUT_MS));
        if (err != ESP_OK) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        vTaskDelay(pdMS_TO_TICKS(10));   /* reset needs ~2.8 ms */

        int rd_ok = 1;
        for (int i = 0; i < 8; i++) {
            uint8_t rd[2] = {MS5611_PROM_READ + (i * 2), 0};
            err = i2c_master_transmit_receive(b->dev, rd, 1, rd, 2,
                                              pdMS_TO_TICKS(I2C_TIMEOUT_MS));
            if (err != ESP_OK) { rd_ok = 0; break; }
            b->prom[i] = (uint16_t)((rd[0] << 8) | rd[1]);
        }
        if (!rd_ok) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        b->ok = ms5611_prom_crc_ok(b);
        if (b->ok) return ESP_OK;
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    return ESP_FAIL;
}

esp_err_t ms5611_start_conv(const ms5611_t *b, uint8_t osr_cmd)
{
    return i2c_master_transmit(b->dev, &osr_cmd, 1,
                               pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}

esp_err_t ms5611_read_adc(const ms5611_t *b, uint32_t *adc24)
{
    uint8_t wr = MS5611_ADC_READ;
    uint8_t rd[3] = {0, 0, 0};
    esp_err_t err = i2c_master_transmit_receive(
        b->dev, &wr, 1, rd, 3, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
    if (err != ESP_OK) return err;
    *adc24 = ((uint32_t)rd[0] << 16) | ((uint32_t)rd[1] << 8) | rd[2];
    return ESP_OK;
}

bool ms5611_prom_crc_ok(const ms5611_t *b)
{
    /* stored CRC is the low nibble of word7.  Genuine MEAS parts store
     * crc4() which ends in ^0x0F (application-note convention); our GY-63
     * clone modules program the raw remainder instead — verified on the
     * bench: A stored 4 == 0xB^0x0F, B stored 7 == 0x8^0x0F.  Accept both. */
    uint8_t stored = (uint8_t)(b->prom[7] & 0x0F);
    uint8_t c = crc4(b->prom);
    return c == stored || (uint8_t)(c ^ 0x0F) == stored;
}

uint8_t ms5611_crc_computed(const ms5611_t *b) { return crc4(b->prom); }
uint8_t ms5611_crc_stored(const ms5611_t *b)
{
    return (uint8_t)(b->prom[7] & 0x0F);
}