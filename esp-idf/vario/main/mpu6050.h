/* mpu6050.h — minimal MPU6050 driver (registers/config as Arduino t007). */
#ifndef MPU6050_H
#define MPU6050_H

#include <stdbool.h>
#include <stdint.h>

#include "driver/i2c_master.h"

typedef struct {
    i2c_master_dev_handle_t dev;
    bool ok;
} mpu6050_t;

esp_err_t mpu6050_init(mpu6050_t *m, i2c_master_bus_handle_t bus, uint8_t addr);
/* 14-byte burst: accel XYZ, temp, gyro XYZ (raw int16 counts) */
esp_err_t mpu6050_read(mpu6050_t *m, int16_t out[8]);

#endif
