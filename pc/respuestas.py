"""
Qué palabras entiende la bolita y qué contesta.

Cada respuesta es un audio grabado en  pc/respuestas/<nombre>.wav  (se graba con  grabar.py).
Si grabas varias tomas (hola.wav, hola_2.wav, hola_3.wav...) elige una al azar cada vez.
Al reproducirse se le aplica el efecto de voz actual (tom, ardilla...), así que puedes grabarlas
con tu voz normal.

Para agregar una palabra: añade una línea a RESPUESTAS y graba su frase con
    py -3.12 grabar.py <nombre>
"""
import glob
import os
import random
import re
import unicodedata

import numpy as np

from bolita import ANGRY, HAPPY, LISTEN, NEUTRAL, SAD, SLEEPY, SURPRISED

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "respuestas")
FS = 16000

# (palabras: expresión regular sobre el texto en minúsculas y sin acentos,
#  nombre del audio de respuesta (None = no contesta con audio),
#  frase sugerida para grabar,
#  cara, rutina del brazo (None = no se mueve; "CANTA" = canta; "VOZ" = cambia la voz))
# Se usa la PRIMERA que coincida, así que las más específicas van arriba.
RESPUESTAS = [
    (r"\b(otra voz|cambia (la |de )?voz)\b", "voz", "¿Así? ¿Te gusta mi voz nueva?", SURPRISED, "VOZ"),
    (r"\b(canta|cantame|cancion|musica)\b", None, None, HAPPY, "CANTA"),
    (r"\b(te llamas|llamas|quien eres|tu nombre)\b", "nombre", "¡Soy la Bolita, y tengo un brazo robot!", HAPPY, "saludo"),
    (r"\b(como estas|que tal|como te va|como andas)\b", "bien", "¡Súper bien! ¿Y tú cómo estás?", HAPPY, "si"),
    (r"\b(hola|buenos dias|buenas tardes|que onda)\b", "hola", "¡Hola, hola! ¿Qué hacemos hoy?", HAPPY, "saludo"),
    (r"\b(adios|bye|nos vemos|hasta luego)\b", "adios", "¡Adiós! ¡Vuelve pronto!", HAPPY, "saludo"),
    (r"\b(baila|bailale|fiesta)\b", "baile", "¡A bailar se ha dicho!", HAPPY, "baile"),
    (r"\b(estirate|estira|estirado)\b", "estirar", "¡Uuuf, qué buena estirada!", SURPRISED, "estirar"),
    (r"\b(agarra|toma|recoge)\b", "agarrar", "¡Lo tengo!", LISTEN, "agarrar"),
    (r"\b(suelta|sueltalo)\b", "soltar", "Ahí te va.", NEUTRAL, "soltar"),
    (r"\b(inicio|quieto|alto|detente)\b", "quieto", "Ok, me quedo quieto.", NEUTRAL, "inicio"),
    (r"\b(bu|susto|cuidado)\b", "susto", "¡Aaay! ¡Qué susto!", SURPRISED, "susto"),
    (r"\b(duermete|a dormir|buenas noches)\b", "noches", "Buenas noches... zzz", SLEEPY, "inicio"),
    (r"\b(tonto|tonta|feo|fea)\b", "triste", "Oye... eso no fue bonito.", SAD, "no"),
    (r"\b(enojate|enojado|enojada)\b", "enojado", "¡Grrr! ¡Ya me enojé!", ANGRY, "no"),
    (r"\b(te quiero|bonito|bonita|lindo|linda|amigo|amiga|gracias)\b", "gracias", "¡Aww, gracias! Tú también.", HAPPY, "si"),
]

# Cuando no entiende ninguna palabra (solo si tom.py corre con --no-repetir)
NO_ENTENDI = ("no_entendi", "Mmm... no te entendí. ¿Me lo repites?")


def normalizar(texto):
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def buscar(texto):
    """Regresa (nombre, sugerida, cara, rutina) de la primera palabra que aparezca, o None."""
    t = normalizar(texto)
    for patron, nombre, sugerida, cara, rutina in RESPUESTAS:
        if re.search(patron, t):
            return nombre, sugerida, cara, rutina
    return None


def todas():
    """(nombre, frase sugerida) de todas las respuestas que se graban, sin repetir."""
    vistas, out = set(), []
    for _, nombre, sugerida, _, _ in RESPUESTAS + [(None, *NO_ENTENDI, None, None)]:
        if nombre and nombre not in vistas:
            vistas.add(nombre)
            out.append((nombre, sugerida))
    return out


def archivos(nombre):
    """Todas las tomas grabadas de una respuesta: nombre.wav, nombre_2.wav, ..."""
    fs = glob.glob(os.path.join(CARPETA, f"{nombre}.wav")) + glob.glob(os.path.join(CARPETA, f"{nombre}_*.wav"))
    return sorted(fs)


def cargar(nombre):
    """Audio (float, 16 kHz) de una toma al azar, o None si no se ha grabado."""
    fs = archivos(nombre) if nombre else []
    if not fs:
        return None
    import soundfile as sf

    x, fs_arch = sf.read(random.choice(fs), dtype="float64", always_2d=True)
    x = x.mean(axis=1)
    if fs_arch != FS:  # por si alguien pone un .wav de otro lado
        from fractions import Fraction

        from scipy.signal import resample_poly

        fr = Fraction(FS, fs_arch).limit_denominator(1000)
        x = resample_poly(x, fr.numerator, fr.denominator)
    return np.asarray(x)
