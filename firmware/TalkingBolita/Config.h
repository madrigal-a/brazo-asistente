// =====================================================================
//  Talking Bolita + brazo — configuración de pines y ajustes
//  Placa: ESP32-S3 N16R8 (16 MB flash, 8 MB PSRAM octal)
//  Evitar GPIO 35, 36, 37 (los usa la PSRAM octal), 19/20 (USB nativo),
//  y 0, 3, 45, 46 (pines de arranque).
// =====================================================================
#pragma once

// ---------- Pantalla TFT 2.4" ST7789 (SPI) ----------
#define PIN_TFT_SCK   12   // SCK / SCL
#define PIN_TFT_MOSI  11   // SDI / SDA / MOSI
#define PIN_TFT_MISO  13   // SDO / MISO
#define PIN_TFT_CS    10   // CS
#define PIN_TFT_DC     9   // DC / RS
#define PIN_TFT_RST   14   // RESET / RST
#define PIN_TFT_BL    21   // LED / BL (backlight)

// Si los colores salen invertidos (fondo blanco en vez de azul oscuro),
// cambia TFT_INVERT. Si rojo y azul salen cambiados, cambia TFT_RGB_ORDER.
#define TFT_INVERT     false
#define TFT_RGB_ORDER  false
#define TFT_SPI_HZ     40000000

// ---------- Touch ----------
// Nuestra pantalla NO trae el chip del touch (U1 vacío atrás): se controla con 2 botones.
// Los cables T_CLK, T_CS, T_DIN, T_DO y T_IRQ de la pantalla no se conectan.

// ---------- Amplificador MAX98357 (I2S) ----------
#define PIN_I2S_BCLK   4   // BCLK
#define PIN_I2S_LRC    5   // LRC / WS
#define PIN_I2S_DOUT   6   // DIN del MAX98357
#define AUDIO_RATE  16000

// ---------- Botones (a GND, usan pull-up interno) ----------
#define PIN_BTN_FUNC  15   // FUNCTION: mantener = hablar · en el menú: elegir
#define PIN_BTN_MODE  16   // MODE: abrir menú / siguiente · mantener = salir
// Los dos a la vez = PARO del brazo.

// ---------- Arduino Uno del brazo (UART) ----------
#define PIN_ARM_TX  40   // -> pin 0 (RX) del Uno, directo
#define PIN_ARM_RX  41   // <- pin 1 (TX) del Uno, CON divisor 1k/2k (5 V -> 3.3 V)
#define ARM_BAUD    115200

// ---------- Comunicación con la computadora ----------
#define SERIAL_BAUD  460800   // con 921600 se perdían bytes (ERR checksum); el audio solo necesita ~33 KB/s

// Segundos sin actividad para que la bolita se duerma sola
#define SLEEP_AFTER_S  60
