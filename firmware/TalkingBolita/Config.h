// =====================================================================
//  Talking Bolita + brazo — configuración de pines y ajustes
//  Placa: ESP32-S3 N16R8 (16 MB flash, 8 MB PSRAM octal)
//  Evitar GPIO 35, 36, 37 (los usa la PSRAM octal), 19/20 (USB nativo),
//  y 0, 3, 45, 46 (pines de arranque).
// =====================================================================
#pragma once

// ---------- Pantalla TFT 2.4" ST7789 (SPI) ----------
#define PIN_TFT_SCK   12   // SCK / SCL        (también T_CLK del touch)
#define PIN_TFT_MOSI  11   // SDI / SDA / MOSI (también T_DIN del touch)
#define PIN_TFT_MISO  13   // SDO / MISO       (también T_DO del touch)
#define PIN_TFT_CS    10   // CS
#define PIN_TFT_DC     9   // DC / RS
#define PIN_TFT_RST   14   // RESET / RST
#define PIN_TFT_BL    21   // LED / BL (backlight)

// Si los colores salen invertidos (fondo blanco en vez de azul oscuro),
// cambia TFT_INVERT. Si rojo y azul salen cambiados, cambia TFT_RGB_ORDER.
#define TFT_INVERT     false
#define TFT_RGB_ORDER  false
#define TFT_SPI_HZ     40000000

// ---------- Touch resistivo XPT2046 (comparte SCK/MOSI/MISO con la pantalla) ----------
#define PIN_TOUCH_CS   8   // T_CS
#define PIN_TOUCH_IRQ  7   // T_IRQ (opcional, -1 si no lo conectas)

// ---------- Amplificador MAX98357 (I2S) ----------
#define PIN_I2S_BCLK   4   // BCLK
#define PIN_I2S_LRC    5   // LRC / WS
#define PIN_I2S_DOUT   6   // DIN del MAX98357
#define AUDIO_RATE  16000

// ---------- Botones (a GND, usan pull-up interno) ----------
#define PIN_BTN1  15   // cambiar pantalla: cara <-> control del brazo
#define PIN_BTN2  16   // brazo a INICIO y detener rutina (paro)
// Mantén el botón 2 presionado al encender para recalibrar el touch.

// ---------- Arduino Uno del brazo (UART) ----------
#define PIN_ARM_TX  40   // -> pin 0 (RX) del Uno, directo
#define PIN_ARM_RX  41   // <- pin 1 (TX) del Uno, CON divisor 1k/2k (5 V -> 3.3 V)
#define ARM_BAUD    115200

// ---------- Comunicación con la computadora ----------
#define SERIAL_BAUD  921600

// Segundos sin actividad para que la bolita se duerma sola
#define SLEEP_AFTER_S  60
