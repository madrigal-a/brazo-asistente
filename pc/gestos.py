"""
Gestos sencillos del brazo: mueven uno o dos servos un poco y los regresan.

Usan el comando de prueba del Uno  "T canal ángulo"  (mueve directo un canal del PCA9685),
así que funcionan aunque el control de potenciómetros todavía no esté bien calibrado.
Al terminar cada gesto los servos regresan a su reposo (no se manda HOME: aún no está calibrado).

Probar desde la terminal:
    python gestos.py                      # lista los gestos
    python gestos.py saludo               # por la ESP32 (busca el puerto sola)
    python gestos.py saludo --port COM5   # ESP32 en un puerto dado
    python gestos.py saludo --uno COM7    # directo al Arduino Uno por su USB (sin ESP32)
    python gestos.py todos                # todos, uno tras otro
    python gestos.py --t 11 60            # un solo comando: canal 11 a 60°
    python gestos.py prueba --port COM8   # mueve cada servo UNO POR UNO y lo regresa
    python gestos.py identificar --port COM8  # canal por canal, esperando Enter: para saber cuál es cuál
    python gestos.py --manual --port COM8 # escribes "11 60" + Enter y lo manda (ver ayuda adentro)

Para ajustar: cambia SERVOS (reposo de cada canal) y GESTOS (ángulos) aquí abajo.
"""
import argparse
import threading
import time

# ---------------------------------------------------------------- ajustes
# canal del PCA9685 -> (nombre, ángulo de reposo). El reposo es la CASA (26 nov, medida con la TUI):
# base 90, hombro 100, codo 90. La muñeca (11) y la pinza (10) no se usan: se quedan sueltas.
# Los ángulos son absolutos (mismo pulso = misma posición), así que se pueden repetir siempre;
# solo el PRIMER movimiento después de encender brinca desde donde esté el brazo.
SERVOS = {
    14: ("base", 90),
    13: ("hombro", 100),
    12: ("codo", 90),
}
CASA = {14: 90, 13: 100, 12: 90}
ESTIRADO = {13: 170, 12: 10}  # la base se queda donde esté
# Rangos seguros (igual que LIM_MIN / LIM_MAX de BrazoESP.ino): nunca se mandan ángulos fuera de aquí
LIMITES = {14: (50, 140), 13: (100, 170), 12: (10, 90)}

VEL = 120  # velocidad normal en °/s (el T del Uno es instantáneo: aquí se hace en pasitos)
PASO_S = 0.03  # cada cuánto se manda un pasito (30 ms)
FIN = ""  # qué mandar al terminar un gesto ("" = nada: cada servo ya regresa solo a la casa)

# Cada gesto es una lista de pasos:  ({canal: ángulo, ...}, espera_en_s [, velocidad °/s])
# Los canales de un mismo paso se mueven al mismo tiempo. Después del último paso, cada servo
# que se movió regresa solo a su reposo (la casa).
_SI = [(ESTIRADO, 0.5, 80)] + [({12: 15}, 0.15, 60), ({12: 10}, 0.15, 60)] * 3  # estirado, codo 10<->15 x3
_BAILE = [({14: 50, 13: 160}, 0.1, 90)] + [({14: 140, 13: 165}, 0.1), ({14: 50, 13: 160}, 0.1)] * 3  # base en todo su rango
GESTOS = {
    "inicio": [(CASA, 0.3, 60)],            # a la casa (también prende los 3 servos)
    "estirar": [(ESTIRADO, 2.0, 80)],      # se estira, espera 2 s y regresa a la casa
    "si": _SI,
    "baile": _BAILE,                        # base 50<->140 y hombro 160<->165, 3 veces
    # Los que siguen no los definimos todavía: usan los de arriba para que la voz no truene
    "saludo": _SI,
    "no": [({14: 70}, 0.1), ({14: 110}, 0.1), ({14: 70}, 0.1), ({14: 90}, 0.1)],  # base de lado a lado
    "susto": [({14: 70}, 0.1), ({14: 110}, 0.1), ({14: 90}, 0.1)],
    "agarrar": [],                          # sin pinza (está suelta)
    "soltar": [],
    # "mueve la base / el hombro / el codo" (sin número): se mueve dentro de su rango y regresa
    "mover_base": [({14: 130}, 0.3, 60), ({14: 60}, 0.3, 60)],
    "mover_hombro": [({13: 150}, 0.5, 50)],
    "mover_codo": [({12: 45}, 0.5, 50)],
    # prueba: cada servo por separado, ~20° y regresa (base, hombro, codo)
    "prueba": [
        ({14: 110}, 0.4), ({14: 90}, 0.6),
        ({13: 120}, 0.4), ({13: 100}, 0.6),
        ({12: 70}, 0.4), ({12: 90}, 0.6),
    ],
}


def recortar(canal, angulo):
    """Ángulo dentro del rango seguro del canal (LIMITES); otros canales: 0-180."""
    lo, hi = LIMITES.get(canal, (0, 180))
    return int(max(lo, min(hi, round(angulo))))


# ---------------------------------------------------------------- motor de gestos
class Gestos:
    """Corre los gestos en un hilo aparte, así la bolita puede hablar mientras se mueve.

    enviar: función que manda una línea de texto al Uno (Bolita.arm o UnoDirecto.arm).
    """

    def __init__(self, enviar, fin=FIN, vel=VEL, eco=print):
        self.enviar = enviar
        self.fin = fin
        self.vel = vel
        self.eco = eco
        self._hilo = None
        self._parar = threading.Event()
        # dónde creemos que está cada servo: el Uno arranca en la casa, y se va actualizando con
        # cada gesto y con ir(). Así un gesto empieza desde donde quedó el brazo (sin brincos).
        self.pos = {c: float(rep) for c, (_, rep) in SERVOS.items()}

    def hacer(self, nombre, esperar=False, repetir=False):
        """Empieza un gesto (corta el anterior). Regresa False si no existe.
        repetir=True: lo repite sin fin hasta parar() (p. ej. bailar mientras dura la música)."""
        if nombre not in GESTOS:
            self.eco(f"   [brazo] no hay gesto '{nombre}' (hay: {', '.join(GESTOS)})")
            return False
        self.parar()
        self._parar.clear()
        self.eco(f"   [brazo] {nombre}")
        self._hilo = threading.Thread(target=self._correr, args=(GESTOS[nombre], repetir), daemon=True)
        self._hilo.start()
        if esperar:
            self._hilo.join()
        return True

    def ir(self, canal, angulo, vel=60):
        """Mueve un servo a un ángulo (recortado a su rango) en pasitos suaves y se queda ahí.
        Regresa el ángulo al que va de verdad."""
        a = recortar(canal, angulo)
        self.parar()
        self._parar.clear()
        if canal not in self.pos:
            self.pos[canal] = float(a)  # canal que no conocemos: brinca directo
        self._hilo = threading.Thread(target=self._mover, args=(self.pos, {canal: a}, vel), daemon=True)
        self._hilo.start()
        return a

    def comando(self, canal, angulo):
        """Un solo T (para pruebas)."""
        self.enviar(f"T {int(canal)} {int(max(0, min(180, angulo)))}")

    def ocupado(self):
        return bool(self._hilo and self._hilo.is_alive())

    def parar(self):
        """Corta el gesto en curso (los servos igual regresan a su reposo)."""
        if self.ocupado():
            self._parar.set()
            self._hilo.join(3)

    # --- interno
    def _mover(self, pos, destino, vel, forzar=False):
        paso = vel * PASO_S
        while True:
            if self._parar.is_set() and not forzar:
                return False
            listo = True
            for c, a in destino.items():
                d = a - pos[c]
                if abs(d) > paso:
                    pos[c] += paso if d > 0 else -paso
                    listo = False
                else:
                    pos[c] = a
                self.enviar(f"T {c} {round(pos[c])}")
            time.sleep(PASO_S)
            if listo:
                return True

    def _correr(self, pasos, repetir=False):
        pos = self.pos  # empieza desde donde quedó el brazo
        usados = set()
        try:
            cortado = False
            while not cortado:
                for p in pasos:
                    angs = {c: max(LIMITES[c][0], min(LIMITES[c][1], a)) for c, a in p[0].items() if c in SERVOS}
                    vel = p[2] if len(p) > 2 else self.vel
                    usados |= set(angs)
                    if not self._mover(pos, angs, vel) or self._parar.wait(p[1]):
                        cortado = True
                        break
                if not repetir or not pasos:
                    break
            # siempre regresa al reposo (aunque lo hayan cortado), sin prisa
            self._mover(pos, {c: SERVOS[c][1] for c in usados}, min(self.vel, 150), forzar=True)
        finally:
            if self.fin:
                self.enviar(self.fin)


# ---------------------------------------------------------------- Uno directo por USB
class UnoDirecto:
    """Para probar sin la ESP32: el Uno conectado a la compu por su USB (115200)."""

    def __init__(self, port, eco=True):
        import serial

        self.ser = serial.Serial(port, 115200, timeout=0.1)
        self._alive = True
        if eco:
            threading.Thread(target=self._leer, daemon=True).start()
        time.sleep(2.5)  # al abrir el puerto el Uno se reinicia y va a CASA

    def arm(self, text):
        self.ser.write((text + "\n").encode())

    def _leer(self):
        while self._alive:
            try:
                l = self.ser.readline().decode(errors="ignore").strip()
            except Exception:
                break
            if l and not l.startswith(("T canal", "S ")):
                print("   uno>", l)

    def close(self):
        self._alive = False
        time.sleep(0.15)
        self.ser.close()


AYUDA_MANUAL = """
Modo manual — escribe y presiona Enter:
  11 60      canal 11 a 60°  (manda T 11 60)
  11         elige el canal 11 (o  c 12  para cambiar a otro)
  60         ya con un canal elegido: lo manda a 60°
  + / -      mueve el canal elegido 5°   (++ / -- = 15°)
  r          regresa el canal elegido a su reposo
  prueba     mueve cada servo uno por uno y lo regresa (o cualquier gesto: saludo, si, no...)
  h          HOME (pose de casa del Uno: OJO, todavía no está calibrada)
  q          salir (los servos se quedan donde están)
Canales: base 14, hombro 13, codo 12, muñeca 11, pinza 10 (la pinza vibra: no la dejes así)
"""


def manual(g):
    print(AYUDA_MANUAL)
    canal, pos = None, {}
    while True:
        try:
            l = input(f"[{'canal ' + str(canal) + ' = ' + str(pos.get(canal, '?')) + '°' if canal is not None else 'sin canal'}] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            l = "q"
        p = l.split()
        try:
            if not p:
                continue
            if p[0] in ("q", "salir"):
                return
            if p[0] in ("h", "home", "casa"):
                g.enviar("HOME")
                pos.clear()
            elif p[0] in GESTOS:
                g.hacer(p[0], esperar=True)
                pos.clear()
            elif p[0] in ("?", "ayuda"):
                print(AYUDA_MANUAL)
            elif p[0] == "r" and canal is not None:
                pos[canal] = SERVOS.get(canal, ("", 90))[1]
                g.comando(canal, pos[canal])
            elif set(p[0]) <= {"+", "-"} and canal is not None:
                paso = 5 if len(p[0]) == 1 else 15
                a = pos.get(canal, SERVOS.get(canal, ("", 90))[1])
                pos[canal] = max(0, min(180, a + (paso if p[0][0] == "+" else -paso)))
                g.comando(canal, pos[canal])
            elif len(p) == 2 and p[0] in ("c", "canal"):
                canal = int(p[1])
                print(f"   canal {canal} elegido ({SERVOS.get(canal, ('?',))[0]}); escribe un ángulo o + / -")
            elif len(p) == 2:
                canal, a = int(p[0]), int(p[1])
                pos[canal] = max(0, min(180, a))
                g.comando(canal, pos[canal])
            elif len(p) == 1 and canal is None:
                if not 0 <= int(p[0]) <= 15:
                    print("   primero elige un canal (0-15), o escribe canal y ángulo: 11 60")
                    continue
                canal = int(p[0])
                print(f"   canal {canal} elegido ({SERVOS.get(canal, ('?',))[0]}); escribe un ángulo o + / -")
            elif len(p) == 1:
                pos[canal] = max(0, min(180, int(p[0])))
                g.comando(canal, pos[canal])
            else:
                print("   no entendí; escribe ? para ver la ayuda")
                continue
            if canal is not None and canal in pos:
                print(f"   T {canal} {pos[canal]}")
        except ValueError:
            print("   no entendí; escribe ? para ver la ayuda")


def identificar(g, canales=None, amplitud=15, pausa=True):
    """Mueve cada canal ±amplitud alrededor de su reposo y lo regresa, uno por uno."""
    canales = canales or list(SERVOS)
    print("Se mueve un canal a la vez, poquito, y regresa. Anota qué parte del brazo se movió.\n")
    for c in canales:
        nombre, rep = SERVOS.get(c, ("?", 90))
        if pausa:
            try:
                input(f"Enter para mover el canal {c} (creemos que es: {nombre})... ")
            except (EOFError, KeyboardInterrupt):
                return
        pos = {c: float(rep)}
        g.enviar(f"T {c} {rep}")
        time.sleep(0.3)
        for destino in (rep + amplitud, rep - amplitud, rep):
            g._parar.clear()
            g._mover(pos, {c: max(0, min(180, destino))}, 60, forzar=True)
            time.sleep(0.3)
        print(f"   ✔ canal {c} listo")
    print("\nListo. Si un canal no movió nada, revisa ese conector en la placa azul.")


def main():
    ap = argparse.ArgumentParser(description="Gestos sencillos del brazo (comando T)")
    ap.add_argument("gesto", nargs="?", help="nombre del gesto o 'todos'")
    ap.add_argument("--port", help="puerto de la ESP32")
    ap.add_argument("--uno", help="puerto del Arduino Uno (directo, sin ESP32)")
    ap.add_argument("--t", nargs=2, type=int, metavar=("CANAL", "ANGULO"), help="manda un solo T")
    ap.add_argument("--manual", action="store_true", help="escribes los comandos con el teclado")
    args = ap.parse_args()

    if not args.gesto and not args.t and not args.manual:
        print("Gestos:", ", ".join(GESTOS), "+ identificar")
        print("Servos:", ", ".join(f"{n} = canal {c} (reposo {r}°)" for c, (n, r) in SERVOS.items()))
        return

    if args.uno:
        dev = UnoDirecto(args.uno)
        print("Uno en", args.uno)
    else:
        from bolita import Bolita

        dev = Bolita(args.port, on_line=lambda l: print("   esp32>", l))
        print("ESP32 en", dev.port, "  (si no es, usa --port COMx)")

    g = Gestos(dev.arm)
    try:
        if args.manual:
            manual(g)
        elif args.gesto == "identificar":
            identificar(g)
        elif args.t:
            g.comando(*args.t)
            print(f"T {args.t[0]} {args.t[1]}  (para salir del modo prueba: python gestos.py inicio)")
            time.sleep(1)
        elif args.gesto == "todos":
            for n in GESTOS:
                g.hacer(n, esperar=True)
                time.sleep(1.0)
        else:
            g.hacer(args.gesto, esperar=True)
            time.sleep(0.5)
    except KeyboardInterrupt:
        g.parar()
    finally:
        dev.close()


if __name__ == "__main__":
    main()
