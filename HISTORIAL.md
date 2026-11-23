# Historial del proyecto

## 23 nov 2026 — sesión 1 (con Claude)

**Idea.** Empezó como "Talking Bolita": mascota tipo Talking Tom con cara expresiva en la pantalla
de la ESP32-S3 y filtro de Kalman para la voz (tema de la materia de señales). Se descartó la
extensión de 127 V con relés. Como no hay micrófono funcional (los INMP441 anteriores nunca
sirvieron), la **computadora hace de micrófono** y procesa todo en Python. Después se agregó el
**brazo robótico** de la práctica de Dinámica de Sistemas Mecatrónicos, controlado por un Arduino Uno
que recibe órdenes de la ESP.

**Decisiones.**
- ESP ↔ Uno por **UART en los pines 0/1 del Uno** (no SoftwareSerial): más confiable y permite
  probar el brazo escribiendo comandos en el Monitor Serie. Contra: desconectar el cable del pin 0
  al subir código.
- El Uno conserva el funcionamiento de la práctica (control de potes + botón) y agrega modo remoto.
- Los servos no reportan su posición: el brazo arranca en **casa** (`HOME_POS`) como referencia.
- Kalman 1D en cada pote para quitar el temblor; Kalman AR(10) con LPC por trama para la voz
  (+6–7 dB de SNR en pruebas sintéticas, `pc/demo_kalman.py`).
- La pantalla dibuja la cara con código (8 expresiones, `docs/caras.png`), no con imágenes.

**Calibración y hallazgos (para el reporte).**
1. `P` con la fuente apagada daba casi los mismos números en cualquier pose → los potes se
   alimentan de la fuente de servos. Con la fuente encendida (servos desconectados) sí funcionó.
2. Lecturas con fuente encendida (orden A0 A1 A2 A3):
   - control recogido: `P 84 180 18 119 (ADC: 537 142 742 428)`
   - control estirado: `P 139 6 180 118 (ADC: 367 779 135 432)`
   - hombro y codo llegan al tope del mapeo original (ADC 240–800), igual que en el código original.
3. El orden de los potes del código original de los usuarios (base A0) no coincidía con el
   cableado; el cableado sigue la Figura 1 (**base A3, hombro A2, codo A1, muñeca A0**).
   Con eso: casa = 119 22 175 84, estirado = 118 175 10 139 (con 5° de margen en los topes).
4. Prueba de canales con `T`: base 14, hombro 13, codo 12, muñeca 11, pinza 10 (vibra), 15 vacío.
5. Con canales corregidos: **base y hombro siguen bien al control**. El pote del codo mueve la
   muñeca del robot y el de la muñeca parece no hacer nada (pendiente). Invertir el codo no ayudó.
6. El Arduino IDE pisó dos veces el archivo nuevo con la versión abierta → se creó la carpeta
   `BrazoUnoV2` en la compu de Alonso. En el repo el sketch se llama `firmware/BrazoUno`.

**Fuente:** 5.0 V, límite 3 A.

**Siguiente:** ver `PENDIENTES.md`.
