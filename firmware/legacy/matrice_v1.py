# main_matrix.py -- firmware "focus" pour Waveshare ESP32-S3-Matrix
#
# Materiel confirme :
#   ESP32-S3FH4R2, 8x8 WS2812B sur GPIO14
#   QMI8658C (accelerometre + gyro) en I2C, SDA=GPIO11 SCL=GPIO12, adresse 0x6B
#
# Le calcul des degrades est identique, ligne pour ligne, a celui de
# simulateur-matrice.html. Ce que tu regles dans le simulateur est ce que tu
# obtiens ici -- c'est tout l'interet d'avoir les deux.
#
# Protocole serie : inchange depuis la v1.
#   RRGGBB,mode\n   ou, mieux ici, STATE:deep|working|free|offline[,progress]\n
#   PING\n
# focus_agent.py fonctionne sans modification : les couleurs hexa connues sont
# retraduites en etats (voir hex_to_state).

import math
import select
import sys
import time

import neopixel
from machine import I2C, Pin

# ---------------------------------------------------------------- reglages
# (recopies depuis le panneau "Constantes a recopier" du simulateur)

MAX_BRIGHTNESS = 0.14  # PLAFOND DUR. Voir la note de consommation plus bas.
SPEED = 1.00
BREATH_AMOUNT = 0.45
SHOW_RING = True
MAPPING = "row"  # "row" ou "snake" -- a determiner avec le chenillard

GAMMA = 2.2
N = 8
PIN_MATRIX = 14
WATCHDOG_S = 30
FRAME_MS = 33  # ~30 fps ; une trame WS2812 de 64 LED prend ~1,9 ms

# ATTENTION CONSOMMATION
# 64 LED en blanc plein = ~3,8 A. Un port USB en fournit 0,5.
# A 0.14 et sur des couleurs monochromes, on reste vers 150-250 mA.
# Ne monte pas MAX_BRIGHTNESS au-dela de ~0.25 : brown-out, et la carte,
# minuscule, n'evacue pas la chaleur de 64 LED.

STATES = {
    "deep": {
        "ramp": ((18, 0, 0), (168, 12, 8), (255, 58, 26)),
        "field": "vertical",
        "breathe": 9.0,
    },
    "working": {
        "ramp": ((22, 9, 0), (170, 70, 0), (255, 150, 38)),
        "field": "diagonal",
        "breathe": 7.0,
    },
    "free": {
        "ramp": ((0, 12, 4), (0, 74, 28), (26, 150, 66)),
        "field": "horizontal",
        "breathe": 12.0,
    },
    "offline": {
        "ramp": ((0, 0, 0), (8, 9, 11), (18, 20, 24)),
        "field": "radial",
        "breathe": 0,
    },
}

# Retro-compatibilite avec focus_agent.py, qui envoie encore des couleurs hexa
HEX_TO_STATE = {
    "FF0000": "deep",
    "FF5A00": "working",
    "00FF00": "free",
    "000000": "offline",
}

np = neopixel.NeoPixel(Pin(PIN_MATRIX), N * N)


# ---------------------------------------------------------------- degrades


def _clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def ramp(stops, t):
    """Interpolation dans une rampe a 3 arrets. t sur 0..1."""
    t = _clamp(t, 0.0, 1.0)
    seg = 0 if t < 0.5 else 1
    k = t * 2 if t < 0.5 else (t - 0.5) * 2
    a, b = stops[seg], stops[seg + 1]
    return (
        a[0] + (b[0] - a[0]) * k,
        a[1] + (b[1] - a[1]) * k,
        a[2] + (b[2] - a[2]) * k,
    )


def field(kind, x, y, t):
    """Champ spatial : 0..1 pour le pixel (x, y) a l'instant t."""
    u = x / (N - 1)
    v = y / (N - 1)
    if kind == "vertical":
        return _clamp(1 - v + 0.14 * math.sin(t * 0.9 + u * 2.4), 0.0, 1.0)
    if kind == "diagonal":
        return ((u + v) / 2 + t * 0.06) % 1
    if kind == "horizontal":
        return _clamp(u + 0.12 * math.sin(t * 0.7 + v * 1.8), 0.0, 1.0)
    if kind == "radial":
        d = math.sqrt((u - 0.5) ** 2 + (v - 0.5) ** 2) / 0.707
        return _clamp(1 - d, 0.0, 1.0)
    return 0.0


def rotate(x, y, deg):
    m = N - 1
    if deg == 90:
        return y, m - x
    if deg == 180:
        return m - x, m - y
    if deg == 270:
        return m - y, x
    return x, y


def led_index(x, y):
    if MAPPING == "snake":
        return y * N + ((N - 1 - x) if (y % 2) else x)
    return y * N + x


def _build_ring():
    r = []
    for x in range(N):
        r.append((x, 0))
    for y in range(1, N):
        r.append((N - 1, y))
    for x in range(N - 2, -1, -1):
        r.append((x, N - 1))
    for y in range(N - 2, 0, -1):
        r.append((0, y))
    return r


RING = _build_ring()


def draw(state, t, progress=1.0, rot=0):
    st = STATES.get(state, STATES["offline"])

    breath = 1.0
    if st["breathe"] > 0 and BREATH_AMOUNT > 0:
        p = (t % st["breathe"]) / st["breathe"]
        w = 0.5 - 0.5 * math.cos(2 * math.pi * p)
        breath = 1 - BREATH_AMOUNT * (1 - w) * 0.45
    gain = (MAX_BRIGHTNESS * breath) ** GAMMA

    for y in range(N):
        for x in range(N):
            rx, ry = rotate(x, y, rot)
            c = ramp(st["ramp"], field(st["field"], rx, ry, t * SPEED))
            np[led_index(x, y)] = (
                int(_clamp(c[0] * gain, 0, 255)),
                int(_clamp(c[1] * gain, 0, 255)),
                int(_clamp(c[2] * gain, 0, 255)),
            )

    if SHOW_RING and st["breathe"] > 0:
        lit = int(len(RING) * _clamp(progress, 0.0, 1.0) + 0.5)
        for i in range(lit, len(RING)):
            x, y = RING[i]
            j = led_index(x, y)
            r, g, b = np[j]
            np[j] = (r * 12 // 100, g * 12 // 100, b * 12 // 100)

    np.write()


# ---------------------------------------------------------------- QMI8658C

I2C_ADDR = 0x6B
_i2c = None


def imu_init():
    global _i2c
    try:
        _i2c = I2C(0, sda=Pin(11), scl=Pin(12), freq=400_000)
        if I2C_ADDR not in _i2c.scan():
            _i2c = None
            return False
        _i2c.writeto_mem(I2C_ADDR, 0x02, b"\x60")  # CTRL1 : auto-increment
        _i2c.writeto_mem(I2C_ADDR, 0x03, b"\x23")  # CTRL2 : accel +/-4g, 250 Hz
        _i2c.writeto_mem(I2C_ADDR, 0x08, b"\x01")  # CTRL7 : accel actif
        return True
    except Exception:
        _i2c = None
        return False


def read_accel():
    """(ax, ay, az) en g, ou None."""
    if _i2c is None:
        return None
    try:
        d = _i2c.readfrom_mem(I2C_ADDR, 0x35, 6)
    except Exception:
        return None
    out = []
    for i in range(0, 6, 2):
        v = d[i] | (d[i + 1] << 8)
        if v & 0x8000:
            v -= 0x10000
        out.append(v / 8192.0)  # sensibilite a +/-4 g
    return tuple(out)


def orientation(acc):
    """Rotation a appliquer pour que le degrade reste vertical. 0/90/180/270."""
    if acc is None:
        return 0
    ax, ay = acc[0], acc[1]
    if abs(ax) < 0.35 and abs(ay) < 0.35:
        return 0  # a plat : rien a corriger
    if abs(ax) > abs(ay):
        return 90 if ax > 0 else 270
    return 0 if ay > 0 else 180


# ---------------------------------------------------------------- serie

_poller = select.poll()
_poller.register(sys.stdin, select.POLLIN)
_pending = ""


def read_line():
    global _pending
    while _poller.poll(0):
        ch = sys.stdin.read(1)
        if ch is None:
            return None
        if ch in ("\n", "\r"):
            if _pending:
                line, _pending = _pending, ""
                return line
            continue
        _pending += ch
        if len(_pending) > 96:
            _pending = ""
    return None


def parse(line):
    """-> (etat, progression) ou None."""
    line = line.strip()
    if line.upper().startswith("STATE:"):
        parts = line[6:].split(",")
        st = parts[0].strip().lower()
        if st not in STATES:
            return None
        prog = 1.0
        if len(parts) > 1:
            try:
                prog = _clamp(float(parts[1]), 0.0, 1.0)
            except ValueError:
                pass
        return st, prog
    # ancien format : "FF0000,solid"
    hexcol = line.split(",")[0].lstrip("#").upper()
    if hexcol in HEX_TO_STATE:
        return HEX_TO_STATE[hexcol], 1.0
    return None


# ---------------------------------------------------------------- chenillard


def chase():
    """Test de cablage : compare avec la case du simulateur."""
    i = 0
    while True:
        for j in range(N * N):
            np[j] = (0, 0, 0)
        np[i % (N * N)] = (60, 60, 60)
        np.write()
        i += 1
        time.sleep_ms(250)


# ---------------------------------------------------------------- boucle

if __name__ == "__main__":
    has_imu = imu_init()

    state, progress = "offline", 1.0
    last_msg = time.ticks_ms()
    started = time.ticks_ms()
    rot = 0
    last_imu = 0

    while True:
        now = time.ticks_ms()

        line = read_line()
        if line is not None:
            last_msg = now
            if line.strip().upper() != "PING":
                got = parse(line)
                if got:
                    state, progress = got

        if has_imu and time.ticks_diff(now, last_imu) > 400:
            last_imu = now
            rot = orientation(read_accel())

        if time.ticks_diff(now, last_msg) > WATCHDOG_S * 1000:
            state = "offline"  # l'hote s'est tu : on ne ment pas

        draw(state, time.ticks_diff(now, started) / 1000.0, progress, rot)
        time.sleep_ms(FRAME_MS)
