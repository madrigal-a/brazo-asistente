"""
Demo del filtro de Kalman para el reporte de la materia.

    python demo_kalman.py --grabar 4                 # graba 4 s con el micrófono
    python demo_kalman.py --wav mi_voz.wav           # o usa un archivo
    python demo_kalman.py --grabar 4 --ruido 5       # suma ruido blanco a 5 dB de SNR y mide la mejora
    python demo_kalman.py --sintetica --ruido 5      # sin micrófono: vocales sintéticas

Guarda en la carpeta resultados/: original.wav, ruidosa.wav, kalman.wav y kalman.png
(forma de onda + espectrogramas antes/después).
"""
import argparse
import os
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.signal import lfilter, resample_poly

import dsp

FS = dsp.FS


def synthetic_speech(seed=0):
    """Dos 'vocales' (pulsos glotales filtrados por formantes) con silencios."""

    def vowel(f0, forms, dur):
        n = int(dur * FS)
        e = np.zeros(n)
        e[:: int(FS / f0)] = 1
        y = e
        for f, bw in forms:
            r = np.exp(-np.pi * bw / FS)
            th = 2 * np.pi * f / FS
            y = lfilter([1], [1, -2 * r * np.cos(th), r * r], y)
        return y * np.hanning(n)

    s = np.concatenate([
        np.zeros(4000),
        vowel(120, [(700, 80), (1200, 90), (2600, 120)], 0.5),  # "a"
        np.zeros(2000),
        vowel(210, [(300, 60), (2300, 100), (3000, 150)], 0.5),  # "i"
        np.zeros(4000),
    ])
    return 0.5 * s / np.max(np.abs(s))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--grabar", type=float, help="segundos a grabar")
    g.add_argument("--wav")
    g.add_argument("--sintetica", action="store_true")
    ap.add_argument("--ruido", type=float, help="suma ruido blanco con este SNR en dB")
    ap.add_argument("--orden", type=int, default=10, help="orden del modelo AR (LPC)")
    ap.add_argument("--iter", type=int, default=3)
    ap.add_argument("--salida", default="resultados")
    args = ap.parse_args()
    os.makedirs(args.salida, exist_ok=True)

    if args.grabar:
        import sounddevice as sd

        print("Grabando: deja ~1 s de silencio al inicio y luego habla...")
        x = sd.rec(int(args.grabar * FS), samplerate=FS, channels=1, dtype="float32")
        sd.wait()
        x = x[:, 0].astype(np.float64)
    elif args.wav:
        x, fs = sf.read(args.wav, always_2d=True)
        x = x[:, 0]
        if fs != FS:
            x = resample_poly(x, FS, fs)
    else:
        x = synthetic_speech()

    clean_ref = None
    y = x
    if args.ruido is not None:
        rng = np.random.default_rng(1)
        n = rng.standard_normal(len(x))
        n *= np.sqrt(np.mean(x**2) / 10 ** (args.ruido / 10) / np.mean(n**2))
        y = x + n
        clean_ref = x

    t0 = time.time()
    out = dsp.kalman_denoise(y, order=args.orden, iterations=args.iter)
    print(f"Kalman: {time.time() - t0:.2f} s para {len(y)/FS:.1f} s de audio (orden {args.orden})")
    if clean_ref is not None:
        print(f"SNR entrada {dsp.snr_db(clean_ref, y):.1f} dB  ->  salida {dsp.snr_db(clean_ref, out):.1f} dB")

    sf.write(os.path.join(args.salida, "original.wav"), x, FS)
    if clean_ref is not None:
        sf.write(os.path.join(args.salida, "ruidosa.wav"), np.clip(y, -1, 1), FS)
    sf.write(os.path.join(args.salida, "kalman.wav"), np.clip(out, -1, 1), FS)

    # ---- gráficas
    t = np.arange(len(y)) / FS
    fig, ax = plt.subplots(3, 1, figsize=(11, 8), constrained_layout=True)
    ax[0].plot(t, y, lw=0.5, color="0.6", label="entrada")
    ax[0].plot(t, out, lw=0.6, color="C0", label="Kalman")
    ax[0].set_title("Forma de onda")
    ax[0].set_xlabel("s")
    ax[0].legend(loc="upper right")
    for a, sig, title in ((ax[1], y, "Espectrograma de entrada"), (ax[2], out, "Espectrograma después del filtro de Kalman")):
        a.specgram(sig, NFFT=512, Fs=FS, noverlap=384, cmap="magma", vmin=-120)
        a.set_title(title)
        a.set_ylabel("Hz")
        a.set_xlabel("s")
    png = os.path.join(args.salida, "kalman.png")
    fig.savefig(png, dpi=120)
    print(f"Listo: {args.salida}/ (wav y {os.path.basename(png)})")


if __name__ == "__main__":
    main()
