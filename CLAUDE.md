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
ESP32-S3 (firmware/TalkingBolita/): pantalla 2.4" sin touch (cara + menú del brazo), bocina, 2 botones (Function = hablar, Mode = menú)
   │ UART 115200 (GPIO 40 TX → pin 0 del Uno; GPIO 41 RX ← pin 1 del Uno con divisor 1k/2k)
   ▼
Arduino Uno (firmware/BrazoESP/, o BrazoManual/ sin ESP) + PCA9685 ─► 5 servos.  Control "maestro": bracito con 4 potes + botón.
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
  240×320 **sin touch** (el chip U1 no viene soldado), botones Function GPIO 15 y Mode GPIO 16 (los dos = paro)
  (pines en `firmware/TalkingBolita/Config.h`). Placa YD-ESP32-S3. MAX98357 (VIN a **3V3**: el 5Vin de esta placa es entrada) + bocina 8 Ω 2 W.
- La ESP habla con la compu por el USB-C **UART** (no el nativo): en el nativo Python da `Write timeout`.
- No hay micrófono en la ESP: el audio lo captura la computadora.
- La voz puede salir por la bocina de la ESP, la compu o las dos (`tom.py --audio esp|pc|ambos`;
  sin la opción pregunta al arrancar). La ESP32-S3 no sirve para audífonos BT (solo BLE).
- Brazo: mientras no se calibre el control, las reacciones son gestos con `T canal ángulo`
  (`pc/gestos.py`). En el Uno, `?` y `P` no sacan del modo prueba (la ESP manda `?` cada 300 ms).

## Protocolo Uno (texto, 115200, una línea por comando) — `firmware/BrazoESP`
`J b h c m` ángulos (−1 = no cambiar) · `H 0-100` pinza · `V °/s` · `HOME` · `ESTIRA` · `MAN`
(volver al control) · `?` → `S b h c m mano modo` · `P` → `P b h c m (ADC ...)` ·
`T canal ángulo` prueba un canal crudo (si es una articulación, el Uno anota dónde quedó) ·
diagnóstico de BrazoManual: `D`, `REVISA`, `BUSCA j`, `CAL j a`, `PUNTO n`.
`OFF [c]` suelta todos / un canal. **Ahora `HAY_CONTROL = false` (se quitaron los potes):** al
encender todo queda suelto y cada servo se prende con su primera orden; probar con `pc/tui_brazo.py`.
Con `HAY_CONTROL = true`: al encender copia al control (como BrazoManual). Cuando llega la ESP (cualquier línea; manda `?`
cada 300 ms) se queda quieto y pasa a REMOTO; con la ESP conectada los potes y el botón se ignoran,
salvo que llegue `MAN`. Sin ESP (2 s sin nada) y en REMOTO, mover un pote >20° regresa al control.
`BrazoUno`/`BrazoUnoV2` son las versiones viejas (mapeo 240–800, codo mal); ya no se usan.

ESP ↔ compu: tramas binarias `A5 5A tipo len16 datos checksum` (ver `TalkingBolita.ino` y
`pc/bolita.py`). Tipos: M cara, L mirada, A audio 16 kHz, S parar audio, V volumen,
B orden para el brazo (rutina o comando crudo), P ping.
ESP → compu: líneas de texto: `PTT 1` / `PTT 0` / `PTT C` (Function: grabar / soltar / cancelar),
`VOZ` (menú: otra voz), `CANTA` (menú: canta), `PARO`, `DONE` (terminó el audio), `READY`.

## Cómo trabajar aquí
- Compilar antes de entregar:
  - Uno: `arduino-cli compile -b arduino:avr:uno firmware/BrazoESP` (y `firmware/BrazoManual`) (librería *Adafruit PWM Servo Driver Library* + *Adafruit BusIO*)
  - ESP32: `arduino-cli compile -b "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M" firmware/TalkingBolita` (librería *LovyanGFX*; incluir `Display.h` **antes** de `ESP_I2S.h`, choque de tipos en core 4.x)
  - Python: `python pc/tom.py --simular` funciona sin hardware. En la compu de Alonso: `py -3.12` (tiene Python 2.7 también).
- Palabras → respuestas: tabla `RESPUESTAS` en `pc/respuestas.py`; audios en `pc/respuestas/*.wav` (se graban con `pc/grabar.py`);
  modelo Vosk en `pc/modelos/` (no va al repo).
- **Cuidado con el Arduino IDE:** si un `.ino` está abierto, el IDE vuelve a guardar su versión vieja
  encima. Pide cerrar la pestaña sin guardar, o entrega el cambio como líneas para pegar en el IDE.
- Cambios de calibración (canales, potes, `INVERT`, `HOME_POS`, `STRETCH_POS`, `LIM_*`,
  `HAND_*_DEG`, `CAL_*`) están al inicio de `BrazoESP.ino` **y** `BrazoManual.ino` (mantenerlos iguales); anótalos en `HISTORIAL.md`, que
  sirven para el reporte de la práctica.
- Seguridad: cambios de cables siempre con la fuente apagada; prender la fuente con la mano en el
  switch; si la fuente marca CC, algo está forzado.
- Commits con mensajes en español.
