// =====================================================================
//  Brazo robótico — Arduino Uno + PCA9685
//  Basado en el código de la práctica (Tabla 2), con dos modos:
//
//   MANUAL  : el control (bracito con 4 potenciómetros) mueve el brazo y el
//             botón cierra la mano (igual que el código original).
//   REMOTO  : la ESP32-S3 manda órdenes por serial (pines 0/1, 115200).
//             Mientras la ESP esté conectada, los potenciómetros y el botón NO hacen nada.
//             Sin ESP (2 s sin recibir nada), mover un pote más de 20° regresa a MANUAL.
//
//  También puedes probar el modo remoto desde el Monitor Serie (115200,
//  "Nueva línea") escribiendo los comandos de abajo.
//
//  Comandos (una línea cada uno):
//    J b h c m    ángulos de base, hombro, codo, muñeca (0-180, -1 = no cambiar)
//    H p          mano: 0 = abierta, 100 = cerrada
//    V v          velocidad en grados/s (10-400)
//    HOME         posición de casa (brazo recogido)
//    ESTIRA       brazo estirado
//    MAN          regresar a modo manual
//    ?            pedir estado (ángulos a los que el brazo está mandado)
//    P            ángulos que marca el control (potenciómetros) y lectura cruda del ADC, para calibrar
//    T c a        PRUEBA: mueve solo el canal c (0-15) del PCA9685 al ángulo a. Sirve para
//                 saber qué servo está en cada canal. Sales de la prueba con MAN o HOME.
//  Respuesta a "?":  S b h c m mano modo(0=manual,1=remoto)   (la ESP la pide cada 300 ms)
//
//  ⚠ Al subir código desconecta el cable que llega al pin 0 (RX) desde la ESP.
//  Librería: "Adafruit PWM Servo Driver Library"
// =====================================================================
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

#define MIN_PULSE_WIDTH 650
#define MAX_PULSE_WIDTH 2350
#define FREQUENCY       50
#define HAND_OPEN       90    // cuentas del PCA9685, igual que tu código (botón suelto)
#define HAND_CLOSED     180   // botón presionado ("Grab")

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

enum { BASE, SHOULDER, ELBOW, WRIST, NJ };
const char* NAMES[NJ] = {"base", "hombro", "codo", "muneca"};
// ----- Cableado: ajusta aquí si un servo o un pote está en otro lugar -----
const uint8_t CH[NJ]  = {14, 13, 12, 11};     // canal del PCA9685 de: base, hombro, codo, muñeca (probado con T)
const uint8_t POT[NJ] = {A3, A2, A1, A0};     // pote de: base A3, hombro A2, codo A1, muñeca A0 (Figura 1)
const bool INVERT[NJ] = {false, false, false, false};  // true si el servo gira al revés que el control
const uint8_t HAND_CH = 10;                  // pinza: vibra, falta ajustar HAND_OPEN/CLOSED
const uint8_t BTN_PIN = 13;

// ----- Calibración (anota en el reporte lo que cambies aquí) -----
int LIM_MIN[NJ]  = {0,   0,   0,   0};    // límites de seguridad en grados
int LIM_MAX[NJ]  = {180, 180, 180, 180};
int HOME_POS[NJ] = {119, 22,  175, 84};   // CASA: brazo recogido ("hecho bolita")
int STRETCH_POS[NJ] = {118, 175, 10, 139}; // ESTIRADO
// Para obtener estos números: pon el control en la pose que quieras, escribe "P" en el
// Monitor Serie y copia los 4 ángulos que responde (P base hombro codo muñeca).
// La fuente debe estar ENCENDIDA (los potes toman de ahí su voltaje); desconecta los
// servos de la placa azul mientras lo haces para que no se muevan.
const int POT_LO = 240, POT_HI = 800;     // rango útil del ADC (map(pot, 800, 240, ...))
const int TAKEOVER_DEG = 20;              // cuánto mover un pote para volver a manual

float cur[NJ], tgt[NJ], potRef[NJ], potA[NJ];
float handCur = 0, handTgt = 0;           // 0..100
float speedDps = 90;                      // velocidad en modo remoto
bool remote = false;
bool catchUp = false;   // al pasar a manual, alcanza al control despacio
bool testMode = false;  // comando T: no mover nada más

// Mientras la ESP esté conectada (manda "?" cada 300 ms), el control de potenciómetros y su
// botón quedan BLOQUEADOS: solo obedece a la ESP. Si pasan ESP_TIMEOUT_MS sin recibir nada
// (ESP desconectada o apagada), el control vuelve a funcionar (mueve un pote >20° para tomarlo).
const uint32_t ESP_TIMEOUT_MS = 2000;
uint32_t lastRx = 0;

// ----- Filtro de Kalman 1D para cada potenciómetro (quita el temblor de los servos) -----
// Modelo: el ángulo es casi constante (x[k] = x[k-1] + w), la lectura del ADC tiene ruido (z = x + v)
struct Kalman1D { float x, p; };
Kalman1D kf[NJ];
const float KQ = 0.4;   // varianza del proceso: qué tanto puede cambiar el pote entre lecturas
const float KR = 12.0;  // varianza de la medición: ruido del ADC (en cuentas^2)

float kalmanStep(Kalman1D& k, float z) {
  k.p += KQ;                    // predicción
  float g = k.p / (k.p + KR);   // ganancia de Kalman
  k.x += g * (z - k.x);         // corrección
  k.p *= (1 - g);
  return k.x;
}

float readPotAngle(int j) {
  float v = kalmanStep(kf[j], analogRead(POT[j]));
  float a = (POT_HI - v) * 180.0 / (POT_HI - POT_LO);  // 800 -> 0°, 240 -> 180°
  return constrain(a, 0, 180);
}

uint16_t jointCounts(int j, float a);
uint16_t angleToCounts(float a) {
  float us = MIN_PULSE_WIDTH + a / 180.0 * (MAX_PULSE_WIDTH - MIN_PULSE_WIDTH);
  return (uint16_t)(us / 1000000.0 * FREQUENCY * 4096);
}

uint16_t jointCounts(int j, float a) { return angleToCounts(INVERT[j] ? 180 - a : a); }

float clampJoint(int j, float a) { return constrain(a, LIM_MIN[j], LIM_MAX[j]); }

// (va aquí abajo y no junto a lastRx: el IDE declara las funciones antes de la primera,
//  y si quedara arriba de struct Kalman1D, kalmanStep no compila)
bool espConectada() { return lastRx != 0 && millis() - lastRx < ESP_TIMEOUT_MS; }

void enterRemote() {
  if (!remote) {
    for (int j = 0; j < NJ; j++) potRef[j] = potA[j];
    remote = true;
  }
}

void sendStatus() {
  Serial.print('S');
  for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print((int)cur[j]); }
  Serial.print(' '); Serial.print((int)handCur);
  Serial.print(' '); Serial.println(remote ? 1 : 0);
}

// ----- Lectura de comandos -----
char line[48];
uint8_t lineLen = 0;

void handleLine(char* s) {
  lastRx = millis();  // llegó algo de la ESP (o del Monitor Serie): control bloqueado
  if (s[0] == 'T') {
    int c, a;
    if (sscanf(s + 1, "%d %d", &c, &a) == 2 && c >= 0 && c <= 15) {
      testMode = true;
      pwm.setPWM(c, 0, angleToCounts(constrain(a, 0, 180)));
      Serial.print("T canal "); Serial.print(c); Serial.print(" -> "); Serial.println(a);
    }
    return;
  }
  // "?" y "P" solo preguntan: NO sacan del modo prueba (la ESP manda "?" cada 300 ms)
  if (!strcmp(s, "?")) { sendStatus(); return; }
  if (!strcmp(s, "P")) {
    Serial.print('P');
    for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print((int)potA[j]); }
    Serial.print("   (ADC:");
    for (int j = 0; j < NJ; j++) { Serial.print(' '); Serial.print(analogRead(POT[j])); }
    Serial.println(")");
    return;
  }
  testMode = false;  // cualquier otro comando sale del modo prueba
  if (s[0] == 'J') {
    int v[NJ];
    int n = sscanf(s + 1, "%d %d %d %d", &v[0], &v[1], &v[2], &v[3]);
    if (n > 0) enterRemote();
    for (int j = 0; j < n; j++) if (v[j] >= 0) tgt[j] = clampJoint(j, v[j]);
  } else if (s[0] == 'H' && s[1] != 'O') {
    int p;
    if (sscanf(s + 1, "%d", &p) == 1) { enterRemote(); handTgt = constrain(p, 0, 100); }
  } else if (s[0] == 'V') {
    int v;
    if (sscanf(s + 1, "%d", &v) == 1) speedDps = constrain(v, 10, 400);
  } else if (!strcmp(s, "HOME")) {
    enterRemote();
    for (int j = 0; j < NJ; j++) tgt[j] = HOME_POS[j];
    handTgt = 0;
  } else if (!strcmp(s, "ESTIRA")) {
    enterRemote();
    for (int j = 0; j < NJ; j++) tgt[j] = STRETCH_POS[j];
  } else if (!strcmp(s, "MAN")) {
    remote = false;
    catchUp = true;
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
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(FREQUENCY);
  pwm.setPWM(HAND_CH, 0, HAND_OPEN);

  // Al encender, el brazo va a CASA y se queda ahí. Los servos no dicen en qué ángulo
  // están, así que la casa es nuestro "cero": desde ahí sabemos siempre dónde está.
  // Enciende los servos con el brazo cerca de la casa para que no dé un brinco.
  // Cuando mueves el control más de 20° (o llega una orden de la ESP), toma el control.
  for (int j = 0; j < NJ; j++) {
    kf[j].x = analogRead(POT[j]);
    kf[j].p = KR;
    potA[j] = readPotAngle(j);
    cur[j] = tgt[j] = HOME_POS[j];
    pwm.setPWM(CH[j], 0, jointCounts(j, cur[j]));
    potRef[j] = potA[j];
  }
  remote = true;  // "retenido" en casa hasta que muevas el control
  Serial.println("BRAZO listo");
}

void loop() {
  static uint32_t lastStep = 0;
  readSerial();

  uint32_t now = millis();
  if (now - lastStep < 20) return;  // 50 Hz
  float dt = (now - lastStep) / 1000.0;
  lastStep = now;

  for (int j = 0; j < NJ; j++) potA[j] = readPotAngle(j);
  if (testMode) return;
  bool esp = espConectada();
  bool btn = !esp && digitalRead(BTN_PIN) == LOW;  // con la ESP conectada el botón no cuenta

  if (esp) {
    // ESP conectada: ignora los potenciómetros. Si estaba en manual, se queda donde está.
    if (!remote) {
      for (int j = 0; j < NJ; j++) tgt[j] = cur[j];
      enterRemote();
      catchUp = false;
    }
  } else if (remote) {
    // Sin ESP: si alguien mueve un potenciómetro, recupera el control manual
    for (int j = 0; j < NJ; j++)
      if (fabs(potA[j] - potRef[j]) > TAKEOVER_DEG) { remote = false; catchUp = true; break; }
  }

  float maxStep;
  if (!remote) {
    for (int j = 0; j < NJ; j++) tgt[j] = clampJoint(j, potA[j]);
    handTgt = btn ? 100 : 0;
    // en manual sigue al control casi directo; justo después de cambiar de modo, despacio
    maxStep = (catchUp ? 70 : 300) * dt;
    if (catchUp) {
      bool close = true;
      for (int j = 0; j < NJ; j++) if (fabs(tgt[j] - cur[j]) > 3) close = false;
      if (close) catchUp = false;
    }
  } else {
    if (btn) handTgt = 100;  // el botón siempre puede cerrar la mano
    maxStep = speedDps * dt;
  }

  // Mueve cada articulación hacia su objetivo sin pasar de la velocidad máxima
  for (int j = 0; j < NJ; j++) {
    float d = tgt[j] - cur[j];
    cur[j] += constrain(d, -maxStep, maxStep);
    pwm.setPWM(CH[j], 0, jointCounts(j, cur[j]));
  }
  float dh = handTgt - handCur;
  handCur += constrain(dh, -400 * dt, 400 * dt);
  pwm.setPWM(HAND_CH, 0, HAND_OPEN + (int)((HAND_CLOSED - HAND_OPEN) * handCur / 100.0));

}
