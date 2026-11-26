# Brazo asistente — Talking Bolita 🟡🦾

> **Estado actual y pendientes:** ver [PENDIENTES.md](PENDIENTES.md).

Una mascota tipo Talking Tom que además controla un brazo robótico: le hablas, limpia tu voz con
un **filtro de Kalman**, hace caras según cómo hablas, te repite con voz chistosa y el brazo
reacciona. Mantienes el botón **Function** para hablarle; con **Mode** abres un menú para mover el brazo.

```
 Micrófono de la compu ──► Python: Kalman + efectos + caras ──USB──► ESP32-S3: pantalla + bocina + 2 botones
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

### Pantalla roja 2.4" ST7789 (SPI, sin touch)
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
| T_CLK, T_CS, T_DIN, T_DO, T_IRQ | sin conectar |

Nuestro módulo (2.4" TFT SPI 240x320 V1.3) **no trae touch**: atrás, el lugar del chip U1 junto a
"TOUCH" está vacío. Por eso se controla con 2 botones.
En la placa YD-ESP32-S3 el GPIO 14 es el tercer pin de la fila de arriba, junto a 5Vin.

### Amplificador MAX98357
| MAX98357 | ESP32-S3 |
|---|---|
| VIN | **3V3** (en la YD-ESP32-S3 el pin 5Vin es una *entrada* para fuente externa, no saca 5 V) |
| GND | GND |
| BCLK | GPIO 4 |
| LRC | GPIO 5 |
| DIN | GPIO 6 |
| GAIN, SD | sin conectar |
| + / − | bocina de 8 Ω |

### Botones (una pata al GPIO, la otra a GND)
| Botón | GPIO | Qué hace |
|---|---|---|
| **Function** | 15 | en la cara: **mantener para hablar** · en el menú: elegir · en "Mover brazo": mantener = mover, toque = cambia + / − |
| **Mode** | 16 | abre el menú · siguiente opción · **mantener = salir** |
| los dos a la vez | | **PARO**: detiene la rutina, el audio, y manda el brazo a inicio |

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

**Con la ESP conectada, el control queda bloqueado:** la ESP le pregunta `?` al Uno cada 300 ms y,
mientras eso pase, el Uno **ignora los potenciómetros y el botón** (así el ruido de los potes no
mueve los servos). Si deja de recibir algo durante 2 s (ESP apagada o desconectada), el control
vuelve a funcionar al mover un pote más de 20°. Escribir en el Monitor Serie también lo bloquea 2 s.

**Calibración (para el reporte):**
1. Con la fuente **encendida** (los potes toman de ahí su voltaje) y los servos desconectados de
   la placa azul, pon el control en la pose recogida, escribe `P` en el Monitor Serie y copia los 4 ángulos que responde (`P base hombro codo muñeca`)
   en `HOME_POS`.
2. Haz lo mismo con el brazo estirado → `STRETCH_POS`.
3. Mueve cada articulación a sus extremos sin que choque y anota los ángulos en `LIM_MIN` / `LIM_MAX`.
4. Los ángulos de las rutinas (saludar, bailar...) están en `firmware/TalkingBolita/Arm.h`.

Los potenciómetros también tienen un **filtro de Kalman 1D** (`kalmanStep`) que quita el temblor
de los servos: puedes graficar la lectura cruda contra la filtrada para el reporte.

### Pantalla y botones
- **Cara:** mantén **Function** mientras hablas (sale un micrófono rojo arriba a la derecha) y
  suéltalo al terminar: la bolita te repite. Si lo presionas mientras habla, se calla y te escucha.
- **Menú (Mode):** Seguir, Pausa/Reanudar (deja de escuchar), Canta, Saluda, Baila, Cerrar/Abrir mano,
  Brazo a inicio, Mover brazo, Otra voz y PARO. Mode pasa a la siguiente opción, Function la
  elige y mantener Mode regresa a la cara.
- **Mover brazo:** 4 sliders (base, hombro, codo, muñeca). Mode cambia de articulación, mantener
  Function la mueve (40 °/s) y un toque de Function cambia la dirección (+ / −). Mantener Mode
  regresa al menú. Arriba dice si el Uno responde y en qué modo está.

---

## 3. Python (en la compu)

```bash
cd pc
pip install -r requirements.txt
```

### Audio: ¿dónde suena la voz?
El micrófono siempre es el de la compu (el predeterminado de Windows; si conectas audífonos BT a la
compu, los usa). Para la voz de la bolita, al arrancar `tom.py` te pregunta:

```
¿Dónde quieres que suene la voz?
  1) bocina de la ESP32
  2) compu (bocinas o audífonos)
  3) las dos
```
o lo eliges directo con `--audio esp`, `--audio pc` o `--audio ambos`. Con "compu", la bocina de la
ESP32 queda en silencio pero le sigue llegando el audio para **mover la boca**. Con "las dos", el
volumen de la compu lo bajas en Windows y el de la ESP con `--volumen` (default 130).

```bash
python tom.py --mics              # lista dispositivos: luego --mic N (entrada) / --bocina N (salida)
```

### Brazo: gestos sencillos (`pc/gestos.py`)
Mientras el control de potenciómetros no esté calibrado, las reacciones del brazo son **gestos
sencillos**: mueven uno o dos servos con el comando de prueba `T canal ángulo`, en pasitos, y los
regresan a su reposo (la pose de casa); al final se manda `HOME`. La pinza (canal 10) no se usa.

| Gesto | Qué mueve |
|---|---|
| saludo | muñeca (11) de lado a lado |
| si | muñeca (11) arriba-abajo |
| no | base (14) izquierda-derecha |
| baile | base (14) + muñeca (11) |
| susto | hombro (13) rápido y regresa |
| estirar | hombro (13) + codo (12) |
| agarrar | codo (12) |
| soltar | muñeca (11) |

```bash
python gestos.py                  # lista gestos y servos
python gestos.py saludo           # lo manda por la ESP32 (ESP -> UART -> Uno)
python gestos.py saludo --uno COM7  # directo al Uno por su USB, sin la ESP32
python gestos.py --t 11 60        # un solo comando T
python gestos.py prueba --port COM8   # cada servo UNO POR UNO, ~25° y regresa
python gestos.py --manual --port COM8 # teclado: "11 60", "+", "-", "h" (casa), "q" (salir)
python tom.py --brazo rutinas     # usar las rutinas completas de Arm.h
python tom.py --brazo no          # no mover el brazo
```
Los ángulos se cambian en `SERVOS` y `GESTOS` al inicio de `gestos.py`.

**Probar un servo con la voz** (`pc/servo_voz.py`, necesita Vosk). Mantén Function y di, por ejemplo:

| Dices | Manda |
|---|---|
| "prueba el servo diez y muévelo a veinte grados" | `T 10 20` |
| "canal once a sesenta" | `T 11 60` |
| "mueve el codo a ciento veinte" | `T 12 120` |
| "la muñeca a sesenta grados" / "pinza a veinte" / "base a cien" / "hombro a cuarenta y cinco" | `T 11 60` / `T 10 20` / `T 14 100` / `T 13 45` |

El servo se queda en ese ángulo; di **"quieto"** o **"inicio"** para mandar el brazo a casa
(`HOME`). Con la pinza ten cuidado: si vibra, mándala a otro ángulo o a casa enseguida.
En la terminal sale lo que entendió Vosk (`-> servo 10 a 20°`); si escribe "servo" de otra
forma, agrégala a `PALABRA_SERVO` en `servo_voz.py`.

### Sin hardware (para avanzar hoy mismo)
```bash
python tom.py --simular
```
Usa el micrófono y las bocinas de la compu e imprime qué cara pondría la bolita.

### Probar la ESP32
Conecta el USB-C de la placa que **no** es el nativo: el programa habla con la compu por el puerto
UART. Si Python da `Write timeout`, cambia el cable al otro USB-C.
```bash
python probar_esp.py              # recorre las caras, mueve ojos y suena una melodía
python musica.py                  # la canción de la bolita (prueba de bocina)
python musica.py --niveles        # la toca a 60, 100, 140, 180 y 220: ve dónde empieza a distorsionar
python probar_esp.py --brazo      # además prueba los gestos del brazo (sí, no, saludo)
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

Al iniciar, quédate callado 2 s para que mida el ruido. Luego **mantén Function mientras hablas**
(push-to-talk). Con `--auto` escucha sola al detectar tu voz, como antes; `--simular` siempre
escucha sola porque no hay botón.

**Cómo elige la cara:**
| Lo que haces | Cara |
|---|---|
| Mantienes Function | escuchando (ojos grandes) |
| Gritas | sorpresa |
| Hablas más agudo que tu normal | feliz |
| Hablas más grave que tu normal | enojado |
| Te repite | habla con la boca al ritmo del audio |
| 60 s sin hacerle caso | se duerme (zzz) |
| Le gritas | sorpresa y el brazo se echa para atrás |

Tu tono "normal" lo aprende con cada frase, así que lo agudo y lo grave son relativos a tu voz.

### Palabras y respuestas grabadas (sin internet)
`tom.py` reconoce palabras con **Vosk** (modelo `vosk-model-small-es-0.42` en `pc/modelos/`; si solo
está el `.zip`, lo descomprime solo la primera vez). Si en lo que dijiste hay una palabra de la
lista, la bolita **contesta con una frase grabada** y mueve el brazo; si no, te repite como Talking
Tom (con `--no-repetir` dice "no te entendí"). En la terminal imprime lo que entendió y si
`-> contesta` o `-> repite`. `--sin-palabras` lo apaga.

**Grabar las respuestas** (con tu voz normal: el efecto de voz se aplica al reproducir):
```bash
py -3.12 grabar.py             # menú con todas las frases (✔ grabada / · falta)
py -3.12 grabar.py hola        # abre directo una frase
py -3.12 grabar.py --lista     # solo imprime la lista
```
En el menú escribes el número de una frase (o `f` = la primera que falta) y ahí: `g` grabar,
`o` otra toma, `e` escuchar con la voz de la bolita, `n` escuchar sin efecto, `b` borrar (las pasa a
`.bak`), `s`/`a` siguiente/anterior, `l` volver a la lista. Al grabar: Enter, dices la frase, Enter
(se ve un contador; ignora Enters de menos de 0.7 s y corta sola a los 10 s).
Se guardan en `pc/respuestas/<nombre>.wav`; con varias tomas (`hola_2.wav`...) elige una al azar.
Mientras falte grabar una, te repite y avisa en la terminal.

| Dices | Contesta (sugerido) | Cara | Brazo |
|---|---|---|---|
| canta, cántame, canción, música | *la canción de la bolita* | feliz | baila |
| cómo te llamas, quién eres | "¡Soy la Bolita, y tengo un brazo robot!" | feliz | saluda |
| cómo estás, qué tal | "¡Súper bien! ¿Y tú cómo estás?" | feliz | sí |
| hola, buenos días, qué onda | "¡Hola, hola! ¿Qué hacemos hoy?" | feliz | saluda |
| adiós, nos vemos | "¡Adiós! ¡Vuelve pronto!" | feliz | saluda |
| baila, fiesta | "¡A bailar se ha dicho!" | feliz | baila |
| estírate | "¡Uuuf, qué buena estirada!" | sorpresa | se estira |
| agarra, toma, recoge / suelta | "¡Lo tengo!" / "Ahí te va." | escuchando / neutral | agarra / suelta |
| quieto, alto, inicio | "Ok, me quedo quieto." | neutral | inicio |
| bu, susto, cuidado | "¡Aaay! ¡Qué susto!" | sorpresa | se echa para atrás |
| duérmete, buenas noches | "Buenas noches... zzz" | dormido | inicio |
| tonto, feo / enójate | "Oye... eso no fue bonito." / "¡Grrr!" | triste / enojado | dice que no |
| te quiero, amigo, gracias | "¡Aww, gracias! Tú también." | feliz | sí |
| otra voz | "¿Así? ¿Te gusta mi voz nueva?" | sorpresa | (cambia la voz) |

Se editan en `RESPUESTAS` dentro de `pc/respuestas.py` (una línea por palabra). Tip: si Vosk
entiende algo distinto a lo que dijiste (lo ves en la terminal), agrega esa palabra a la línea.

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

**La canción de la bolita** (`pc/cancion.py`) es una melodía original hecha con síntesis aditiva:
cada nota es la fundamental más el 2.º y 3.er armónico con una envolvente ADSR, y el bajo lleva los
armónicos fuertes para que se "oiga" aunque la bocina chiquita casi no reproduzca graves.

**Efectos de voz** (también procesamiento de señales): remuestreo (tom, ardilla, monstruo),
modulación en anillo a 60 Hz (robot) y retardos con retroalimentación (eco).

---

## 5. Problemas comunes

| Problema | Solución |
|---|---|
| No suena | Revisa VIN del MAX98357 a 5V y BCLK/LRC/DIN. Debe sonar el *pío* al arrancar. |
| "Uno: sin respuesta" en la pantalla | Revisa el divisor en GPIO 41 y que las tierras estén unidas |
| El brazo no obedece a la ESP | `python probar_uart.py --port COM8 --uno COM6`: dice si falla la ida (GPIO 40 → pin 0, GND) o la vuelta (pin 1 → divisor → GPIO 41). Si el Uno contesta, la bolita sonríe |
| Presionas Function y `tom.py` no escucha | La bolita está en **Pausa** o en el menú: Mode → "Reanudar", o mantén Mode para volver a la cara (`tom.py` lo avisa) |
| Suena distorsionado o con chasquidos | Baja el volumen (`--volumen 100`; el default es 130). Con `musica.py --niveles` ves el máximo limpio |
| La bolita se oye a sí misma | Aleja la bocina del micrófono de la compu |
| Detecta voz cuando no hablas | Recalibra en silencio, o sube el `+ 12` del umbral en `tom.py` |
| `PortAudio library not found` (Linux) | `sudo apt install libportaudio2` |
| No encuentra el puerto | `python tom.py --puertos` y luego `--port` |
