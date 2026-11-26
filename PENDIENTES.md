# Estado y pendientes (26 nov 2026)

## Ahora: probar el UART ESP ↔ Uno con `firmware/BrazoESP`
`BrazoManual.ino` (en `firmware/BrazoManual/`) ya mueve bien los 4 ejes con el control.
`BrazoESP.ino` es ese mismo código + las órdenes de la ESP. Probar en este orden:
1. **Uno solo.** Quita el cable del pin 0, sube `BrazoESP`, fuente encendida. En el Monitor Serie
   (115200, "Nueva línea"): debe copiar al control igual que BrazoManual. Luego `?` → `S ...`,
   `V 60`, `J -1 -1 120 -1` (el codo va suave a 120°), `HOME`, `MAN` (regresa al control despacio).
2. **Ida (ESP → Uno).** Conecta GPIO 40 → pin 0 y GND común. Al prender la ESP el brazo se queda
   quieto (modo remoto). `py -3.12 pc/gestos.py --manual --port COM8` y prueba un canal.
3. **Vuelta (Uno → ESP).** Pin 1 → divisor 1k/2k → GPIO 41. `py -3.12 pc/probar_uart.py --port COM8`:
   debe decir que el Uno contestó y la cara sonríe.
4. **Voz, motor por motor.** `py -3.12 pc/tom.py --port COM8` y di "mueve el codo a ciento veinte",
   "la base a noventa"... (articulaciones → `J` a 60 °/s; "servo diez a veinte" → `T` crudo).
5. Después: rutinas (baile + música, saludo...) con `J`/`HOME` en vez de `T` (casa ya se puede medir con `P`).

## Cambio de planes (25 nov)
- **La bocina de la ESP ya no suena** (probablemente el MAX98357). Ahora **el micrófono y las
  bocinas son los de la compu** (o audífonos BT conectados a la compu). La ESP no puede usar
  audífonos BT: la S3 solo tiene BLE, y los audífonos usan Bluetooth clásico.
- **El brazo hace gestos sencillos** con `T canal ángulo` (`pc/gestos.py`), así funciona aunque el
  control no esté calibrado.
- **Volver a subir el sketch al Uno** (`BrazoUno` o `BrazoUnoV2`, el que usen): antes, el `?` que la
  ESP manda cada 300 ms sacaba al servo del modo prueba y el `T` se deshacía.
- **Volver a subir `TalkingBolita.ino`**: la boca ahora se mueve aunque el volumen de la ESP esté en 0.
- Probar en orden: `python gestos.py saludo --uno COMx` (Uno solo) → `python gestos.py saludo`
  (pasando por la ESP) → `python tom.py`.

> Si usas Claude: abre este repo y dile *"lee CLAUDE.md, HISTORIAL.md y PENDIENTES.md y sigamos con el pendiente 1"*.

## Lo que ya funciona
- `BrazoUno.ino` sube y responde en el Monitor Serie (115200, "Nueva línea"): `?`, `P`, `T`, `J`, `HOME`...
- Los potes se leen bien **con la fuente encendida** (sin fuente dan lecturas falsas).
- Canales del PCA9685, comprobados con `T canal ángulo`:

| Canal | Servo |
|---|---|
| 14 | base |
| 13 | hombro |
| 12 | codo |
| 11 | muñeca |
| 10 | pinza (solo vibra) |
| 15 | nada |

- Con el control: **base y hombro ya se mueven bien**.

## Pendientes (en este orden)
1. **Codo (canal 12).** Con el control, base, hombro y muñeca ya funcionan (25 nov); el codo no.
   Separar si es el servo o el pote:
   - Monitor Serie (cable del pin 0 quitado): `T 12 150`, `T 12 175`. ¿Se mueve?
     - **No:** es el servo, su conector o la fuente. Probar el servo del codo en el canal 15 (vacío)
       con `T 15 150`, o un servo que sí jale en el canal 12. Ver si la fuente marca CC (el codo carga peso).
     - **Sí:** es el pote. `P`, mover solo el pote del codo, `P` otra vez: el 3.er número (A1) debe
       cambiar. Ojo: el ADC del codo llegó a 142 en una punta (fuera de 240–800) → el ángulo se queda
       en 180 en esa zona. Ajustar `POT_LO`/`POT_HI` o el mapeo del codo, y revisar `INVERT` del codo
       (en `BrazoUnoV2` está en `true`, en `BrazoUno` en `false`).
2. **Sentido de giro.** Si una articulación va al revés que el control → `true` en `INVERT[NJ]`
   (base, hombro, codo, muñeca). En el repo están todos en `false`.
3. **Pinza (canal 10).** Vibra con `T 10 60` / `T 10 120` (choca con su tope). Probar `T 10 0`,
   `T 10 20`, `T 10 40` y el botón del control; ajustar `HAND_OPEN` / `HAND_CLOSED` (cuentas del
   PCA9685; el código original usaba 90 y 180). **No dejarla vibrando**: se calienta.
4. **Casa y estirado.** Volver a medir con `P` cuando los potes estén bien asignados y poner los
   valores en `HOME_POS` / `STRETCH_POS` (ahora: casa 119 22 175 84, estirado 118 175 10 139).
5. Ajustar los ángulos de las rutinas (saludo, baile...) en `firmware/TalkingBolita/Arm.h`.
6. ESP32-S3: cargar `TalkingBolita.ino`, calibrar el touch y conectar al Uno (GPIO 40 → pin 0,
   GPIO 41 ← pin 1 con divisor 1k/2k, GND común).
7. Python: `pip install -r pc/requirements.txt`, `python pc/probar_esp.py --brazo`, `python pc/tom.py`.

## Ojo con el Arduino IDE
El IDE volvió a guardar versiones viejas encima de los archivos nuevos cuando estaban abiertos.
Antes de reemplazar un `.ino`, cierra su pestaña sin guardar.
