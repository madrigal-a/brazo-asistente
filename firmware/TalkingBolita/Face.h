// =====================================================================
//  Cara de la bolita: todo se dibuja con código (sin imágenes), así las
//  expresiones se mezclan suavemente entre sí.
// =====================================================================
#pragma once
#include <math.h>
#include "Display.h"

enum Mood : uint8_t {
  NEUTRAL = 0,  // normal
  LISTEN,       // escuchando (ojos grandes, mira hacia arriba)
  HAPPY,        // feliz (ojos ^ ^, cachetes)
  SURPRISED,    // susto / sorpresa (ojos enormes, boca en "o")
  ANGRY,        // enojado (cejas, se pone rojo)
  SAD,          // triste (azul, mira abajo)
  SLEEPY,       // dormido (párpados, zzz)
  OUCH,         // le picaste (> <)
  MOOD_COUNT
};

// Parámetros que definen una expresión. Todos son float para poder
// interpolar de una expresión a otra.
struct FaceParams {
  float eyeOpen;  // apertura vertical de los ojos
  float eyeW;     // ancho de los ojos
  float pupil;    // tamaño de pupila
  float brow;     // >0 enojado (ceja hacia adentro), <0 triste
  float lidTop;   // párpado de arriba (sueño) 0..1
  float happy;    // ojos ^ ^ 0..1
  float smile;    // -1 triste .. 1 sonrisa
  float mouthO;   // boca en "o" 0..1
  float squash;   // aplastar (+) o estirar (-) el cuerpo
  float blush;    // cachetes 0..1
  float squint;   // ojos > < 0..1
  float r, g, b;  // color del cuerpo
  float lookY;    // hacia dónde mira en vertical
};

static const int FP_N = sizeof(FaceParams) / sizeof(float);

//                               open  w    pup  brow  lid  hap  smile  O    squa   blush sq   r    g    b   lookY
static const FaceParams MOODS[MOOD_COUNT] = {
  /* NEUTRAL   */ {1.00, 1.00, 1.00,  0.0, 0.0, 0.0,  0.40, 0.0,  0.00, 0.30, 0, 255, 200,  40,  0.0},
  /* LISTEN    */ {1.12, 1.00, 1.20,  0.0, 0.0, 0.0,  0.15, 0.15,-0.04, 0.30, 0, 255, 210,  60, -0.35},
  /* HAPPY     */ {1.00, 1.00, 1.00,  0.0, 0.0, 0.9,  1.00, 0.0,  0.05, 0.90, 0, 255, 190,  40,  0.0},
  /* SURPRISED */ {1.40, 1.12, 0.55,  0.0, 0.0, 0.0,  0.00, 1.0, -0.10, 0.20, 0, 255, 225,  90, -0.1},
  /* ANGRY     */ {0.85, 1.00, 0.85,  0.8, 0.0, 0.0, -0.80, 0.0,  0.07, 0.00, 0, 255,  90,  50,  0.1},
  /* SAD       */ {0.90, 1.00, 1.10, -0.65,0.0, 0.0, -0.70, 0.0,  0.08, 0.00, 0, 150, 170, 230,  0.6},
  /* SLEEPY    */ {1.00, 1.00, 1.00,  0.0, 0.72,0.0,  0.00, 0.25, 0.06, 0.20, 0, 230, 180,  60,  0.4},
  /* OUCH      */ {1.00, 1.00, 1.00,  0.3, 0.0, 0.0, -0.60, 0.6,  0.12, 0.60, 1, 255, 120,  70,  0.0},
};

static inline float frand(float a, float b) { return a + (b - a) * (float)(esp_random() % 10000) / 10000.0f; }
static inline float clampf(float v, float a, float b) { return v < a ? a : (v > b ? b : v); }

class Face {
 public:
  bool begin(LGFX* tft) {
    _tft = tft;
    _spr = new LGFX_Sprite(tft);
    _spr->setPsram(true);
    _spr->setColorDepth(16);
    if (!_spr->createSprite(tft->width(), tft->height())) return false;
    _cur = MOODS[NEUTRAL];
    _target = _cur;
    return true;
  }

  // intensity 0..1 mezcla entre NEUTRAL y la expresión.
  // holdMs > 0: la expresión dura ese tiempo y luego regresa a la anterior.
  void setMood(Mood m, float intensity = 1.0f, uint32_t holdMs = 0) {
    if (m >= MOOD_COUNT) return;
    if (holdMs > 0) {
      _tempMood = m;
      _tempIntensity = intensity;
      _holdUntil = millis() + holdMs;
    } else {
      _baseMood = m;
      _baseIntensity = intensity;
      _holdUntil = 0;
    }
  }

  void setLook(float x, float y) {
    _lookTX = clampf(x, -1, 1);
    _lookTY = clampf(y, -1, 1);
    _lastExtLook = millis();
  }

  void setTalkLevel(float lvl) { _talkIn = clampf(lvl, 0, 1); }

  LGFX_Sprite* sprite() { return _spr; }
  bool isTalking() const { return _talk > 0.04f; }

  Mood mood() const { return _holdUntil ? _tempMood : _baseMood; }

  // push=false: dibuja en el sprite sin mandarlo a la pantalla (para dibujar encima)
  void update(float dt, bool push = true) {
    _t += dt;
    uint32_t now = millis();
    if (_holdUntil && now > _holdUntil) _holdUntil = 0;

    Mood m = mood();
    float inten = _holdUntil ? _tempIntensity : _baseIntensity;
    buildTarget(m, inten);

    // Interpolación suave hacia la expresión objetivo
    float k = 1.0f - expf(-dt * 9.0f);
    float* c = (float*)&_cur;
    const float* t = (const float*)&_target;
    for (int i = 0; i < FP_N; i++) c[i] += (t[i] - c[i]) * k;

    // Nivel de voz: sube rápido, baja más lento
    float ka = _talkIn > _talk ? 1.0f - expf(-dt * 30.0f) : 1.0f - expf(-dt * 8.0f);
    _talk += (_talkIn - _talk) * ka;

    // Mirada: si la compu no la controla, mira a lugares al azar
    if (now - _lastExtLook > 3000 && _t > _nextSaccade) {
      _lookTX = (m == SLEEPY) ? 0 : frand(-0.75f, 0.75f);
      _lookTY = frand(-0.35f, 0.35f);
      _nextSaccade = _t + frand(1.2f, 4.0f);
    }
    float kl = 1.0f - expf(-dt * 14.0f);
    _lookX += (_lookTX - _lookX) * kl;
    _lookY += (_lookTY - _lookY) * kl;

    // Parpadeo
    if (_t > _nextBlink && _blinkT < 0) _blinkT = 0;
    float blink = 1.0f;
    if (_blinkT >= 0) {
      _blinkT += dt;
      const float dur = 0.16f;
      if (_blinkT >= dur) {
        _blinkT = -1;
        _nextBlink = _t + (m == SLEEPY ? frand(4, 8) : frand(2, 5.5f));
      } else {
        blink = 1.0f - sinf(M_PI * _blinkT / dur);
      }
    }
    draw(blink, push);
  }

 private:
  LGFX* _tft = nullptr;
  LGFX_Sprite* _spr = nullptr;
  FaceParams _cur, _target;
  Mood _baseMood = NEUTRAL, _tempMood = NEUTRAL;
  float _baseIntensity = 1, _tempIntensity = 1;
  uint32_t _holdUntil = 0, _lastExtLook = 0;
  float _t = 0, _nextBlink = 2, _blinkT = -1, _nextSaccade = 1;
  float _lookX = 0, _lookY = 0, _lookTX = 0, _lookTY = 0;
  float _talk = 0, _talkIn = 0;

  void buildTarget(Mood m, float inten) {
    const float* n = (const float*)&MOODS[NEUTRAL];
    const float* e = (const float*)&MOODS[m];
    float* t = (float*)&_target;
    inten = clampf(inten, 0, 1);
    for (int i = 0; i < FP_N; i++) t[i] = n[i] + (e[i] - n[i]) * inten;
  }

  uint16_t col(float r, float g, float b) {
    return _spr->color565((uint8_t)clampf(r, 0, 255), (uint8_t)clampf(g, 0, 255), (uint8_t)clampf(b, 0, 255));
  }

  void draw(float blink, bool push) {
    auto& s = *_spr;
    const int W = s.width(), H = s.height();
    const FaceParams& p = _cur;

    uint16_t bg = col(18, 22, 44);
    uint16_t body = col(p.r, p.g, p.b);
    uint16_t shade = col(p.r * 0.7f, p.g * 0.7f, p.b * 0.7f);
    uint16_t dark = col(40, 25, 30);
    uint16_t white = TFT_WHITE;

    s.fillScreen(bg);

    // Respiración + rebote al hablar
    float breathe = 0.015f * sinf(_t * 2.2f);
    float squash = p.squash + breathe + _talk * 0.12f * sinf(_t * 25.0f);
    const float R = 98;
    float rx = R * (1 + squash), ry = R * (1 - squash);
    float cx = W / 2.0f;
    float cy = H / 2.0f + 8 + (R - ry) - _talk * 6;

    // Sombra en el piso y cuerpo
    s.fillEllipse(cx, H / 2.0f + 8 + R + 4, rx * 0.8f, 7, col(10, 12, 26));
    s.fillEllipse(cx, cy + 5, rx, ry, shade);
    s.fillEllipse(cx, cy, rx, ry - 3, body);
    // brillo
    s.fillEllipse(cx - rx * 0.45f, cy - ry * 0.55f, 14, 9, col(p.r + 60, p.g + 60, p.b + 60));

    // Ojos
    float ey = cy - ry * 0.18f;
    float ex = rx * 0.38f;
    drawEye(cx - ex, ey, -1, blink, body, dark, white);
    drawEye(cx + ex, ey, +1, blink, body, dark, white);

    // Cachetes
    if (p.blush > 0.05f) {
      float a = p.blush * 0.85f;
      uint16_t pink = col(p.r + (255 - p.r) * a, p.g + (120 - p.g) * a, p.b + (150 - p.b) * a);
      s.fillEllipse(cx - rx * 0.62f, cy + ry * 0.18f, 15, 8, pink);
      s.fillEllipse(cx + rx * 0.62f, cy + ry * 0.18f, 15, 8, pink);
    }

    // Boca
    float my = cy + ry * 0.38f;
    if (_talk > 0.04f) {
      float mrx = 9 + 14 * _talk, mry = 3 + 20 * _talk;
      s.fillEllipse(cx, my, mrx, mry, dark);
      if (mry > 8) s.fillEllipse(cx, my + mry * 0.55f, mrx * 0.6f, mry * 0.35f, col(240, 100, 120));
    } else if (p.mouthO > 0.3f) {
      float o = p.mouthO;
      s.fillEllipse(cx, my, 4 + 8 * o, 5 + 11 * o, dark);
    } else if (p.smile > 0.15f) {
      float rr = 16 + 8 * p.smile, span = 30 + 35 * p.smile;
      s.fillArc(cx, my - rr, rr - 2, rr + 2, 90 - span, 90 + span, dark);
    } else if (p.smile < -0.15f) {
      float rr = 16 - 4 * p.smile, span = 25 - 25 * p.smile;
      s.fillArc(cx, my + rr + 6, rr - 2, rr + 2, 270 - span, 270 + span, dark);
    } else {
      s.fillRoundRect(cx - 9, my - 2, 18, 5, 2, dark);
    }

    // Zzz
    if (mood() == SLEEPY) {
      s.setTextColor(col(200, 210, 255));
      for (int i = 0; i < 3; i++) {
        float ph = fmodf(_t * 0.5f + i / 3.0f, 1.0f);
        s.setTextSize(1 + i);
        s.setCursor(cx + rx * 0.6f + ph * 30 + i * 8, cy - ry - 5 - ph * 40 + i * 10);
        s.print("z");
      }
    }

    if (push) s.pushSprite(0, 0);
  }

  void drawEye(float ex, float ey, int side, float blink, uint16_t body, uint16_t dark, uint16_t white) {
    auto& s = *_spr;
    const FaceParams& p = _cur;

    // Ojos > <
    if (p.squint > 0.5f) {
      float d = -side * 12;  // la punta apunta al centro de la cara
      s.drawWideLine(ex - d, ey - 13, ex + d, ey, 3.5f, dark);
      s.drawWideLine(ex + d, ey, ex - d, ey + 13, 3.5f, dark);
      return;
    }

    float rx = 22 * p.eyeW;
    float ry = 30 * p.eyeOpen * blink;
    if (ry < 3) {  // ojo cerrado
      s.drawWideLine(ex - rx, ey, ex + rx, ey, 2.5f, dark);
      return;
    }
    s.fillEllipse(ex, ey, rx, ry, white);

    // Pupila
    float pr = fminf(12 * p.pupil, fminf(rx, ry) - 1);
    float lx = _lookX, ly = clampf(_lookY + p.lookY, -1, 1);
    float px = ex + lx * fmaxf(rx - pr - 3, 0);
    float py = ey + ly * fmaxf(ry - pr - 3, 0);
    s.fillCircle(px, py, pr, dark);
    s.fillCircle(px - pr * 0.35f, py - pr * 0.4f, fmaxf(pr * 0.3f, 1), white);

    float top = ey - ry - 3, h = 2 * ry + 6;
    // Párpado de arriba (sueño)
    if (p.lidTop > 0.02f) s.fillRect(ex - rx - 3, top, 2 * rx + 6, h * p.lidTop, body);

    // Cejas: enojado (+) baja la esquina interior, triste (-) la exterior
    if (fabsf(p.brow) > 0.03f) {
      float inner = ex - side * (rx + 4);
      float outer = ex + side * (rx + 4);
      float di = fmaxf(p.brow, 0) * h * 0.55f;
      float dO = fmaxf(-p.brow, 0) * h * 0.55f;
      s.fillTriangle(outer, top, inner, top, inner, top + di, body);
      s.fillTriangle(outer, top, inner, top + di, outer, top + dO, body);
    }

    // Ojos felices ^ ^: tapa la parte de abajo con el color del cuerpo
    if (p.happy > 0.02f) {
      float c = ey + ry * (2.3f - 1.4f * p.happy);
      s.fillEllipse(ex, c, rx * 1.15f, ry * 1.1f, body);
    }
  }
};
