// =====================================================================
//  Brazo robótico — MODO SOLO (Arduino Uno + PCA9685 + control de potes)
//
//  Úsalo cuando el brazo trabaja SOLITO con el control (bracito con 4
//  potenciómetros + botón), SIN la ESP32. Para usarlo con la ESP sube
//  firmware/BrazoESP en su lugar.
//
//  Qué arregla respecto a la versión anterior (codo y muñeca):
//   1. "Fantasma" del ADC: el Uno tiene UN solo convertidor que se pasa de
//      un pin a otro. Si lees A0 justo después de A1, A0 "recuerda" el voltaje
//      de A1 (sobre todo si el cable del pote está flojo o el pote es de valor
//      alto). Por eso el pote del codo movía la muñeca. Ahora cada pin se lee
//      una vez de sobra (se tira), se espera, y se promedian 4 lecturas.
//   2. Cada pote tiene su propia calibración (recta de 2 puntos), así el codo
//      ya no se queda pegado en el tope (su ADC va de ~140 a ~780).
//   3. Comandos para encontrar el problema en 1 minuto: D, REVISA y BUSCA.
//
//  Comandos (Monitor Serie 115200, "Nueva línea"):
//    P          una lectura: ángulo, ADC y botón de cada pote
//    D          monitor en vivo (4 por segundo). Mueve UN pote y mira qué cambia.
//               Cualquier otro comando lo detiene.
//    REVISA     revisa los cables de cada pote (señal suelta, falta V+ o GND)
//    BUSCA j    (j: 0 base, 1 hombro, 2 codo, 3 muñeca) durante 4 s mueve SOLO
//               ese pote de un tope al otro: dice en qué pin (A0-A3) está y lo
//               aplica al momento. Imprime la línea POT[] para pegar aquí.
//    T c a      PRUEBA: canal c (0-15) del PCA9685 al ángulo a. Sale con MAN.
//    CAL j a    lleva la articulación j al ángulo a y la congela (el control no la mueve)
//    PUNTO n    (1 o 2) "con el control así, el ángulo es a". Imprime CAL_* para pegar.
//    MAN        regresa a seguir al control (sale de T / CAL / BUSCA)
//
//  ⚠ Prende la fuente de servos ANTES o junto con el Uno: los potes toman de ahí su voltaje.
//  Librería: "Adafruit PWM Servo Driver Library"
// =====================================================================
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define MIN_PULSE_WIDTH 650
#define MAX_PULSE_WIDTH 2350
#define FREQUENCY       50

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

enum { BASE, SHOULDER, ELBOW, WRIST, NJ };
const char* NAMES[NJ] = {"base", "hombro", "codo", "muneca"};

// ===================== CONFIGURACIÓN (todo lo que se calibra está aquí) =====================
// ⚠ Si cambias CH, INVERT, LIM_* o HAND_* aquí, cámbialos igual en BrazoESP.ino.
const uint8_t CH[NJ]  = {14, 13, 12, 11};   // canal PCA9685: base, hombro, codo, muñeca (probado con T)
uint8_t       POT[NJ] = {A3, A2, A1, A0};   // pote de: base, hombro, codo, muñeca (Figura 1). BUSCA lo corrige.
const bool INVERT[NJ] = {false, false, false, false};  // true si el servo gira al revés que el control
const uint8_t BTN_PIN = 13;

// Pinza (canal 10), en GRADOS del servo (como T). Calibra con T 10 0, T 10 10 ... sin zumbido.
const uint8_t HAND_CH = 10;
int HAND_OPEN_DEG   = 10;    // botón suelto
int HAND_CLOSED_DEG = 45;    // botón presionado
const bool HAND_RELAX = true; // mano abierta y quieta → apaga su pulso a 1 s (no zumba)

// Calibración de cada pote: cuando el ADC marca CAL_ADC1 el ángulo es CAL_ANG1, y con CAL_ADC2 es CAL_ANG2.
// Base y hombro: mapeo original (ADC 800 → 0°, 240 → 180°), que ya funcionaba.
// Codo y muñeca: estimados de las lecturas del 23 nov (recogido / estirado). Afinar con CAL + PUNTO.
//   codo:   recogido ADC 142 → 175°,  estirado ADC 779 → 10°
//   muñeca: recogido ADC 537 →  84°,  estirado ADC 367 → 139°
int CAL_ANG1[NJ] = {45,  45,  175, 84};
int CAL_ADC1[NJ] = {660, 660, 142, 537};
int CAL_ANG2[NJ] = {135, 135, 10,  139};
int CAL_ADC2[NJ] = {380, 380, 779, 367};

int LIM_MIN[NJ] = {0,   0,   0,   0};      // límites de seguridad en grados
int LIM_MAX[NJ] = {180, 180, 180, 180};
const float MAX_DPS = 300;                 // velocidad máxima siguiendo al control (°/s)
const float DEADBAND = 1.0;                // no mover si el cambio es menor (quita zumbido)
// =============================================================================================

float cur[NJ], tgt[NJ], potA[NJ];
float handCur = 0, handTgt = 0;            // 0..100
bool testMode = false;                     // T: no mover nada más
bool live = false;                         // D: monitor en vivo
int calJoint = -1;                         // CAL: articulación congelada
bool handOff = false;
uint32_t handStillMs = 0;

// ----- Filtro de Kalman 1D para cada potenciómetro -----
// Modelo: x[k] = x[k-1] + w (el pote casi no cambia en 20 ms),  z = x + v (ruido del ADC)
struct Kalman1D { float x, p; };
Kalman1D kf[NJ];
const float KQ = 0.4;   // varianza del proceso
const float KR = 12.0;  // varianza de la medición (cuentas^2)

float kalmanStep(Kalman1D& k, float z) {
  k.p += KQ;
  float g = k.p / (k.p + KR);
  k.x += g * (z - k.x);
  k.p *= (1 - g);
  return k.x;
}

// ----- Lectura del ADC sin "fantasma" del pin anterior -----
int readADC(uint8_t pin) {
  analogRead(pin);                 // 1a lectura: se tira (el capacitor interno aún tiene el pin anterior)
  delayMicroseconds(50);
  int s = 0;
  for (uint8_t i = 0; i < 4; i++) s += analogRead(pin);
  return s / 4;
}

float adcToAngle(int j, float v) {
  if (CAL_ADC2[j] == CAL_ADC1[j]) return 90;
  float a = CAL_ANG1[j] + (v - CAL_ADC1[j]) * (float)(CAL_ANG2[j] - CAL_ANG1[j]) / (CAL_ADC2[j] - CAL_ADC1[j]);
  return constrain(a, 0, 180);
}

uint16_t angleToCounts(float a) {
  float us = MIN_PULSE_WIDTH + a / 180.0 * (MAX_PULSE_WIDTH - MIN_PULSE_WIDTH);
  return (uint16_t)(us / 1000000.0 * FREQUENCY * 4096);
}
uint16_t jointCounts(int j, float a) { return angleToCounts(INVERT[j] ? 180 - a : a); }
float clampJoint(int j, float a) { return constrain(a, LIM_MIN[j], LIM_MAX[j]); }

void setHand(float pct) {
  float a = HAND_OPEN_DEG + (HAND_CLOSED_DEG - HAND_OPEN_DEG) * pct / 100.0;
  pwm.setPWM(HAND_CH, 0, angleToCounts(a));
}

void resetFilter(int j) {
  long s = 0;
  for (int i = 0; i < 8; i++) s += readADC(POT[j]);
  kf[j].x = s / 8.0;
  kf[j].p = KR;
  potA[j] = adcToAngle(j, kf[j].x);
}

const char* pinName(uint8_t pin) {
  switch (pin) { case A0: return "A0"; case A1: return "A1"; case A2: return "A2"; case A3: return "A3"; }
  return "A?";
}

// ----- Diagnóstico -----
void printP() {
  for (int j = 0; j < NJ; j++) {
    Serial.print(NAMES[j]); Serial.print('('); Serial.print(pinName(POT[j])); Serial.print(F(")="));
    Serial.print((int)potA[j]); Serial.print(F("deg adc ")); Serial.print((int)kf[j].x);
    Serial.print(F("  "));
  }
  Serial.print(F("boton "));
  Serial.println(digitalRead(BTN_PIN) == LOW ? F("PRESIONADO") : F("suelto"));
}

// Revisa cada pote: con la resistencia interna (pull-up) encendida un momento,
// un pin con su pote bien conectado casi no cambia; un pin con el cable suelto se va a ~1023.
void revisaCables() {
  Serial.println(F("--- REVISA: no muevas el control ---"));
  for (int j = 0; j < NJ; j++) {
    uint8_t pin = POT[j];
    int normal = readADC(pin);
    pinMode(pin, INPUT_PULLUP);
    delay(3);
    int conPull = readADC(pin);
    pinMode(pin, INPUT);
    delay(3);
    Serial.print(NAMES[j]); Serial.print(F(" (")); Serial.print(pinName(pin)); Serial.print(F("): adc "));
    Serial.print(normal); Serial.print(F(", con pull-up ")); Serial.print(conPull); Serial.print(F(" -> "));
    if (conPull - normal > 250)  Serial.println(F("!! CABLE DE SENAL SUELTO (el pin flota y copia al pote anterior)"));
    // Marca 0 pero con pull-up sube un poco: el pote SÍ está a GND por su pista → no le llega V+.
    else if (normal < 15 && conPull > 25) Serial.println(F("!! NO LE LLEGA V+ (rojo) al pote: el cursor y el GND si estan conectados"));
    else if (normal < 15)        Serial.println(F("!! marca 0: falta el V+ (rojo) del pote, o el pote esta en su tope"));
    else if (normal > 1008)      Serial.println(F("!! marca 1023: falta el GND (negro) del pote, o el pote esta en su tope"));
    else                         Serial.println(F("OK"));
  }
  Serial.println(F("(si dice OK pero el servo no sigue al pote, usa BUSCA y D)"));
}

// BUSCA j: durante 4 s mide el mínimo y máximo de A0..A3 y elige el que más se movió.
void busca(int j) {
  const uint8_t pins[4] = {A0, A1, A2, A3};
  int mn[4], mx[4];
  for (int i = 0; i < 4; i++) { mn[i] = 1023; mx[i] = 0; }
  Serial.print(F("BUSCA ")); Serial.print(NAMES[j]);
  Serial.println(F(": mueve SOLO ese pote de un tope al otro durante 4 s..."));
  uint32_t t0 = millis();
  while (millis() - t0 < 4000) {
    for (int i = 0; i < 4; i++) {
      int v = readADC(pins[i]);
      if (v < mn[i]) mn[i] = v;
      if (v > mx[i]) mx[i] = v;
    }
  }
  int best = 0;
  for (int i = 0; i < 4; i++) {
    Serial.print(pinName(pins[i])); Serial.print(F(": de ")); Serial.print(mn[i]);
    Serial.print(F(" a ")); Serial.print(mx[i]); Serial.print(F("  (rango ")); Serial.print(mx[i] - mn[i]); Serial.println(')');
    if (mx[i] - mn[i] > mx[best] - mn[best]) best = i;
  }
  int range = mx[best] - mn[best];
  if (range < 100) {
    Serial.println(F("!! Ningun pin cambio: ese pote no llega al Uno (revisa sus 3 cables) o no lo moviste."));
    return;
  }
  // ¿Otro pin también se movió mucho? Es "fantasma" o dos potes en el mismo cable.
  for (int i = 0; i < 4; i++)
    if (i != best && mx[i] - mn[i] > range / 2)
      { Serial.print(F("!! ")); Serial.print(pinName(pins[i])); Serial.println(F(" tambien se movio: cable suelto/compartido en ese pin (usa REVISA)")); }
  POT[j] = pins[best];
  resetFilter(j);
  Serial.print(F("=> ")); Serial.print(NAMES[j]); Serial.print(F(" esta en ")); Serial.print(pinName(pins[best]));
  Serial.print(F(". Ya aplicado (hasta que se reinicie). Su ADC va de ")); Serial.print(mn[best]);
  Serial.print(F(" a ")); Serial.println(mx[best]);
  Serial.print(F("Pega en el codigo: uint8_t       POT[NJ] = {"));
  for (int k = 0; k < NJ; k++) { Serial.print(pinName(POT[k])); if (k < NJ - 1) Serial.print(F(", ")); }
  Serial.println(F("};"));
}

void printArray(const __FlashStringHelper* name, int* v) {
  Serial.print(F("int ")); Serial.print(name); Serial.print(F("[NJ] = {"));
  for (int j = 0; j < NJ; j++) { Serial.print(v[j]); if (j < NJ - 1) Serial.print(F(", ")); }
  Serial.println(F("};"));
}

void printCal() {
  Serial.println(F("--- copia estas 4 lineas en BrazoManual.ino ---"));
  printArray(F("CAL_ANG1"), CAL_ANG1);
  printArray(F("CAL_ADC1"), CAL_ADC1);
  printArray(F("CAL_ANG2"), CAL_ANG2);
  printArray(F("CAL_ADC2"), CAL_ADC2);
}

// ----- Comandos -----
char line[32];
uint8_t lineLen = 0;

void handleLine(char* s) {
  live = false;  // cualquier comando detiene el monitor D
  if (s[0] == 'T' && s[1] == ' ') {
    int c, a;
    if (sscanf(s + 1, "%d %d", &c, &a) == 2 && c >= 0 && c <= 15) {
      testMode = true;
      if (c == HAND_CH) handOff = false;
      pwm.setPWM(c, 0, angleToCounts(constrain(a, 0, 180)));
      Serial.print(F("T canal ")); Serial.print(c); Serial.print(F(" -> ")); Serial.println(a);
    }
  } else if (!strcmp(s, "D")) {
    live = true;
  } else if (!strcmp(s, "P")) {
    printP();
  } else if (!strcmp(s, "REVISA")) {
    revisaCables();
  } else if (!strncmp(s, "BUSCA", 5)) {
    int j;
    if (sscanf(s + 5, "%d", &j) == 1 && j >= 0 && j < NJ) busca(j);
    else Serial.println(F("Uso: BUSCA j  (0 base, 1 hombro, 2 codo, 3 muneca)"));
  } else if (!strncmp(s, "CAL", 3)) {
    int j, a;
    if (sscanf(s + 3, "%d %d", &j, &a) == 2 && j >= 0 && j < NJ) {
      testMode = false;
      calJoint = j;
      tgt[j] = clampJoint(j, a);
      Serial.print(F("CAL ")); Serial.print(NAMES[j]); Serial.print(F(" -> ")); Serial.print((int)tgt[j]);
      Serial.println(F("  (pon el control igual que el brazo y escribe PUNTO 1 o PUNTO 2)"));
    } else {
      printCal();
    }
  } else if (!strncmp(s, "PUNTO", 5)) {
    int n;
    if (calJoint < 0) { Serial.println(F("Primero usa CAL j a")); return; }
    if (sscanf(s + 5, "%d", &n) == 1 && (n == 1 || n == 2)) {
      int j = calJoint;
      int adc = (int)(kf[j].x + 0.5);
      if (n == 1) { CAL_ANG1[j] = (int)tgt[j]; CAL_ADC1[j] = adc; }
      else        { CAL_ANG2[j] = (int)tgt[j]; CAL_ADC2[j] = adc; }
      Serial.print(F("Punto ")); Serial.print(n); Serial.print(F(" de ")); Serial.print(NAMES[j]);
      Serial.print(F(": ")); Serial.print((int)tgt[j]); Serial.print(F(" grados = ADC ")); Serial.println(adc);
      if (abs(CAL_ADC2[j] - CAL_ADC1[j]) < 60)
        Serial.println(F("!! Los 2 puntos estan muy cerca: usa angulos mas separados (60+ grados)"));
      printCal();
    }
  } else if (!strcmp(s, "MAN") || !strcmp(s, "HOME")) {
    testMode = false;
    calJoint = -1;
    Serial.println(F("Siguiendo al control"));
  } else {
    Serial.println(F("Comandos: P, D, REVISA, BUSCA j, T c a, CAL j a, PUNTO n, MAN"));
  }
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) { line[lineLen] = 0; handleLine(line); lineLen = 0; }
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(BTN_PIN, INPUT_PULLUP);
  for (int j = 0; j < NJ; j++) pinMode(POT[j], INPUT);
  pwm.begin();
  Wire.beginTransmission(0x40);
  if (Wire.endTransmission() == 0) Serial.println(F("PCA9685 OK (0x40)"));
  else Serial.println(F("!! PCA9685 NO RESPONDE: revisa SDA->A4, SCL->A5, VCC->5V del Uno y GND"));
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(FREQUENCY);
  for (int c = 0; c < 16; c++) pwm.setPWM(c, 0, 4096);  // todos apagados (sueltos)

  // Arranca el filtro ya en la pose del control y enciende los servos uno por uno en esa pose
  for (int j = 0; j < NJ; j++) {
    resetFilter(j);
    cur[j] = tgt[j] = clampJoint(j, potA[j]);
  }
  for (int j = 0; j < NJ; j++) {
    pwm.setPWM(CH[j], 0, jointCounts(j, cur[j]));
    delay(250);
  }
  setHand(0);
  Serial.println(F("BRAZO MANUAL listo (copiando al control). Escribe D para ver los potes en vivo."));
}

void loop() {
  static uint32_t lastStep = 0, lastLive = 0;
  readSerial();

  uint32_t now = millis();
  if (now - lastStep < 20) return;  // 50 Hz
  float dt = (now - lastStep) / 1000.0;
  lastStep = now;

  for (int j = 0; j < NJ; j++) potA[j] = adcToAngle(j, kalmanStep(kf[j], readADC(POT[j])));
  if (live && now - lastLive > 250) { lastLive = now; printP(); }
  if (testMode) return;

  // El control manda: cada articulación sigue a su pote (menos la que se está calibrando)
  for (int j = 0; j < NJ; j++)
    if (j != calJoint) {
      float a = clampJoint(j, potA[j]);
      if (fabs(a - tgt[j]) >= DEADBAND) tgt[j] = a;
    }
  handTgt = digitalRead(BTN_PIN) == LOW ? 100 : 0;

  float maxStep = MAX_DPS * dt;
  for (int j = 0; j < NJ; j++) {
    float step = (j == calJoint) ? 40 * dt : maxStep;
    cur[j] += constrain(tgt[j] - cur[j], -step, step);
    pwm.setPWM(CH[j], 0, jointCounts(j, cur[j]));
  }

  handCur += constrain(handTgt - handCur, -400 * dt, 400 * dt);
  if (HAND_RELAX && handTgt == 0 && handCur <= 0.5) {
    if (!handOff) {
      if (handStillMs == 0) handStillMs = now;
      if (now - handStillMs > 1000) { pwm.setPWM(HAND_CH, 0, 4096); handOff = true; }
      else setHand(handCur);
    }
  } else {
    handStillMs = 0;
    handOff = false;
    setHand(handCur);
  }
}
