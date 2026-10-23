idf_component_register(
    SRCS
        "main.c"
        "tx.c"
        "ms5611.c"
        "mpu6050.c"
        "baro_proc.c"
        "estimators.c"
        "madgwick.c"
        "bench.c"
        "../../../filter_benchmark/portable/vario_core/vario_core.c"
    INCLUDE_DIRS
        "."
        "../../../filter_benchmark/portable/vario_core"
    REQUIRES
        esp_driver_i2c
        esp_driver_usb_serial_jtag
        esp_timer
        esp_hw_support
        freertos
)

# double precision for parity with the Python reference implementations
idf_component_get_property(lib ${COMPONENT_NAME} COMPONENT_LIB)
target_compile_definitions(${lib} PRIVATE VARIO_USE_DOUBLE)
