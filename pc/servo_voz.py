"""
Órdenes por voz para probar un servo:  "prueba el servo diez y muévelo a veinte grados".

Vosk escribe los números con letra ("diez", "ciento veinte"), así que aquí se convierten a número.
Formas que entiende (en cualquier orden de palabras de relleno):
    "servo 10 a 20"  /  "canal once a sesenta grados"  /  "motor doce a noventa"
    "mueve el codo a ciento veinte"  /  "la muñeca a sesenta grados"  /  "pinza a veinte"
Regresa (canal, ángulo) y tom.py manda  "T canal ángulo"  al Uno.
"""
import re

from respuestas import normalizar

# Nombres de articulación -> canal del PCA9685 (igual que BrazoUno.ino)
ARTICULACIONES = {
    "base": 14,
    "hombro": 13,
    "codo": 12,
    "muneca": 11,
    "pinza": 10,
    "mano": 10,
}
# Cómo puede escribir Vosk "servo" (agrega aquí si en la terminal ves otra cosa)
PALABRA_SERVO = r"(servo|servos|siervo|serbo|cervo|canal|motor)"

_NUM = {
    "cero": 0, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19,
    "veinte": 20, "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23,
    "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
    "veintinueve": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60,
    "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
}


def numeros(texto):
    """Lista de números que aparecen en el texto, en orden: 'ciento treinta y cinco' -> [135]."""
    out, cur, y = [], None, False
    for tok in normalizar(texto).split():
        if tok.isdigit():
            val = int(tok)
        elif tok in _NUM:
            val = _NUM[tok]
        elif tok == "y" and cur is not None:
            y = True
            continue
        else:
            if cur is not None:
                out.append(cur)
            cur, y = None, False
            continue
        if cur is None:
            cur = val
        elif cur % 100 == 0 and 0 < val < 100 and not tok.isdigit():  # ciento + veinte
            cur += val
        elif cur % 10 == 0 and cur % 100 >= 30 and val < 10 and y:  # treinta y cinco
            cur += val
        else:
            out.append(cur)
            cur = val
        y = False
    if cur is not None:
        out.append(cur)
    return out


def buscar(texto):
    """(canal, ángulo) si el texto es una orden para un servo, si no None.
    "mueve la base" (sin número) -> (14, None): que se mueva un poco y regrese."""
    t = normalizar(texto)
    if re.search(r"\b" + PALABRA_SERVO + r"\b", t):
        n = numeros(t.split(re.search(r"\b" + PALABRA_SERVO + r"\b", t).group(0), 1)[1])
        if len(n) >= 2 and 0 <= n[0] <= 15:
            return n[0], max(0, min(180, n[1]))
        return None
    for nombre, canal in ARTICULACIONES.items():
        m = re.search(r"\b" + nombre + r"\b", t)
        if m:
            n = numeros(t[m.end():])
            if n:
                return canal, max(0, min(180, n[0]))
            if re.search(r"\b(mueve|muevete|mover|muevelo|muevela|menea)\b", t):
                return canal, None
    return None


if __name__ == "__main__":
    import sys

    frase = " ".join(sys.argv[1:]) or "prueba el servo diez y muevelo a veinte grados"
    print(frase, "->", numeros(frase), buscar(frase))
