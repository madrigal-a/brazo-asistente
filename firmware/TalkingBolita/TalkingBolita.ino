// =====================================================================
//  Talking Bolita — ESP32-S3
//  La compu escucha y procesa la voz (filtro de Kalman, efectos);
//  la ESP32 dibuja la cara, reproduce el audio, tiene la pantalla touch
//  para controlar el brazo y le manda órdenes al Arduino Uno del brazo.
//
//  Arduino IDE:  Placa "ESP32S3 Dev Module"
//                PSRAM: "OPI PSRAM"   Flash Size: "16MB"
//                Conecta el USB-C marcado COM/UART (no el "USB").
//  Librería:     LovyanGFX (desde el gestor de librerías)
// =====================================================================
#include "Config.h"
#include "Display.h"   // LovyanGFX va ANTES que ESP_I2S (choque de tipos en el core 4.x)
#include "Face.h"
#include "Arm.h"
#include "Ui.h"
#include <ESP_I2S.h>

LGFX tft;
Face face;
Arm arm;
Ui ui;
I2SClass i2s;

// ---------------- Audio: búfer circular en PSRAM ----------------
static const size_t RING_N = AUDIO_RATE * 12;  // 12 s de audio
static int16_t* ring = nullptr;
static volatile size_t rHead = 0, rTail = 0;   // head: escribe la tarea serial; tail: lee la de audio
static volatile bool g_flush = false;
static volatile float g_level = 0;             // volumen de lo que suena (para la boca)
static volatile uint8_t g_volume = 200;
static volatile bool g_playDone = false;

static size_t ringFree() { return (rTail + RING_N - rHead - 1) % RING_N; }

static void ringPush(const int16_t* s, size_t n) {
  size_t f = ringFree();
  if (n > f) n = f;  // si se llena, se descarta lo que sobra
  size_t h = rHead;
  for (size_t i = 0; i < n; i++) {
    ring[h] = s[i];
    h = (h + 1) % RING_N;
  }
  rHead = h;
}

static size_t ringPop(int16_t* out, size_t n) {
  size_t t = rTail, h = rHead, c = 0;
  while (c < n && t != h) {
    out[c++] = ring[t];
    t = (t + 1) % RING_N;
  }
  rTail = t;
  return c;
}

void audioTask(void*) {
  static int16_t mono[256];
  static int16_t st[512];
  bool wasPlaying = false;
  for (;;) {
    if (g_flush) { rTail = rHead; g_flush = false; }
    size_t n = ringPop(mono, 256);
    float acc = 0;
    int vol = g_volume;
    for (int i = 0; i < 256; i++) {
      int32_t v = i < (int)n ? ((int32_t)mono[i] * vol) / 255 : 0;
      st[2 * i] = st[2 * i + 1] = (int16_t)v;  // mismo audio en L y R
      acc += (float)v * v;
    }
    g_level = n ? sqrtf(acc / 256) / 32768.0f : 0;
    if (wasPlaying && n == 0) g_playDone = true;
    wasPlaying = n > 0;
    i2s.write((uint8_t*)st, sizeof(st));  // se bloquea hasta que hay espacio: marca el ritmo
  }
}

// ---------------- Protocolo serial ----------------
// Trama: A5 5A | tipo | largo (2 bytes LE) | datos | checksum (suma de datos & 0xFF)
//  'M' [mood, intensidad 0-255, hold_ds]  expresión (hold en décimas de s, 0 = fija)
//  'L' [x int8, y int8]                   mirada (-100..100)
//  'A' [int16 LE ...]                     audio 16 kHz mono
//  'S' []                                 cortar el audio
//  'V' [0-255]                            volumen
//  'B' [texto]                            orden para el brazo: rutina (saludo, baile...) o comando crudo (J 90 90 90 90)
//  'P' []                                 ping -> responde PONG
struct FaceCmd { char type; int8_t a, b; uint8_t c; char txt[40]; };
QueueHandle_t faceQ;
volatile uint32_t g_lastActivity = 0;

void handleFrame(char type, uint8_t* d, uint16_t len) {
  switch (type) {
    case 'A': ringPush((int16_t*)d, len / 2); g_lastActivity = millis(); break;
    case 'S': g_flush = true; break;
    case 'V': if (len >= 1) g_volume = d[0]; break;
    case 'B': {
      FaceCmd c{'B', 0, 0, 0, {0}};
      memcpy(c.txt, d, len < sizeof(c.txt) - 1 ? len : sizeof(c.txt) - 1);
      xQueueSend(faceQ, &c, 0);
      break;
    }
    case 'P': Serial.println("PONG"); break;
    case 'M':
      if (len >= 3) { FaceCmd c{'M', (int8_t)d[0], (int8_t)d[2], d[1], {0}}; xQueueSend(faceQ, &c, 0); }
      break;
    case 'L':
      if (len >= 2) { FaceCmd c{'L', (int8_t)d[0], (int8_t)d[1], 0, {0}}; xQueueSend(faceQ, &c, 0); }
      break;
  }
}

void serialTask(void*) {
  static uint8_t buf[512];
  alignas(4) static uint8_t payload[2048];
  int state = 0;
  char type = 0;
  uint16_t len = 0, idx = 0;
  uint8_t sum = 0;
  for (;;) {
    int avail = Serial.available();
    if (avail <= 0) { vTaskDelay(1); continue; }
    int n = Serial.read(buf, avail > (int)sizeof(buf) ? sizeof(buf) : avail);
    for (int i = 0; i < n; i++) {
      uint8_t b = buf[i];
      switch (state) {
        case 0: state = (b == 0xA5) ? 1 : 0; break;
        case 1: state = (b == 0x5A) ? 2 : (b == 0xA5 ? 1 : 0); break;
        case 2: type = (char)b; state = 3; break;
        case 3: len = b; state = 4; break;
        case 4:
          len |= (uint16_t)b << 8; idx = 0; sum = 0;
          state = (len > sizeof(payload)) ? 0 : (len == 0 ? 6 : 5);
          break;
        case 5:
          payload[idx++] = b; sum += b;
          if (idx >= len) state = 6;
          break;
        case 6:
          if (b == sum) handleFrame(type, payload, len);
          else Serial.println("ERR checksum");
          state = 0;
          break;
      }
    }
  }
}

// ---------------- Botones ----------------
const int BTN_PINS[2] = {PIN_BTN1, PIN_BTN2};
bool btnPrev[2] = {true, true};
uint32_t btnTime[2] = {0, 0};

void onButton(int i) {
  g_lastActivity = millis();
  Serial.printf("BTN %d\n", i + 1);
  if (i == 0) {
    ui.toggleScreen();
  } else {
    arm.stop();      // paro: detiene la rutina y regresa a inicio
    arm.home();
    face.setMood(SURPRISED, 0.6f, 600);
  }
}

void readButtons() {
  uint32_t now = millis();
  for (int i = 0; i < 2; i++) {
    bool v = digitalRead(BTN_PINS[i]);
    if (v != btnPrev[i] && now - btnTime[i] > 40) {
      btnTime[i] = now;
      btnPrev[i] = v;
      if (!v) onButton(i);  // presionado = LOW
    }
  }
}

// Pitido de arranque para probar la bocina
void bootChirp() {
  static int16_t s[AUDIO_RATE / 4];
  for (int i = 0; i < AUDIO_RATE / 4; i++) {
    float t = (float)i / AUDIO_RATE;
    float f = 600 + 1400 * t * 4;
    float env = sinf(M_PI * i / (AUDIO_RATE / 4));
    s[i] = (int16_t)(6000 * env * sinf(2 * M_PI * f * t));
  }
  ringPush(s, AUDIO_RATE / 4);
}

void setup() {
  for (int i = 0; i < 2; i++) pinMode(BTN_PINS[i], INPUT_PULLUP);

  Serial.setRxBufferSize(32768);
  Serial.begin(SERIAL_BAUD);

  tft.init();
  tft.setRotation(1);  // horizontal 320x240
  tft.setBrightness(220);
  tft.fillScreen(TFT_BLACK);

  ring = (int16_t*)ps_malloc(RING_N * sizeof(int16_t));
  if (!ring || !face.begin(&tft)) {
    tft.setTextColor(TFT_RED);
    tft.setTextSize(2);
    tft.setCursor(10, 100);
    tft.print("Sin PSRAM: elige\n OPI PSRAM en Herramientas");
    while (true) { Serial.println("ERR sin PSRAM"); delay(2000); }
  }

  arm.begin(Serial1, PIN_ARM_RX, PIN_ARM_TX, ARM_BAUD);
  ui.begin(&tft, &face, &arm);
  ui.calibrateTouch(digitalRead(PIN_BTN2) == LOW);  // botón 2 al encender = recalibrar

  i2s.setPins(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DOUT);
  if (!i2s.begin(I2S_MODE_STD, AUDIO_RATE, I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("ERR i2s");
  }

  faceQ = xQueueCreate(32, sizeof(FaceCmd));
  xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 5, nullptr, 0);
  xTaskCreatePinnedToCore(serialTask, "serial", 6144, nullptr, 4, nullptr, 0);

  bootChirp();
  face.setMood(HAPPY, 1, 1500);
  g_lastActivity = millis();
  Serial.println("READY TalkingBolita");
  arm.sendLine("?");
}

void loop() {
  static uint32_t last = millis();
  uint32_t now = millis();
  float dt = (now - last) / 1000.0f;
  last = now;
  if (dt > 0.1f) dt = 0.1f;

  FaceCmd c;
  while (xQueueReceive(faceQ, &c, 0) == pdTRUE) {
    if (c.type == 'M') {
      face.setMood((Mood)c.a, c.c / 255.0f, (uint8_t)c.b * 100);
      g_lastActivity = now;
    } else if (c.type == 'L') {
      face.setLook(c.a / 100.0f, c.b / 100.0f);
    } else if (c.type == 'B') {
      arm.command(c.txt);
    }
  }

  readButtons();

  if (g_playDone) { g_playDone = false; Serial.println("DONE"); }

  // Se duerme si nadie le hace caso
  if (now - g_lastActivity > SLEEP_AFTER_S * 1000UL && face.mood() != SLEEPY) {
    face.setMood(SLEEPY);
  }

  arm.update();
  face.setTalkLevel(g_level * 7.0f);
  ui.update(dt);  // touch + dibuja la pantalla activa (~30 ms a 40 MHz)
}
