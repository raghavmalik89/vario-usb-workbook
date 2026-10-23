/* mpu6050.c — register map/config mirrors arduino/t007 exactly:
 * PWR_MGMT_1=0x01 (X-gyro PLL), SMPLRT_DIV=4 (1 kHz/5 = 200 Hz),
 * CONFIG=0x03 (DLPF ~44 Hz), GYRO_CONFIG=0x08 (+-500 dps),
 * ACCEL_CONFIG=0x10 (+-8 g).
 */
#include "mpu6050.h"
#include "config.h"

#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define REG_SMPLRT_DIV   0x19
#define REG_CONFIG       0x1A
#define REG_GYRO_CONFIG  0x1B
#define REG_ACCEL_CONFIG 0x1C
#define REG_PWR_MGMT_1   0x6B
#define REG_ACCEL_XOUT_H 0x3B
#define REG_WHO_AM_I     0x75

static esp_err_t wr(mpu6050_t *m, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = {reg, val};
    return i2c_master_transmit(m->dev, buf, 2, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
}

esp_err_t mpu6050_init(mpu6050_t *m, i2c_master_bus_handle_t bus, uint8_t addr)
{
    memset(m, 0, sizeof(*m));
    i2c_device_config_t dev = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = addr,
        .scl_speed_hz = I2C_FREQ_HZ,
    };
    esp_err_t err = i2c_master_bus_add_device(bus, &dev, &m->dev);
    if (err != ESP_OK) return err;

    uint8_t reg = REG_WHO_AM_I;
    uint8_t id = 0;
    err = i2c_master_transmit_receive(m->dev, &reg, 1, &id, 1,
                                      pdMS_TO_TICKS(I2C_TIMEOUT_MS));
    if (err != ESP_OK) return err;
    if (id != 0x68) return ESP_FAIL;

    if ((err = wr(m, REG_PWR_MGMT_1, 0x01)) != ESP_OK) return err;
    vTaskDelay(pdMS_TO_TICKS(10));   /* PLL settle after sleep exit */
    if ((err = wr(m, REG_SMPLRT_DIV, 4)) != ESP_OK) return err;
    if ((err = wr(m, REG_CONFIG, 0x03)) != ESP_OK) return err;
    if ((err = wr(m, REG_GYRO_CONFIG, 0x08)) != ESP_OK) return err;
    if ((err = wr(m, REG_ACCEL_CONFIG, 0x10)) != ESP_OK) return err;
    m->ok = true;
    return ESP_OK;
}

esp_err_t mpu6050_read(mpu6050_t *m, int16_t out[8])
{
    uint8_t reg = REG_ACCEL_XOUT_H;
    uint8_t rd[14];
    esp_err_t err = i2c_master_transmit_receive(
        m->dev, &reg, 1, rd, 14, pdMS_TO_TICKS(I2C_TIMEOUT_MS));
    if (err != ESP_OK) return err;
    for (int i = 0; i < 8; i++) {
        out[i] = (int16_t)((rd[2 * i] << 8) | rd[2 * i + 1]);
    }
    return ESP_OK;
}
