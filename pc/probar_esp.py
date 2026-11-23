"""
Prueba del hardware sin micrófono: recorre todas las caras, mueve los ojos,
suena una melodía por la bocina y (opcional) prueba las rutinas del brazo.

    python probar_esp.py
    python probar_esp.py --port COM5 --brazo
"""
import argparse
import time

import numpy as np

from bolita import MOOD_NAMES, NEUTRAL, Bolita


def melody():
    fs, notes = 16000, [523, 659, 784, 1047, 784, 659, 523]
    out = []
    for f in notes:
        t = np.arange(int(0.16 * fs)) / fs
        out.append(0.4 * np.sin(2 * np.pi * f * t) * np.hanning(len(t)))
    return (np.concatenate(out) * 32767).astype("<i2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--brazo", action="store_true")
    args = ap.parse_args()

    b = Bolita(args.port, on_line=lambda l: print("  esp32>", l))
    print("Conectado a", b.port)
    b.ping()
    time.sleep(0.3)

    for m, name in enumerate(MOOD_NAMES):
        print("Cara:", name)
        b.mood(m)
        time.sleep(1.6)
    b.mood(NEUTRAL)

    print("Ojos: izquierda, derecha, arriba, abajo")
    for x, y in ((-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)):
        b.look(x, y)
        time.sleep(0.6)

    print("Audio: melodía (la boca debe moverse)")
    secs = b.play(melody())
    b.wait_done(secs + 2)

    if args.brazo:
        for r, secs in (("inicio", 2), ("si", 2), ("no", 2), ("saludo", 5), ("inicio", 2)):
            print("Brazo:", r)
            b.arm(r)
            time.sleep(secs)

    print("Listo. Presiona los botones o la pantalla para ver sus mensajes (Ctrl+C para salir).")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        b.close()


if __name__ == "__main__":
    main()
