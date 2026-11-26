// =====================================================================
//  Brazo robótico — CON ESP32 (Arduino Uno + PCA9685 + control de potes)
//
//  Es BrazoManual.ino (lectura de potes sin "fantasma", calibración por pote, D/REVISA/BUSCA/CAL)
//  + el protocolo de la ESP32-S3 por UART (pines 0/1 del Uno, 115200).
//  También funciona SOLO: si nadie le manda nada, copia al control igual que BrazoManual.
//
//  ⚠ SIN CONTROL DE POTES (HAY_CONTROL = false, como está ahora): al encender TODOS los servos quedan
//    SUELTOS (sin pulso). Cada uno se "prende" la primera vez que le mandas algo (J, T, HOME...) y
//    brinca directo a ese ángulo: los servos no dicen dónde están. OFF los vuelve a soltar.
//    Los potes, MAN y el botón no hacen nada. Para probar canales: python pc/tui_brazo.py
//
//  Modos (con HAY_CONTROL = true):
//   CONTROL : el brazo copia al control de potes y el botón cierra la pinza (como BrazoManual).
//   REMOTO  : obedece a la ESP (o a lo que escribas en el Monitor Serie).
//
//   - Al encender: CONTROL.
//   - En cuanto llega la ESP (empieza a mandar "?" cada 300 ms) el brazo se queda QUIETO donde
//     está y pasa a REMOTO. Mientras la ESP siga conectada, los potes y el botón se ignoran.
//   - J, H, HOME, ESTIRA o T → REMOTO.     MAN → CONTROL (alcanza al control despacio).
//   - Sin ESP (2 s sin recibir nada) y en REMOTO: mover un pote más de 20° regresa a CONTROL.
//
//  Comandos (Monitor Serie 115200, "Nueva línea"; la ESP manda los mismos):
//    J b h c m    ángulos de base, hombro, codo, muñeca (0-180, -1 = no cambiar). Ej: J -1 -1 120 -1
//    H p          pinza: 0 = abierta, 100 = cerrada
//    V v          velocidad en modo remoto, grados/s (10-400). Al encender: 90
//    HOME         posición de casa (recogido)      ESTIRA   brazo estirado
//    MAN          regresar a seguir al control
//    OFF          suelta TODOS los servos (sin pulso, no hacen fuerza)    OFF c   suelta solo el canal c
//    ?            estado → "S b h c m pinza modo prendidos"  (modo 0 = control, 1 = remoto;
//                 prendidos: bits 0-3 base..muñeca, bit 4 pinza). La ESP lo pide cada 300 ms
//    P            ángulos del control y ADC → "P b h c m (ADC ...)"
//    T c a        PRUEBA: canal c (0-15) del PCA9685 al ángulo a (crudo, sin INVERT). Sale con J/HOME/MAN...
//    D            monitor en vivo de los potes (lo detiene cualquier comando menos "?")
//    REVISA       revisa los cables de cada pote
//    BUSCA j      encuentra en qué pin (A0-A3) está el pote j (0 base, 1 hombro, 2 codo, 3 muñeca)
//    CAL j a      congela la articulación j en el ángulo a;  PUNTO 1 / PUNTO 2 para calibrar su pote
//
//  ⚠ Al subir código QUITA el cable que llega al pin 0 (RX) desde la ESP (si no, falla la subida).
//  ⚠ Prende la fuente de servos ANTES o junto con el Uno: los potes toman de ahí su voltaje.
//  Conexión: ESP GPIO 40 → pin 0 del Uno (directo).  Uno pin 1 → divisor 1k/2k → ESP GPIO 41.  GND común.
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

// ===================== CONFIGURACIÓN (igual que BrazoManual.ino) =====================
const bool HAY_CONTROL = false;             // false: se quitaron los potes del control (no los leas)
// ⚠ Si cambias algo aquí, cámbialo igual en BrazoManual.ino (y anótalo en HISTORIAL.md).
const uint8_t CH[NJ]  = {14, 13, 12, 11};   // canal PCA9685: base, hombro, codo, muñeca (probado con T)
uint8_t       POT[NJ] = {A3, A2, A1, A0};   // pote de: base, hombro, codo, muñeca. BUSCA lo corrige.
const bool INVERT[NJ] = {false, false, false, false};  // true si el servo gira al revés que el control
const uint8_t BTN_PIN = 13;

// Pinza (canal 10), en GRADOS del servo (como T).
const uint8_t HAND_CH = 10;
int HAND_OPEN_DEG   = 10;    // botón suelto / H 0
int HAND_CLOSED_DEG = 45;    // botón presionado / H 100
const bool HAND_RELAX = true; // mano abierta y quieta → apaga su pulso a 1 s (no zumba)

// Calibración de cada pote (recta de 2 puntos): ADC CAL_ADC1 → CAL_ANG1 grados, CAL_ADC2 → CAL_ANG2.
int CAL_ANG1[NJ] = {45,  45,  175, 84};
int CAL_ADC1[NJ] = {660, 660, 142, 537};
int CAL_ANG2[NJ] = {135, 135, 10,  139};
int CAL_ADC2[NJ] = {380, 380, 779, 367};

int LIM_MIN[NJ] = {0,   0,   0,   0};      // límites de seguridad en grados
int LIM_MAX[NJ] = {180, 180, 180, 180};
const float MAX_DPS = 300;                 // velocidad máxima siguiendo al control (°/s)
const float CATCHUP_DPS = 70;              // velocidad al regresar al control (MAN / sin ESP)
const float DEADBAND = 1.0;                // no mover si el cambio es menor (quita zumbido)

// Poses (b h c m), medidas con la TUI el 26 nov. -1 = no tocar esa articulación (se queda suelta).
int HOME_POS[NJ]    = {90,  80,  90, -1};    // CASA
int STRETCH_POS[NJ] = {100, 165, 5,  -1};    // ESTIRADO

const uint32_t ESP_TIMEOUT_MS = 2000;      // sin recibir nada en este tiempo = ESP desconectada
const int TAKEOVER_DEG = 20;               // sin ESP: mover un pote esto regresa a CONTROL
// =====================================================================================

float cur[NJ], tgt[NJ], potA[NJ], potRef[NJ];
float handCur = 0, handTgt = 0;            // 0..100
float speedDps = 90;                       // velocidad en modo remoto
bool remote = false;                       // false = CONTROL, true = REMOTO
bool catchUp = false;                      // regresando al control despacio
bool testMode = false;                     // T: no mover nada más
bool live = false;                         // D: monitor en vivo
int calJoint = -1;                         // CAL: articulación congelada
bool handOff = false;
bool on[NJ];                               // articulación con pulso (false = suelta)
bool handOn = true;                        // pinza con pulso
uint32_t handStillMs = 0;
uint32_t lastRx = 0;

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

// ----- PCA9685: escribe y recuerda cada canal, y se recupera si el chip se reinicia -----
// Si la placa azul pierde su alimentación un instante (fuente apagada/prendida, falso contacto,
// bajón por un servo trabado), el PCA9685 vuelve a arrancar DORMIDO y a otra frecuencia: ya no
// saca pulsos aunque el Uno le siga mandando ángulos. revisaPCA() lo nota y lo reconfigura.
uint16_t lastCnt[16];          // último valor de cada canal (4096 = sin pulso)
uint8_t prescaleOK = 0;        // prescaler correcto (para 50 Hz) leído al configurar
bool pcaPerdido = false;

void pwmSet(uint8_t c, uint16_t v) {
  lastCnt[c] = v;
  pwm.setPWM(c, 0, v);
}

void configuraPCA() {
  pwm.begin();
  Wire.setWireTimeout(3000, true);  // si el PCA9685 se queda sin VCC a medio mensaje, el Uno no se cuelga
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(FREQUENCY);
  prescaleOK = pwm.readPrescale();
}

void revisaPCA() {
  Wire.beginTransmission(0x40);
  bool responde = Wire.endTransmission() == 0;
  if (!responde) {
    if (!pcaPerdido) Serial.println(F("!! PCA9685 NO RESPONDE (se desconecto o perdio VCC). Esperando..."));
    pcaPerdido = true;
    return;
  }
  if (!pcaPerdido && pwm.readPrescale() == prescaleOK) return;  // todo bien
  configuraPCA();
  for (uint8_t c = 0; c < 16; c++) pwm.setPWM(c, 0, lastCnt[c]);  // cada servo a su último ángulo
  pcaPerdido = false;
  Serial.println(F("!! El PCA9685 se reinicio (perdio su alimentacion?): reconfigurado y servos restaurados"));
}

void setHand(float pct) {
  float a = HAND_OPEN_DEG + (HAND_CLOSED_DEG - HAND_OPEN_DEG) * pct / 100.0;
  pwmSet(HAND_CH, angleToCounts(a));
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

// (va después de los struct: el IDE declara las funciones antes de la primera)
bool espConectada() { return lastRx != 0 && millis() - lastRx < ESP_TIMEOUT_MS; }

// ----- Cambios de modo -----
void enterRemote() {
  if (!remote) {
    for (int j = 0; j < NJ; j++) { tgt[j] = cur[j]; potRef[j] = potA[j]; }  // se queda donde está
    remote = true;
    catchUp = false;
  }
  calJoint = -1;
}

void enterControl() {
  if (!HAY_CONTROL) { Serial.println(F("!! No hay control de potes (HAY_CONTROL = false)")); return; }
  remote = false;
  catchUp = true;      // alcanza al control despacio
  testMode = false;
  calJoint = -1;
}

// ----- Respuestas -----
void sendStatus() {
  Serial.print('S');
  for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print((int)(cur[j] + 0.5)); }
  Serial.print(' '); Serial.print((int)(handCur + 0.5));
  Serial.print(' '); Serial.print(remote ? 1 : 0);
  int m = 0;
  for (int j = 0; j < NJ; j++) if (on[j]) m |= 1 << j;
  if (handOn && !handOff) m |= 1 << 4;
  Serial.print(' '); Serial.println(m);
}

// Prende una articulación que estaba suelta: brinca directo a su objetivo (no sabemos dónde está)
void prende(int j) {
  if (!on[j]) { on[j] = true; cur[j] = tgt[j]; }
}

void suelta(int c) {
  pwmSet(c, 4096);  // sin pulso: el servo deja de hacer fuerza
  for (int j = 0; j < NJ; j++) if (CH[j] == c) on[j] = false;
  if (c == HAND_CH) { handOn = false; handTgt = handCur = 0; }
}

// "P b h c m  (ADC ... , pines A3 A2 A1 A0, boton suelto)"  — empieza con P: la ESP lo usa como "pong"
void printP() {
  Serial.print('P');
  for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print((int)potA[j]); }
  Serial.print(F("  (ADC"));
  for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print((int)kf[j].x); }
  Serial.print(F(", pines"));
  for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print(pinName(POT[j])); }
  Serial.print(F(", boton "));
  Serial.print(digitalRead(BTN_PIN) == LOW ? F("PRESIONADO") : F("suelto"));
  Serial.println(remote ? F(", modo REMOTO)") : F(", modo CONTROL)"));
}

// ----- Diagnóstico (igual que BrazoManual) -----
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
    else if (normal < 15 && conPull > 25) Serial.println(F("!! NO LE LLEGA V+ (rojo) al pote: el cursor y el GND si estan conectados"));
    else if (normal < 15)        Serial.println(F("!! marca 0: falta el V+ (rojo) del pote, o el pote esta en su tope"));
    else if (normal > 1008)      Serial.println(F("!! marca 1023: falta el GND (negro) del pote, o el pote esta en su tope"));
    else                         Serial.println(F("OK"));
  }
}

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
  for (int i = 0; i < 4; i++)
    if (i != best && mx[i] - mn[i] > range / 2)
      { Serial.print(F("!! ")); Serial.print(pinName(pins[i])); Serial.println(F(" tambien se movio: cable suelto/compartido en ese pin (usa REVISA)")); }
  POT[j] = pins[best];
  resetFilter(j);
  Serial.print(F("=> ")); Serial.print(NAMES[j]); Serial.print(F(" esta en ")); Serial.println(pinName(pins[best]));
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
  Serial.println(F("--- copia estas 4 lineas en BrazoESP.ino y BrazoManual.ino ---"));
  printArray(F("CAL_ANG1"), CAL_ANG1);
  printArray(F("CAL_ADC1"), CAL_ADC1);
  printArray(F("CAL_ANG2"), CAL_ANG2);
  printArray(F("CAL_ADC2"), CAL_ADC2);
}

// ----- Comandos -----
char line[48];
uint8_t lineLen = 0;

void handleLine(char* s) {
  lastRx = millis();  // llegó algo (de la ESP o del Monitor Serie)

  // Preguntas: no cambian de modo ni detienen el monitor D (la ESP manda "?" cada 300 ms)
  if (!strcmp(s, "?")) { sendStatus(); return; }
  if (!strcmp(s, "P"))  { printP(); return; }

  live = false;  // cualquier otro comando detiene el monitor D

  if (s[0] == 'T' && s[1] == ' ') {
    int c, a;
    if (sscanf(s + 1, "%d %d", &c, &a) == 2 && c >= 0 && c <= 15) {
      a = constrain(a, 0, 180);
      enterRemote();
      testMode = true;
      pwmSet(c, angleToCounts(a));
      // Si es el canal de una articulación, anota dónde quedó (para que al salir de T no brinque)
      for (int j = 0; j < NJ; j++)
        if (CH[j] == c) { cur[j] = tgt[j] = INVERT[j] ? 180 - a : a; on[j] = true; }
      if (c == HAND_CH) { handOff = false; handOn = true; }
      Serial.print(F("T canal ")); Serial.print(c); Serial.print(F(" -> ")); Serial.println(a);
    }
  } else if (s[0] == 'J' && (s[1] == ' ' || s[1] == 0)) {
    int v[NJ];
    int n = sscanf(s + 1, "%d %d %d %d", &v[0], &v[1], &v[2], &v[3]);
    if (n > 0) {
      enterRemote();
      testMode = false;
      for (int j = 0; j < n; j++) if (v[j] >= 0) { tgt[j] = clampJoint(j, v[j]); prende(j); }
    }
  } else if (s[0] == 'H' && (s[1] == ' ' || (s[1] >= '0' && s[1] <= '9'))) {
    int p;
    if (sscanf(s + 1, "%d", &p) == 1) { enterRemote(); testMode = false; handOn = true; handTgt = constrain(p, 0, 100); }
  } else if (s[0] == 'V' && (s[1] == ' ' || (s[1] >= '0' && s[1] <= '9'))) {
    int v;
    if (sscanf(s + 1, "%d", &v) == 1) speedDps = constrain(v, 10, 400);
  } else if (!strcmp(s, "HOME")) {
    enterRemote();
    testMode = false;
    for (int j = 0; j < NJ; j++) if (HOME_POS[j] >= 0) { tgt[j] = clampJoint(j, HOME_POS[j]); prende(j); }
    handTgt = 0;
  } else if (!strcmp(s, "ESTIRA")) {
    enterRemote();
    testMode = false;
    for (int j = 0; j < NJ; j++) if (STRETCH_POS[j] >= 0) { tgt[j] = clampJoint(j, STRETCH_POS[j]); prende(j); }
  } else if (!strcmp(s, "MAN")) {
    enterControl();
    Serial.println(F("Siguiendo al control"));
  } else if (!strncmp(s, "OFF", 3)) {
    int c;
    if (sscanf(s + 3, "%d", &c) == 1 && c >= 0 && c <= 15) {
      suelta(c);
      Serial.print(F("OFF canal ")); Serial.println(c);
    } else {
      testMode = false;
      for (int k = 0; k < 16; k++) suelta(k);
      Serial.println(F("OFF todos (sueltos)"));
    }
  } else if (!strcmp(s, "D")) {
    live = true;
  } else if (!strcmp(s, "REVISA")) {
    revisaCables();
  } else if (!strncmp(s, "BUSCA", 5)) {
    int j;
    if (sscanf(s + 5, "%d", &j) == 1 && j >= 0 && j < NJ) busca(j);
    else Serial.println(F("Uso: BUSCA j  (0 base, 1 hombro, 2 codo, 3 muneca)"));
  } else if (!strncmp(s, "CAL", 3)) {
    int j, a;
    if (!HAY_CONTROL) {
      Serial.println(F("!! CAL necesita el control de potes (HAY_CONTROL = false)"));
    } else if (sscanf(s + 3, "%d %d", &j, &a) == 2 && j >= 0 && j < NJ) {
      enterControl();
      catchUp = false;
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
  } else {
    Serial.println(F("Comandos: J b h c m, H p, V v, HOME, ESTIRA, MAN, OFF [c], ?, P, T c a, D, REVISA, BUSCA j, CAL j a, PUNTO n"));
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
  for (int c = 0; c < 16; c++) lastCnt[c] = 4096;
  configuraPCA();
  Wire.beginTransmission(0x40);
  if (Wire.endTransmission() == 0) Serial.println(F("OK PCA9685 (0x40)"));
  else Serial.println(F("!! PCA9685 NO RESPONDE: revisa SDA->A4, SCL->A5, VCC->5V del Uno y GND"));
  for (int c = 0; c < 16; c++) pwmSet(c, 4096);  // todos apagados (sueltos)

  if (!HAY_CONTROL) {
    // Sin control: todos sueltos. Se prenden con la primera orden (J, T, HOME...)
    for (int j = 0; j < NJ; j++) { on[j] = false; cur[j] = tgt[j] = HOME_POS[j] >= 0 ? HOME_POS[j] : 90; }
    handOn = false;
    remote = true;
    Serial.println(F("BRAZO ESP listo, SIN control: servos sueltos hasta que les mandes algo"));
    Serial.println(F("(si ves esta linea sin haber reiniciado tu, el Uno se reinicio: USB o bajon de voltaje)"));
    return;
  }
  // Arranca en la pose del control y enciende los servos uno por uno en esa pose (sin brinco)
  for (int j = 0; j < NJ; j++) {
    on[j] = true;
    resetFilter(j);
    cur[j] = tgt[j] = clampJoint(j, potA[j]);
    potRef[j] = potA[j];
  }
  for (int j = 0; j < NJ; j++) {
    pwmSet(CH[j], jointCounts(j, cur[j]));
    delay(250);
  }
  setHand(0);
  Serial.println(F("BRAZO ESP listo (copiando al control hasta que hable la ESP)"));
}

void loop() {
  static uint32_t lastStep = 0, lastLive = 0;
  static bool espAntes = false;
  readSerial();

  uint32_t now = millis();
  if (now - lastStep < 20) return;  // 50 Hz
  float dt = (now - lastStep) / 1000.0;
  lastStep = now;

  if (HAY_CONTROL)
    for (int j = 0; j < NJ; j++) potA[j] = adcToAngle(j, kalmanStep(kf[j], readADC(POT[j])));
  if (live && now - lastLive > 250) { lastLive = now; printP(); }
  static uint32_t lastPCA = 0;
  if (now - lastPCA > 1000) { lastPCA = now; revisaPCA(); }
  if (testMode) return;

  bool esp = espConectada();
  if (esp && !espAntes) enterRemote();   // llegó la ESP: el brazo se queda quieto y la obedece
  espAntes = esp;

  if (remote && !esp && HAY_CONTROL) {
    // Sin ESP: si alguien mueve un pote, el control recupera el brazo
    for (int j = 0; j < NJ; j++)
      if (fabs(potA[j] - potRef[j]) > TAKEOVER_DEG) { enterControl(); break; }
  }

  float maxStep;
  if (!remote) {
    // CONTROL: cada articulación sigue a su pote (menos la que se está calibrando)
    for (int j = 0; j < NJ; j++)
      if (j != calJoint) {
        float a = clampJoint(j, potA[j]);
        if (catchUp || fabs(a - tgt[j]) >= DEADBAND) tgt[j] = a;
      }
    handTgt = digitalRead(BTN_PIN) == LOW ? 100 : 0;
    maxStep = (catchUp ? CATCHUP_DPS : MAX_DPS) * dt;
    if (catchUp) {
      bool cerca = true;
      for (int j = 0; j < NJ; j++) if (fabs(tgt[j] - cur[j]) > 3) cerca = false;
      if (cerca) catchUp = false;
    }
  } else {
    maxStep = speedDps * dt;
    if (!esp && HAY_CONTROL && digitalRead(BTN_PIN) == LOW) handTgt = 100;  // sin ESP el botón puede cerrar la pinza
  }

  for (int j = 0; j < NJ; j++) {
    float step = (j == calJoint) ? 40 * dt : maxStep;
    cur[j] += constrain(tgt[j] - cur[j], -step, step);
    if (on[j]) pwmSet(CH[j], jointCounts(j, cur[j]));
  }
  if (!handOn) return;  // pinza suelta

  handCur += constrain(handTgt - handCur, -400 * dt, 400 * dt);
  if (HAND_RELAX && handTgt == 0 && handCur <= 0.5) {
    if (!handOff) {
      if (handStillMs == 0) handStillMs = now;
      if (now - handStillMs > 1000) { pwmSet(HAND_CH, 4096); handOff = true; }
      else setHand(handCur);
    }
  } else {
    handStillMs = 0;
    handOff = false;
    setHand(handCur);
  }
}
