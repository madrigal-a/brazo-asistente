# CLAUDE.md — Brazo asistente (Talking Bolita)

Instrucciones para Claude (o cualquier persona) que continúe este proyecto.
**Responde siempre en español.** Los usuarios son estudiantes de Ingeniería Mecatrónica
(Universidad Anáhuac); explica paso a paso y en términos prácticos.

Antes de cualquier cosa lee **`PENDIENTES.md`** (qué falta) y **`HISTORIAL.md`** (qué se
decidió y por qué). Al terminar una sesión, actualiza los dos.

## Qué es
Una mascota tipo Talking Tom que además controla un brazo robótico:

```
Micrófono de la compu ─► Python (pc/): Kalman + efectos de voz + caras ─USB─► ESP32-S3
ESP32-S3 (firmware/TalkingBolita/): pantalla touch 2.4" (cara + control del brazo), bocina, 2 botones
   │ UART 115200 (GPIO 40 TX → pin 0 del Uno; GPIO 41 RX ← pin 1 del Uno con divisor 1k/2k)
   ▼
Arduino Uno (firmware/BrazoUno/) + PCA9685 ─► 5 servos.  Control "maestro": bracito con 4 potes + botón.
```

Dos materias: **procesamiento de señales** (filtro de Kalman para limpiar voz en `pc/dsp.py`, y
Kalman 1D en los potes del Uno) y **dinámica de sistemas mecatrónicos** (práctica del brazo:
calibración, pruebas repetitivas, reporte).

## Hardware (comprobado)
- **Arduino Uno + PCA9685** (I2C en A4/A5), fuente de laboratorio **5.0 V, límite 3 A** a la placa azul.
- **Los potes toman su voltaje de la fuente de servos**: con la fuente apagada `P` da basura.
- Canales del PCA9685 (comprobados con `T`): **base 14, hombro 13, codo 12, muñeca 11, pinza 10**
  (uno abajo de la práctica, que usaba 11–15). El canal 15 está vacío.
- Potes según la Figura 1 de la práctica: **base A3, hombro A2, codo A1, muñeca A0** — pero el
  codo/muñeca aún no cuadra (ver PENDIENTES).
- Botón del control en el pin 13 (INPUT_PULLUP).
- Pinza: el código original usaba cuentas crudas 90 (suelta) y 180 (presionado). Con `T 10 60/120`
  solo vibra: **no dejar servos vibrando** (se queman).
- Servos: 3× MG996R, 1× SG90, 1× HPS-2018MG. **No pasar de 6 V** (SG90).
- Cables de servo: naranja/blanco = señal (amarillo en la placa), rojo = V+, café/negro = GND.
- ESP32-S3 N16R8 (PSRAM octal: en Arduino IDE elegir **OPI PSRAM**, 16MB). Pantalla ST7789
  240×320 con touch XPT2046 (pines en `firmware/TalkingBolita/Config.h`). MAX98357 + bocina 8 Ω.
- No hay micrófono en la ESP: el audio lo captura la computadora.

## Protocolo Uno (texto, 115200, una línea por comando)
`J b h c m` ángulos (−1 = no cambiar) · `H 0-100` pinza · `V °/s` · `HOME` · `ESTIRA` · `MAN`
(volver a potes) · `?` → `S b h c m mano modo` · `P` → ángulos de los potes + ADC crudo ·
`T canal ángulo` prueba un canal crudo (sale con `MAN`/`HOME`).
Al encender va a `HOME_POS` y se queda; si un pote se mueve >20° pasa a modo manual (copia al
control, primero despacio). Cualquier comando de la ESP lo pone en modo remoto.

ESP ↔ compu: tramas binarias `A5 5A tipo len16 datos checksum` (ver `TalkingBolita.ino` y
`pc/bolita.py`). Tipos: M cara, L mirada, A audio 16 kHz, S parar audio, V volumen,
B orden para el brazo (rutina o comando crudo), P ping.

## Cómo trabajar aquí
- Compilar antes de entregar:
  - Uno: `arduino-cli compile -b arduino:avr:uno firmware/BrazoUno` (librería *Adafruit PWM Servo Driver Library* + *Adafruit BusIO*)
  - ESP32: `arduino-cli compile -b "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M" firmware/TalkingBolita` (librería *LovyanGFX*; incluir `Display.h` **antes** de `ESP_I2S.h`, choque de tipos en core 4.x)
  - Python: `python pc/tom.py --simular` funciona sin hardware.
- **Cuidado con el Arduino IDE:** si un `.ino` está abierto, el IDE vuelve a guardar su versión vieja
  encima. Pide cerrar la pestaña sin guardar, o entrega el cambio como líneas para pegar en el IDE.
- Cambios de calibración (canales, potes, `INVERT`, `HOME_POS`, `STRETCH_POS`, `LIM_*`,
  `HAND_OPEN/CLOSED`) están todos al inicio de `BrazoUno.ino`; anótalos en `HISTORIAL.md`, que
  sirven para el reporte de la práctica.
- Seguridad: cambios de cables siempre con la fuente apagada; prender la fuente con la mano en el
  switch; si la fuente marca CC, algo está forzado.
- Commits con mensajes en español.
