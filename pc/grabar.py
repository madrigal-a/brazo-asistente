"""
Menú para grabar las frases con las que contesta la bolita (se guardan en pc/respuestas/).

    py -3.12 grabar.py              # menú: lista de frases (✔ grabada / · falta), escuchar, regrabar...
    py -3.12 grabar.py hola         # abre directo la frase "hola"
    py -3.12 grabar.py --lista      # solo imprime la lista
    py -3.12 grabar.py --mic 2      # otro micrófono (ver: py -3.12 tom.py --mics)

Al grabar: Enter para empezar, dices la frase, Enter para terminar (se ve un contador). Se limpia
con el filtro de Kalman, se le quitan los silencios y la escuchas con la voz de la bolita antes
de guardarla. Grábalas con tu voz normal: el efecto (tom, ardilla...) se aplica al reproducir.
"""
import argparse
import os
import sys
import time

import numpy as np
import sounddevice as sd
import soundfile as sf

import dsp
import respuestas

FS = dsp.FS
BLOCK = 320  # 20 ms


def limpiar_teclado():
    """Borra las teclas que se presionaron antes (si no, un Enter guardado corta la grabación)."""
    try:
        import msvcrt  # Windows

        while msvcrt.kbhit():
            msvcrt.getwch()
    except ImportError:
        try:
            import termios

            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass


def preguntar(texto):
    limpiar_teclado()
    return input(texto)


def esperar_enter(t0, minimo=0.7, maximo=10.0):
    """Espera Enter mostrando los segundos. Ignora Enter antes de 'minimo' s; corta sola a los 'maximo' s."""
    try:
        import msvcrt
    except ImportError:  # fuera de Windows: input() normal
        while True:
            input()
            if time.time() - t0 >= minimo:
                return
    while True:
        dt = time.time() - t0
        print(f"\r   🔴 grabando {dt:4.1f} s   (Enter para TERMINAR)", end="", flush=True)
        if dt >= maximo:
            print("  -> 10 s, se detuvo sola")
            return
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in "\r\n" and dt >= minimo:
                print()
                return
        time.sleep(0.05)


class Grabadora:
    def __init__(self, mic=None):
        self._buf = []
        self._on = False
        self.stream = sd.InputStream(samplerate=FS, channels=1, blocksize=BLOCK, dtype="float32",
                                     device=mic, callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        if self._on:
            self._buf.append(indata[:, 0].copy())

    def grabar(self, segundos=None):
        """Graba hasta que presiones Enter (o 'segundos' si se indica)."""
        self._buf, self._on = [], True
        if segundos:
            time.sleep(segundos)
        else:
            limpiar_teclado()
            esperar_enter(time.time())
        self._on = False
        time.sleep(0.05)
        return np.concatenate(self._buf) if self._buf else np.zeros(0)

    def close(self):
        self.stream.stop()


def recortar(x, umbral_db, margen=0.15):
    """Quita el silencio del principio y del final (tramas de 20 ms bajo el umbral)."""
    n = len(x) // BLOCK
    if n == 0:
        return x
    dbs = np.array([dsp.rms_db(x[i * BLOCK : (i + 1) * BLOCK]) for i in range(n)])
    voz = np.where(dbs > umbral_db)[0]
    if len(voz) == 0:
        return np.zeros(0)
    m = int(margen * FS)
    return x[max(0, voz[0] * BLOCK - m) : min(len(x), (voz[-1] + 1) * BLOCK + m)]


def siguiente_nombre(nombre):
    """hola.wav si no existe; si ya hay, hola_2.wav, hola_3.wav..."""
    if not respuestas.archivos(nombre):
        return f"{nombre}.wav"
    k = 2
    while os.path.exists(os.path.join(respuestas.CARPETA, f"{nombre}_{k}.wav")):
        k += 1
    return f"{nombre}_{k}.wav"


def duracion(archivo):
    try:
        return sf.info(archivo).duration
    except Exception:
        return 0.0


def estado(nombre):
    fs = respuestas.archivos(nombre)
    if not fs:
        return "·", "falta"
    durs = ", ".join(f"{duracion(f):.1f}s" for f in fs)
    return "✔", (f"{len(fs)} tomas: " if len(fs) > 1 else "") + durs


def imprimir_lista(lista, voz=None):
    print()
    print("=" * 72)
    print("  FRASES DE LA BOLITA" + (f"   (escuchar con voz: {voz})" if voz else ""))
    print("=" * 72)
    for i, (nombre, frase) in enumerate(lista, 1):
        marca, info = estado(nombre)
        print(f" {i:2d} {marca} {nombre:11s} {info:16s} \"{frase}\"")
    hechas = sum(1 for n, _ in lista if respuestas.archivos(n))
    print(f"\n  {hechas} de {len(lista)} grabadas.   Carpeta: {respuestas.CARPETA}")


def reproducir(x):
    sd.play(x, FS)
    sd.wait()


class Estudio:
    """Graba, escucha y guarda las frases."""

    def __init__(self, args):
        self.args = args
        self.voz = args.voz
        self.g = Grabadora(args.mic)
        print("Midiendo el ruido del cuarto... quédate callado 1 segundo")
        ruido = self.g.grabar(1.2)[int(0.2 * FS):]
        self.noise_var = dsp.estimate_noise_var(ruido)
        n = len(ruido) // BLOCK
        ruido_db = float(np.median([dsp.rms_db(ruido[i * BLOCK:(i + 1) * BLOCK]) for i in range(n)])) if n else -60
        self.umbral = max(ruido_db + 8, -55)  # bajito para no cortar finales suaves ("zzz")
        print(f"Ruido {ruido_db:.0f} dBFS.")

    def escuchar(self, nombre, original=False):
        fs = respuestas.archivos(nombre)
        if not fs:
            print("   Todavía no está grabada.")
            return
        for f in fs:
            x, _ = sf.read(f, dtype="float64")
            print(f"   ▶ {os.path.basename(f)} ({len(x) / FS:.1f} s)" + ("" if original else f" con voz {self.voz}"))
            reproducir(x if original else dsp.voice_effect(x, self.voz))

    def grabar(self, nombre, frase, otra_toma=False):
        """Graba hasta que quede bien. Regresa True si se guardó."""
        while True:
            print(f"\n   Di: \"{frase}\"")
            preguntar("   Enter para EMPEZAR a grabar...")
            x = recortar(self.g.grabar(), self.umbral)
            if len(x) < 0.3 * FS:
                print("   No se oyó nada (o muy corto). Acércate al micrófono y otra vez.")
                continue
            limpio = x if self.args.sin_kalman else dsp.kalman_denoise(x, noise_var=self.noise_var)
            limpio = 0.9 * limpio / max(1e-6, np.max(np.abs(limpio)))
            print(f"   {len(limpio) / FS:.1f} s. Escúchala con voz '{self.voz}'...")
            reproducir(dsp.voice_effect(limpio, self.voz))
            while True:
                r = preguntar("   [g] guardar  [e] escuchar otra vez  [r] repetir grabación  [c] cancelar  > ").strip().lower()
                if r == "e":
                    reproducir(dsp.voice_effect(limpio, self.voz))
                elif r in ("g", "r", "c"):
                    break
            if r == "c":
                return False
            if r == "r":
                continue
            if otra_toma:
                destino = siguiente_nombre(nombre)
            else:
                destino = f"{nombre}.wav"
                self.borrar(nombre, avisar=False)  # reemplaza las tomas anteriores
            sf.write(os.path.join(respuestas.CARPETA, destino), limpio, FS, subtype="PCM_16")
            print(f"   ✔ guardada: respuestas/{destino}")
            return True

    def borrar(self, nombre, avisar=True):
        """No borra de verdad: las pasa a .bak (por si acaso)."""
        fs = respuestas.archivos(nombre)
        for f in fs:
            os.replace(f, f[:-4] + ".bak")
        if avisar:
            print(f"   {len(fs)} toma(s) movidas a .bak" if fs else "   No había nada grabado.")

    def frase(self, lista, i):
        """Submenú de una frase. Regresa el índice de la siguiente a mostrar, o None para volver a la lista."""
        nombre, texto = lista[i]
        while True:
            marca, info = estado(nombre)
            print()
            print("-" * 72)
            print(f" [{i + 1}/{len(lista)}] {marca} {nombre}  ({info})")
            print(f"   \"{texto}\"")
            print("-" * 72)
            print("   [g] grabar (reemplaza)   [o] otra toma   [e] escuchar   [n] escuchar sin efecto")
            print("   [b] borrar   [s] siguiente   [a] anterior   [l] lista")
            r = preguntar("   > ").strip().lower()
            if r == "g":
                if self.grabar(nombre, texto) and i + 1 < len(lista):
                    return i + 1  # al guardar, pasa a la siguiente
            elif r == "o":
                self.grabar(nombre, texto, otra_toma=True)
            elif r == "e":
                self.escuchar(nombre)
            elif r == "n":
                self.escuchar(nombre, original=True)
            elif r == "b":
                if preguntar("   ¿Seguro? (s/n) ").strip().lower() == "s":
                    self.borrar(nombre)
            elif r in ("s", ""):
                return min(i + 1, len(lista) - 1) if i + 1 < len(lista) else None
            elif r == "a":
                return max(i - 1, 0)
            elif r in ("l", "q", "m"):
                return None

    def menu(self, lista, inicio=None):
        i = inicio
        while True:
            if i is not None:
                i = self.frase(lista, i)
                continue
            imprimir_lista(lista, self.voz)
            print("  número = abrir frase   f = primera que falta   v = cambiar voz   q = salir")
            r = preguntar("  > ").strip().lower()
            if r == "q":
                return
            if r == "v":
                self.voz = dsp.VOCES[(dsp.VOCES.index(self.voz) + 1) % len(dsp.VOCES)]
            elif r == "f":
                faltan = [k for k, (n, _) in enumerate(lista) if not respuestas.archivos(n)]
                if faltan:
                    i = faltan[0]
                else:
                    print("  ¡Ya están todas!")
            elif r.isdigit() and 1 <= int(r) <= len(lista):
                i = int(r) - 1

    def close(self):
        self.g.close()


def main():
    ap = argparse.ArgumentParser(description="Grabar las respuestas de la bolita")
    ap.add_argument("nombre", nargs="?", help="abrir directo esta frase")
    ap.add_argument("--lista", action="store_true", help="solo imprimir la lista")
    ap.add_argument("--mic", type=int, default=None)
    ap.add_argument("--voz", default="tom", choices=dsp.VOCES, help="voz para escucharlas")
    ap.add_argument("--sin-kalman", action="store_true")
    args = ap.parse_args()

    os.makedirs(respuestas.CARPETA, exist_ok=True)
    lista = respuestas.todas()

    if args.lista:
        imprimir_lista(lista)
        return

    inicio = None
    if args.nombre:
        nombres = [n for n, _ in lista]
        if args.nombre not in nombres:
            print(f"'{args.nombre}' no está en respuestas.py. Opciones: {', '.join(nombres)}")
            return 1
        inicio = nombres.index(args.nombre)

    estudio = Estudio(args)
    try:
        estudio.menu(lista, inicio)
    except KeyboardInterrupt:
        pass
    finally:
        estudio.close()
        print("\nListo. Las frases están en pc/respuestas/")


if __name__ == "__main__":
    sys.exit(main())
