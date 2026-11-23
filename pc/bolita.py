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


def guess_port():
    for dev, desc in list_ports():
        d = desc.lower()
        if any(k in d for k in ("ch34", "cp210", "usb serial", "usb-serial", "uart", "esp32", "jtag")):
            return dev
    ports = list_ports()
    return ports[0][0] if ports else None


class Bolita:
    def __init__(self, port=None, baud=921600, on_line=None):
        port = port or guess_port()
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
        self._frame("V", [int(np.clip(v, 0, 255))])

    def arm(self, text):
        """Orden para el brazo: rutina ("saludo", "baile", "agarrar", "soltar", "susto",
        "si", "no", "inicio") o comando crudo para el Uno ("J 90 120 60 90", "H 100")."""
        self._frame("B", text.encode()[:39])

    def stop_audio(self):
        self._frame("S")

    def ping(self):
        self._frame("P")

    def play(self, samples_int16, chunk=512):
        """Manda audio int16 a 16 kHz. Regresa la duración en segundos."""
        data = np.asarray(samples_int16, dtype="<i2")
        self.done_event.clear()
        for i in range(0, len(data), chunk):
            self._frame("A", data[i : i + chunk].tobytes())
        return len(data) / 16000

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
