# Brazo asistente — Talking Bolita 🟡🦾

> **Estado:** presentado y funcionando (27 nov 2026). Comandos para correrlo: [COMANDOS.md](COMANDOS.md).
> Contexto completo para el reporte: [docs/CONTEXTO_REPORTE.md](docs/CONTEXTO_REPORTE.md) ·
> historial de decisiones: [HISTORIAL.md](HISTORIAL.md) · pendientes: [PENDIENTES.md](PENDIENTES.md).

Una mascota tipo Talking Tom que además controla un brazo robótico: le hablas, limpia tu voz con
un **filtro de Kalman**, hace caras según cómo hablas, te repite con voz chistosa y el brazo
reacciona. Mantienes el botón **Function** para hablarle; con **Mode** abres un menú para mover el brazo.

```
 Micrófono de la compu ──► Python: Kalman + efectos + caras ──USB──► ESP32-S3: pantalla + bocina + 2 botones
                                                                          │ UART 115200 (GPIO 40 → pin 0)
                                                                          ▼
                                                     Arduino Uno + PCA9685 ──► servos: base, hombro, codo
```

- **`firmware/TalkingBolita/`**: sketch de Arduino para la ESP32-S3
- **`firmware/BrazoESP/`**: sketch del Arduino Uno del brazo (el que se usa): órdenes de la ESP, rangos, casa
- **`firmware/BrazoManual/`**: sketch del Uno para usar el brazo solo con el control de potenciómetros
- `firmware/BrazoUno/`, `firmware/BrazoUnoV2/`: versiones viejas (ya no se usan)
- **`pc/`**: programas de Python (`tom.py` = la bolita con TUI, `tui_brazo.py` = probar el brazo canal por canal)
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
  codo 12, muñeca 11, pinza 10 (ya está así en `BrazoESP.ino`).
- **Orden de encendido:** primero el Uno (USB) y la ESP, **después** la fuente de servos. Con la
  fuente prendida y el Uno apagado, el PCA9685 no tiene VCC, la señal queda al aire y el codo se fuerza.

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
1. Gestor de librerías → **Adafruit PWM Servo Driver Library** (instala también *Adafruit BusIO*).
2. Abre `firmware/BrazoESP/BrazoESP.ino`, placa **Arduino Uno**, sube (con el cable del pin 0 desconectado).
3. En el **Monitor Serie a 115200 con "Nueva línea"** debe decir
   `BRAZO ESP listo, SIN control: en CASA (base, hombro, codo)`. Ahí también puedes escribir:

| Comando | Qué hace |
|---|---|
| `J 90 120 60 -1` | base, hombro, codo, muñeca en grados (−1 = no cambiar), suave a la velocidad `V` |
| `V 60` | velocidad en °/s |
| `HOME` / `ESTIRA` | casa (90 100 90) / estirado (base igual, 170, 10) |
| `T 14 60` | prueba: mueve solo ese canal del PCA9685 (respeta los rangos si es una articulación) |
| `OFF` / `OFF 12` | soltar todos los servos / solo uno (dejan de hacer fuerza) |
| `?` | estado: `S base hombro codo muñeca pinza modo prendidos` |
| `H 100` / `H 0` | cerrar / abrir pinza (no se usa: está suelta) |

**Al encender** el Uno lleva la base, el codo y el hombro a la **casa**, uno por uno (0.5 s entre
cada uno). Los servos no dicen en qué ángulo están, así que la casa es la referencia: el primer
movimiento brinca desde donde haya quedado el brazo. La muñeca y la pinza quedan sueltas.

**Rangos seguros** (fuera de ellos el servo choca con el tope, jala ~2.5 A y se queda forzando):
**base 50–140°, hombro 100–170°, codo 10–90°**. Están en `LIM_MIN` / `LIM_MAX` y ningún comando los pasa.

**Protecciones:** si el PCA9685 se reinicia (perdió su alimentación un instante), el Uno lo nota cada
segundo, lo reconfigura y regresa cada servo a su último ángulo (`!! El PCA9685 se reinicio`). El I2C
tiene timeout para que el Uno no se cuelgue.

Se quitaron los potenciómetros del control (`HAY_CONTROL = false`). Con el control puesto, usa
`firmware/BrazoManual/` (o `HAY_CONTROL = true`): ahí está la lectura del ADC sin "fantasma", la
calibración de 2 puntos por pote (`CAL j a` + `PUNTO n`) y el filtro de Kalman 1D de cada pote.

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

### Probar el brazo canal por canal (`pc/tui_brazo.py`)
```bash
python tui_brazo.py --port COM8     # por la ESP32
python tui_brazo.py --uno COM6      # directo al Uno por USB (cierra el Monitor Serie, quita el cable del pin 0)
```
↑↓ canal · ←→ ±5° · número + Enter = ir a ese ángulo · Espacio = barrido · `m`/`M` marcar mínimo /
máximo seguro · `r` reenviar todo · `o`/`O` soltar · `k`/`n`/`z` anotar OK / no responde / zumba ·
`q` salir (guarda un reporte en `pc/resultados/` e imprime `LIM_MIN`/`LIM_MAX` para el firmware).

### Brazo: gestos (`pc/gestos.py`)
Cada gesto mueve los servos en pasitos de 30 ms con `T canal ángulo`, nunca fuera de su rango, y al
final regresa a la casa. Los gestos recuerdan dónde quedó cada servo (no brincan al empezar).

| Gesto | Qué hace |
|---|---|
| inicio | casa: base 90, hombro 100, codo 90 |
| estirar | hombro 170, codo 10 (la base no se mueve), espera 2 s y regresa |
| si / saludo | estirado + codo 10 ↔ 15 tres veces |
| baile | base 50 ↔ 140 y hombro 160 ↔ 165; con la canción se repite lo que dura la música |
| no / susto | base de lado a lado (70 ↔ 110) |
| mover_base / mover_hombro / mover_codo | esa articulación se mueve dentro de su rango y regresa |
| prueba | cada servo por separado, ~20° y regresa |

```bash
python gestos.py                       # lista gestos y servos
python gestos.py baile --port COM8     # por la ESP32 (ESP -> UART -> Uno)
python gestos.py baile --uno COM6      # directo al Uno por su USB, sin la ESP32
python gestos.py --manual --port COM8  # teclado: "14 90", "+", "-", "q"
```
Los ángulos se cambian en `CASA`, `ESTIRADO`, `LIMITES` y `GESTOS` al inicio de `gestos.py`
(y los mismos en `BrazoESP.ino`, `tui_brazo.py` y `Arm.h`).

**Mover el brazo con la voz** (`pc/servo_voz.py`):

| Dices | Hace |
|---|---|
| "mueve la base" / "mueve el hombro" / "mueve el codo" | se mueve dentro de su rango y regresa |
| "mueve la base a noventa", "el codo a cuarenta" | va a ese ángulo (recortado a su rango) y se queda |
| "prueba el servo diez a veinte grados" | `T 10 20` (prueba cruda de un canal) |

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

### Talking Bolita (TUI)
`tom.py` abre una pantalla en la terminal con la configuración (se cambia con teclas), la barra
del micrófono con el umbral de voz y la lista de frases: qué entendió Vosk y si coincidió con una
respuesta (✓ / ✗). Teclas: **1** casa · **2** sí · **3** baile · `v` voz · `p` botón Function /
automático · `k` Kalman · `r` repetir / "no entendí" · `m` mover el brazo antes de hablar ·
`b` brazo · `+`/`-` volumen · `q` salir. `--sin-tui` deja solo texto.
```bash
python tom.py --port COM8         # (sin --port la busca sola)
python tom.py --port COM8 --audio pc --auto   # voz por la compu y escucha sola
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

Se usa la **primera** línea que coincide (por eso "¿te gusta bailar?" es un sí y no un baile).
Por defecto el brazo se mueve **antes** de que la bolita hable (tecla `m`).

| Dices | Contesta | Cara | Brazo |
|---|---|---|---|
| te gusta, te gustaría, te encanta (lo que sea) | "¡Sí! ¡Me encanta!" | feliz | sí |
| canta, cántame, canción, música | *la canción de la bolita* | feliz | baila toda la canción |
| cómo te llamas, quién eres | "¡Soy la Bolita, y tengo un brazo robot!" | feliz | sí |
| cómo estás, qué tal | "¡Súper bien! ¿Y tú cómo estás?" | feliz | sí |
| hola, buenos días, qué onda | "¡Hola, hola! ¿Qué hacemos hoy?" | feliz | sí |
| adiós, nos vemos | "¡Adiós! ¡Vuelve pronto!" | feliz | sí |
| baila, bailar, fiesta | "¡A bailar se ha dicho!" + la canción | feliz | baila desde antes de hablar y toda la canción |
| estírate | "¡Uuuf, qué buena estirada!" | sorpresa | se estira |
| agarra, toma, recoge / suelta | "¡Lo tengo!" / "Ahí te va." | escuchando / neutral | (nada: pinza suelta) |
| quieto, alto, inicio, casa | "Ok, me quedo quieto." | neutral | casa |
| bu, susto, cuidado | "¡Aaay! ¡Qué susto!" | sorpresa | base de lado a lado |
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
| No suena | Revisa VIN del MAX98357 a 3V3 y BCLK/LRC/DIN. Debe sonar el *pío* al arrancar. |
| "Uno: sin respuesta" en la pantalla | Revisa el divisor en GPIO 41 y que las tierras estén unidas |
| El codo (o un servo) se queda forzando al prender | Prende primero el Uno y después la fuente; revisa que no le pidas un ángulo fuera de su rango |
| "De repente" deja de moverse | Monitor Serie del Uno: `BRAZO ESP listo` = se reinició el Uno (tecla `r` en la TUI); `!! El PCA9685 se reinicio` = falso contacto en la placa azul; llegan `T canal` y no se mueve = fuente en CC o cable desoldado |
| `could not open port ... Acceso denegado` | Otro programa tiene abierto el COM (Monitor Serie del IDE): ciérralo |
| El brazo no obedece a la ESP | `python probar_uart.py --port COM8 --uno COM6`: dice si falla la ida (GPIO 40 → pin 0, GND) o la vuelta (pin 1 → divisor → GPIO 41). Si el Uno contesta, la bolita sonríe |
| Presionas Function y `tom.py` no escucha | La bolita está en **Pausa** o en el menú: Mode → "Reanudar", o mantén Mode para volver a la cara (`tom.py` lo avisa) |
| Suena distorsionado o con chasquidos | Baja el volumen (`--volumen 100`; el default es 130). Con `musica.py --niveles` ves el máximo limpio |
| La bolita se oye a sí misma | Aleja la bocina del micrófono de la compu |
| Detecta voz cuando no hablas | Recalibra en silencio, o sube el `+ 12` del umbral en `tom.py` |
| `PortAudio library not found` (Linux) | `sudo apt install libportaudio2` |
| No encuentra el puerto | `python tom.py --puertos` y luego `--port` |
