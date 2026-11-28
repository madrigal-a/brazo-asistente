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

## 25 nov 2026 — sesión 2 (con Claude)

**Problema.** La bocina dejó de sonar (probablemente el amplificador MAX98357).

**Decisiones.**
- Se pensó en un menú Bluetooth en la ESP para audífonos, pero **la ESP32-S3 solo tiene BLE** y los
  audífonos usan Bluetooth clásico (A2DP / HFP): no se puede. Se decidió que **la compu sea micrófono
  y bocinas** (lo predeterminado de Windows; si hay audífonos BT conectados a la compu, se usan).
  `tom.py --audio pc` es el nuevo default; la ESP recibe el audio con volumen 0 solo para mover la boca.
- Firmware ESP: el nivel de la boca (`g_level`) se calcula **antes** del volumen.
- Como el control del brazo aún no está calibrado, las reacciones son **gestos sencillos** con el
  comando `T canal ángulo` (`pc/gestos.py`): 1–2 servos, en pasitos de 30 ms (~120 °/s), regresan a
  su reposo (= `HOME_POS`) y al final `HOME`. Pinza fuera (vibra). `tom.py --brazo rutinas` usa las de `Arm.h`.
- **Bug encontrado:** en el Uno cualquier comando distinto de `T` salía del modo prueba, y la ESP
  manda `?` cada 300 ms → un `T` mandado por la ESP se deshacía. Ahora `?` y `P` no salen del modo
  prueba (`BrazoUno.ino` y `BrazoUnoV2.ino`).
- Opción `--uno COMx` para mandar los gestos directo al Uno por USB, sin la ESP.
- Respaldo de los archivos anteriores en `respaldo_25nov/`.
- Más tarde la bocina de la ESP volvió a sonar → `tom.py` pregunta al arrancar dónde suena la voz
  (ESP / compu / las dos); también `--audio esp|pc|ambos`.
- Orden por voz para probar servos: "prueba el servo diez a veinte grados" → `T 10 20`
  (`pc/servo_voz.py` convierte los números en letra que da Vosk). "quieto"/"inicio" → `HOME`.

- La detección automática del puerto agarró el Uno (COM6) en vez de la ESP (COM8): ahora prefiere
  CH343/CP210x, excluye el puerto de `--uno` e imprime cuál eligió. Usar `--port COM8` para ir seguros.
- Los servos se movían solos porque el Uno seguía leyendo los potes (ruido >20° = toma el control).
  Ahora, **mientras la ESP esté conectada** (cualquier línea recibida en los últimos 2 s), los potes y
  el botón del control se ignoran; sin ESP vuelven a funcionar (`espConectada()` en BrazoUno/V2).
- `tom.py` no reaccionaba a Function aunque `probar_esp.py` sí veía `BTN FUNC` → la ESP solo manda
  `PTT 1` en la cara y sin pausa; ahora `tom.py` avisa cuando llega `BTN FUNC` sin `PTT 1`.
- Prueba del UART: la ESP reenvía a la compu lo que dice el Uno (`UNO ...`), sonríe cuando el Uno
  contesta `P` y avisa `UNO ok` / `UNO sin respuesta`. `pc/probar_uart.py` prueba ida y vuelta
  (y con `--uno COM6` escucha al Uno por USB para probar solo la ida).
- `gestos.py prueba` (servo por servo) y `gestos.py --manual` (comandos por teclado) para probar sin voz.

- **UART resuelto:** los cables del Uno estaban en TX/RX (GPIO 43/44) de la ESP, que son los del
  USB a la compu: por eso `tom.py` no veía el botón y el Uno no recibía nada. Pasados a
  **GPIO 40 → pin 0** (y GND común), sin divisor por ahora. `probar_uart.py`: el Uno contestó 10
  veces el `?` de la ESP. `gestos.py identificar --port COM8` movió la base y `tom.py` mueve un
  canal por voz ("mueve el canal 14 a 60"). La vuelta (pin 1 → GPIO 41) espera el divisor 1k/2k.
- Se quitó el `HOME` del final de los gestos y del modo manual (casa aún sin calibrar).
- **Con el control (sin UART): base, hombro y muñeca se mueven bien; el codo (canal 12) no.**

## 26 nov 2026 — sesión 3 (con Claude)

- `BrazoManual.ino` (hecho aparte) resolvió el codo y la muñeca: el "fantasma" del ADC del Uno
  (un pin copiaba al anterior) se quita leyendo una vez de sobra, esperando 50 µs y promediando 4;
  cada pote tiene su recta de calibración de 2 puntos (`CAL_*`: codo ADC 142 → 175°, 779 → 10°;
  muñeca 537 → 84°, 367 → 139°). Agrega `D`, `REVISA`, `BUSCA`, `CAL`/`PUNTO`. Pinza en grados
  (abierta 10°, cerrada 45°) y se apaga al estar abierta 1 s para que no zumbe.
- Este repo se había quedado en el 23 nov; se trajo la versión del 25 nov (voz con Vosk, gestos,
  probar_uart...) desde `Downloads/talking-bolita` (sin modelos ni respaldos).
- Nuevo **`firmware/BrazoESP`** = BrazoManual + protocolo de la ESP (`J H V HOME ESTIRA MAN ? P T`).
  Arranca copiando al control; al llegar la ESP se queda quieto y la obedece; `MAN` regresa al
  control despacio (70 °/s). `T` en un canal de articulación actualiza dónde quedó (no brinca al salir).
  Compilado con avr-gcc: 19.8 KB flash (60 %), 815 B RAM (40 %).
- `tom.py`: "mueve el codo a 120" ahora manda `V 60` + `J -1 -1 120 -1` (suave) en vez de `T` (brinco).
- UART probado: la **ida ESP → Uno funciona** (el Uno contesta `S ...` al `?` de la ESP, visto en el
  Monitor Serie). Falta la vuelta (pin 1 → divisor 1k/2k → GPIO 41). La ESP debe ir por el USB-C
  "COM" (CH343, COM8); por el nativo sale como otro COM y no habla.
- Con `T`, algunos servos se quedan "apretados" pero no se mueven. **Se quitaron los potes** del
  control: `HAY_CONTROL = false` en BrazoESP (servos sueltos al encender, se prenden con la primera
  orden; sin esto los pines al aire movían los servos al azar). Nuevo comando `OFF [canal]`;
  `?` agrega un 7.º número con los servos prendidos (bits).
- Nueva TUI `pc/tui_brazo.py` para mover canal por canal en pasitos suaves, hacer barridos, ver si
  el Uno recibió cada orden y anotar OK / no responde / zumba (guarda reporte en `pc/resultados/`).
- Prueba con la TUI (por la ESP): **base y muñeca responden perfecto**; hombro y codo se traban o
  "se aplastan". Causa probable: la casa vieja (hombro 22°, codo 175°) está en los topes mecánicos,
  el servo empuja contra el tope, jala ~2.5 A y la fuente (límite 3 A) entra en CC → los demás se
  aflojan. La TUI ahora arranca hombro y codo en 90° y permite marcar el rango seguro (`m` / `M`),
  que imprime como `LIM_MIN` / `LIM_MAX` para el firmware.
- Con la TUI ya funciona todo. Poses medidas: **casa 90 80 90**, **estirado 100 165 5** (base,
  hombro, codo); muñeca y pinza se quedan sueltas (`-1` en `HOME_POS` / `STRETCH_POS`). Los ángulos
  son absolutos (mismo pulso = misma posición), así que se repiten sin importar dónde se encienda;
  solo el primer movimiento brinca. Gestos: sí = estirado + codo 5↔10 ×3; baile = base 50↔110 y
  hombro 160↔165 ×3. saludo = sí; no/susto = base 70↔110; agarrar/soltar no hacen nada (sin pinza).
- "De repente no funciona" al desconectar/conectar o apagar la fuente. Causas probables: (1) el
  PCA9685 pierde alimentación un instante y arranca dormido a otra frecuencia → ya no saca pulsos;
  (2) el Uno se reinicia (USB o bajón) y suelta los servos. BrazoESP ahora revisa el prescaler del
  PCA9685 cada 1 s y lo reconfigura y restaura los servos (`!! El PCA9685 se reinicio`); I2C con
  timeout de 3 ms para no colgarse. TUI: tecla `r` reenvía los ángulos. Orden de encendido en PENDIENTES.
- **Ya funciona** el brazo por la ESP (base, hombro, codo) con casa, estirado, sí y baile.
- El baile ahora dura lo que la música: `Gestos.hacer(..., repetir=True)` repite el gesto hasta
  `parar()` y luego regresa a casa; `tom.py` lo usa al cantar (canción de 13.7 s). "baila" /
  "bailar" / "fiesta" ahora contesta y pone la canción con el baile (antes solo bailaba ~5 s sin música).
- Lo intermitente del codo era **un cable desoldado**.
- `tom.py` ahora es una **TUI**: configuración con teclas (voz, Function/automático, Kalman, repetir
  o "no entendí", brazo, mover-antes-de-hablar, volumen), barra del micrófono con el umbral, lista
  de frases con lo que entendió Vosk y si coincidió (✓/✗), y teclas 1/2/3 para casa/sí/baile.
  `--sin-tui` deja el modo de antes. Los mensajes de librerías (numba) se filtran.
- Nueva respuesta: "¿te gusta…?" / "¿te gustaría…?" → siempre **sí** (gesto `si` y luego la frase
  grabada `si.wav`, que falta grabar). Por defecto el brazo se mueve **antes** de hablar (tecla m).
  "baila" dice su frase y luego canta y baila. "casa" también manda a casa.
- El repo de X: no tenía el modelo de Vosk (está en .gitignore): se copió a `pc/modelos/`.
- Con solo la fuente (Uno sin corriente) el codo se queda forzado: sin VCC el PCA9685 no saca señal
  y el servo lee ruido. Regla: **primero el Uno, luego la fuente** (opcional: 10 kΩ de señal a GND).
- BrazoESP: `ARRANCA_EN_CASA = true` → al encender prende base, codo y hombro (en ese orden, 0.5 s
  entre cada uno) directo en la casa 90 80 90; muñeca y pinza quedan sueltas. La TUI ya los toma
  como prendidos en la casa (su primer movimiento es suave).
- **Rangos medidos** (fuera de ellos chocan con el tope): base 50–140, hombro 100–170, codo 10–90.
  Puestos en `LIM_MIN` / `LIM_MAX` del Uno (ahora también `T` los respeta), en `gestos.py` y en la TUI.
- **Poses nuevas:** casa 90 100 90 · estirado (base igual) 170 10 · sí = estirado + codo 10↔15 ×3 ·
  baile = base 50↔140 y hombro 160↔165. Igual en `Arm.h`.
- Voz por articulación: "mueve la base / el hombro / el codo" sin número hace un movimiento dentro
  de su rango y regresa (`mover_*` en gestos.py); con número ("el codo a ciento cincuenta") se
  recorta al rango (→ 90°) y la TUI lo dice. Los gestos ahora recuerdan dónde quedó cada servo
  (`Gestos.pos`, `Gestos.ir`): antes, después de mover la base por voz, el baile brincaba.
- En "baila" el brazo empieza a bailar antes de la frase y sigue durante toda la canción.

## 27 nov 2026 — presentación
- **Se presentó y todo funcionó** (voz, caras, casa, estirado, sí, baile con la canción, movimientos por voz).
- Se grabó `si.wav` ("¡Sí! ¡Me encanta!").
- `COMANDOS.md` con todos los comandos para correrlo; `docs/CONTEXTO_REPORTE.md` con todo lo necesario
  para el reporte (qué cambió desde el 23 nov, datos medidos, problemas y soluciones).
- README actualizado (BrazoESP, rangos, gestos, TUI). Todo subido a GitHub.

**Siguiente:** ver `PENDIENTES.md`.
