@echo off
rem IDF v6.1 via EIM (C:\esp + C:\Espressif\tools). MSYSTEM cleared so any
rem inherited Git Bash env does not confuse tool subprocesses.
set MSYSTEM=
set IDF_PATH=C:\esp\v6.1\esp-idf
set IDF_TOOLS_PATH=C:\Espressif\tools
set IDF_PYTHON_ENV_PATH=C:\Espressif\tools\python\v6.1\venv
set IDF_VERSION=6.1.0
set ESP_IDF_VERSION=6.1
set ESP_ROM_ELF_DIR=C:\Espressif\tools\esp-rom-elfs\20241011
set PATH=C:\Espressif\tools\ccache\4.12.1\ccache-4.12.1-windows-x86_64;C:\Espressif\tools\cmake\4.0.3\bin;C:\Espressif\tools\esp32ulp-elf\2.38_20240113\esp32ulp-elf\bin;C:\Espressif\tools\ninja\1.12.1;C:\Espressif\tools\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin;C:\Espressif\tools\xtensa-esp-elf-gdb\17.1_20260402\xtensa-esp-elf-gdb\bin;C:\Espressif\tools\python\v6.1\venv\Scripts;%PATH%
"%IDF_PYTHON_ENV_PATH%\Scripts\python.exe" "%IDF_PATH%\tools\idf.py" %*
