"""
Talking Bolita — programa principal (corre en la computadora).

    python tom.py                 # busca la ESP32 sola
    python tom.py --port COM5     # o /dev/ttyUSB0, /dev/cu.usbserial-xxxx
    python tom.py --simular       # sin ESP32: suena en la compu e imprime las caras
    python tom.py --puertos       # lista puertos seriales
    python tom.py --mics          # lista micrófonos

Flujo: escucha -> detecta voz -> graba -> filtro de Kalman -> (palabras con Vosk, opcional:
       mueven el brazo) -> efecto de voz -> la ESP32 lo reproduce mientras la cara "habla".
"""
import argparse
import json
import os
import queue
import re
import sys
import time
import unicodedata
from collections import deque

import numpy as np
import sounddevice as sd

import dsp
from bolita import ANGRY, HAPPY, LISTEN, MOOD_NAMES, NEUTRAL, SAD, SLEEPY, SURPRISED, Bolita, list_ports

FS = dsp.FS
BLOCK = 320  # 20 ms


# ---------------------------------------------------------------- modo simulación
class FakeBolita:
    """Igual que Bolita pero sin hardware: imprime las caras y suena en la compu."""

    def __init__(self, on_line=None):
        self._m = None

    def mood(self, m, intensity=1.0, hold_s=0.0):
        if m != self._m:
            print(f"   [cara] {MOOD_NAMES[m]} ({intensity:.1f})")
            self._m = m

    def look(self, x, y):
        pass

    def volume(self, v):
        pass

    def arm(self, text):
        print(f"   [brazo] {text}")

    def stop_audio(self):
        sd.stop()

    def play(self, samples_int16, chunk=512):
        sd.play(np.asarray(samples_int16) / 32767.0, FS)
        return len(samples_int16) / FS

    def wait_done(self, timeout):
        sd.wait()
        return True

    def close(self):
        pass


# ---------------------------------------------------------------- palabras (Vosk, opcional)
def normalize(text):
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


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


# (expresión regular, cara, rutina del brazo o None). Se usa la primera que coincida.
KEYWORDS = [
    (r"\b(otra voz|cambia (la )?voz)\b", None, None),  # cambia la voz
    (r"\b(saluda|saludame|hola)\b", HAPPY, "saludo"),
    (r"\b(baila|bailale|fiesta)\b", HAPPY, "baile"),
    (r"\b(estirate|estira|estirado)\b", SURPRISED, "estirar"),
    (r"\b(agarra|toma|recoge)\b", LISTEN, "agarrar"),
    (r"\b(suelta|sueltalo)\b", NEUTRAL, "soltar"),
    (r"\b(inicio|quieto|alto|detente)\b", NEUTRAL, "inicio"),
    (r"\b(bu|susto|cuidado)\b", SURPRISED, "susto"),
    (r"\b(duermete|a dormir|buenas noches)\b", SLEEPY, "inicio"),
    (r"\b(tonto|feo|fea|tonta)\b", SAD, "no"),
    (r"\b(enojate|enojado|grr+)\b", ANGRY, "no"),
    (r"\b(te quiero|bonito|bonita|lindo|linda|amigo|verdad)\b", HAPPY, "si"),
]


# ---------------------------------------------------------------- programa
def main():
    ap = argparse.ArgumentParser(description="Talking Bolita")
    ap.add_argument("--port")
    ap.add_argument("--puertos", action="store_true", help="lista puertos seriales")
    ap.add_argument("--mics", action="store_true", help="lista micrófonos")
    ap.add_argument("--mic", type=int, default=None, help="índice del micrófono")
    ap.add_argument("--voz", default="tom", choices=dsp.VOCES)
    ap.add_argument("--sin-kalman", action="store_true")
    ap.add_argument("--vosk", help="carpeta del modelo de Vosk en español (opcional)")
    ap.add_argument("--guardar", help="carpeta donde guardar cada frase (original/kalman/efecto)")
    ap.add_argument("--volumen", type=int, default=200, help="0-255")
    ap.add_argument("--simular", action="store_true", help="sin ESP32")
    args = ap.parse_args()

    if args.puertos:
        for dev, desc in list_ports():
            print(f"{dev:20s} {desc}")
        return
    if args.mics:
        print(sd.query_devices())
        return

    state = {"voz": args.voz}

    def on_line(line):
        if line.startswith(("BTN", "TOUCH", "READY", "ERR")):
            print(f"   [esp32] {line}")

    bol = FakeBolita() if args.simular else Bolita(args.port, on_line=on_line)
    if not args.simular:
        print(f"Conectado a {bol.port}")
    bol.volume(args.volumen)

    words = None
    if args.vosk:
        print("Cargando Vosk...")
        words = Words(args.vosk)

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
    print(f"Voz: {state['voz']}  |  Kalman: {'no' if args.sin_kalman else 'sí'}  |  Ctrl+C para salir\n")
    bol.mood(NEUTRAL)

    pre = deque(maxlen=15)  # 300 ms antes de que empiece la voz
    rec, f0s, dbs = [], [], []
    recording, above = False, 0
    last_voice = last_mood_t = 0.0
    live_mood = None
    n_frase = 0
    clock = 0.0  # reloj de audio (segundos de micrófono procesados)
    base_f0 = 0.0  # tu tono normal; se aprende con cada frase (agudo/grave es relativo a él)

    try:
        while True:
            b = q.get()
            db = dsp.rms_db(b)
            clock += BLOCK / FS
            now = clock

            if not recording:
                pre.append(b)
                above = above + 1 if db > thr else 0
                if above >= 3:
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
            if now - last_voice < 0.7 and dur < 6:
                continue

            # ---- terminó la frase: procesar
            recording, above = False, 0
            pre.clear()
            if dur < 0.45:
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
            if words:
                text = words.recognize(clean)
                norm = normalize(text)
                for pat, mood, rutina in KEYWORDS:
                    if re.search(pat, norm):
                        if mood is None:
                            state["voz"] = dsp.VOCES[(dsp.VOCES.index(state["voz"]) + 1) % len(dsp.VOCES)]
                        else:
                            talk_mood, talk_int = mood, 1.0
                            if mood == SLEEPY:
                                after_mood = SLEEPY
                        if rutina:
                            bol.arm(rutina)
                            rutina_hecha = True
                        break
            if not rutina_hecha and talk_mood == SURPRISED:
                bol.arm("susto")  # si le gritas, el brazo se echa para atrás

            out = dsp.voice_effect(clean, state["voz"])
            info = f"#{n_frase} {dur:.1f}s  tono {med_f0:.0f} Hz  máx {max_db:.0f} dB  kalman {t_k*1000:.0f} ms  voz {state['voz']}"
            if words:
                info += f'  "{text}"'
            print(info)

            if args.guardar:
                base = os.path.join(args.guardar, f"frase{n_frase:03d}")
                sf.write(base + "_1_original.wav", audio, FS)
                sf.write(base + "_2_kalman.wav", clean, FS)
                sf.write(base + "_3_efecto.wav", out, FS)

            bol.mood(talk_mood, talk_int)
            secs = bol.play(dsp.to_int16(out))
            t_end = time.time() + secs
            bol.wait_done(secs + 2.0)
            if t_end > time.time():
                time.sleep(t_end - time.time())
            time.sleep(0.3)
            while not q.empty():  # descarta lo que oyó el micrófono mientras hablaba la bocina
                q.get_nowait()
            bol.mood(after_mood)

    except KeyboardInterrupt:
        print("\nAdiós 👋")
    finally:
        stream.stop()
        bol.close()


if __name__ == "__main__":
    sys.exit(main())
