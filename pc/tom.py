"""
Talking Bolita — programa principal (corre en la computadora).

    python tom.py                 # busca la ESP32 sola
    python tom.py --port COM5     # o /dev/ttyUSB0, /dev/cu.usbserial-xxxx
    python tom.py --simular       # sin ESP32: suena en la compu e imprime las caras
    python tom.py --puertos       # lista puertos seriales
    python tom.py --mics          # lista micrófonos
    python tom.py --auto          # escucha sola (sin el botón Function)
    python tom.py --audio esp     # la voz sale por la bocina de la ESP32 (pc = compu, ambos = las dos)
                                  # sin --audio te pregunta al arrancar
    python tom.py --brazo rutinas # rutinas completas de Arm.h (por defecto: gestos sencillos con T)
    python tom.py --uno COM7      # gestos directo al Arduino Uno por USB, sin pasar por la ESP32

Audio: por defecto el micrófono y las bocinas son los PREDETERMINADOS de Windows. Si conectas
audífonos Bluetooth, Windows los pone solos y el programa los usa. --mic N / --bocina N para elegir.

Flujo: mantienes FUNCTION en la ESP32 -> graba mientras lo mantienes -> filtro de Kalman
       -> Vosk reconoce las palabras -> si hay una palabra de respuestas.py contesta con su frase
       grabada (grabar.py) y mueve el brazo; si no, te repite (o con --no-repetir dice "no entendí") -> (palabras con Vosk, opcional:
       mueven el brazo) -> efecto de voz -> la ESP32 lo reproduce mientras la cara "habla".
"""
import argparse
import json
import os
import queue
import sys
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
    ap.add_argument("--brazo", default="gestos", choices=["gestos", "rutinas", "no"], help="gestos: mueve 1-2 servos con T y regresa | rutinas: las de Arm.h | no: no mover")
    ap.add_argument("--uno", help="puerto del Arduino Uno para mandarle los gestos directo por USB (sin la ESP32)")
    args = ap.parse_args()

    if args.puertos:
        for dev, desc in list_ports():
            print(f"{dev:20s} {desc}")
        return
    if args.mics:
        print(sd.query_devices())
        return

    ptt = not (args.auto or args.simular)  # push-to-talk: graba solo mientras mantienes FUNCTION
    state = {"voz": args.voz, "ptt": False, "cancel": False, "cantar": False, "gestos": None}

    def siguiente_voz():
        state["voz"] = dsp.VOCES[(dsp.VOCES.index(state["voz"]) + 1) % len(dsp.VOCES)]
        print(f"   [voz] {state['voz']}")

    def aviso_ptt():
        if not state["ptt"]:
            print("   ⚠ Presionaste Function pero la bolita no empezó a escuchar: ¿está en PAUSA o en el menú?")
            print("     (Mode -> 'Reanudar', o mantén Mode para regresar a la cara)")

    def on_line(line):
        if line == "BTN FUNC":
            import threading

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
    try:
        mic_nombre = (sd.query_devices(args.mic) if args.mic is not None else sd.query_devices(kind="input"))["name"]
        sal_nombre = (sd.query_devices(args.bocina) if args.bocina is not None else sd.query_devices(kind="output"))["name"]
    except Exception:
        mic_nombre = sal_nombre = "?"
    print(f"Micrófono: {mic_nombre}")
    print("Voz sale por: " + {"esp": "bocina de la ESP32", "pc": sal_nombre, "ambos": f"bocina de la ESP32 + {sal_nombre}"}[args.audio])

    # ---- brazo
    uno = None
    if args.brazo == "gestos":
        if args.uno:
            uno = UnoDirecto(args.uno)
            print(f"Brazo: gestos directo al Uno en {args.uno}")
        state["gestos"] = Gestos(uno.arm if uno else bol.arm)

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
        if args.brazo == "no":
            print(f"   [brazo] (apagado con --brazo no) {cmds[-1]}")
            return
        if state["gestos"]:
            state["gestos"].parar()
        for c in cmds:
            (uno.arm if uno else bol.arm)(c)
        print(f"   [brazo] {cmds[-1]}   (se queda ahí)")

    def brazo(rutina):
        """Mueve el brazo según el modo elegido con --brazo."""
        if args.brazo == "no" or not rutina:
            return
        if state["gestos"]:
            state["gestos"].hacer(rutina)
        else:
            bol.arm(rutina)

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
    if words:
        grabadas = [n for n, _ in respuestas.todas() if respuestas.archivos(n)]
        print(f"Respuestas grabadas: {len(grabadas)} de {len(respuestas.todas())}  (graba las demás con grabar.py)")

    if args.guardar:
        os.makedirs(args.guardar, exist_ok=True)
        import soundfile as sf

    q = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(indata[:, 0].copy())

    stream = sd.InputStream(samplerate=FS, channels=1, blocksize=BLOCK, dtype="float32", device=args.mic, callback=cb)
    stream.start()

    # ---- calibración del ruido
    print("Calibrando ruido... quédate callado 2 segundos")
    bol.mood(SLEEPY, 0.4)
    cal = [q.get() for _ in range(int(2 * FS / BLOCK))][10:]  # descarta el arranque
    cal = np.concatenate(cal)
    noise_var = dsp.estimate_noise_var(cal)
    noise_db = float(np.median([dsp.rms_db(b) for b in cal.reshape(-1, BLOCK)]))
    thr = max(noise_db + 12, -55)
    print(f"Ruido: {noise_db:.1f} dBFS  ->  umbral de voz {thr:.1f} dBFS")
    print(f"Voz: {state['voz']}  |  Kalman: {'no' if args.sin_kalman else 'sí'}  |  Ctrl+C para salir")
    if ptt:
        print("Mantén FUNCTION en la bolita mientras hablas y suéltalo al terminar.\n")
    else:
        print("Habla cuando quieras: detecta tu voz sola.\n")
    bol.mood(NEUTRAL)

    pre = deque(maxlen=15)  # 300 ms antes de que empiece la voz
    rec, f0s, dbs = [], [], []
    recording, above = False, 0
    last_voice = last_mood_t = 0.0
    live_mood = None
    n_frase = 0
    clock = 0.0  # reloj de audio (segundos de micrófono procesados)
    base_f0 = 0.0  # tu tono normal; se aprende con cada frase (agudo/grave es relativo a él)

    def esperar_audio(restante):
        """Espera a que termine de sonar; se corta si presionas FUNCTION."""
        t_end = time.time() + restante
        bol.wait_done(restante + 2.0)
        # si presionas FUNCTION mientras habla, la ESP32 se calla y te escucha de inmediato
        while time.time() < t_end and not state["ptt"]:
            time.sleep(0.02)
        if not state["ptt"]:
            time.sleep(0.3)
        while not q.empty():  # descarta lo que oyó el micrófono mientras sonaba la bocina
            q.get_nowait()

    def cantar():
        state["cantar"] = False
        print("🎵 cantando")
        bol.mood(HAPPY, 1.0)
        brazo("baile")
        esperar_audio(bol.play(dsp.to_int16(cancion_bolita()), stop=lambda: state["ptt"]))
        bol.mood(NEUTRAL)

    try:
        while True:
            b = q.get()
            if state["cantar"] and not recording:
                cantar()
                continue
            db = dsp.rms_db(b)
            clock += BLOCK / FS
            now = clock

            if not recording:
                pre.append(b)
                above = above + 1 if db > thr else 0
                if (state["ptt"] if ptt else above >= 3):
                    recording, rec, f0s, dbs = True, list(pre), [], []
                    last_voice = now
                    live_mood = None
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
            if ptt:
                if state["ptt"] and dur < 12:  # sigue mantenido (máximo 12 s)
                    continue
            elif now - last_voice < 0.7 and dur < 6:
                continue

            # ---- terminó la frase: procesar
            recording, above = False, 0
            pre.clear()
            hubo_voz = any(d > thr for d in dbs)
            if dur < 0.45 or not hubo_voz or state["cancel"]:
                if ptt and not state["cancel"]:
                    print("   (no te oí: habla mientras mantienes FUNCTION)" if dur >= 0.45 else "   (muy corto)")
                state["cancel"] = False
                bol.mood(NEUTRAL)
                continue
            n_frase += 1
            audio = np.concatenate(rec)
            trim = int(max(0.0, now - last_voice - 0.15) * FS)  # quita el silencio final
            audio = audio[: len(audio) - trim]

            t0 = time.time()
            clean = audio if args.sin_kalman else dsp.kalman_denoise(audio, noise_var=noise_var)
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
                if orden:  # "prueba el servo diez a veinte grados": mueve ese servo y no habla
                    print(f'#{n_frase} "{text}"  -> servo {orden[0]} a {orden[1]}°')
                    servo(*orden)
                    bol.mood(HAPPY, 0.8, 1.5)
                    continue
                hallado = respuestas.buscar(text)
                if hallado:
                    nombre, _, cara, rutina = hallado
                    talk_mood, talk_int = cara, 1.0
                    if cara == SLEEPY:
                        after_mood = SLEEPY
                    if rutina == "CANTA":
                        state["cantar"] = True
                    elif rutina == "VOZ":
                        siguiente_voz()
                    elif rutina:
                        brazo(rutina)
                        rutina_hecha = True
                    contestar = respuestas.cargar(nombre)
                    if nombre and contestar is None:
                        print(f"   (falta grabar la respuesta '{nombre}': py -3.12 grabar.py {nombre})")
                elif args.no_repetir:
                    contestar = respuestas.cargar(respuestas.NO_ENTENDI[0])
                    talk_mood, talk_int = SAD, 0.5
                    if contestar is None:  # tampoco está grabado "no entendí": solo pone cara
                        print(f'   #{n_frase} "{text}"  (no entendí)')
                        bol.mood(SAD, 0.6, 1.5)
                        continue
            if not rutina_hecha and talk_mood == SURPRISED:
                brazo("susto")  # si le gritas, el brazo se echa para atrás

            out = dsp.voice_effect(clean if contestar is None else contestar, state["voz"])
            info = f"#{n_frase} {dur:.1f}s  tono {med_f0:.0f} Hz  máx {max_db:.0f} dB  kalman {t_k*1000:.0f} ms  voz {state['voz']}"
            if words:
                info += f'  "{text}"' + ("  -> repite" if contestar is None else "  -> contesta")
            print(info)

            if args.guardar:
                base = os.path.join(args.guardar, f"frase{n_frase:03d}")
                sf.write(base + "_1_original.wav", audio, FS)
                sf.write(base + "_2_kalman.wav", clean, FS)
                sf.write(base + "_3_efecto.wav", out, FS)

            if state["cantar"]:  # le dijiste "canta": en lugar de repetirte, canta
                cantar()
                continue
            bol.mood(talk_mood, talk_int)
            esperar_audio(bol.play(dsp.to_int16(out), stop=lambda: state["ptt"]))
            bol.mood(after_mood)

    except KeyboardInterrupt:
        print("\nAdiós 👋")
    finally:
        stream.stop()
        if state["gestos"]:
            state["gestos"].parar()
        bol.close()
        if uno:
            uno.close()


if __name__ == "__main__":
    sys.exit(main())
