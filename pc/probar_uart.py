"""
Prueba del UART entre la ESP32 y el Arduino Uno (GPIO 40 -> pin 0, GPIO 41 <- pin 1 con divisor).

    python probar_uart.py --port COM8              # prueba de ida y vuelta (necesita el TalkingBolita.ino nuevo)
    python probar_uart.py --port COM8 --uno COM6   # además escucha al Uno por su USB (prueba la ida sin el divisor)

Qué hace:
  1) IDA y VUELTA: la compu le pide a la ESP que mande "P" al Uno. El Uno contesta "P ..." por su
     pin 1, la ESP lo recibe por el GPIO 41, SONRÍE en la pantalla y lo reenvía a la compu como "UNO P ...".
  2) Solo IDA (con --uno): la ESP le manda "?" al Uno cada 300 ms. El Uno contesta "S ..." y eso
     también sale por su USB, así que si en el COM del Uno aparecen líneas "S ...", la ida ESP -> Uno funciona.
"""
import argparse
import time

from bolita import HAPPY, NEUTRAL, Bolita


def main():
    ap = argparse.ArgumentParser(description="Prueba del UART ESP32 <-> Uno")
    ap.add_argument("--port", help="puerto de la ESP32 (ej. COM8)")
    ap.add_argument("--uno", help="puerto USB del Uno (ej. COM6), opcional")
    args = ap.parse_args()

    lineas_esp = []
    b = Bolita(args.port, on_line=lineas_esp.append, excluir=args.uno)
    print(f"ESP32 en {b.port}")

    # ---- 2) solo ida, escuchando al Uno por su USB
    ida_ok = None
    if args.uno:
        import serial

        print(f"\n[1/2] Escuchando al Uno en {args.uno} (3 s)...")
        u = serial.Serial(args.uno, 115200, timeout=0.2)  # al abrir, el Uno se reinicia
        lineas_uno, t_fin = [], time.time() + 3.5
        while time.time() < t_fin:
            l = u.readline().decode(errors="ignore").strip()
            if l:
                lineas_uno.append(l)
        u.close()
        status = [l for l in lineas_uno if l.startswith("S ")]
        ida_ok = len(status) > 0
        if ida_ok:
            print(f"   ✔ IDA ESP -> Uno funciona: el Uno contestó {len(status)} veces el '?' de la ESP (ej. '{status[-1]}')")
        else:
            print("   ✘ El Uno no recibió nada de la ESP.")
            print("     Revisa: cable del GPIO 40 de la ESP al pin 0 del Uno, y GND común.")
            if lineas_uno:
                print(f"     (el Uno sí dijo: {lineas_uno[:3]})")
        time.sleep(1.0)

    # ---- 1) ida y vuelta
    print(f"\n[{'2/2' if args.uno else '1/1'}] Ida y vuelta: ESP -> Uno 'P' -> ESP -> compu ...")
    b.mood(NEUTRAL)
    lineas_esp.clear()
    vuelta = None
    for _ in range(3):
        b.arm("P")
        t_fin = time.time() + 1.0
        while time.time() < t_fin and not vuelta:
            vuelta = next((l for l in lineas_esp if l.startswith("UNO P")), None)
            time.sleep(0.05)
        if vuelta:
            break
    if vuelta:
        print(f"   ✔ IDA Y VUELTA funcionan: {vuelta[4:]}")
        print("     (la bolita debió sonreír en la pantalla)")
        b.mood(HAPPY, 1, 2)
    else:
        nuevos = [l for l in lineas_esp if l.startswith("UNO")]
        if nuevos:
            print(f"   ? La ESP sí recibe del Uno ({nuevos[:2]}) pero no llegó la respuesta a 'P'.")
        elif ida_ok:
            print("   ✘ La ida funciona pero la VUELTA no: revisa el divisor 1k/2k del pin 1 del Uno al GPIO 41,")
            print("     o sube el TalkingBolita.ino nuevo (la versión vieja no reenvía lo que dice el Uno).")
        else:
            print("   ✘ No regresó nada. Puede ser:")
            print("     - la ESP tiene el TalkingBolita.ino viejo (no reenvía lo que dice el Uno): súbele el nuevo;")
            print("     - falta el divisor del pin 1 del Uno al GPIO 41 (la vuelta);")
            print("     - o la ida: cable GPIO 40 -> pin 0 y GND. Prueba con --uno COM6 para saber cuál.")
    otros = [l for l in lineas_esp if l.startswith("UNO") and not l.startswith("UNO P")]
    if otros:
        print("   La ESP también reportó:", ", ".join(o[4:] for o in otros[:4]))
    b.close()


if __name__ == "__main__":
    main()
