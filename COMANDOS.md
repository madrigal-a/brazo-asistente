# Comandos para correr el brazo y la bolita

Todos en **PowerShell**, desde la carpeta del proyecto. Puertos de la compu de Alonso:
**ESP32 = COM8** (USB-C "COM", chip CH343) · **Arduino Uno = COM6**. Si cambian, mira la lista (paso 0).

## 0. Antes de empezar
```powershell
cd X:\Anahuac\asistente-bolita
```
```powershell
py -3.12 -m serial.tools.list_ports
```
Solo la primera vez en una compu nueva:
```powershell
py -3.12 -m pip install -r pc/requirements.txt
```

**Orden de encendido:** 1) USB del Uno y de la ESP conectados · 2) prender la fuente (5.0 V, 3 A)
con la mano en el switch. Al encender, el Uno lleva base, codo y hombro a la casa (90 100 90).
Nunca prendas la fuente con el Uno apagado (el codo se queda forzando).

## 1. Subir el firmware del Uno (solo si cambió)
1. Quita el cable que llega al **pin 0** del Uno (viene del GPIO 40 de la ESP).
2. Arduino IDE → Archivo → Abrir → `X:\Anahuac\asistente-bolita\firmware\BrazoESP\BrazoESP.ino`
3. Placa **Arduino Uno**, puerto **COM6**, **Subir**.
4. Monitor Serie (115200): debe decir `BRAZO ESP listo, SIN control: en CASA (base, hombro, codo)`.
5. Cierra el Monitor Serie (si no, COM6 queda ocupado) y vuelve a poner el cable del pin 0.

## 2. Probar SOLO el robot (sin la bolita)

### TUI del brazo (canal por canal)
Por la ESP (lo normal):
```powershell
py -3.12 pc/tui_brazo.py --port COM8
```
Directo al Uno por USB (cierra el Monitor Serie y quita el cable GPIO 40 → pin 0):
```powershell
py -3.12 pc/tui_brazo.py --uno COM6
```
Teclas: ↑↓ canal · ←→ ±5° · número + Enter = ir a ese ángulo · Espacio = barrido ·
`r` reenviar todo · `o` / `O` soltar uno / todos · `v` velocidad · `q` salir.
Los rangos ya vienen puestos (base 50–140, hombro 100–170, codo 10–90).

### Gestos uno por uno
```powershell
py -3.12 pc/gestos.py inicio --port COM8
```
```powershell
py -3.12 pc/gestos.py estirar --port COM8
```
```powershell
py -3.12 pc/gestos.py si --port COM8
```
```powershell
py -3.12 pc/gestos.py baile --port COM8
```
```powershell
py -3.12 pc/gestos.py prueba --port COM8
```
Otros: `mover_base`, `mover_hombro`, `mover_codo`, `no`. Para ver la lista:
```powershell
py -3.12 pc/gestos.py
```
Mismo, pero directo al Uno sin ESP: cambia `--port COM8` por `--uno COM6`.

### Comandos a mano (escribes "14 90" + Enter)
```powershell
py -3.12 pc/gestos.py --manual --port COM8
```

### Probar el cable ESP ↔ Uno
```powershell
py -3.12 pc/probar_uart.py --port COM8
```
(La vuelta Uno → ESP necesita el divisor 1k/2k en GPIO 41; sin él dice "no regresó nada", pero la ida sí funciona.)

## 3. La bolita (voz + brazo) — TUI
```powershell
py -3.12 pc/tom.py --port COM8
```
Pregunta dónde suena la voz (1 ESP · 2 compu · 3 las dos), calibra el ruido 2 s (silencio) y abre la TUI.
Mantén **Function** en la bolita mientras hablas.

Variantes:
```powershell
py -3.12 pc/tom.py --port COM8 --audio pc
```
```powershell
py -3.12 pc/tom.py --port COM8 --audio pc --auto
```
```powershell
py -3.12 pc/tom.py --simular
```
```powershell
py -3.12 pc/tom.py --port COM8 --sin-tui
```
`--audio pc` = voz por la compu sin preguntar · `--auto` = escucha sola, sin el botón ·
`--simular` = sin ESP ni brazo · `--sin-tui` = solo texto, como antes.

Teclas en la TUI: **1** casa · **2** sí · **3** baile con música · `v` voz · `p` botón/automático ·
`k` Kalman · `r` repetir / "no entendí" · `m` mover y luego hablar · `b` brazo on/off · `+ -` volumen · `q` salir.

Qué decirle:
| Frase | Qué hace |
|---|---|
| "baila" / "bailar" / "fiesta" / "canta" | baila toda la canción |
| "¿te gusta …?" | gesto sí y luego dice "sí" |
| "inicio" / "quieto" / "casa" | a la casa |
| "estírate" | estirado |
| "hola" | gesto sí + "¡Hola!" |
| "mueve la base" / "el hombro" / "el codo" | se mueve dentro de su rango y regresa |
| "mueve la base a noventa" | va a 90° (recortado a su rango) |

## 4. Grabar respuestas
```powershell
py -3.12 pc/grabar.py
```
```powershell
py -3.12 pc/grabar.py si
```

## 5. Útiles
```powershell
py -3.12 pc/tom.py --mics
```
```powershell
py -3.12 pc/tom.py --puertos
```

## Si algo falla
- `could not open port ... Acceso denegado` → otro programa usa ese COM (Monitor Serie, otra terminal): ciérralo.
- `could not open port ... no puede encontrar` → ese COM no existe: revisa el paso 0 (¿la ESP en el USB-C "COM"?).
- El brazo no se mueve: mira el Monitor Serie del Uno. `BRAZO ESP listo` = se reinició (presiona `r` en la TUI);
  `!! El PCA9685 se reinicio` = la placa azul perdió alimentación; llegan `T canal ...` pero no se mueve = fuente en CC o cable.
