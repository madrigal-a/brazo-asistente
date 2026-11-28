// =====================================================================
//  Comunicación con el Arduino Uno del brazo + rutinas (saludar, bailar...)
//  Protocolo de texto: ver BrazoUno.ino
// =====================================================================
#pragma once
#include <Arduino.h>

enum Joint { J_BASE = 0, J_SHOULDER, J_ELBOW, J_WRIST, J_N };
static const char* JOINT_NAMES[J_N] = {"Base", "Hombro", "Codo", "Muneca"};

// Un cuadro clave de una rutina: ángulos (-1 = no cambiar), mano (-1 = no cambiar),
// velocidad en °/s y cuánto esperar antes del siguiente cuadro.
// b = CASA o ESTIRADO usa las poses guardadas en el Uno (HOME_POS / STRETCH_POS).
#define CASA     -2
#define ESTIRADO -3
struct KeyFrame { int16_t b, s, e, w, hand, speed, waitMs; };

// ----- Rutinas: ajusta los ángulos a tu brazo -----
static const KeyFrame R_INICIO[] = {
  {CASA, 0, 0, 0, -1, 60, 1500},
};
static const KeyFrame R_ESTIRAR[] = {
  {ESTIRADO, 0, 0, 0, -1, 60, 2500},
};
// Casa: 90 100 90 · estirado: (base igual) 170 10 (HOME_POS / STRETCH_POS del Uno). Muñeca y pinza sueltas.
static const KeyFrame R_SALUDO[] = {   // = sí: se estira y mueve el codo 10 <-> 15 tres veces
  {ESTIRADO, 0, 0, 0, -1, 80, 2200},
  {-1, -1, 15, -1, -1, 60, 250}, {-1, -1, 10, -1, -1, 60, 250},
  {-1, -1, 15, -1, -1, 60, 250}, {-1, -1, 10, -1, -1, 60, 250},
  {-1, -1, 15, -1, -1, 60, 250}, {-1, -1, 10, -1, -1, 60, 400},
  {CASA, 0, 0, 0, -1, 60, 2000},
};
static const KeyFrame R_BAILE[] = {    // base 50 <-> 140, hombro 160 <-> 165, tres veces
  {50, 160, -1, -1, -1, 90, 1200},
  {140, 165, -1, -1, -1, 120, 750}, {50, 160, -1, -1, -1, 120, 750},
  {140, 165, -1, -1, -1, 120, 750}, {50, 160, -1, -1, -1, 120, 750},
  {140, 165, -1, -1, -1, 120, 750}, {50, 160, -1, -1, -1, 120, 750},
  {CASA, 0, 0, 0, -1, 60, 1800},
};
static const KeyFrame R_AGARRAR[] = {   // sin pinza todavía: no hace nada
  {-1, -1, -1, -1, -1, 60, 100},
};
static const KeyFrame R_SOLTAR[] = {
  {-1, -1, -1, -1, -1, 60, 100},
};
static const KeyFrame R_SUSTO[] = {     // base de lado a lado
  {70, -1, -1, -1, -1, 160, 400}, {110, -1, -1, -1, -1, 160, 450}, {90, -1, -1, -1, -1, 160, 450},
};
static const KeyFrame R_NO[] = {
  {70, -1, -1, -1, -1, 160, 400}, {110, -1, -1, -1, -1, 160, 450},
  {70, -1, -1, -1, -1, 160, 450}, {90, -1, -1, -1, -1, 160, 450},
};
#define R_SI R_SALUDO

struct Routine { const char* name; const KeyFrame* frames; uint8_t n; };
#define RT(name, arr) {name, arr, sizeof(arr) / sizeof(arr[0])}
static const Routine ROUTINES[] = {
  RT("inicio", R_INICIO), RT("estirar", R_ESTIRAR), RT("saludo", R_SALUDO), RT("baile", R_BAILE),
  RT("agarrar", R_AGARRAR), RT("soltar", R_SOLTAR), RT("susto", R_SUSTO),
  RT("si", R_SI), RT("no", R_NO),
};
static const int N_ROUTINES = sizeof(ROUTINES) / sizeof(ROUTINES[0]);

class Arm {
 public:
  int pos[J_N] = {90, 90, 90, 90};  // último estado conocido (o lo que mandamos)
  int hand = 0;
  bool remote = false;
  bool pong = false;  // el Uno contestó un "P" (prueba del UART): la cara sonríe

  void begin(HardwareSerial& s, int rx, int tx, uint32_t baud) {
    _s = &s;
    s.begin(baud, SERIAL_8N1, rx, tx);
  }

  bool online() const { return _lastStatus && millis() - _lastStatus < 1000; }
  bool busy() const { return _rt != nullptr; }

  void sendLine(const char* l) {
    _s->println(l);
  }

  // Mover una articulación (desde los sliders). Se manda a lo más cada 50 ms.
  void setJoint(int j, int a) {
    if (j < 0 || j >= J_N) return;
    stop();
    pos[j] = constrain(a, 0, 180);
    _dirty = true;
    _holdStatusUntil = millis() + 600;
  }

  void setHand(int p) {
    stop();
    hand = constrain(p, 0, 100);
    _s->printf("H %d\n", hand);
    _holdStatusUntil = millis() + 600;
  }

  void speed(int dps) { _s->printf("V %d\n", dps); }

  // Ejecuta una rutina por nombre; si no existe, manda el texto tal cual al Uno.
  bool command(const char* txt) {
    for (int i = 0; i < N_ROUTINES; i++) {
      if (!strcasecmp(txt, ROUTINES[i].name)) { play(ROUTINES[i]); return true; }
    }
    sendLine(txt);
    return false;
  }

  void play(const Routine& r) {
    _rt = &r;
    _frame = 0;
    _frameAt = 0;
  }

  void stop() { _rt = nullptr; }

  void home() { command("inicio"); }

  void update() {
    uint32_t now = millis();
    // Rutina en curso
    if (_rt && now >= _frameAt) {
      if (_frame >= _rt->n) {
        _rt = nullptr;
      } else {
        const KeyFrame& k = _rt->frames[_frame++];
        if (k.speed > 0) speed(k.speed);
        if (k.b == CASA) {
          _s->println("HOME");
        } else if (k.b == ESTIRADO) {
          _s->println("ESTIRA");
        } else {
          int v[J_N] = {k.b, k.s, k.e, k.w};
          _s->printf("J %d %d %d %d\n", v[0], v[1], v[2], v[3]);
          for (int j = 0; j < J_N; j++) if (v[j] >= 0) pos[j] = v[j];
        }
        if (k.hand >= 0) { hand = k.hand; _s->printf("H %d\n", hand); }
        _frameAt = now + k.waitMs;
        _holdStatusUntil = _frameAt;
      }
    }
    // Sliders: manda los ángulos acumulados
    if (_dirty && now - _lastSend > 50) {
      _lastSend = now;
      _dirty = false;
      speed(180);
      _s->printf("J %d %d %d %d\n", pos[0], pos[1], pos[2], pos[3]);
    }
    // Pide el estado al Uno cada 300 ms (si no hay rutina mandando cosas)
    if (now - _lastPoll > 300) { _lastPoll = now; _s->println("?"); }
    // Estado que manda el Uno: "S b h c m mano modo"
    while (_s->available()) {
      char c = _s->read();
      if (c == '\n' || c == '\r') {
        if (_len) { _buf[_len] = 0; parse(_buf); _len = 0; }
      } else if (_len < sizeof(_buf) - 1) {
        _buf[_len++] = c;
      }
    }
  }

 private:
  HardwareSerial* _s = nullptr;
  const Routine* _rt = nullptr;
  uint8_t _frame = 0;
  uint32_t _frameAt = 0, _lastSend = 0, _lastPoll = 0, _lastStatus = 0, _holdStatusUntil = 0;
  bool _dirty = false;
  char _buf[64];
  uint8_t _len = 0;

  void parse(const char* l) {
    // Lo que no sea el estado "S ..." ni el eco de los pasitos "T canal ..." se reenvía a la compu
    // como "UNO <línea>" (sirve para probar el UART: python probar_uart.py)
    if (l[0] != 'S' && strncmp(l, "T canal", 7) != 0) {
      Serial.print("UNO ");
      Serial.println(l);
      if (l[0] == 'P') pong = true;
    }
    int b, s, e, w, h, m;
    if (l[0] == 'S' && sscanf(l + 1, "%d %d %d %d %d %d", &b, &s, &e, &w, &h, &m) == 6) {
      _lastStatus = millis();
      remote = m;
      // Mientras arrastras un slider o corre una rutina, no sobreescribimos lo que mandamos
      if (millis() > _holdStatusUntil && !_rt) {
        pos[0] = b; pos[1] = s; pos[2] = e; pos[3] = w; hand = h;
      }
    }
  }
};
