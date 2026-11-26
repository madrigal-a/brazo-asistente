"""
Talking Bolita — programa principal (corre en la computadora). Abre una TUI (pantalla en la
terminal) con la configuración, el nivel del micrófono y las frases que reconoce.

    python tom.py                 # busca la ESP32 sola
    python tom.py --port COM8     # o /dev/ttyUSB0, /dev/cu.usbserial-xxxx
    python tom.py --simular       # sin ESP32: suena en la compu, escucha solo
    python tom.py --sin-tui       # como antes: solo imprime líneas
    python tom.py --puertos       # lista puertos seriales
    python tom.py --mics          # lista micrófonos
    python tom.py --auto          # escucha sola (sin el botón Function)
    python tom.py --audio esp     # la voz sale por la bocina de la ESP32 (pc = compu, ambos = las dos)
                                  # sin --audio te pregunta al arrancar
    python tom.py --brazo rutinas # rutinas de Arm.h en la ESP (por defecto: gestos de gestos.py)
    python tom.py --uno COM6      # gestos directo al Arduino Uno por USB, sin pasar por la ESP32

Teclas en la TUI:
    1 casa · 2 "sí" · 3 baile con música      (igual que si lo dijeras)
    v voz · p botón Function / automático · k Kalman · r si no entiende: repite / "no entendí"
    m primero mueve el brazo y luego habla · b brazo prendido/apagado · + / - volumen · q salir

Audio: el micrófono y las bocinas son los PREDETERMINADOS de Windows (--mic N / --bocina N para elegir).

Flujo: mantienes FUNCTION en la ESP32 (o habla sola con --auto) -> graba -> filtro de Kalman
       -> Vosk reconoce las palabras -> si hay una palabra de respuestas.py mueve el brazo y contesta
       con su frase grabada (grabar.py); si no, te repite (o dice "no entendí") con efecto de voz.
"""
import argparse
import builtins
import json
import os
import queue
import sys
import threading
import time
from collections import deque

import numpy as np
import sounddevice as sd

import dsp
import respuestas
import servo_voz
from gestos import Gestos, UnoDirecto
from cancion import cancion_bolita
from bolita import ANGRY, HAPPY, LISTEN, MOOD_NAMES, NEUTRAL, SAD, SLEEPY, SURPRISED, Bolita, list_ports

FS = dsp.FS
BLOCK = 320  # 20 ms


# ---------------------------------------------------------------- modo simulación
class FakeBolita:
    """Igual que Bolita pero sin hardware: imprime las caras y suena en la compu."""

    def __init__(self, on_line=None, salida=None):
        self._m = None
        self.salida = salida
        self.port = "(simulada)"

    def mood(self, m, intensity=1.0, hold_s=0.0):
        if m != self._m:
            print(f"   [cara] {MOOD_NAMES[m]} ({intensity:.1f})")
            self._m = m

    def look(self, x, y):
        pass

    def volume(self, v):
        pass

    def arm(self, text):
        if not text.startswith("T "):  # los pasitos de los gestos no se imprimen
            print(f"   [brazo] {text}")

    def stop_audio(self):
        sd.stop()

    def play(self, samples_int16, chunk=512, stop=None):
        sd.play(np.asarray(samples_int16) / 32767.0, FS, device=self.salida)
        return len(samples_int16) / FS

    def wait_done(self, timeout):
        sd.wait()
        return True

    def close(self):
        pass


# ---------------------------------------------------------------- palabras (Vosk)
MODELO_VOSK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modelos", "vosk-model-small-es-0.42")


def buscar_modelo(ruta):
    """Usa la ruta dada o, si no, pc/modelos/vosk-model-small-es-0.42 (lo descomprime si solo está el .zip)."""
    if ruta:
        return ruta
    if os.path.isdir(MODELO_VOSK):
        return MODELO_VOSK
    if os.path.isfile(MODELO_VOSK + ".zip"):
        import zipfile

        print("Descomprimiendo el modelo de Vosk (solo la primera vez)...")
        with zipfile.ZipFile(MODELO_VOSK + ".zip") as z:
            z.extractall(os.path.dirname(MODELO_VOSK))
        return MODELO_VOSK
    return None


class Words:
    def __init__(self, model_path):
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        self.model = Model(model_path)
        self.Rec = KaldiRecognizer

    def recognize(self, x):
        rec = self.Rec(self.model, FS)
        rec.AcceptWaveform(dsp.to_int16(x).tobytes())
        return json.loads(rec.FinalResult()).get("text", "")


# ---------------------------------------------------------------- TUI
VERDE, ROJO, AMARILLO, CIAN, GRIS, NEGRITA, FIN = (
    "\x1b[32m", "\x1b[31m", "\x1b[33m", "\x1b[36m", "\x1b[90m", "\x1b[1m", "\x1b[0m")


class Pantalla:
    """Dibuja la TUI en un hilo aparte. Lo que el programa imprime va a la sección de mensajes."""

    def __init__(self, state, info):
        self.state = state
        self.info = info          # textos fijos: puerto, micrófono, salida...
        self.frases = deque(maxlen=8)
        self.log = deque(maxlen=6)
        self._print = builtins.print
        self._vivo = True
        self._carpeta = os.path.dirname(os.path.abspath(__file__))

    def mensaje(self, *a, **k):
        # solo lo que imprime el código de esta carpeta (numba y otras librerías a veces imprimen basura)
        if os.path.dirname(os.path.abspath(sys._getframe(1).f_code.co_filename)) != self._carpeta:
            return
        texto = " ".join(str(x) for x in a).strip()
        for l in texto.splitlines():
            if l.strip():
                self.log.append(time.strftime("%H:%M:%S ") + l.strip())

    def frase(self, n, texto, ok, detalle):
        """ok: True = coincidió, False = no, None = sin Vosk / sin texto."""
        self.frases.appendleft((n, time.strftime("%H:%M:%S"), texto, ok, detalle))

    def empieza(self):
        builtins.print = self.mensaje
        sys.stdout.write("\x1b[?25l")
        threading.Thread(target=self._dibujar, daemon=True).start()

    def termina(self):
        self._vivo = False
        time.sleep(0.15)
        builtins.print = self._print
        sys.stdout.write("\x1b[?25h\n")
        sys.stdout.flush()

    def _dibujar(self):
        while self._vivo:
            try:
                sys.stdout.write(self._pantalla())
                sys.stdout.flush()
            except Exception:
                pass
            time.sleep(0.12)

    def _pantalla(self):
        s = self.state
        si_no = lambda v: f"{VERDE}sí{FIN}" if v else f"{GRIS}no{FIN}"
        estados = {"escuchando": f"{VERDE}🎤 ESCUCHANDO{FIN}", "pensando": f"{AMARILLO}… pensando{FIN}",
                   "brazo": f"{CIAN}🦾 moviendo el brazo{FIN}", "hablando": f"{CIAN}🗣 hablando{FIN}",
                   "cantando": f"{CIAN}🎵 cantando y bailando{FIN}", "esperando": f"{GRIS}esperando{FIN}",
                   "calibrando": f"{AMARILLO}calibrando ruido (silencio){FIN}"}
        # nivel del micrófono: barra de -70 a -10 dBFS con la marca del umbral
        ancho = 40
        pos = lambda db: int(np.clip((db + 70) / 60, 0, 1) * (ancho - 1))
        n, u = pos(s["db"]), pos(s["umbral"])
        barra = "".join(("█" if i <= n else "─") if i != u else "|" for i in range(ancho))
        modo = "botón Function" if s["modo_ptt"] else "automático (detecta tu voz)"
        brazo = s["brazo"] if s["brazo"] != "no" else f"{GRIS}apagado{FIN}"
        L = ["\x1b[H\x1b[J",
             f"{NEGRITA}TALKING BOLITA{FIN}   {estados.get(s['estado'], s['estado'])}   cara: {s['cara']}\n",
             f"{GRIS}{self.info}{FIN}\n\n",
             f"{NEGRITA}Configuración{FIN}  (tecla entre paréntesis)\n",
             f"  (v) voz: {CIAN}{s['voz']}{FIN}     (p) escuchar con: {modo}     (k) Kalman: {si_no(s['kalman'])}\n",
             f"  (r) si no entiende: {'dice no entendí' if s['no_repetir'] else 'te repite'}"
             f"     (b) brazo: {brazo}     (m) mover y luego hablar: {si_no(s['mover_antes'])}\n",
             f"  (+/-) volumen ESP: {s['volumen']}\n\n",
             f"  mic {barra} {s['db']:5.0f} dB   (| = umbral {s['umbral']:.0f} dB)\n\n",
             f"{NEGRITA}Frases que reconoció{FIN}  (la más nueva arriba)\n"]
        if not self.frases:
            L.append(f"  {GRIS}(todavía nada: {'mantén FUNCTION y habla' if s['modo_ptt'] else 'habla'}){FIN}\n")
        for n, hora, texto, ok, detalle in self.frases:
            marca = f"{VERDE}✓{FIN}" if ok else (f"{ROJO}✗{FIN}" if ok is False else f"{GRIS}·{FIN}")
            t = f'"{texto}"' if texto else f"{GRIS}(Vosk no entendió palabras){FIN}"
            L.append(f"  {marca} #{n:<3} {GRIS}{hora}{FIN}  {t:<38} {detalle}\n")
        L.append(f"\n{GRIS}1 casa · 2 sí · 3 baile    v p k r m b +/-    q salir{FIN}\n")
        L.append(f"{NEGRITA}Mensajes{FIN}\n")
        L.extend(f"  {l}\n" for l in self.log)
        return "".join(L)


# ---------------------------------------------------------------- programa
def main():
    ap = argparse.ArgumentParser(description="Talking Bolita")
    ap.add_argument("--port")
    ap.add_argument("--puertos", action="store_true", help="lista puertos seriales")
    ap.add_argument("--mics", action="store_true", help="lista micrófonos")
    ap.add_argument("--mic", type=int, default=None, help="índice del micrófono")
    ap.add_argument("--voz", default="tom", choices=dsp.VOCES)
    ap.add_argument("--sin-kalman", action="store_true")
    ap.add_argument("--vosk", help="carpeta del modelo de Vosk (por defecto pc/modelos/vosk-model-small-es-0.42)")
    ap.add_argument("--sin-palabras", action="store_true", help="no reconocer palabras: solo repite")
    ap.add_argument("--no-repetir", action="store_true", help="si no entiende ninguna palabra, dice 'no entendí' en vez de repetirte")
    ap.add_argument("--guardar", help="carpeta donde guardar cada frase (original/kalman/efecto)")
    ap.add_argument("--volumen", type=int, default=130, help="0-255 (con el MAX98357 a 3.3 V, más de ~150 distorsiona)")
    ap.add_argument("--simular", action="store_true", help="sin ESP32 (escucha sola, como --auto)")
    ap.add_argument("--auto", action="store_true", help="escucha sola al detectar voz, sin el botón Function")
    ap.add_argument("--audio", choices=["esp", "pc", "ambos"], help="dónde suena la voz: esp (bocina de la ESP32), pc (bocinas/audífonos de la compu) o ambos. Sin esto, pregunta al arrancar")
    ap.add_argument("--bocina", type=int, default=None, help="índice del dispositivo de salida (ver --mics); por defecto el de Windows")
    ap.add_argument("--brazo", default="gestos", choices=["gestos", "rutinas", "no"], help="gestos: los de gestos.py | rutinas: las de Arm.h | no: no mover")
    ap.add_argument("--uno", help="puerto del Arduino Uno para mandarle los gestos directo por USB (sin la ESP32)")
    ap.add_argument("--sin-tui", action="store_true", help="sin pantalla: solo imprime líneas (como antes)")
    args = ap.parse_args()

    if args.puertos:
        for dev, desc in list_ports():
            print(f"{dev:20s} {desc}")
        return
    if args.mics:
        print(sd.query_devices())
        return

    state = {
        "voz": args.voz, "ptt": False, "cancel": False, "cantar": False, "gestos": None, "salir": False,
        "modo_ptt": not (args.auto or args.simular),  # push-to-talk: graba solo mientras mantienes FUNCTION
        "kalman": not args.sin_kalman, "no_repetir": args.no_repetir, "mover_antes": True,
        "brazo": args.brazo, "volumen": args.volumen, "estado": "esperando", "cara": "neutral",
        "db": -99.0, "umbral": -50.0, "manual": queue.Queue(),
    }
    brazo_original = args.brazo if args.brazo != "no" else "gestos"

    def siguiente_voz():
        state["voz"] = dsp.VOCES[(dsp.VOCES.index(state["voz"]) + 1) % len(dsp.VOCES)]
        print(f"   [voz] {state['voz']}")

    def aviso_ptt():
        if not state["ptt"]:
            print("⚠ Presionaste Function pero no empezó a escuchar: ¿está en PAUSA o en el menú? (Mode -> 'Reanudar')")

    def on_line(line):
        if line == "BTN FUNC":
            threading.Timer(0.4, aviso_ptt).start()
        elif line.startswith("UNO"):
            print(f"   [uno] {line[3:].strip()}")
        if line == "PTT 1":
            state["ptt"], state["cancel"] = True, False
        elif line == "PTT 0":
            state["ptt"] = False
        elif line == "PTT C":  # cancelado (paro o pausa): no se procesa
            state["ptt"], state["cancel"] = False, True
        elif line == "VOZ":  # "Otra voz" en el menú de la ESP32
            siguiente_voz()
        elif line == "CANTA":  # "Canta" en el menú de la ESP32
            state["cantar"] = True
        elif line.startswith(("PARO", "READY", "ERR")):
            print(f"   [esp32] {line}")
            if line.startswith("PARO") and state["gestos"]:
                state["gestos"].parar()

    if args.simular:
        args.audio = "pc"
    elif not args.audio:
        print("¿Dónde quieres que suene la voz?")
        print("  1) bocina de la ESP32")
        print("  2) compu (bocinas o audífonos)")
        print("  3) las dos")
        r = input("Elige 1, 2 o 3 [1]: ").strip()
        args.audio = {"2": "pc", "3": "ambos"}.get(r, "esp")
    bol = FakeBolita(salida=args.bocina) if args.simular else Bolita(args.port, on_line=on_line, audio=args.audio, salida=args.bocina, excluir=args.uno)
    if not args.simular:
        print(f"ESP32 en {bol.port}   (si no es, usa --port COMx; --puertos para ver la lista)")
    bol.volume(args.volumen)
    # la TUI muestra la cara actual
    _mood = bol.mood

    def mood(m, *a, **k):
        state["cara"] = MOOD_NAMES[m]
        return _mood(m, *a, **k)

    bol.mood = mood
    try:
        mic_nombre = (sd.query_devices(args.mic) if args.mic is not None else sd.query_devices(kind="input"))["name"]
        sal_nombre = (sd.query_devices(args.bocina) if args.bocina is not None else sd.query_devices(kind="output"))["name"]
    except Exception:
        mic_nombre = sal_nombre = "?"
    sale_por = {"esp": "bocina de la ESP32", "pc": sal_nombre, "ambos": f"ESP32 + {sal_nombre}"}[args.audio]
    print(f"Micrófono: {mic_nombre}")
    print("Voz sale por: " + sale_por)

    # ---- brazo
    uno = None
    if args.brazo == "gestos":
        if args.uno:
            uno = UnoDirecto(args.uno)
            print(f"Brazo: gestos directo al Uno en {args.uno}")
        state["gestos"] = Gestos(uno.arm if uno else bol.arm, eco=lambda *a: print(*a))

    # canal del PCA9685 -> posición en "J base hombro codo muñeca" (igual que BrazoESP.ino)
    JUNTAS = {14: 0, 13: 1, 12: 2, 11: 3}
    VEL_VOZ = 60  # °/s al mover una articulación por voz (suave)

    def servo(canal, angulo):
        """Orden por voz: "mueve el codo a 120" -> J -1 -1 120 -1 (suave, a VEL_VOZ °/s).
        Un canal que no es articulación (pinza 10, 15...) se manda con T (prueba cruda, instantáneo)."""
        if canal in JUNTAS:
            v = [-1] * 4
            v[JUNTAS[canal]] = angulo
            cmds = [f"V {VEL_VOZ}", "J " + " ".join(map(str, v))]
        else:
            cmds = [f"T {canal} {angulo}"]
        if state["brazo"] == "no":
            print(f"   [brazo] (apagado) {cmds[-1]}")
            return
        if state["gestos"]:
            state["gestos"].parar()
        for c in cmds:
            (uno.arm if uno else bol.arm)(c)
        print(f"   [brazo] {cmds[-1]}   (se queda ahí)")

    def brazo(rutina, repetir=False, esperar=False):
        """Mueve el brazo según el modo elegido. esperar=True: regresa cuando termina el gesto."""
        if state["brazo"] == "no" or not rutina:
            return
        if state["gestos"]:
            if esperar:
                state["estado"] = "brazo"
            state["gestos"].hacer(rutina, repetir=repetir, esperar=esperar)
            if esperar:
                while not q.empty():  # descarta lo que oyó el micrófono mientras se movían los servos
                    q.get_nowait()
        else:
            bol.arm(rutina)  # rutinas de Arm.h: la ESP las corre sola

    words = None
    if not args.sin_palabras:
        modelo = buscar_modelo(args.vosk)
        try:
            if not modelo:
                raise FileNotFoundError("no está pc/modelos/vosk-model-small-es-0.42")
            print("Cargando Vosk (palabras)...")
            words = Words(modelo)
        except Exception as e:  # sin vosk o sin modelo: solo repite
            print(f"⚠ Sin reconocimiento de palabras ({e}). Solo va a repetir.")
            print("  Para activarlo: py -3.12 -m pip install vosk")
    faltan = []
    if words:
        faltan = [n for n, _ in respuestas.todas() if not respuestas.archivos(n)]
        print(f"Respuestas grabadas: {len(respuestas.todas()) - len(faltan)} de {len(respuestas.todas())}"
              + (f"  (faltan: {', '.join(faltan)} -> py -3.12 grabar.py <nombre>)" if faltan else ""))

    if args.guardar:
        os.makedirs(args.guardar, exist_ok=True)
        import soundfile as sf

    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata[:, 0].copy())

    stream = sd.InputStream(samplerate=FS, channels=1, blocksize=BLOCK, dtype="float32", device=args.mic, callback=cb)
    stream.start()

    # ---- TUI
    pantalla = None
    terminal = None
    if not args.sin_tui:
        from tui_brazo import Terminal, leer_tecla

        info = f"ESP32 {bol.port} · mic: {mic_nombre} · voz sale por: {sale_por}"
        if uno:
            info += f" · Uno {args.uno}"
        pantalla = Pantalla(state, info)
        if faltan:
            pantalla.mensaje(f"Faltan grabar: {', '.join(faltan)}  (py -3.12 grabar.py <nombre>)")
        terminal = Terminal().__enter__()
        pantalla.empieza()

        def teclas():
            while not state["salir"]:
                k = leer_tecla()
                if k is None:
                    time.sleep(0.03)
                    continue
                if k in ("q", "\x03"):
                    state["salir"] = True
                elif k == "1":
                    state["manual"].put("inicio")
                elif k == "2":
                    state["manual"].put("te gusta")
                elif k == "3":
                    state["manual"].put("baila")
                elif k == "v":
                    siguiente_voz()
                elif k == "p":
                    state["modo_ptt"] = not state["modo_ptt"]
                elif k == "k":
                    state["kalman"] = not state["kalman"]
                elif k == "r":
                    state["no_repetir"] = not state["no_repetir"]
                elif k == "m":
                    state["mover_antes"] = not state["mover_antes"]
                elif k == "b":
                    state["brazo"] = "no" if state["brazo"] != "no" else brazo_original
                    if state["brazo"] == "no" and state["gestos"]:
                        state["gestos"].parar()
                elif k in ("+", "-"):
                    state["volumen"] = int(np.clip(state["volumen"] + (10 if k == "+" else -10), 0, 255))
                    bol.volume(state["volumen"])

        threading.Thread(target=teclas, daemon=True).start()

    # ---- calibración del ruido
    state["estado"] = "calibrando"
    print("Calibrando ruido... quédate callado 2 segundos")
    bol.mood(SLEEPY, 0.4)
    cal = [q.get() for _ in range(int(2 * FS / BLOCK))][10:]  # descarta el arranque
    cal = np.concatenate(cal)
    noise_var = dsp.estimate_noise_var(cal)
    noise_db = float(np.median([dsp.rms_db(b) for b in cal.reshape(-1, BLOCK)]))
    thr = max(noise_db + 12, -55)
    state["umbral"] = thr
    print(f"Ruido: {noise_db:.1f} dBFS  ->  umbral de voz {thr:.1f} dBFS")
    if args.sin_tui:
        print(f"Voz: {state['voz']}  |  Kalman: {'sí' if state['kalman'] else 'no'}  |  Ctrl+C para salir")
        print("Mantén FUNCTION en la bolita mientras hablas y suéltalo al terminar.\n" if state["modo_ptt"]
              else "Habla cuando quieras: detecta tu voz sola.\n")
    bol.mood(NEUTRAL)
    state["estado"] = "esperando"

    pre = deque(maxlen=15)  # 300 ms antes de que empiece la voz
    rec, f0s, dbs = [], [], []
    recording, above = False, 0
    last_voice = last_mood_t = 0.0
    live_mood = None
    n_frase = 0
    clock = 0.0  # reloj de audio (segundos de micrófono procesados)
    base_f0 = 0.0  # tu tono normal; se aprende con cada frase (agudo/grave es relativo a él)

    def anota(n, texto, ok, detalle):
        if pantalla:
            pantalla.frase(n, texto, ok, detalle)
        else:
            print(f'#{n} "{texto}"  {detalle}')

    def esperar_audio(restante):
        """Espera a que termine de sonar; se corta si presionas FUNCTION."""
        t_end = time.time() + restante
        bol.wait_done(restante + 2.0)
        # si presionas FUNCTION mientras habla, la ESP32 se calla y te escucha de inmediato
        while time.time() < t_end and not state["ptt"] and not state["salir"]:
            time.sleep(0.02)
        if not state["ptt"]:
            time.sleep(0.3)
        while not q.empty():  # descarta lo que oyó el micrófono mientras sonaba la bocina
            q.get_nowait()

    def cantar():
        state["cantar"] = False
        state["estado"] = "cantando"
        print("🎵 cantando")
        bol.mood(HAPPY, 1.0)
        brazo("baile", repetir=True)  # baila todo lo que dura la canción
        esperar_audio(bol.play(dsp.to_int16(cancion_bolita()), stop=lambda: state["ptt"]))
        if state["gestos"]:
            state["gestos"].parar()  # termina el baile y regresa a la casa
        bol.mood(NEUTRAL)
        state["estado"] = "esperando"

    def responder(texto, repetir_audio=None):
        """Busca una respuesta para el texto y la ejecuta: brazo (primero, si mover_antes) y luego la frase.
        repetir_audio: lo que dijiste ya filtrado (para repetirte si no hay respuesta); None = no repetir.
        Regresa (audio a decir o None, cara, intensidad, cara_después, rutina_hecha)."""
        talk_mood, talk_int, after_mood = HAPPY, 0.7, NEUTRAL
        hallado = respuestas.buscar(texto) if texto else None
        if not hallado:
            return None, talk_mood, talk_int, after_mood, False
        nombre, _, cara, rutina = hallado
        talk_mood, talk_int = cara, 1.0
        if cara == SLEEPY:
            after_mood = SLEEPY
        hecha = False
        if rutina == "CANTA":
            state["cantar"] = True
        elif rutina == "VOZ":
            siguiente_voz()
        elif rutina:
            if state["mover_antes"]:
                bol.mood(cara, 1.0)
                brazo(rutina, esperar=True)  # primero el brazo...
            else:
                brazo(rutina)  # ...o al mismo tiempo que habla
            hecha = True
        contestar = respuestas.cargar(nombre) if nombre else None
        if nombre and contestar is None:
            print(f"(falta grabar la respuesta '{nombre}': py -3.12 grabar.py {nombre})")
        return contestar, talk_mood, talk_int, after_mood, hecha

    def hablar(audio, cara, intensidad, despues):
        state["estado"] = "hablando"
        bol.mood(cara, intensidad)
        esperar_audio(bol.play(dsp.to_int16(audio), stop=lambda: state["ptt"]))
        bol.mood(despues)
        state["estado"] = "esperando"

    try:
        while not state["salir"]:
            try:
                b = q.get(timeout=0.5)
            except queue.Empty:
                continue
            if state["cantar"] and not recording:
                cantar()
                continue
            if not recording and not state["manual"].empty():  # tecla 1 / 2 / 3: como si lo dijeras
                texto = state["manual"].get()
                n_frase += 1
                contestar, cara, inten, despues, _ = responder(texto)
                h = respuestas.buscar(texto)
                anota(n_frase, texto + " (tecla)", True, f"→ {h[0] or h[3]}  brazo: {h[3]}")
                if state["cantar"]:
                    if contestar is not None:  # "¡A bailar se ha dicho!" y luego la canción
                        hablar(dsp.voice_effect(contestar, state["voz"]), cara, inten, HAPPY)
                    cantar()
                elif contestar is not None:
                    hablar(dsp.voice_effect(contestar, state["voz"]), cara, inten, despues)
                state["estado"] = "esperando"
                continue
            db = dsp.rms_db(b)
            state["db"] = db
            clock += BLOCK / FS
            now = clock
            modo_ptt = state["modo_ptt"]

            if not recording:
                pre.append(b)
                above = above + 1 if db > thr else 0
                if (state["ptt"] if modo_ptt else above >= 3):
                    recording, rec, f0s, dbs = True, list(pre), [], []
                    last_voice = now
                    live_mood = None
                    state["estado"] = "escuchando"
                    if not pantalla:
                        print("🎤 escuchando...")
                continue

            # ---- grabando
            rec.append(b)
            dbs.append(db)
            if db > thr:
                last_voice = now
                f0 = dsp.pitch_hz(b)
                if f0 > 0:
                    f0s.append(f0)
                    bol.look(0.4 * np.sin(now * 3), -np.clip((f0 - 180) / 150, -1, 1))

            # cara en vivo según cómo hablas (cada 250 ms)
            if now - last_mood_t > 0.25:
                last_mood_t = now
                recent_db = max(dbs[-12:]) if dbs else -99
                recent_f0 = np.median(f0s[-10:]) if f0s else 0
                if recent_db > max(noise_db + 38, -14):
                    m = SURPRISED  # gritaste
                elif base_f0 and recent_f0 > 1.3 * base_f0:
                    m = HAPPY  # voz más aguda que tu normal
                elif base_f0 and 0 < recent_f0 < 0.82 * base_f0:
                    m = ANGRY  # voz más grave que tu normal
                else:
                    m = LISTEN
                if m != live_mood:
                    bol.mood(m, 0.8)
                    live_mood = m

            dur = len(rec) * BLOCK / FS
            if modo_ptt:
                if state["ptt"] and dur < 12:  # sigue mantenido (máximo 12 s)
                    continue
            elif now - last_voice < 0.7 and dur < 6:
                continue

            # ---- terminó la frase: procesar
            recording, above = False, 0
            pre.clear()
            state["estado"] = "pensando"
            hubo_voz = any(d > thr for d in dbs)
            if dur < 0.45 or not hubo_voz or state["cancel"]:
                if modo_ptt and not state["cancel"]:
                    print("(no te oí: habla mientras mantienes FUNCTION)" if dur >= 0.45 else "(muy corto)")
                state["cancel"] = False
                bol.mood(NEUTRAL)
                state["estado"] = "esperando"
                continue
            n_frase += 1
            audio = np.concatenate(rec)
            trim = int(max(0.0, now - last_voice - 0.15) * FS)  # quita el silencio final
            audio = audio[: len(audio) - trim]

            t0 = time.time()
            clean = dsp.kalman_denoise(audio, noise_var=noise_var) if state["kalman"] else audio
            t_k = time.time() - t0

            talk_mood, talk_int = HAPPY, 0.7
            max_db = max(dbs) if dbs else -99
            med_f0 = float(np.median(f0s)) if f0s else 0
            if max_db > max(noise_db + 38, -14):
                talk_mood, talk_int = SURPRISED, 0.8
            elif base_f0 and 0 < med_f0 < 0.82 * base_f0:
                talk_mood, talk_int = ANGRY, 0.6
            if med_f0 > 0:
                base_f0 = med_f0 if not base_f0 else 0.8 * base_f0 + 0.2 * med_f0
            after_mood = NEUTRAL

            rutina_hecha = False
            text = ""
            contestar = None  # audio de la respuesta grabada (None = te repite)
            if words:
                text = words.recognize(audio)  # Vosk entiende mejor el audio original que el filtrado
                orden = servo_voz.buscar(text)
                if orden:  # "mueve el codo a ciento veinte": mueve ese servo y no habla
                    anota(n_frase, text, True, f"→ servo {orden[0]} a {orden[1]}°")
                    servo(*orden)
                    bol.mood(HAPPY, 0.8, 1.5)
                    state["estado"] = "esperando"
                    continue
                hallado = respuestas.buscar(text)
                if hallado:
                    nombre, _, _, rutina = hallado
                    falta = "" if not nombre or respuestas.archivos(nombre) else f"  {AMARILLO}(falta grabar '{nombre}'){FIN}"
                    anota(n_frase, text, True, f"→ {nombre or rutina}  brazo: {rutina or '-'}{falta}")
                    contestar, talk_mood, talk_int, after_mood, rutina_hecha = responder(text)
                else:
                    anota(n_frase, text, False if text else None,
                          "no entendí" if state["no_repetir"] else "→ te repite")
                    if state["no_repetir"]:
                        contestar = respuestas.cargar(respuestas.NO_ENTENDI[0])
                        talk_mood, talk_int = SAD, 0.5
                        if contestar is None:  # tampoco está grabado "no entendí": solo pone cara
                            bol.mood(SAD, 0.6, 1.5)
                            state["estado"] = "esperando"
                            continue
            else:
                anota(n_frase, "", None, "→ te repite (sin Vosk)")
            if not rutina_hecha and talk_mood == SURPRISED:
                brazo("susto")  # si le gritas, el brazo se echa para atrás

            out = dsp.voice_effect(clean if contestar is None else contestar, state["voz"])
            info = f"#{n_frase} {dur:.1f}s  tono {med_f0:.0f} Hz  máx {max_db:.0f} dB  kalman {t_k*1000:.0f} ms  voz {state['voz']}"
            if not pantalla:
                info += f'  "{text}"' + ("  -> repite" if contestar is None else "  -> contesta")
            print(info)

            if args.guardar:
                base = os.path.join(args.guardar, f"frase{n_frase:03d}")
                sf.write(base + "_1_original.wav", audio, FS)
                sf.write(base + "_2_kalman.wav", clean, FS)
                sf.write(base + "_3_efecto.wav", out, FS)

            if state["cantar"]:  # le dijiste "canta" o "baila": en lugar de repetirte, canta y baila
                if contestar is not None:  # "¡A bailar se ha dicho!" y luego la canción
                    hablar(out, talk_mood, talk_int, HAPPY)
                cantar()
                continue
            hablar(out, talk_mood, talk_int, after_mood)

    except KeyboardInterrupt:
        pass
    finally:
        state["salir"] = True
        if pantalla:
            pantalla.termina()
            terminal.__exit__(None, None, None)
        print("Adiós 👋")
        stream.stop()
        if state["gestos"]:
            state["gestos"].parar()
        bol.close()
        if uno:
            uno.close()


if __name__ == "__main__":
    sys.exit(main())
