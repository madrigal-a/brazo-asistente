"""
Procesamiento de señales de la bolita.

- kalman_denoise(): filtro de Kalman para limpiar voz (modelo autorregresivo, LPC)
- efectos de voz: ardilla, tom, monstruo, robot, eco
- features(): intensidad (dB) y tono (Hz) de un bloque, para elegir la cara

Modelo del filtro de Kalman (Paliwal & Basu, 1987):
    La voz limpia s[n] se modela como un proceso AR de orden p:
        s[n] = a1 s[n-1] + ... + ap s[n-p] + w[n],      w ~ N(0, Q)
    El micrófono mide voz + ruido blanco:
        y[n] = s[n] + v[n],                              v ~ N(0, R)

    Estado:      x[n] = [s[n], s[n-1], ..., s[n-p+1]]^T
    Transición:  x[n] = F x[n-1] + G w[n]     (F: matriz compañera con los a_k)
    Medición:    y[n] = H x[n] + v[n]         (H = [1 0 ... 0])

    Los coeficientes a_k y Q se recalculan cada trama de 20 ms con
    Levinson-Durbin; R (varianza del ruido) se estima en los silencios.
"""
from fractions import Fraction

import numpy as np
from scipy.signal import resample_poly

FS = 16000

try:  # numba acelera el filtro ~50x; si no está instalado funciona igual, más lento
    from numba import njit
except ImportError:  # pragma: no cover
    def njit(*a, **k):
        def deco(f):
            return f
        return deco(a[0]) if a and callable(a[0]) else deco


# ---------------------------------------------------------------- LPC
def autocorr(x, p):
    n = len(x)
    return np.array([np.dot(x[: n - k], x[k:]) for k in range(p + 1)]) / n


def levinson(r, p):
    """Levinson-Durbin. Regresa (a, err) con s[n] ≈ sum a_k s[n-k], err = varianza del residuo."""
    a = np.zeros(p)
    err = r[0]
    if err <= 0:
        return a, 0.0
    for i in range(p):
        acc = r[i + 1] - np.dot(a[:i], r[i:0:-1])
        k = acc / err
        a_new = a.copy()
        a_new[i] = k
        a_new[:i] = a[:i] - k * a[:i][::-1]
        a = a_new
        err *= 1 - k * k
        if err <= 0:
            return a, 1e-12
    return a, err


def estimate_noise_var(y, frame=320, quantile=0.1):
    """Varianza del ruido = energía media de las tramas más silenciosas."""
    n = len(y) // frame
    if n == 0:
        return float(np.var(y))
    e = np.var(y[: n * frame].reshape(n, frame), axis=1)
    k = max(1, int(n * quantile))
    return float(np.mean(np.sort(e)[:k]))


# ---------------------------------------------------------------- Kalman
@njit(cache=True)
def _kalman_frame(y, a, Q, R, x, P):
    """Filtra una trama muestra por muestra. x, P se actualizan (estado continuo entre tramas)."""
    p = a.shape[0]
    out = np.empty_like(y)
    xp = np.empty(p)
    Pp = np.empty((p, p))
    for n in range(y.shape[0]):
        # --- Predicción: x = F x ;  P = F P F^T + Q e1 e1^T
        s0 = 0.0
        for k in range(p):
            s0 += a[k] * x[k]
        xp[0] = s0
        for k in range(1, p):
            xp[k] = x[k - 1]
        # F P (filas): fila 0 = a^T P, fila k = fila k-1 de P
        FP0 = np.zeros(p)
        for j in range(p):
            acc = 0.0
            for k in range(p):
                acc += a[k] * P[k, j]
            FP0[j] = acc
        # (F P) F^T
        acc00 = 0.0
        for k in range(p):
            acc00 += FP0[k] * a[k]
        Pp[0, 0] = acc00 + Q
        for j in range(1, p):
            Pp[0, j] = FP0[j - 1]
            Pp[j, 0] = FP0[j - 1]
        for i in range(1, p):
            for j in range(1, p):
                Pp[i, j] = P[i - 1, j - 1]
        # --- Actualización con la medición y[n]
        S = Pp[0, 0] + R
        innov = y[n] - xp[0]
        for i in range(p):
            K = Pp[i, 0] / S
            x[i] = xp[i] + K * innov
        for i in range(p):
            Ki = Pp[i, 0] / S
            for j in range(p):
                P[i, j] = Pp[i, j] - Ki * Pp[0, j]
        out[n] = x[0]
    return out


def kalman_denoise(y, order=10, frame=320, noise_var=None, iterations=3):
    """
    Limpia voz con filtro de Kalman.
    y: señal float (-1..1). noise_var: varianza del ruido (si None se estima).
    iterations: desde la 2a pasada los coeficientes LPC se calculan sobre la señal
    ya filtrada (mejor modelo de la voz). Con 3 pasadas se gana ~6-7 dB de SNR.
    """
    y = np.asarray(y, dtype=np.float64)
    R = estimate_noise_var(y, frame) if noise_var is None else float(noise_var)
    R = max(R, 1e-10)
    ref = y
    out = y
    for it in range(iterations):
        x = np.zeros(order)
        P = np.eye(order) * R
        out = np.empty_like(y)
        for start in range(0, len(y), frame):
            seg_y = y[start : start + frame]
            ry = autocorr(seg_y, order)
            # Potencia de la voz limpia en la trama: el ruido blanco solo suma R en r[0]
            rx0 = max(ry[0] - R, 0.01 * ry[0])
            if it == 0:
                r = ry.copy()
                r[0] = rx0
            else:
                r = autocorr(ref[start : start + frame], order)
            r[0] *= 1.0001  # pequeña regularización
            a, err = levinson(r, order)
            # Q = error de predicción normalizado * potencia estimada de la voz.
            # En tramas de puro ruido rx0 es muy chico -> Q chico -> el filtro las apaga.
            Q = max(err / max(r[0], 1e-20) * rx0, 1e-12)
            out[start : start + frame] = _kalman_frame(seg_y, a, Q, R, x, P)
        ref = out
    return out


def snr_db(clean, test):
    noise = test - clean
    return 10 * np.log10(np.sum(clean**2) / (np.sum(noise**2) + 1e-20))


# ---------------------------------------------------------------- Efectos de voz
def _speed(x, factor):
    """Reproduce más rápido (factor>1, más agudo) o más lento (factor<1, más grave)."""
    fr = Fraction(1 / factor).limit_denominator(24)
    return resample_poly(x, fr.numerator, fr.denominator)


def _normalize(x, peak=0.9):
    m = np.max(np.abs(x)) if len(x) else 0
    return x * (peak / m) if m > 1e-6 else x


def voice_effect(x, voz, fs=FS):
    x = np.asarray(x, dtype=np.float64)
    if voz == "ardilla":
        y = _speed(x, 1.75)
    elif voz == "tom":
        y = _speed(x, 1.4)
    elif voz == "monstruo":
        y = _speed(x, 0.72)
    elif voz == "robot":
        y = _speed(x, 1.15)
        t = np.arange(len(y)) / fs
        y = y * np.sin(2 * np.pi * 60 * t)  # modulación en anillo
    elif voz == "eco":
        y = _speed(x, 1.3)
        d = int(0.18 * fs)
        y = np.concatenate([y, np.zeros(3 * d)])
        for g, k in ((0.5, 1), (0.25, 2), (0.12, 3)):
            y[k * d :] += g * y[: len(y) - k * d]
    else:  # "normal"
        y = x.copy()
    # fade-in/out para evitar chasquidos
    n = min(len(y) // 2, int(0.01 * fs))
    if n > 0:
        ramp = np.linspace(0, 1, n)
        y[:n] *= ramp
        y[-n:] *= ramp[::-1]
    return _normalize(y)


VOCES = ["tom", "ardilla", "monstruo", "robot", "eco", "normal"]


# ---------------------------------------------------------------- Rasgos para las caras
def rms_db(block):
    return 20 * np.log10(np.sqrt(np.mean(np.square(block))) + 1e-9)


def pitch_hz(block, fs=FS, fmin=70, fmax=450):
    """Tono por autocorrelación. Regresa 0 si el bloque no tiene voz."""
    x = block - np.mean(block)
    if np.max(np.abs(x)) < 1e-4:
        return 0.0
    r = np.correlate(x, x, mode="full")[len(x) - 1 :]
    if r[0] <= 0:
        return 0.0
    r = r / r[0]
    lo, hi = int(fs / fmax), min(int(fs / fmin), len(r) - 1)
    if hi <= lo:
        return 0.0
    lag = lo + int(np.argmax(r[lo:hi]))
    return fs / lag if r[lag] > 0.45 else 0.0


def to_int16(x):
    return (np.clip(x, -1, 1) * 32767).astype("<i2")
