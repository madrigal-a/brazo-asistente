# Brazo asistente — Talking Bolita 🟡🦾

> **Estado actual y pendientes:** ver [PENDIENTES.md](PENDIENTES.md).

Una mascota tipo Talking Tom que además controla un brazo robótico: le hablas, limpia tu voz con
un **filtro de Kalman**, hace caras según cómo hablas, te repite con voz chistosa y el brazo
reacciona. Desde la pantalla touch también mueves el brazo con sliders y botones.

```
 Micrófono de la compu ──► Python: Kalman + efectos + caras ──USB──► ESP32-S3: pantalla touch + bocina + 2 botones
                                                                          │ serial (TX/RX)
                                                                          ▼
                                                     Arduino Uno + PCA9685 ──► 5 servos del brazo (+ potenciómetros)
```

- **`firmware/TalkingBolita/`**: sketch de Arduino para la ESP32-S3
- **`firmware/BrazoUno/`**: sketch para el Arduino Uno del brazo
- **`pc/`**: programas de Python
- **`docs/caras.png`**: vista previa de las 8 expresiones

![caras](docs/caras.png)

---

## 1. Conexiones

### Pantalla roja 2.4" ST7789 (SPI)
| Pantalla | ESP32-S3 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SCL / SCK | GPIO 12 |
| SDA / SDI / MOSI | GPIO 11 |
| CS | GPIO 10 |
| DC / RS | GPIO 9 |
| RES / RST | GPIO 14 |
| BL / LED / BLK | GPIO 21 |
| SDO / MISO | GPIO 13 |
| T_CLK | GPIO 12 (junto con SCK) |
| T_DIN | GPIO 11 (junto con MOSI) |
| T_DO | GPIO 13 (junto con MISO) |
| T_CS | GPIO 8 |
| T_IRQ | GPIO 7 |

La primera vez que arranca te pide tocar las 4 esquinas para calibrar el touch. Para repetir la
calibración, mantén el botón 2 presionado al encender.

### Amplificador MAX98357
| MAX98357 | ESP32-S3 |
|---|---|
| VIN | 5V |
| GND | GND |
| BCLK | GPIO 4 |
| LRC | GPIO 5 |
| DIN | GPIO 6 |
| GAIN, SD | sin conectar |
| + / − | bocina de 8 Ω |

### Botones (una pata al GPIO, la otra a GND)
| Botón | GPIO | Qué hace |
|---|---|---|
| 1 | 15 | cambia de pantalla: cara ↔ control del brazo |
| 2 | 16 | paro: detiene la rutina y manda el brazo a inicio |

### ESP32-S3 ↔ Arduino Uno del brazo
| ESP32-S3 | Arduino Uno | |
|---|---|---|
| GPIO 40 (TX) | pin 0 (RX) | directo |
| GPIO 41 (RX) | pin 1 (TX) | **con divisor**: Uno TX → 1 kΩ → GPIO 41, y GPIO 41 → 2 kΩ → GND |
| GND | GND | obligatorio |

```
 Uno pin 1 (TX, 5 V) ──[ 1 kΩ ]──┬── GPIO 41 de la ESP (≈3.3 V)
                                 │
                              [ 2 kΩ ]
                                 │
                                GND
```

- El divisor es necesario porque la ESP32 **no aguanta 5 V**. Si no lo pones, la ESP igual puede
  mandar órdenes; solo no verá la posición real del brazo.
- **Al subir código al Uno, desconecta el cable del pin 0**, si no, la subida falla.
- El resto del brazo se conecta como en la Figura 1 de la práctica (PCA9685 en A4/A5, potes en
  A0–A3, botón en el pin 13). Los servos con su propia fuente de 5 V, 3 A.
  En nuestro brazo los servos quedaron un canal abajo de la práctica: base 14, hombro 13,
  codo 12, muñeca 11, pinza 10 (ya está así en `BrazoUno.ino`).

### Bocina
Cable multifilar de 22–24 AWG, o un jumper con el conector cortado y soldado. Ninguna terminal
de la bocina va a GND: solo a + y − del MAX98357.

---

## 2. Cargar el firmware (Arduino IDE)

1. **Gestor de placas** → instala **esp32** de Espressif (3.x o 4.x).
2. **Gestor de librerías** → instala **LovyanGFX**.
3. Abre `firmware/TalkingBolita/TalkingBolita.ino`.
4. Herramientas:
   - Placa: **ESP32S3 Dev Module**
   - PSRAM: **OPI PSRAM** ← importante (la N16R8 tiene PSRAM octal)
   - Flash Size: **16MB**
   - USB CDC On Boot: **Disabled**
5. Conecta el USB-C marcado **COM** o **UART** (no el que dice USB) y sube el código.

Al arrancar debe sonar un *pío* y la bolita sonríe.
- Si la pantalla sale con colores invertidos → `TFT_INVERT true` en `Config.h`.
- Si rojo y azul salen cambiados → `TFT_RGB_ORDER true`.
- Si la pantalla dice "Sin PSRAM" → revisa el paso de PSRAM.

### Arduino Uno del brazo
1. Gestor de librerías → **Adafruit PWM Servo Driver Library**.
2. Abre `firmware/BrazoUno/BrazoUno.ino`, placa **Arduino Uno**, sube (con el pin 0 desconectado).
3. Funciona igual que la práctica (potenciómetros + botón de la mano). Además, en el
   **Monitor Serie a 115200 con "Nueva línea"** puedes escribir:

| Comando | Qué hace |
|---|---|
| `J 90 120 60 90` | base, hombro, codo, muñeca en grados (−1 = no cambiar) |
| `H 100` / `H 0` | cerrar / abrir mano |
| `V 60` | velocidad en °/s |
| `HOME` | posición de casa (recogido) |
| `ESTIRA` | brazo estirado |
| `MAN` | regresar a potenciómetros |
| `?` | estado |
| `P` | ángulos del control + ADC crudo (para calibrar) |
| `T 14 60` | prueba: mueve solo ese canal del PCA9685 (salir con `MAN`) |

**Al encender**, el brazo va a la posición de **casa** (recogido) y se queda ahí. Esa es su
referencia: los servos no avisan en qué ángulo están, así que el programa siempre parte de una
posición conocida. Enciende los servos con el brazo cerca de la casa para que no dé un brinco.
En cuanto mueves el control (el bracito de potenciómetros) más de 20°, el brazo lo empieza a
copiar, primero despacio hasta alcanzarlo. Si llega una orden de la ESP, obedece a la ESP.

**Calibración (para el reporte):**
1. Con la fuente **encendida** (los potes toman de ahí su voltaje) y los servos desconectados de
   la placa azul, pon el control en la pose recogida, escribe `P` en el Monitor Serie y copia los 4 ángulos que responde (`P base hombro codo muñeca`)
   en `HOME_POS`.
2. Haz lo mismo con el brazo estirado → `STRETCH_POS`.
3. Mueve cada articulación a sus extremos sin que choque y anota los ángulos en `LIM_MIN` / `LIM_MAX`.
4. Los ángulos de las rutinas (saludar, bailar...) están en `firmware/TalkingBolita/Arm.h`.

Los potenciómetros también tienen un **filtro de Kalman 1D** (`kalmanStep`) que quita el temblor
de los servos: puedes graficar la lectura cruda contra la filtrada para el reporte.

### Pantalla touch
- **Cara:** tócala para "picarla" (pone > < y el brazo se asusta). El ícono del brazo, abajo a la
  derecha, abre el control.
- **Control:** 4 sliders (base, hombro, codo, muñeca) y botones Cerrar/Abrir, Inicio, Saluda,
  Baila y Cara. Arriba dice si el Uno responde y en qué modo está.

---

## 3. Python (en la compu)

```bash
cd pc
pip install -r requirements.txt
```

### Sin hardware (para avanzar hoy mismo)
```bash
python tom.py --simular
```
Usa el micrófono y las bocinas de la compu e imprime qué cara pondría la bolita.

### Probar la ESP32
```bash
python probar_esp.py              # recorre las caras, mueve ojos y suena una melodía
python probar_esp.py --brazo      # además prueba rutinas del brazo (sí, no, saludo)
python tom.py --puertos           # si no encuentra la placa, para ver el nombre del puerto
```

### Talking Bolita
```bash
python tom.py                     # o: python tom.py --port COM5
python tom.py --voz ardilla
python tom.py --guardar frases    # guarda original / kalman / efecto de cada frase (para el reporte)
python tom.py --sin-kalman        # para comparar
python tom.py --mics              # lista micrófonos; luego --mic N
```

Al iniciar, quédate callado 2 s para que mida el ruido.

**Cómo elige la cara:**
| Lo que haces | Cara |
|---|---|
| Empiezas a hablar | escuchando (ojos grandes) |
| Gritas | sorpresa |
| Hablas más agudo que tu normal | feliz |
| Hablas más grave que tu normal | enojado |
| Te repite | habla con la boca al ritmo del audio |
| 60 s sin hacerle caso | se duerme (zzz) |
| Tocas la cara | > < y el brazo se asusta |
| Le gritas | sorpresa y el brazo se echa para atrás |

Tu tono "normal" lo aprende con cada frase, así que lo agudo y lo grave son relativos a tu voz.

### Palabras (opcional, sin internet)
1. `pip install vosk`
2. Descarga **vosk-model-small-es-0.42** de <https://alphacephei.com/vosk/models> y descomprímelo.
3. `python tom.py --vosk ruta/a/vosk-model-small-es-0.42`

| Dices | Cara | Brazo |
|---|---|---|
| hola, saluda | feliz | saluda |
| baila, fiesta | feliz | baila |
| estírate | sorpresa | se estira |
| agarra, toma, recoge | escuchando | agarra |
| suelta | neutral | abre la mano |
| quieto, alto, inicio | neutral | inicio |
| bu, susto, cuidado | sorpresa | se echa para atrás |
| tonto, feo / enójate | triste / enojado | dice que no |
| te quiero, bonito, amigo | feliz | dice que sí |
| duérmete, buenas noches | dormido | inicio |
| otra voz | — | (cambia la voz) |

Se editan en `KEYWORDS` dentro de `tom.py`.

---

## 4. Para la materia: filtro de Kalman

Todo está en `pc/dsp.py` → `kalman_denoise()`.

- **Modelo de la voz:** proceso autorregresivo de orden 10,
  `s[n] = a1·s[n-1] + … + a10·s[n-10] + w[n]`, con `w ~ N(0, Q)`.
- **Medición:** `y[n] = s[n] + v[n]`, con `v ~ N(0, R)` (ruido del micrófono).
- **Estado:** `x[n] = [s[n], …, s[n-9]]`, matriz de transición compañera `F` con los `a_k`, `H = [1 0 … 0]`.
- Cada trama de 20 ms se recalculan los `a_k` (LPC con Levinson-Durbin) y `Q`.
  `R` se estima en las tramas más silenciosas.
- Se hacen 3 pasadas: desde la segunda, los LPC salen de la voz ya filtrada.

**Resultados con señal sintética + ruido blanco:** 0 dB → 8.2 dB, 5 dB → 11.8 dB de SNR (~+7 dB).

```bash
python demo_kalman.py --grabar 4 --ruido 5   # tu voz + ruido conocido: mide la mejora en dB
python demo_kalman.py --grabar 4             # tu voz con el ruido real del cuarto
python demo_kalman.py --sintetica --ruido 0  # sin micrófono
```
Genera `resultados/kalman.png` (forma de onda y espectrogramas antes/después) y los `.wav`.

**Efectos de voz** (también procesamiento de señales): remuestreo (tom, ardilla, monstruo),
modulación en anillo a 60 Hz (robot) y retardos con retroalimentación (eco).

---

## 5. Problemas comunes

| Problema | Solución |
|---|---|
| No suena | Revisa VIN del MAX98357 a 5V y BCLK/LRC/DIN. Debe sonar el *pío* al arrancar. |
| "Uno: sin respuesta" en la pantalla | Revisa el divisor en GPIO 41 y que las tierras estén unidas |
| El brazo no obedece a la ESP | Cable de GPIO 40 al pin 0 del Uno; prueba los comandos en el Monitor Serie |
| El touch no responde o está chueco | Mantén el botón 2 al encender para recalibrar |
| Suena con chasquidos | Baja el volumen: `python tom.py --volumen 120` |
| La bolita se oye a sí misma | Aleja la bocina del micrófono de la compu |
| Detecta voz cuando no hablas | Recalibra en silencio, o sube el `+ 12` del umbral en `tom.py` |
| `PortAudio library not found` (Linux) | `sudo apt install libportaudio2` |
| No encuentra el puerto | `python tom.py --puertos` y luego `--port` |
