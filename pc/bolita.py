"""Cliente serial para hablar con la ESP32 (mismo protocolo que TalkingBolita.ino)."""
import struct
import threading
import time

import numpy as np
import serial
import serial.tools.list_ports

NEUTRAL, LISTEN, HAPPY, SURPRISED, ANGRY, SAD, SLEEPY, OUCH = range(8)
MOOD_NAMES = ["neutral", "escuchando", "feliz", "sorpresa", "enojado", "triste", "dormido", "auch"]


def list_ports():
    return [(p.device, p.description) for p in serial.tools.list_ports.comports()]


def guess_port(excluir=None):
    """Adivina el puerto de la ESP32. excluir: puerto que NO es la ESP (p. ej. el del Uno).
    Prefiere el chip de la ESP (CH343 / CP210x / ESP32) sobre el típico de un Uno (CH340 / "Arduino")."""
    excluir = (excluir or "").upper()
    ports = [(dev, desc.lower()) for dev, desc in list_ports()
             if "bluetooth" not in desc.lower() and dev.upper() != excluir]
    for claves in (("ch343", "cp210", "esp32", "jtag", "enhanced"),
                   ("usb serial", "usb-serial", "serie usb", "uart", "ch34")):
        for dev, d in ports:
            if "arduino" not in d and any(k in d for k in claves):
                return dev
    return ports[0][0] if ports else None


class Bolita:
    def __init__(self, port=None, baud=460800, on_line=None, audio="esp", salida=None, excluir=None):  # baud = SERIAL_BAUD en Config.h
        """audio: dónde suena la voz.
            "esp"   = bocina de la ESP32
            "pc"    = bocinas/audífonos de la compu (la ESP32 en silencio, pero igual recibe el
                      audio para mover la boca)
            "ambos" = en las dos al mismo tiempo
        salida: índice del dispositivo de salida de la compu (None = el predeterminado de Windows)."""
        self.audio_pc = audio in ("pc", "ambos")
        self.esp_suena = audio in ("esp", "ambos")
        self.salida = salida
        port = port or guess_port(excluir)
        if not port:
            raise RuntimeError("No encontré la ESP32. Conéctala y usa --port (ej. COM5 o /dev/ttyUSB0)")
        self.port = port
        # DTR/RTS en falso antes de abrir: así la placa no se reinicia ni entra en modo de carga
        self.ser = serial.Serial(None, baud, timeout=0.1, write_timeout=5)
        self.ser.port = port
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        self.on_line = on_line
        self.done_event = threading.Event()
        self._lock = threading.Lock()
        self._alive = True
        threading.Thread(target=self._reader, daemon=True).start()
        time.sleep(1.5)

    # ---------------- envío ----------------
    def _frame(self, t, payload=b""):
        payload = bytes(payload)
        hdr = b"\xA5\x5A" + t.encode() + struct.pack("<H", len(payload))
        with self._lock:
            self.ser.write(hdr + payload + bytes([sum(payload) & 0xFF]))

    def mood(self, m, intensity=1.0, hold_s=0.0):
        self._frame("M", [int(m), int(np.clip(intensity, 0, 1) * 255), int(np.clip(hold_s * 10, 0, 127))])

    def look(self, x, y):
        self._frame("L", struct.pack("bb", int(np.clip(x, -1, 1) * 100), int(np.clip(y, -1, 1) * 100)))

    def volume(self, v):
        # si la ESP32 no debe sonar, su bocina va en 0 (el volumen de la compu lo pones en Windows)
        self._frame("V", [int(np.clip(v, 0, 255)) if self.esp_suena else 0])

    def arm(self, text):
        """Orden para el brazo: rutina ("saludo", "baile", "agarrar", "soltar", "susto",
        "si", "no", "inicio") o comando crudo para el Uno ("J 90 120 60 90", "H 100")."""
        self._frame("B", text.encode()[:39])

    def stop_audio(self):
        if self.audio_pc:
            import sounddevice as sd

            sd.stop()
        self._frame("S")

    def ping(self):
        self._frame("P")

    def play(self, samples_int16, chunk=512, stop=None):
        """Manda audio int16 a 16 kHz. Regresa los segundos que le faltan por sonar.
        No lo manda de golpe: al principio a 2x la velocidad real y luego a 1x con 0.5 s de
        ventaja, así no se pierden datos en el serial y caben canciones largas en la ESP32.
        stop: función opcional; si regresa True se corta el audio (p. ej. presionaste Function)."""
        data = np.asarray(samples_int16, dtype="<i2")
        self.done_event.clear()
        if self.audio_pc:  # suena en la compu; a la ESP32 le sigue llegando para mover la boca
            import sounddevice as sd

            sd.play(data / 32767.0, 16000, device=self.salida)
        t0 = time.time()
        for i in range(0, len(data), chunk):
            if stop and stop():
                self.stop_audio()
                return 0.0
            self._frame("A", data[i : i + chunk].tobytes())
            enviado = (i + chunk) / 16000
            esperar = max((enviado - 0.05) / 2, enviado - 0.5) - (time.time() - t0)
            if esperar > 0:
                time.sleep(esperar)
        return max(0.0, len(data) / 16000 - (time.time() - t0))

    def wait_done(self, timeout):
        return self.done_event.wait(timeout)

    # ---------------- recepción ----------------
    def _reader(self):
        buf = b""
        while self._alive:
            try:
                buf += self.ser.read(256)
            except serial.SerialException:
                break
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode(errors="ignore").strip()
                if not text:
                    continue
                if text == "DONE":
                    self.done_event.set()
                if self.on_line:
                    self.on_line(text)

    def close(self):
        self._alive = False
        time.sleep(0.15)
        self.ser.close()
