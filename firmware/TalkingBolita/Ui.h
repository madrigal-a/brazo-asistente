// =====================================================================
//  Interfaz con 2 botones (la pantalla no trae touch: el chip U1 de atrás viene vacío)
//
//  FUNCTION (GPIO 15)              MODE (GPIO 16)
//  Cara:  mantener = hablar         toque = abrir el menú
//  Menú:  elegir la opción          toque = siguiente opción · mantener = volver a la cara
//  Brazo: mantener = mover          toque = siguiente articulación · mantener = volver al menú
//         toque = cambiar dirección
//  Los dos a la vez = PARO (lo maneja TalkingBolita.ino)
// =====================================================================
#pragma once
#include "Display.h"
#include "Face.h"
#include "Arm.h"

enum Screen { SCR_FACE, SCR_MENU, SCR_ARM };

enum MenuItem { M_SEGUIR, M_PAUSA, M_CANTA, M_SALUDA, M_BAILA, M_MANO, M_INICIO, M_MOVER, M_VOZ, M_PARO, M_N };

class Ui {
 public:
  Screen screen = SCR_FACE;
  bool paused = false;    // en pausa la bolita no escucha (Function no hace nada en la cara)
  bool talking = false;   // Function mantenido: la compu está grabando
  bool paroPedido = false;  // el menú pidió paro; TalkingBolita.ino lo atiende

  void begin(LGFX* tft, Face* face, Arm* arm) {
    _tft = tft; _face = face; _arm = arm;
  }

  // ----- MODE -----
  void onModeTap() {
    switch (screen) {
      case SCR_FACE: screen = SCR_MENU; _sel = M_SEGUIR; break;
      case SCR_MENU: _sel = (_sel + 1) % M_N; break;
      case SCR_ARM:  _joint = (_joint + 1) % J_N; _acc = 0; break;
    }
  }
  void onModeLong() {
    if (screen == SCR_MENU) screen = SCR_FACE;
    else if (screen == SCR_ARM) screen = SCR_MENU;
  }

  // ----- FUNCTION fuera de la cara (en la cara es hablar: lo maneja TalkingBolita.ino) -----
  void onFuncPress() {
    if (screen == SCR_MENU) runItem(_sel);
  }
  void onFuncTap() {  // soltado rápido
    if (screen == SCR_ARM) _dir = -_dir;
  }

  // Llamar en cada cuadro. dt en segundos. funcHeld: Function mantenido > 0.3 s
  void update(float dt, bool funcHeld) {
    switch (screen) {
      case SCR_FACE:
        _face->update(dt, false);
        drawFaceOverlay();
        _face->sprite()->pushSprite(0, 0);
        break;
      case SCR_MENU:
        drawMenu();
        break;
      case SCR_ARM:
        if (funcHeld) {  // mantener Function: la articulación se mueve seguido a HOLD_DPS °/s
          _acc += _dir * HOLD_DPS * dt;
          int d = (int)_acc;
          if (d != 0) {
            int a = constrain(_arm->pos[_joint] + d, 0, 180);
            if (a != _arm->pos[_joint]) _arm->setJoint(_joint, a);
            else _dir = -_dir;  // llegó al tope: la próxima vez va al otro lado
            _acc -= d;
          }
        } else {
          _acc = 0;
        }
        drawArmScreen();
        break;
    }
  }

 private:
  LGFX* _tft = nullptr;
  Face* _face = nullptr;
  Arm* _arm = nullptr;
  int _sel = 0;          // opción del menú
  int _joint = 0;        // articulación en "Mover brazo"
  int _dir = +1;         // dirección al mover
  float _acc = 0;
  static constexpr float HOLD_DPS = 40;  // grados por segundo al mantener Function

  const char* itemLabel(int i) const {
    switch (i) {
      case M_SEGUIR: return "Seguir";
      case M_PAUSA:  return paused ? "Reanudar" : "Pausa";
      case M_CANTA:  return "Canta";
      case M_SALUDA: return "Saluda";
      case M_BAILA:  return "Baila";
      case M_MANO:   return _arm->hand > 50 ? "Abrir mano" : "Cerrar mano";
      case M_INICIO: return "Brazo a inicio";
      case M_MOVER:  return "Mover brazo";
      case M_VOZ:    return "Otra voz";
      case M_PARO:   return "PARO";
    }
    return "";
  }

  void runItem(int i) {
    switch (i) {
      case M_SEGUIR: screen = SCR_FACE; break;
      case M_PAUSA:
        paused = !paused;
        if (paused) _face->setMood(SLEEPY, 1);
        else { _face->setMood(NEUTRAL); _face->setMood(HAPPY, 1, 1500); }
        screen = SCR_FACE;
        break;
      case M_CANTA:
        Serial.println("CANTA");  // la compu manda la canción; la boca se mueve con el audio
        _face->setMood(HAPPY, 1, 2000);
        screen = SCR_FACE;
        break;
      case M_SALUDA: _arm->command("saludo"); _face->setMood(HAPPY, 1, 3000); screen = SCR_FACE; break;
      case M_BAILA:  _arm->command("baile");  _face->setMood(HAPPY, 1, 4000); screen = SCR_FACE; break;
      case M_MANO:   _arm->setHand(_arm->hand > 50 ? 0 : 100); break;  // se queda en el menú
      case M_INICIO: _arm->command("inicio"); screen = SCR_FACE; break;
      case M_MOVER:  screen = SCR_ARM; _joint = 0; _acc = 0; break;
      case M_VOZ:
        Serial.println("VOZ");  // la compu cambia el efecto de voz
        _face->setMood(SURPRISED, 0.7f, 800);
        screen = SCR_FACE;
        break;
      case M_PARO: paroPedido = true; screen = SCR_FACE; break;
    }
  }

  // Encima de la cara: micrófono cuando hablas, letrero cuando está en pausa
  void drawFaceOverlay() {
    auto& s = *_face->sprite();
    if (talking) {
      s.fillCircle(300, 20, 10, TFT_RED);
      s.fillRoundRect(296, 11, 8, 12, 4, TFT_WHITE);  // micrófono
      s.drawFastVLine(300, 23, 4, TFT_WHITE);
    }
    if (paused) {
      s.setTextSize(2);
      s.setTextColor(s.color565(255, 200, 40));
      s.setTextDatum(top_center);
      s.drawString("PAUSA", 160, 6);
      s.setTextDatum(top_left);
    }
  }

  void drawMenu() {
    auto& s = *_face->sprite();
    uint16_t bg = s.color565(18, 22, 44);
    uint16_t accent = s.color565(255, 200, 40);
    uint16_t text = s.color565(230, 235, 255);
    uint16_t dim = s.color565(140, 150, 190);
    s.fillScreen(bg);
    s.setTextSize(1);
    s.setTextColor(dim);
    s.setCursor(4, 5);
    s.print("MENU   Mode: siguiente (mantener: salir)   Fn: elegir");
    s.setTextSize(2);
    for (int i = 0; i < M_N; i++) {
      int y = 20 + i * 22;
      bool sel = (i == _sel);
      if (sel) s.fillRoundRect(2, y, 316, 21, 6, accent);
      s.setTextColor(sel ? bg : (i == M_PARO ? s.color565(255, 90, 90) : text));
      s.setCursor(12, y + 3);
      s.print(itemLabel(i));
    }
    s.pushSprite(0, 0);
  }

  void drawArmScreen() {
    auto& s = *_face->sprite();
    uint16_t bg = s.color565(18, 22, 44);
    uint16_t track = s.color565(50, 60, 100);
    uint16_t accent = s.color565(255, 200, 40);
    uint16_t text = s.color565(230, 235, 255);
    uint16_t dim = s.color565(140, 150, 190);
    s.fillScreen(bg);
    s.setTextSize(1);
    s.setTextColor(text);

    // Estado
    s.setCursor(4, 4);
    if (!_arm->online()) s.print("Uno: sin respuesta");
    else s.print(_arm->remote ? "Uno: modo ESP32" : "Uno: modo potes");
    if (_arm->busy()) { s.setCursor(250, 4); s.setTextColor(accent); s.print("rutina..."); }

    // Sliders (mismo dibujo que antes, a 40 px)
    const int X0 = 82, X1 = 276;
    s.setTextSize(2);
    for (int j = 0; j < J_N; j++) {
      int y = 34 + j * 40;
      bool sel = (j == _joint);
      if (sel) s.drawRoundRect(0, y - 17, 318, 34, 6, TFT_WHITE);
      s.setTextColor(sel ? accent : text);
      s.setCursor(4, y - 7);
      s.print(JOINT_NAMES[j]);
      s.fillRoundRect(X0, y - 4, X1 - X0, 8, 4, track);
      int kx = X0 + _arm->pos[j] * (X1 - X0) / 180;
      s.fillRoundRect(X0, y - 4, kx - X0, 8, 4, accent);
      s.fillCircle(kx, y, sel ? 13 : 11, sel ? TFT_WHITE : accent);
      s.setTextSize(1);
      s.setTextColor(text);
      s.setCursor(X1 + 8, y - 3);
      s.printf("%3d", _arm->pos[j]);
      if (sel) { s.setTextColor(accent); s.print(_dir > 0 ? " +" : " -"); }
      s.setTextSize(2);
    }

    // Ayuda
    s.setTextSize(1);
    s.setTextColor(dim);
    s.setCursor(4, 200);
    s.print("Fn mantener: mover   Fn toque: cambia + / -");
    s.setCursor(4, 216);
    s.print("Mode: siguiente   Mode mantener: menu   Ambos: PARO");
    s.pushSprite(0, 0);
  }
};
