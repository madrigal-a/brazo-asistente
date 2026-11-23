// =====================================================================
//  Interfaz touch: pantalla de la cara y pantalla de control del brazo
// =====================================================================
#pragma once
#include <Preferences.h>
#include "Display.h"
#include "Face.h"
#include "Arm.h"

enum Screen { SCR_FACE, SCR_ARM };

struct UiButton { int16_t x, y, w, h; const char* label; };

class Ui {
 public:
  Screen screen = SCR_FACE;

  void begin(LGFX* tft, Face* face, Arm* arm) {
    _tft = tft; _face = face; _arm = arm;
  }

  // Calibración del touch: se guarda en memoria; se repite si mantienes el botón 2 al encender
  void calibrateTouch(bool force) {
    Preferences prefs;
    prefs.begin("touch", false);
    uint16_t cal[8];
    if (!force && prefs.getBytesLength("cal") == sizeof(cal)) {
      prefs.getBytes("cal", cal, sizeof(cal));
      _tft->setTouchCalibrate(cal);
    } else {
      _tft->fillScreen(TFT_BLACK);
      _tft->setTextColor(TFT_WHITE);
      _tft->setTextSize(2);
      _tft->setTextDatum(middle_center);
      _tft->drawString("Toca cada esquina", _tft->width() / 2, _tft->height() / 2 - 12);
      _tft->drawString("cuando aparezca", _tft->width() / 2, _tft->height() / 2 + 12);
      _tft->calibrateTouch(cal, TFT_YELLOW, TFT_BLACK, 18);
      prefs.putBytes("cal", cal, sizeof(cal));
      _tft->setTextDatum(top_left);
    }
    prefs.end();
  }

  void toggleScreen() { screen = (screen == SCR_FACE) ? SCR_ARM : SCR_FACE; }

  // Llamar en cada cuadro. dt en segundos.
  void update(float dt) {
    int32_t tx, ty;
    bool touching = _tft->getTouch(&tx, &ty) > 0;
    bool down = touching && !_wasTouching;  // recién tocó
    _wasTouching = touching;

    if (screen == SCR_FACE) {
      if (down) {
        if (hit(ICON, tx, ty)) {
          screen = SCR_ARM;
        } else {
          _face->setMood(OUCH, 1, 1200);  // le picaste
          _arm->command("susto");
          Serial.println("TOUCH cara");
        }
      }
      _face->update(dt, false);
      drawIcon();
      _face->sprite()->pushSprite(0, 0);
    } else {
      handleArmTouch(touching, down, tx, ty);
      drawArmScreen();
    }
  }

 private:
  LGFX* _tft = nullptr;
  Face* _face = nullptr;
  Arm* _arm = nullptr;
  bool _wasTouching = false;
  int _dragging = -1;

  // ----- Distribución (pantalla horizontal 320x240) -----
  static constexpr UiButton ICON = {270, 196, 46, 40, "Brazo"};
  static constexpr int SL_X0 = 82, SL_X1 = 276, SL_Y0 = 30, SL_DY = 40;
  UiButton _btns[5] = {
    {4, 192, 59, 44, "Mano"},
    {67, 192, 59, 44, "Inicio"},
    {130, 192, 59, 44, "Saluda"},
    {193, 192, 59, 44, "Baila"},
    {256, 192, 60, 44, "Cara"},
  };

  static bool hit(const UiButton& b, int x, int y) {
    return x >= b.x && x < b.x + b.w && y >= b.y && y < b.y + b.h;
  }

  int sliderY(int j) const { return SL_Y0 + j * SL_DY; }

  void handleArmTouch(bool touching, bool down, int x, int y) {
    if (!touching) { _dragging = -1; return; }
    if (down) {
      _dragging = -1;
      for (int j = 0; j < J_N; j++)
        if (abs(y - sliderY(j)) < SL_DY / 2 && x > SL_X0 - 20) _dragging = j;
      if (_dragging < 0) {
        for (int i = 0; i < 5; i++) if (hit(_btns[i], x, y)) pressButton(i);
      }
    }
    if (_dragging >= 0) {
      int a = (int)((x - SL_X0) * 180.0f / (SL_X1 - SL_X0));
      a = constrain(a, 0, 180);
      if (a != _arm->pos[_dragging]) _arm->setJoint(_dragging, a);
    }
  }

  void pressButton(int i) {
    switch (i) {
      case 0: _arm->setHand(_arm->hand > 50 ? 0 : 100); break;
      case 1: _arm->command("inicio"); break;
      case 2: _arm->command("saludo"); _face->setMood(HAPPY, 1, 3000); break;
      case 3: _arm->command("baile"); _face->setMood(HAPPY, 1, 4000); break;
      case 4: screen = SCR_FACE; break;
    }
  }

  void drawIcon() {
    auto& s = *_face->sprite();
    s.fillRoundRect(ICON.x, ICON.y, ICON.w, ICON.h, 8, s.color565(40, 50, 90));
    // bracito simple: base, dos segmentos y pinza
    uint16_t c = s.color565(220, 230, 255);
    int bx = ICON.x + 12, by = ICON.y + 32;
    s.fillRect(bx - 6, by, 14, 4, c);
    s.drawWideLine(bx, by, bx + 8, by - 16, 2, c);
    s.drawWideLine(bx + 8, by - 16, bx + 24, by - 22, 2, c);
    s.drawWideLine(bx + 24, by - 22, bx + 30, by - 16, 1.5f, c);
    s.drawWideLine(bx + 24, by - 22, bx + 31, by - 25, 1.5f, c);
  }

  void drawArmScreen() {
    auto& s = *_face->sprite();
    uint16_t bg = s.color565(18, 22, 44);
    uint16_t track = s.color565(50, 60, 100);
    uint16_t accent = s.color565(255, 200, 40);
    uint16_t text = s.color565(230, 235, 255);
    s.fillScreen(bg);
    s.setTextSize(1);
    s.setTextColor(text);

    // Estado
    s.setCursor(4, 4);
    if (!_arm->online()) s.print("Uno: sin respuesta (revisa RX/TX)");
    else s.print(_arm->remote ? "Uno: modo ESP32" : "Uno: modo potenciometros");
    if (_arm->busy()) { s.setCursor(250, 4); s.setTextColor(accent); s.print("rutina..."); }

    // Sliders
    s.setTextSize(2);
    for (int j = 0; j < J_N; j++) {
      int y = sliderY(j);
      s.setTextColor(text);
      s.setCursor(4, y - 7);
      s.print(JOINT_NAMES[j]);
      s.fillRoundRect(SL_X0, y - 4, SL_X1 - SL_X0, 8, 4, track);
      int kx = SL_X0 + _arm->pos[j] * (SL_X1 - SL_X0) / 180;
      s.fillRoundRect(SL_X0, y - 4, kx - SL_X0, 8, 4, accent);
      s.fillCircle(kx, y, _dragging == j ? 13 : 11, _dragging == j ? TFT_WHITE : accent);
      s.setTextSize(1);
      s.setCursor(SL_X1 + 10, y - 3);
      s.printf("%3d", _arm->pos[j]);
      s.setTextSize(2);
    }

    // Botones
    s.setTextSize(1);
    s.setTextDatum(middle_center);
    for (int i = 0; i < 5; i++) {
      const UiButton& b = _btns[i];
      bool on = (i == 0 && _arm->hand > 50);
      s.fillRoundRect(b.x, b.y, b.w, b.h, 8, on ? accent : track);
      s.setTextColor(on ? bg : text);
      const char* label = (i == 0) ? (_arm->hand > 50 ? "Abrir" : "Cerrar") : b.label;
      s.drawString(label, b.x + b.w / 2, b.y + b.h / 2);
    }
    s.setTextDatum(top_left);
    s.pushSprite(0, 0);
  }
};
