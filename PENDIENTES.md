# Estado y pendientes (23 nov 2026)

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
1. **Codo / muñeca del control.** El pote del codo mueve la muñeca del robot y el de la muñeca
   parece no hacer nada. Prueba: escribir `P`, mover **solo** el pote del codo, `P` otra vez; luego
   lo mismo con la muñeca. Ver qué número cambia (orden: base, hombro, codo, muñeca = A3, A2, A1, A0)
   y corregir la línea `POT[NJ]`.
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
