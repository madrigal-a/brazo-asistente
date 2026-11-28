# Contexto completo para el reporte — Brazo asistente "Talking Bolita"

Documento para terminar el reporte (o para pasárselo a quien lo escriba, persona o IA). Reúne qué es
el proyecto, cómo funciona, todos los números medidos, los problemas que hubo y cómo se resolvieron.
**El reporte que ya existe se hizo con la versión de GitHub del 23 nov 2026**; la sección 2 dice
qué cambió desde entonces. Estado final: **presentado el 27 nov 2026 y todo funcionó.**

Materias: **Procesamiento de señales** (filtro de Kalman para la voz y para los potenciómetros,
efectos de voz, detección de voz) y **Dinámica de sistemas mecatrónicos** (brazo robótico:
calibración, rangos, perfiles de movimiento, pruebas). Universidad Anáhuac, Ingeniería Mecatrónica.

---

## 1. Resumen
Una mascota virtual tipo *Talking Tom* que controla un brazo robótico de 3 grados de libertad útiles
(base, hombro, codo). Le hablas a la computadora; el programa limpia tu voz con un filtro de Kalman,
reconoce palabras sin internet (Vosk), y según lo que dijiste:
- contesta con una frase grabada (con efecto de voz) mientras la cara en la pantalla "habla", y
- mueve el brazo: "¿te gusta…?" → gesto de **sí**; "baila" → **baila toda la canción**; "casa" → posición
  de casa; "mueve el codo a cuarenta" → mueve esa articulación, siempre dentro de su rango seguro.
Si no entiende, te repite con voz chistosa (como Talking Tom).

```
Micrófono de la compu ─► Python (pc/): Kalman AR(10) + Vosk + respuestas + efectos de voz
        │                        │ USB serial 460800 (tramas binarias A5 5A)
        │                        ▼
        │               ESP32-S3: pantalla 2.4" (cara), bocina (MAX98357), botones Function/Mode
        │                        │ UART 115200, texto (GPIO 40 TX → pin 0 RX del Uno)
        │                        ▼
        └──────────────► Arduino Uno + PCA9685 (I2C) ─► servos: base (ch 14), hombro (13), codo (12)
                                       ▲
                         Fuente de laboratorio 5.0 V, límite 3 A (V+ de los servos)
```

## 2. Qué cambió desde la versión de GitHub del 23 nov (la del reporte actual)
| Tema | 23 nov (reporte actual) | Versión final (27 nov) |
|---|---|---|
| Sketch del Uno | `firmware/BrazoUno` (potes + modo remoto) | **`firmware/BrazoESP`** (sin potes, rangos, casa, recuperación del PCA9685). `BrazoManual` para usarlo solo con el control |
| Lectura de potes | `analogRead` directo, mapeo único 240–800 | Lectura sin "fantasma" del ADC + calibración de 2 puntos **por pote** (en BrazoManual) |
| Control de potes | se usaba | **se quitaron** del bracito; el brazo lo manda la voz/ESP (`HAY_CONTROL = false`) |
| Casa | 119 22 175 84 (medida con los potes, estaba en los topes) | **90 100 90** (base, hombro, codo), medida con la TUI |
| Estirado | 118 175 10 139 | **(base igual) 170 10** |
| Rangos | 0–180 en todas | **base 50–140, hombro 100–170, codo 10–90** (fuera de eso chocan) |
| Muñeca y pinza | se movían | **sueltas** (sin pulso) |
| Gestos | muñeca de lado a lado, etc. | sí, baile, estirar, casa, mover_base/hombro/codo (sección 6.5) |
| Baile | ~5 s, sin música en "baila" | **dura toda la canción** y empieza antes de que la bolita hable |
| Comunicación ESP ↔ Uno | planeada | **ida funcionando** (GPIO 40 → pin 0); la vuelta (divisor) no se instaló |
| Programa de la PC | `tom.py` texto | **`tom.py` con TUI** (configuración, nivel del mic, frases reconocidas ✓/✗) |
| Herramientas de prueba | — | **`tui_brazo.py`** (canal por canal, barridos, rangos), `probar_uart.py`, `gestos.py --manual` |
| Respuestas | 15 | **17** (nueva: "¿te gusta…?" → sí, con `si.wav`) |

## 3. Hardware
| Componente | Detalle |
|---|---|
| Microcontrolador del brazo | Arduino Uno (ATmega328P) |
| Driver de servos | PCA9685 (16 canales PWM, I2C en A4/A5, dirección 0x40), VCC del 5V del Uno, V+ de la fuente |
| Servos | 3× MG996R, 1× SG90, 1× HPS-2018MG. No pasar de 6 V (SG90) |
| Fuente de servos | Laboratorio, **5.0 V, límite 3 A** |
| Mascota | ESP32-S3 N16R8 (placa YD-ESP32-S3, PSRAM octal), pantalla ST7789 2.4" 240×320 sin touch, MAX98357 + bocina 8 Ω 2 W, botones Function (GPIO 15) y Mode (GPIO 16) |
| Audio de entrada | micrófono de la computadora (los INMP441 nunca funcionaron) |

**Canales del PCA9685** (comprobados con `T canal ángulo`): base 14, hombro 13, codo 12, muñeca 11,
pinza 10, el 15 vacío (uno abajo de lo que decía la práctica, que usaba 11–15).

**Conexión ESP ↔ Uno:** GPIO 40 (TX de la ESP) → pin 0 (RX del Uno) directo, GND común. La vuelta
(pin 1 del Uno → divisor 1 kΩ / 2 kΩ → GPIO 41) no se instaló: no hace falta para mandar órdenes.
La ESP va a la compu por el USB-C **"COM"** (chip CH343, COM8); por el USB nativo no habla.

**Orden de encendido:** primero el Uno (USB) y la ESP, después la fuente de servos. Con la fuente
prendida y el Uno apagado, el PCA9685 no tiene VCC, los cables de señal quedan al aire y el servo del
codo se va al tope y se queda forzando.

## 4. Software (qué hace cada archivo)
| Archivo | Qué hace |
|---|---|
| `firmware/BrazoESP/BrazoESP.ino` | Uno: recibe órdenes por serial, mueve los servos con límite de velocidad y de rango, arranca en casa, se recupera si el PCA9685 se reinicia |
| `firmware/BrazoManual/BrazoManual.ino` | Uno sin ESP: copia al control de 4 potes (lectura sin fantasma, Kalman 1D, calibración de 2 puntos, diagnóstico `D`/`REVISA`/`BUSCA`/`CAL`/`PUNTO`) |
| `firmware/TalkingBolita/` | ESP32-S3: cara (8 expresiones dibujadas con código), audio I2S desde un búfer en PSRAM, botones, menú, reenvía las órdenes del brazo al Uno; rutinas en `Arm.h` |
| `pc/tom.py` | Programa principal con TUI: micrófono → detección de voz → Kalman → Vosk → respuesta → brazo + voz |
| `pc/dsp.py` | Kalman AR(10) para la voz, LPC (Levinson-Durbin), efectos de voz, tono, nivel en dB |
| `pc/respuestas.py` | Tabla palabra → audio grabado, cara y gesto del brazo |
| `pc/servo_voz.py` | "mueve el codo a ciento veinte" → canal 12, 120° (convierte números escritos en letra) |
| `pc/gestos.py` | Gestos del brazo en pasitos de 30 ms, rangos seguros, memoria de posición |
| `pc/tui_brazo.py` | TUI para probar canal por canal, barridos, marcar rangos, reporte |
| `pc/bolita.py` | Protocolo serial con la ESP |
| `pc/cancion.py` | Canción original por síntesis aditiva (13.7 s) |
| `pc/grabar.py` | Grabar las frases de respuesta |
| `pc/demo_kalman.py` | Mide la mejora de SNR del Kalman y genera gráficas |
| `pc/probar_uart.py`, `pc/probar_esp.py` | Pruebas de comunicación |

### 4.1 Protocolos
**PC → ESP** (binario): `A5 5A | tipo | largo (2 bytes LE) | datos | checksum (suma & 0xFF)`.
Tipos: `M` cara, `L` mirada, `A` audio 16 kHz int16, `S` parar audio, `V` volumen, `B` orden para el
brazo (texto), `P` ping. **ESP → PC** (texto): `PTT 1/0/C` (botón Function), `BTN ...`, `PARO`, `DONE`, `READY`.

**ESP → Uno** (texto, 115200, una línea por orden):
`J b h c m` ángulos (−1 = no cambiar) · `V °/s` velocidad · `HOME` · `ESTIRA` · `T canal ángulo`
(prueba de un canal) · `OFF [canal]` soltar · `?` → `S b h c m pinza modo prendidos` (la ESP lo pide cada 300 ms).

## 5. Procesamiento de señales
### 5.1 Filtro de Kalman para la voz (`pc/dsp.py → kalman_denoise`)
- **Modelo de la voz:** proceso autorregresivo de orden 10: `s[n] = a1·s[n−1] + … + a10·s[n−10] + w[n]`, `w ~ N(0, Q)`.
- **Medición:** `y[n] = s[n] + v[n]`, `v ~ N(0, R)` (ruido del micrófono).
- **Estado:** `x[n] = [s[n], …, s[n−9]]ᵀ`, matriz de transición compañera `F` con los `a_k`, `H = [1 0 … 0]`.
- Cada trama de 20 ms (320 muestras a 16 kHz) se recalculan los `a_k` con LPC (autocorrelación +
  Levinson-Durbin) y `Q` con el error de predicción. `R` se estima con el percentil 10 de la energía
  de las tramas (las más silenciosas, medidas en la calibración de 2 s al arrancar).
- **3 pasadas:** desde la segunda, los coeficientes LPC se calculan sobre la voz ya filtrada (mejor modelo).
- **Resultado (señal sintética + ruido blanco):** SNR de 0 dB → 8.2 dB y de 5 dB → 11.8 dB (**≈ +6 a +7 dB**).
  Para graficar: `py -3.12 pc/demo_kalman.py --grabar 4 --ruido 5` (genera `resultados/kalman.png`).
- Vosk reconoce mejor el audio **original** que el filtrado, así que el filtrado se usa para lo que se reproduce.

### 5.2 Detección de voz y cara
- Bloques de 20 ms. Umbral de voz = ruido medido + 12 dB (mínimo −55 dBFS). Se guardan 300 ms antes
  de que empiece la voz. Con el botón Function (push-to-talk) graba mientras lo mantienes (máx. 12 s);
  en automático corta tras 0.7 s de silencio. Frases de menos de 0.45 s se descartan.
- La cara cambia en vivo: grito (> ruido + 38 dB) → sorpresa; tono 30 % más agudo que tu promedio → feliz;
  18 % más grave → enojado. El tono promedio se aprende con cada frase (filtro 0.8 / 0.2).

### 5.3 Efectos de voz
Remuestreo (tom, ardilla, monstruo), modulación en anillo a 60 Hz (robot), retardos con
retroalimentación (eco). La canción es síntesis aditiva: fundamental + 2.º + 3.er armónico con envolvente ADSR.

### 5.4 Filtro de Kalman 1D en cada potenciómetro (BrazoManual)
Modelo: `x[k] = x[k−1] + w` (el pote casi no cambia en 20 ms), `z[k] = x[k] + v` (ruido del ADC).
`Q = 0.4`, `R = 12 cuentas²`. Predicción `P ← P + Q`; ganancia `K = P / (P + R)`; corrección
`x ← x + K (z − x)`; `P ← (1 − K) P`. Quita el temblor de los servos al copiar al control.

## 6. Dinámica de sistemas mecatrónicos (el brazo)
### 6.1 Modelo del actuador (servo)
Señal PWM de 50 Hz (periodo 20 ms). Ancho de pulso lineal con el ángulo:
`t = 650 µs + (θ / 180°) · (2350 − 650) µs`. El PCA9685 (oscilador 27 MHz, 12 bits) usa
`cuentas = t / 20 000 µs · 4096`.

| θ | Pulso | Cuentas |
|---|---|---|
| 10° | 744 µs | 152 |
| 50° | 1122 µs | 229 |
| 90° | 1500 µs | 307 |
| 100° | 1594 µs | 326 |
| 140° | 1972 µs | 403 |
| 170° | 2256 µs | 461 |

El servo es un lazo cerrado interno (potenciómetro + control proporcional) **sin salida de posición**:
el Uno no sabe dónde está el servo. Consecuencias: (1) se necesita una pose de referencia (casa) al
encender; (2) el primer movimiento "brinca" desde donde haya quedado; (3) mismo pulso = misma posición,
así que las poses se repiten siempre igual.

### 6.2 Perfil de movimiento (limitador de velocidad)
El Uno corre a 50 Hz (cada 20 ms) y mueve cada articulación hacia su objetivo sin pasar de una
velocidad máxima: `θ[k+1] = θ[k] + sat(θ_obj − θ[k], ±ω_max·Δt)`. Velocidades usadas: 60 °/s para
órdenes de voz, 80 °/s estirarse, 90–120 °/s baile, 70 °/s al regresar al control, 300 °/s copiando al
control. Los gestos de la PC hacen lo mismo en pasitos de 30 ms (`T canal ángulo` por pasito).
Al encender se prenden los servos uno por uno, 0.5 s entre cada uno (base → codo → hombro), para no
pedirle a la fuente la corriente de arranque de todos a la vez.

### 6.3 Calibración de los potenciómetros del control (antes de quitarlos)
- Los potes toman su voltaje de la fuente de servos: con la fuente apagada `P` daba basura.
- Lecturas con fuente encendida (orden A0 A1 A2 A3): recogido `ADC 537 142 742 428`, estirado `ADC 367 779 135 432`.
- **"Fantasma" del ADC:** el Uno tiene un solo convertidor con multiplexor; su capacitor de muestreo
  "recuerda" el pin anterior si la impedancia del pote es alta. Por eso el pote del codo movía la muñeca.
  Solución: una lectura de sobra que se tira, esperar 50 µs y promediar 4 lecturas.
- **Calibración de 2 puntos por pote** (recta `θ = θ1 + (ADC − ADC1)·(θ2 − θ1)/(ADC2 − ADC1)`):

| Pote | Pin | Punto 1 | Punto 2 |
|---|---|---|---|
| base | A3 | ADC 660 → 45° | ADC 380 → 135° |
| hombro | A2 | ADC 660 → 45° | ADC 380 → 135° |
| codo | A1 | ADC 142 → 175° | ADC 779 → 10° |
| muñeca | A0 | ADC 537 → 84° | ADC 367 → 139° |

(Base y hombro = el mapeo original 800 → 0°, 240 → 180°.)

### 6.4 Rangos seguros y poses (medidos con la TUI, 26 nov)
Se movió cada articulación de 5 en 5 grados hasta que dejaba de avanzar, zumbaba o la fuente entraba
en CC (corriente limitada), y se regresó un poco.

| Articulación | Canal | Rango seguro | Casa | Estirado |
|---|---|---|---|---|
| Base | 14 | 50°–140° | 90° | (no se mueve) |
| Hombro | 13 | 100°–170° | 100° | 170° |
| Codo | 12 | 10°–90° | 90° | 10° |
| Muñeca | 11 | — (suelta) | — | — |
| Pinza | 10 | — (suelta, vibraba contra su tope) | — | — |

Los rangos están en el firmware (`LIM_MIN` / `LIM_MAX`) y **ninguna orden los puede pasar**, ni siquiera
la prueba cruda `T`. Si por voz pides "el codo a ciento cincuenta", va a 90° (su máximo).

### 6.5 Gestos (secuencias)
| Gesto | Secuencia | Velocidad |
|---|---|---|
| casa | base 90, hombro 100, codo 90 | 60 °/s |
| estirar | hombro 170, codo 10 → espera 2 s → casa | 80 °/s |
| sí | estirado → codo 10 ↔ 15 tres veces → casa | 80 / 60 °/s |
| baile | (base 50, hombro 160) ↔ (base 140, hombro 165), repetido mientras dura la canción → casa | 90–120 °/s |
| no / susto | base 70 ↔ 110 | 120 °/s |
| mover_base | base 130 → 60 → casa | 60 °/s |
| mover_hombro / mover_codo | hombro 150 / codo 45 → casa | 50 °/s |

Orden en el tiempo de "baila" (simulado): 0 s arranca el brazo · 0.4 s "¡A bailar se ha dicho!" (2.1 s) ·
2.9 s la canción (13.7 s) · 16.6 s termina · ~17.4 s el brazo llega a casa.

### 6.6 Corriente y fuente (por qué se trababa)
Un MG996R trabado contra su tope jala ~2.5 A. Con la fuente limitada a 3 A, un servo forzando la
pone en CC (corriente constante), el voltaje baja y los demás servos se aflojan ("el hombro se aplasta").
Por eso los rangos son importantes además de por la mecánica.

## 7. Problemas encontrados y cómo se resolvieron (para la sección de resultados / discusión)
| # | Síntoma | Causa | Solución |
|---|---|---|---|
| 1 | `P` daba casi lo mismo en cualquier pose | Los potes se alimentan de la fuente de servos | Calibrar con la fuente encendida |
| 2 | El orden de los potes del código original no coincidía | Cableado según la Figura 1 de la práctica | base A3, hombro A2, codo A1, muñeca A0 |
| 3 | Los servos estaban en otros canales | Quedaron uno abajo de la práctica | Prueba canal por canal con `T`: base 14 … pinza 10 |
| 4 | El pote del codo movía la muñeca | "Fantasma" del ADC (capacitor de muestreo del multiplexor) | Lectura de sobra + 50 µs + promedio de 4 |
| 5 | El codo se quedaba pegado en un tope del mapeo | Un solo mapeo 240–800 para todos | Calibración de 2 puntos por pote |
| 6 | La bocina de la ESP dejó de sonar | Probable falla del MAX98357 | La voz puede salir por la compu (`--audio pc`); se recuperó después |
| 7 | Audífonos Bluetooth en la ESP | La ESP32-S3 solo tiene BLE; los audífonos usan Bluetooth clásico | La compu es micrófono y bocinas |
| 8 | El Uno no recibía nada de la ESP | Los cables estaban en GPIO 43/44 (los del USB a la compu) | Pasarlos a GPIO 40 → pin 0 |
| 9 | Python no abría la ESP | Estaba conectada por el USB-C nativo | Usar el USB-C "COM" (CH343) |
| 10 | Un `T` mandado por la ESP se deshacía | La ESP manda `?` cada 300 ms y cualquier comando salía del modo prueba | `?` y `P` ya no sacan del modo prueba |
| 11 | Los servos se movían solos | El Uno leía los potes (ruido > 20° = tomaba el control); después, pines al aire sin potes | Ignorar potes con la ESP conectada; luego `HAY_CONTROL = false` |
| 12 | Hombro y codo "apretados" o "se aplastan" | La casa vieja (22° y 175°) estaba en los topes: servo forzando + fuente en CC | Medir rangos y casa nuevas; límites en el firmware |
| 13 | "De repente funciona y de repente no" | (a) el PCA9685 se reinicia y arranca dormido; (b) el Uno se reinicia; (c) **cable del codo desoldado** | Revisión del prescaler cada 1 s y reconfiguración; tecla `r`; resoldar el cable |
| 14 | Con solo la fuente prendida el codo se forzaba | Sin el Uno, el PCA9685 no tiene VCC y la señal queda al aire | Orden de encendido; arrancar siempre en casa |
| 15 | Tras mover la base por voz, el baile brincaba | Los gestos suponían que el brazo estaba en casa | Los gestos recuerdan la última posición |
| 16 | El Arduino IDE pisaba el archivo nuevo | Guardaba la pestaña abierta (versión vieja) | Cerrar la pestaña sin guardar antes de actualizar |

## 8. Cómo se prueba y se opera
Comandos completos en [COMANDOS.md](../COMANDOS.md). Resumen:
1. Subir `firmware/BrazoESP` al Uno (cable del pin 0 desconectado); el Monitor Serie dice `BRAZO ESP listo ... en CASA`.
2. Encender: Uno y ESP por USB → fuente.
3. Probar el brazo: `py -3.12 pc/tui_brazo.py --port COM8` y `py -3.12 pc/gestos.py baile --port COM8`.
4. La bolita: `py -3.12 pc/tom.py --port COM8`.

## 9. Resultados
- **Presentación del 27 nov: todo funcionó.** La bolita reconoce las frases, contesta con voz, cambia
  la cara, y el brazo hace casa, estirado, sí y el baile completo con la canción; también mueve cada
  articulación por voz dentro de su rango.
- Comunicación ESP → Uno estable a 115200 (el Uno contesta el `?` de la ESP cada 300 ms).
- Firmware del Uno: 20.3 KB de flash (62 %), 865 B de RAM (42 %).
- Kalman de voz: ≈ +6–7 dB de SNR en pruebas sintéticas.

## 10. Limitaciones y trabajo futuro
- La vuelta Uno → ESP (divisor 1k/2k en GPIO 41) no se instaló: la ESP no ve la posición real del brazo.
- Muñeca y pinza sin usar (la pinza vibraba contra su tope): calibrar sus rangos.
- Los servos no reportan su posición: con servos con retroalimentación (o leyendo su pote interno) se
  podría evitar el brinco del primer movimiento y detectar atascos.
- Una resistencia de 10 kΩ de cada señal a GND evitaría que los servos se forzaran si se prende la
  fuente con el Uno apagado.
- La fuente de 3 A es justa para varios MG996R a la vez; una de 5 A daría margen.
- El reconocimiento depende del micrófono de la compu y del ruido del lugar.

## 11. Figuras que se pueden usar
- `docs/caras.png`: las 8 expresiones de la bolita.
- `resultados/kalman.png`: forma de onda y espectrogramas antes y después del Kalman (con `demo_kalman.py`).
- Captura de la TUI de `tom.py` (frases reconocidas ✓/✗) y de `tui_brazo.py` (rangos).
- Diagrama de bloques de la sección 1 y la tabla de pulsos de la sección 6.1.
- Tablas de calibración (6.3), rangos y poses (6.4), gestos (6.5) y problemas (7).

Más detalle de cada decisión, en orden: [HISTORIAL.md](../HISTORIAL.md).
