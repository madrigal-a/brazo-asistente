"""
TUI para probar el brazo canal por canal y anotar cuáles responden.

    py -3.12 tui_brazo.py --uno COM6     # directo al Uno por su USB (recomendado: ves si el Uno recibió)
    py -3.12 tui_brazo.py --port COM8    # pasando por la ESP32
    py -3.12 tui_brazo.py --simular      # sin hardware, para ver cómo funciona

Con --uno: cierra el Monitor Serie del IDE y QUITA el cable GPIO 40 -> pin 0 (si la ESP está
conectada a ese pin, le gana al USB y el Uno no oye a la compu).

Teclas:
  ↑ ↓  (w s)        elegir canal
  ← →  (a d)        -5° / +5°          [ ]  -1° / +1°        PgUp PgDn  +15° / -15°
  número + Enter    ir a ese ángulo (ej. 90 Enter)
  Espacio           barrido: -20°, +20° y regresa (para ver si de verdad se mueve)
  o / O             soltar este canal / soltar TODOS (sin pulso: dejan de hacer fuerza)
  v                 velocidad (30 / 60 / 120 / 200 °/s)
  k  n  z  x        anotar: OK / no responde / zumba-apretado / borrar nota
  g                 guardar el reporte en pc/resultados/      q  salir (también guarda)

Cómo se mueve: manda "T canal ángulo" en pasitos de 30 ms (a la velocidad elegida), así el servo
no da brincos. Ojo: la PRIMERA orden a un canal suelto sí brinca directo (el servo no dice dónde está),
por eso cada canal arranca en el ángulo de casa (HOME_POS de BrazoESP.ino).
"""
import argparse
import collections
import datetime
import os
import re
import sys
import threading
import time

# (nombre, canal del PCA9685, ángulo inicial = casa en BrazoESP.ino)
FILAS = [
    ("Base", 14, 119),
    ("Hombro", 13, 22),
    ("Codo", 12, 175),
    ("Muñeca", 11, 84),
    ("Pinza", 10, 10),
    ("Canal 15 (libre)", 15, 90),
]
VELOCIDADES = [30, 60, 120, 200]
PASO_S = 0.03
NOTAS = {"k": "OK", "n": "NO RESPONDE", "z": "ZUMBA / APRETADO"}

VERDE, ROJO, AMARILLO, GRIS, NEGRITA, INV, FIN = (
    "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[90m", "\x1b[1m", "\x1b[7m", "\x1b[0m")


# ---------------------------------------------------------------- teclado (Windows y Linux/Mac)
if os.name == "nt":
    import msvcrt

    _ESPECIALES = {"H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT", "I": "PGUP", "Q": "PGDN"}

    def leer_tecla():
        """Regresa una tecla o None si no hay ninguna."""
        if not msvcrt.kbhit():
            return None
        c = msvcrt.getwch()
        if c in ("\x00", "\xe0"):
            return _ESPECIALES.get(msvcrt.getwch())
        return c

    class Terminal:
        def __enter__(self):
            os.system("")  # activa los colores ANSI en la consola de Windows
            return self

        def __exit__(self, *a):
            pass
else:
    import select
    import termios
    import tty

    _SEQ = {"[A": "UP", "[B": "DOWN", "[D": "LEFT", "[C": "RIGHT", "[5~": "PGUP", "[6~": "PGDN"}

    def leer_tecla():
        if not select.select([sys.stdin], [], [], 0)[0]:
            return None
        c = sys.stdin.read(1)
        if c == "\x1b":
            seq = ""
            while select.select([sys.stdin], [], [], 0.01)[0] and len(seq) < 3:
                seq += sys.stdin.read(1)
            return _SEQ.get(seq)
        return "\r" if c == "\n" else c

    class Terminal:
        def __enter__(self):
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
            return self

        def __exit__(self, *a):
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)


# ---------------------------------------------------------------- conexión
class Conexion:
    """Manda líneas al Uno (directo, por la ESP o simulado) y guarda lo que contesta."""

    def __init__(self, args):
        self.log = collections.deque(maxlen=7)
        self.confirmado = {}  # canal -> último ángulo que el Uno dijo recibir ("T canal c -> a")
        self.lock = threading.Lock()
        self.modo = "simulado"
        self.dev = None
        if args.simular:
            self.anota("(simulado: no se manda nada)")
        elif args.uno:
            from gestos import UnoDirecto

            print(f"Abriendo el Uno en {args.uno} (se reinicia, 3 s)...")
            self.dev = UnoDirecto(args.uno, eco=False)
            self.modo = f"Uno directo {args.uno}"
            threading.Thread(target=self._leer_uno, daemon=True).start()
        else:
            from bolita import Bolita

            print("Abriendo la ESP32...")
            self.dev = Bolita(args.port, on_line=self._linea)
            self.modo = f"ESP32 {self.dev.port}"

    def anota(self, texto):
        self.log.append(time.strftime("%H:%M:%S ") + texto)

    def manda(self, linea):
        with self.lock:
            if self.dev:
                self.dev.arm(linea)

    def _leer_uno(self):
        ser = self.dev.ser
        while True:
            try:
                l = ser.readline().decode(errors="ignore").strip()
            except Exception:
                break
            if l:
                self._linea(l)

    def _linea(self, l):
        if l.startswith("UNO "):  # la ESP reenvía lo que dice el Uno
            l = l[4:]
        m = re.match(r"T canal (\d+) -> (\d+)", l)
        if m:
            self.confirmado[int(m.group(1))] = int(m.group(2))
            return  # llegan muchísimas (una por pasito): no llenan el registro
        if l.startswith("S ") or l in ("DONE",):
            return
        self.anota(l)

    def cierra(self):
        if self.dev:
            self.dev.close()


# ---------------------------------------------------------------- motor: pasitos suaves
class Motor:
    """Cada canal tiene una posición y una lista de metas; un hilo lo acerca en pasitos de 30 ms."""

    def __init__(self, con):
        self.con = con
        self.pos = {c: a for _, c, a in FILAS}
        self.metas = {c: [] for _, c, _ in FILAS}
        self.prendido = {c: False for _, c, _ in FILAS}
        self.vel = 60
        self.lock = threading.Lock()
        threading.Thread(target=self._correr, daemon=True).start()

    def ir(self, canal, angulo, barrido=False):
        angulo = max(0, min(180, int(round(angulo))))
        with self.lock:
            if not self.prendido[canal]:  # primera orden: brinca directo
                self.prendido[canal] = True
                self.pos[canal] = angulo
                self.metas[canal] = []
                self.con.manda(f"T {canal} {angulo}")
                return
            if barrido:
                self.metas[canal].append(angulo)
            else:
                self.metas[canal] = [angulo]

    def destino(self, canal):
        with self.lock:
            return self.metas[canal][-1] if self.metas[canal] else self.pos[canal]

    def suelta(self, canal=None):
        with self.lock:
            for c in ([canal] if canal is not None else self.pos):
                self.metas[c] = []
                self.prendido[c] = False
        self.con.manda(f"OFF {canal}" if canal is not None else "OFF")

    def _correr(self):
        while True:
            t0 = time.time()
            envios = []
            with self.lock:
                paso = self.vel * PASO_S
                for c, metas in self.metas.items():
                    if not metas:
                        continue
                    d = metas[0] - self.pos[c]
                    self.pos[c] += max(-paso, min(paso, d))
                    if abs(metas[0] - self.pos[c]) < 0.01:
                        self.pos[c] = metas[0]
                        metas.pop(0)
                    envios.append(f"T {c} {round(self.pos[c])}")
            for e in envios:
                self.con.manda(e)
            time.sleep(max(0.0, PASO_S - (time.time() - t0)))


# ---------------------------------------------------------------- pantalla
def barra(a, ancho=30):
    i = int(round(a / 180 * (ancho - 1)))
    return "".join("█" if k == i else "─" for k in range(ancho))


def dibuja(sel, motor, con, notas, numero, aviso):
    out = ["\x1b[H\x1b[J", f"{NEGRITA}BRAZO — prueba de canales{FIN}   conexión: {con.modo}   "
           f"velocidad: {motor.vel} °/s\n"]
    out.append(f"   {'articulación':<17}{'canal':>5}  {'ángulo':>6}  {'0°':<3}{'':<24}{'180°':>4}  "
               f"{'estado':<9}{'Uno recibió':<12}nota\n")
    for i, (nombre, c, _) in enumerate(FILAS):
        p = motor.pos[c]
        dest = motor.destino(c)
        ang = f"{p:5.0f}°" + (f"→{dest}" if round(p) != dest else "")
        estado = f"{VERDE}prendido{FIN} " if motor.prendido[c] else f"{GRIS}suelto{FIN}   "
        rec = con.confirmado.get(c)
        rec = f"{rec}°" if rec is not None else ("—" if con.modo.startswith("ESP") else "nada")
        nota = notas.get(c, "")
        color = VERDE if nota == "OK" else (ROJO if nota else "")
        fila = f"{'►' if i == sel else ' '}  {nombre:<17}{c:>5}  {ang:<10}{barra(p)}  "
        if i == sel:
            fila = f"{INV}{fila}{FIN}"
        out.append(f"{fila}{estado}{rec:<12}{color}{nota}{FIN}\n")
    out.append(f"\n{GRIS}↑↓ canal  ←→ ±5°  [ ] ±1°  PgUp/PgDn ±15°  número+Enter ir  Espacio barrido\n"
               f"o soltar canal  O soltar todos  v velocidad  k OK  n no responde  z zumba  x borrar  "
               f"g guardar  q salir{FIN}\n")
    out.append(f"\nÁngulo: {AMARILLO}{numero}_{FIN}\n" if numero else "\n\n")
    out.append((f"{AMARILLO}{aviso}{FIN}" if aviso else "") + "\n")
    out.append(f"{NEGRITA}Lo que dice el Uno / la ESP:{FIN}\n")
    out.extend(f"  {l}\n" for l in con.log)
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def guarda(notas, motor):
    carpeta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resultados")
    os.makedirs(carpeta, exist_ok=True)
    ruta = os.path.join(carpeta, datetime.datetime.now().strftime("prueba_canales_%Y-%m-%d_%H%M.txt"))
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"Prueba de canales — {datetime.datetime.now():%d/%m/%Y %H:%M}\n\n")
        for nombre, c, _ in FILAS:
            f.write(f"{nombre:<18} canal {c:>2}  último ángulo {motor.pos[c]:5.0f}°  "
                    f"{notas.get(c, 'sin probar')}\n")
    return ruta


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser(description="TUI para probar el brazo canal por canal")
    ap.add_argument("--port", help="puerto de la ESP32 (ej. COM8)")
    ap.add_argument("--uno", help="puerto del Uno para mandarle directo por USB (ej. COM6)")
    ap.add_argument("--simular", action="store_true", help="sin hardware")
    args = ap.parse_args()

    con = Conexion(args)
    motor = Motor(con)
    sel, numero, aviso, notas = 0, "", "Los canales empiezan SUELTOS: muévelos y se prenden.", {}
    ultimo = 0

    with Terminal():
        sys.stdout.write("\x1b[?25l")  # esconde el cursor
        try:
            while True:
                k = leer_tecla()
                if k is None:
                    if time.time() - ultimo > 0.1:
                        dibuja(sel, motor, con, notas, numero, aviso)
                        ultimo = time.time()
                    time.sleep(0.02)
                    continue
                c = FILAS[sel][1]
                aviso = ""
                if k in ("UP", "w"):
                    sel = (sel - 1) % len(FILAS)
                elif k in ("DOWN", "s"):
                    sel = (sel + 1) % len(FILAS)
                elif k in ("LEFT", "a", "RIGHT", "d", "[", "]", "PGUP", "PGDN"):
                    delta = {"LEFT": -5, "a": -5, "RIGHT": 5, "d": 5, "[": -1, "]": 1,
                             "PGUP": 15, "PGDN": -15}[k]
                    motor.ir(c, motor.destino(c) + delta)
                elif k.isdigit():
                    numero = (numero + k)[-3:]
                elif k == "\b":
                    numero = numero[:-1]
                elif k in ("\r", "\n"):
                    if numero:
                        motor.ir(c, int(numero))
                        numero = ""
                elif k == "\x1b":
                    numero = ""
                elif k == " ":
                    a = motor.destino(c)
                    for m in (a - 20, a + 20, a):
                        motor.ir(c, max(0, min(180, m)), barrido=True)
                    aviso = f"Barrido del canal {c}: ¿se movió? anota k (OK), n (no responde) o z (zumba)"
                elif k == "o":
                    motor.suelta(c)
                    aviso = f"Canal {c} suelto"
                elif k == "O":
                    motor.suelta()
                    aviso = "Todos sueltos"
                elif k == "v":
                    motor.vel = VELOCIDADES[(VELOCIDADES.index(motor.vel) + 1) % len(VELOCIDADES)]
                elif k in NOTAS:
                    notas[c] = NOTAS[k]
                    sel = min(sel + 1, len(FILAS) - 1)
                elif k == "x":
                    notas.pop(c, None)
                elif k == "g":
                    aviso = "Guardado en " + guarda(notas, motor)
                elif k in ("q", "\x03"):
                    break
                dibuja(sel, motor, con, notas, numero, aviso)
                ultimo = time.time()
        except KeyboardInterrupt:
            pass
        finally:
            sys.stdout.write("\x1b[?25h\n")
    ruta = guarda(notas, motor) if notas else None
    con.cierra()
    print("Los servos se quedan como están (usa O antes de salir para soltarlos).")
    if ruta:
        print("Reporte:", ruta)


if __name__ == "__main__":
    main()
