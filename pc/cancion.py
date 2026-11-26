"""
La canción de la bolita: melodía original sintetizada (no usa archivos ni música con derechos).

    from cancion import cancion_bolita
    x = cancion_bolita()        # numpy float, 16 kHz, pico 0.8

Cada nota es una suma de armónicos (fundamental + 2.º + 3.º) con envolvente ADSR:
es síntesis aditiva, otro tema de procesamiento de señales.
"""
import numpy as np

FS = 16000
BPM = 140
OCTAVO = 60 / BPM / 2  # duración de un octavo en segundos

NOTAS = {"C": -9, "D": -7, "E": -5, "F": -4, "G": -2, "A": 0, "B": 2}


def hz(nombre):
    """'A4' -> 440 Hz, 'C5' -> 523 Hz. None = silencio."""
    if nombre is None:
        return 0.0
    n = NOTAS[nombre[0]] + 12 * (int(nombre[-1]) - 4)
    return 440.0 * 2 ** (n / 12)


# Melodía: (nota, octavos). 8 compases de 8 octavos.
MELODIA = [
    ("G4", 1), ("C5", 1), ("E5", 1), ("G5", 2), ("E5", 1), ("C5", 2),
    ("D5", 1), ("E5", 1), ("F5", 1), ("E5", 1), ("D5", 2), ("G4", 2),
    ("A4", 1), ("C5", 1), ("F5", 1), ("A5", 2), ("G5", 1), ("F5", 2),
    ("E5", 1), ("D5", 1), ("C5", 1), ("D5", 1), ("E5", 4),
    ("G5", 1), ("G5", 1), ("A5", 1), ("G5", 1), ("E5", 2), ("C5", 2),
    ("F5", 1), ("F5", 1), ("G5", 1), ("F5", 1), ("D5", 2), ("B4", 2),
    ("C5", 1), ("E5", 1), ("G5", 1), ("C6", 1), ("B5", 1), ("G5", 1), ("A5", 1), ("B5", 1),
    ("C6", 6), (None, 2),
]
# Bajo: una nota por compás, tocada en cada tiempo (negra)
BAJO = ["C3", "G3", "F3", "C3", "C3", "G3", "C3", "C3"]


def _nota(f, dur, armonicos=(1.0, 0.35, 0.15), ataque=0.01, decay=0.08, sustain=0.6, release=0.05):
    n = int(dur * FS)
    if f <= 0 or n == 0:
        return np.zeros(n)
    t = np.arange(n) / FS
    y = sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(armonicos))
    env = np.full(n, sustain)
    na, nd, nr = int(ataque * FS), int(decay * FS), int(release * FS)
    na, nd = min(na, n), min(nd, max(0, n - na))
    env[:na] = np.linspace(0, 1, na)
    env[na : na + nd] = np.linspace(1, sustain, nd)
    if nr and n > nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return y * env


def cancion_bolita(vueltas=1):
    mel = np.concatenate([_nota(hz(n), d * OCTAVO) for n, d in MELODIA])
    bajo = np.concatenate([
        # el 2.º y 3.er armónico fuertes: la bocina chiquita casi no da graves y así "se oye" el bajo
        np.concatenate([_nota(hz(b), 2 * OCTAVO, armonicos=(0.6, 0.8, 0.4), sustain=0.3) for _ in range(4)])
        for b in BAJO
    ])
    # platillo: ruido cortito en los contratiempos
    rng = np.random.default_rng(7)
    n_hat = int(0.03 * FS)
    hat = rng.standard_normal(n_hat) * np.linspace(1, 0, n_hat) ** 2
    hat = np.diff(hat, prepend=0)  # quita graves (filtro pasa-altas de 1er orden)
    plat = np.zeros(len(mel))
    for k in range(int(len(mel) / (2 * OCTAVO * FS))):
        i = int((2 * k + 1) * OCTAVO * FS)
        if i + n_hat < len(plat):
            plat[i : i + n_hat] += hat

    n = min(len(mel), len(bajo), len(plat))
    y = 0.55 * mel[:n] + 0.3 * bajo[:n] + 0.06 * plat[:n]
    y = np.tile(y, vueltas)
    return 0.8 * y / np.max(np.abs(y))


if __name__ == "__main__":
    import sounddevice as sd

    x = cancion_bolita()
    print(f"{len(x) / FS:.1f} s")
    sd.play(x, FS)
    sd.wait()
