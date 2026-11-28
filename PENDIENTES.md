# Estado y pendientes (27 nov 2026)

## Estado: PRESENTADO — todo funcionó ✅
La bolita reconoce frases, contesta con voz y caras, y el brazo (base, hombro, codo) hace casa,
estirado, sí, baile con la canción completa y movimientos por voz dentro de sus rangos.
Comandos para correrlo: [COMANDOS.md](COMANDOS.md). Contexto para el reporte: [docs/CONTEXTO_REPORTE.md](docs/CONTEXTO_REPORTE.md).

## Pendientes
1. **Terminar el reporte** con `docs/CONTEXTO_REPORTE.md` (el borrador actual se hizo con la versión del 23 nov).
2. Opcional / mejoras:
   - Divisor 1k/2k para la vuelta Uno → ESP (pin 1 → GPIO 41): la ESP vería la posición real.
   - Calibrar rangos de muñeca y pinza para volver a usarlas.
   - Resistencias de 10 kΩ de cada señal de servo a GND (por si se prende la fuente con el Uno apagado).
   - Subir `TalkingBolita.ino` con las rutinas nuevas de `Arm.h` (solo se usan con `--brazo rutinas` y en el PARO).

## Orden de encendido (para que funcione siempre)
1. Fuente de servos APAGADA. Conecta el USB del Uno (le da 5 V al PCA9685) y la ESP.
2. Prende la fuente (5.0 V, 3 A) con la mano en el switch.
3. Al encender, el Uno ya va solo a la casa (base, codo y hombro, uno por uno). Nunca prendas
   la fuente con el Uno apagado: el codo se queda forzando. Si apagas y prendes la fuente, el Uno
   reconfigura solo el PCA9685 y avisa `!! El PCA9685 se reinicio...`.
4. Si "de repente no funciona": mira el Monitor Serie del Uno (COM6):
   - `BRAZO ESP listo...` sin que lo reiniciaras → **el Uno se reinició** (USB o bajón): `r` en la TUI.
   - `!! El PCA9685 se reinicio` → perdió su alimentación (falso contacto en VCC/GND de la placa azul).
   - llegan `T canal ...` pero el servo no se mueve → fuente en CC o servo trabado.
   - no llega nada → cable GPIO 40 → pin 0 o GND común.
   Abrir COM6 (Monitor Serie, `--uno`) **reinicia el Uno** y suelta los servos.

## Historial de pruebas
Las listas de pruebas de cada día (UART, canal por canal, rangos, poses) están en `HISTORIAL.md`.

## Ojo con el Arduino IDE
El IDE volvió a guardar versiones viejas encima de los archivos nuevos cuando estaban abiertos.
Antes de reemplazar un `.ino`, cierra su pestaña sin guardar.
