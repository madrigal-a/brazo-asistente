"""
Prueba de la bocina con la canción de la bolita (sin micrófono).

    py -3.12 musica.py                  # la toca una vez a volumen 120
    py -3.12 musica.py --volumen 90
    py -3.12 musica.py --niveles        # un pedazo a 60, 100, 140, 180 y 220: para ver dónde empieza a distorsionar
    py -3.12 musica.py --simular        # en las bocinas de la compu
"""
import argparse
import time

import numpy as np

from bolita import HAPPY, NEUTRAL, Bolita
from cancion import FS, cancion_bolita


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--volumen", type=int, default=120, help="0-255")
    ap.add_argument("--niveles", action="store_true", help="prueba varios volúmenes")
    ap.add_argument("--brazo", action="store_true", help="el brazo baila mientras canta")
    ap.add_argument("--simular", action="store_true", help="en la compu, sin ESP32")
    args = ap.parse_args()

    x = cancion_bolita()
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")

    if args.simular:
        import sounddevice as sd

        sd.play(x, FS)
        sd.wait()
        return

    b = Bolita(args.port, on_line=lambda l: print("  esp32>", l) if l.startswith("ERR") else None)
    print("Conectado a", b.port)

    if args.niveles:
        pedazo = pcm[: int(4.6 * FS)]  # los primeros 2 compases
        for v in (60, 100, 140, 180, 220):
            print(f"Volumen {v} ...", flush=True)
            b.volume(v)
            b.mood(HAPPY)
            restante = b.play(pedazo)
            b.wait_done(restante + 2)
            time.sleep(0.6)
        print("Usa en tom.py el volumen más alto que se oyó limpio:  py -3.12 tom.py --volumen N")
    else:
        b.volume(args.volumen)
        b.mood(HAPPY)
        if args.brazo:
            b.arm("baile")
        print(f"🎵 Cantando ({len(x) / FS:.0f} s, volumen {args.volumen})")
        restante = b.play(pcm)
        b.wait_done(restante + 2)
    b.mood(NEUTRAL)
    b.close()


if __name__ == "__main__":
    main()
