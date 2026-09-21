# main.py -- focus-light pour Waveshare ESP32-S3-Matrix
#
# Materiel : ESP32-S3FH4R2 (4 Mo flash, 2 Mo PSRAM quad), 8x8 WS2812B sur
#            GPIO14, QMI8658C en I2C sur SDA=11 SCL=12, adresse 0x6B.
# Firmware : MicroPython >= 1.26, variante ESP32_GENERIC_S3 standard.
#
# Les animations reproduisent exactement le calcul de simulateur-matrice.html.
# Ce que tu regles dans le simulateur est ce que la carte affiche.
#
# Outils de calibration, a lancer depuis le REPL apres Ctrl-C :
#     import main
#     main.test_order()      # quelle est la vraie sequence de couleurs
#     main.test_mapping()    # lignes ou serpentin
#     main.test_chase()      # chenillard, a comparer au simulateur
#     main.benchmark()       # images par seconde reellement atteintes

import asyncio
import binascii
import gc
import json
import math
import select
import sys
import time

import neopixel
from machine import I2C, Pin

import config as C

# ---------------------------------------------------------------- matrice

N = 8
NP = neopixel.NeoPixel(Pin(C.PIN_MATRIX), N * N)
try:
    NP.ORDER = C.ORDER
except AttributeError:
    pass


def _rotate(x, y, deg):
    m = N - 1
    if deg == 90:
        return y, m - x
    if deg == 180:
        return m - x, m - y
    if deg == 270:
        return m - y, x
    return x, y


def _build_lut():
    """Table logique -> index physique. Calculee une fois, evite de refaire
    rotation et serpentin sur chaque pixel de chaque image."""
    lut = bytearray(N * N)
    snake = C.MAPPING == "snake"
    for y in range(N):
        for x in range(N):
            rx, ry = _rotate(x, y, C.ROTATION)
            col = (N - 1 - rx) if (snake and ry % 2) else rx
            lut[y * N + x] = ry * N + col
    return lut


LUT = _build_lut()

# Les 28 pixels du perimetre, sens horaire depuis le coin haut-gauche
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


def clear():
    for i in range(N * N):
        NP[i] = (0, 0, 0)
    NP.write()


# ---------------------------------------------------------------- bruit


@micropython.native
def _hash3(i, j, k):
    n = (i * 374761393 + j * 668265263 + k * 1274126177) & 0x7FFFFFFF
    n ^= n >> 13
    n = (n * 1274126177) & 0x7FFFFFFF
    n ^= n >> 16
    return (n & 0xFFFF) / 65535.0


@micropython.native
def noise3(x, y, z):
    xi = int(x // 1)
    yi = int(y // 1)
    zi = int(z // 1)
    xf = x - xi
    yf = y - yi
    zf = z - zi
    xf = xf * xf * (3 - 2 * xf)
    yf = yf * yf * (3 - 2 * yf)
    zf = zf * zf * (3 - 2 * zf)
    a = 0.0
    for dz in (0, 1):
        wz = zf if dz else 1 - zf
        for dy in (0, 1):
            wy = yf if dy else 1 - yf
            for dx in (0, 1):
                wx = xf if dx else 1 - xf
                a += wx * wy * wz * _hash3(xi + dx, yi + dy, zi + dz)
    return a


def _clamp(v, a=0.0, b=1.0):
    return a if v < a else (b if v > b else v)


def _smooth(t):
    return t * t * (3 - 2 * t)


def _gauss(p, c, w):
    d = (p - c) / w
    return math.exp(-d * d)


def _rad(x, y):
    dx = x - 3.5
    dy = y - 3.5
    return math.sqrt(dx * dx + dy * dy) / 4.95


# ---------------------------------------------------------------- animations
# Pack DALLE : structure spatiale fine, lisible d'un seul cote.

ANIMS_PANEL = {
    "aurora": lambda x, y, t, a: _clamp(
        1 - abs(y - (3.5 + 2.2 * a * math.sin(x * .55 + t * .45)
                     + 1.1 * a * math.sin(x * .27 - t * .62))) / 3.4),
    "ember": lambda x, y, t, a: _clamp(
        (1 - y / 7) * (1 - a * .7 + a * 1.4 * noise3(x * .45, y * .3, t * .55))),
    "plasma": lambda x, y, t, a: _clamp(
        .5 + ((math.sin(x * .6 + t * .8) + math.sin(y * .5 - t * .55)
               + math.sin((x + y) * .38 + t * .42)) / 6) * (.4 + a * 1.6)),
    "drift": lambda x, y, t, a: _clamp(
        (noise3(x * .32 + t * .12, y * .32, t * .2) - .5) * (1 + a * 2.2) + .5),
    "breath": lambda x, y, t, a: _clamp(
        1 - _rad(x, y) + a * (.5 * math.sin(t * .9)) * 1.4),
    "wave": lambda x, y, t, a: _clamp(
        .5 + math.sin((x + y) * .62 - t * 1.1) * (.15 + a * .35)),
    "rings": lambda x, y, t, a: _clamp(
        .5 + math.sin(_rad(x, y) * 4.95 * 1.5 - t * 1.6) * (.18 + a * .32)),
    "spiral": lambda x, y, t, a: _clamp(
        .5 + math.sin(math.atan2(y - 3.5, x - 3.5) * 2
                      + _rad(x, y) * 4.95 * .7 - t * .9) * (.18 + a * .32)),
    "scan": lambda x, y, t, a: _clamp(
        1 - abs(y - (((t * .35) % 1) * (N + 4) - 2)) / (1.2 + a * 2.8)),
    "gradient": lambda x, y, t, a: _clamp(
        1 - y / 7 + a * .18 * math.sin(t * .7 + x * .5)),
    "solid": lambda x, y, t, a: _clamp(.82 + a * .18 * math.sin(t * .6)),
}

# Pack DIFFUSEUR : radialement symetriques. Sous un dome, toute structure
# azimutale rendrait le signal dependant de l'endroit ou l'on se tient --
# un collegue au nord et un au sud liraient deux etats differents.
ANIMS_DOME = {
    "pulse": lambda x, y, t, a: _clamp(.55 + .45 * a * math.sin(t * .9) + (1 - a) * .2),
    "swell": lambda x, y, t, a: _clamp(
        .15 + .85 * a * (_smooth(((t * .35) % 1) / .72) if ((t * .35) % 1) < .72
                         else 1 - _smooth((((t * .35) % 1) - .72) / .28))
        + (1 - a) * .5),
    "heartbeat": lambda x, y, t, a: _clamp(
        .18 + .82 * a * (_gauss((t * .45) % 1, .06, .05)
                         + .75 * _gauss((t * .45) % 1, .20, .055)) + (1 - a) * .4),
    "candle": lambda x, y, t, a: _clamp(.62 + .38 * a * (noise3(0, 0, t * .7) * 2 - 1)),
    "ripple": lambda x, y, t, a: _clamp(
        .5 + .5 * math.sin(_rad(x, y) * 3 - t) * (.3 + a * .7)),
    "halo": lambda x, y, t, a: _clamp(
        1 - _rad(x, y) * (.5 + a * .5) + a * .25 * math.sin(t * .8)),
    "steady": lambda x, y, t, a: _clamp(.88 + a * .06 * math.sin(t * .4)),
}

# ---------------------------------------------------------------- niveaux

STATES_PANEL = {
    "deep":    {"anim": "ember",  "speed": 1.00, "amp": .70, "ctr": 1.0, "bp": 9.0, "bd": .30,
                "stops": ((8, 0, 0), (95, 8, 2), (190, 38, 8))},
    "editing": {"anim": "spiral", "speed": .85, "amp": .70, "ctr": 1.2, "bp": 0.0, "bd": 0.0,
                "stops": ((6, 0, 12), (70, 10, 130), (168, 70, 255))},
    "working": {"anim": "aurora", "speed": 1.00, "amp": .75, "ctr": 1.1, "bp": 7.0, "bd": .25,
                "stops": ((22, 14, 0), (175, 115, 0), (250, 215, 80))},
    "free":    {"anim": "drift",  "speed": .55, "amp": .55, "ctr": 0.9, "bp": 12.0, "bd": .35,
                "stops": ((0, 8, 3), (0, 80, 30), (40, 180, 85))},
    "offline": {"anim": "solid",  "speed": .30, "amp": .20, "ctr": 0.6, "bp": 0.0, "bd": 0.0,
                "stops": ((0, 0, 0), (3, 3, 4), (8, 9, 11))},
}

# Rythmes choisis pour rester distinguables sans voir la couleur :
# lourd et lent / ondes regulieres / pulsation nette / presque immobile / eteint.
STATES_DOME = {
    "deep":    {"anim": "swell",  "speed": .55, "amp": .85, "ctr": 1.0, "bp": 0.0, "bd": 0.0,
                "stops": ((8, 0, 0), (95, 8, 2), (190, 38, 8))},
    "editing": {"anim": "ripple", "speed": .80, "amp": .60, "ctr": 1.0, "bp": 0.0, "bd": 0.0,
                "stops": ((6, 0, 12), (70, 10, 130), (168, 70, 255))},
    "working": {"anim": "pulse",  "speed": 1.00, "amp": .70, "ctr": 1.0, "bp": 0.0, "bd": 0.0,
                "stops": ((22, 14, 0), (175, 115, 0), (250, 215, 80))},
    "free":    {"anim": "candle", "speed": .50, "amp": .25, "ctr": 1.0, "bp": 0.0, "bd": 0.0,
                "stops": ((0, 8, 3), (0, 80, 30), (40, 180, 85))},
    "offline": {"anim": "steady", "speed": .30, "amp": .10, "ctr": 1.0, "bp": 0.0, "bd": 0.0,
                "stops": ((0, 0, 0), (3, 3, 4), (8, 9, 11))},
}

STATES = STATES_DOME if C.MODE == "dome" else STATES_PANEL
ANIMS = ANIMS_DOME if C.MODE == "dome" else ANIMS_PANEL
VALID = tuple(STATES.keys())

# ---------------------------------------------------------------- rendu


def _ramp(stops, t):
    t = _clamp(t)
    if t < .5:
        a, b, k = stops[0], stops[1], t * 2
    else:
        a, b, k = stops[1], stops[2], (t - .5) * 2
    return (a[0] + (b[0] - a[0]) * k,
            a[1] + (b[1] - a[1]) * k,
            a[2] + (b[2] - a[2]) * k)


def draw(state, t, progress=1.0, rot_extra=0):
    cfg = STATES.get(state) or STATES["offline"]
    fn = ANIMS.get(cfg["anim"]) or ANIMS["solid"]
    stops, speed, amp, ctr = cfg["stops"], cfg["speed"], cfg["amp"], cfg["ctr"]

    breath = 1.0
    if cfg["bp"] > 0 and cfg["bd"] > 0:
        p = (t % cfg["bp"]) / cfg["bp"]
        breath = 1 - cfg["bd"] * (1 - (.5 - .5 * math.cos(6.283185 * p)))

    # LINEAIRE : elever la luminosite a la puissance 2.2 diviserait par dix.
    gain = C.MAX_BRIGHTNESS * breath
    ts = t * speed
    lut = LUT

    for y in range(N):
        for x in range(N):
            if rot_extra:
                px, py = _rotate(x, y, rot_extra)
            else:
                px, py = x, y
            f = _clamp((fn(px, py, ts, amp) - .5) * ctr + .5)
            c = _ramp(stops, f)
            NP[lut[y * N + x]] = (
                int(_clamp(c[0] * gain, 0, 255)),
                int(_clamp(c[1] * gain, 0, 255)),
                int(_clamp(c[2] * gain, 0, 255)),
            )

    if C.SHOW_RING and C.MODE == "panel" and state != "offline":
        lit = int(len(RING) * _clamp(progress) + .5)
        for i in range(lit, len(RING)):
            x, y = RING[i]
            j = lut[y * N + x]
            r, g, b = NP[j]
            NP[j] = (r * 14 // 100, g * 14 // 100, b * 14 // 100)

    NP.write()


# ---------------------------------------------------------------- QMI8658C

_i2c = None


def imu_init():
    global _i2c
    if not C.USE_IMU:
        return False
    try:
        i2c = I2C(0, sda=Pin(11), scl=Pin(12), freq=400_000)
        if 0x6B not in i2c.scan():
            return False
        i2c.writeto_mem(0x6B, 0x02, b"\x60")   # CTRL1 auto-increment
        i2c.writeto_mem(0x6B, 0x03, b"\x23")   # CTRL2 accel +/-4g, 250 Hz
        i2c.writeto_mem(0x6B, 0x08, b"\x01")   # CTRL7 accel actif
        _i2c = i2c
        return True
    except Exception:
        return False


def read_accel():
    if _i2c is None:
        return None
    try:
        d = _i2c.readfrom_mem(0x6B, 0x35, 6)
    except Exception:
        return None
    out = []
    for i in range(0, 6, 2):
        v = d[i] | (d[i + 1] << 8)
        if v & 0x8000:
            v -= 0x10000
        out.append(v / 8192.0)
    return out


def orientation():
    """Rotation a appliquer pour que le degrade reste vertical."""
    a = read_accel()
    if a is None:
        return 0
    ax, ay = a[0], a[1]
    if abs(ax) < .35 and abs(ay) < .35:
        return 0
    if abs(ax) > abs(ay):
        return 90 if ax > 0 else 270
    return 0 if ay > 0 else 180


# ---------------------------------------------------------------- etat partage

STATE = {"level": "offline", "task": "", "progress": 1.0,
         "last": 0, "rot": 0, "net": False, "hold": False}


def _apply(level, task="", progress=1.0):
    if level in VALID:
        STATE["level"] = level
        STATE["task"] = task
        STATE["progress"] = _clamp(progress)
        STATE["last"] = time.ticks_ms()


# ---------------------------------------------------------------- diffusion
# Le navigateur peut prendre la main et envoyer directement les trames, ce qui
# garantit que la dalle affiche exactement ce que montre le simulateur.
#
# Le protocole est en TEXTE HEXADECIMAL, jamais en binaire : un octet 0x03 dans
# un flux binaire serait interprete comme Ctrl-C par MicroPython et tuerait le
# programme en pleine diffusion. 384 caracteres pour 64 pixels, l'USB encaisse.
#
# Les trames arrivent en ordre LOGIQUE (gauche-droite, haut-bas). La table LUT
# applique rotation et serpentin ici, pour que la calibration ne vive qu'a un
# seul endroit : config.py.

STREAM = {"at": 0}
STREAM_TIMEOUT_MS = 2000


def apply_frame(payload):
    """payload = 384 caracteres hexa + 2 de somme de controle.

    La somme n'est pas du zele. Quand le navigateur passe en arriere-plan, le
    systeme peut geler l'ecriture au milieu d'une ligne : elle part tronquee et
    se recolle a la suivante. Si le recollement fait par hasard 384 caracteres
    hexa valides, on afficherait du bruit sature -- une dalle toute blanche.
    """
    if len(payload) != 386:
        return False
    try:
        raw = binascii.unhexlify(payload[:384])
        want = int(payload[384:386], 16)
    except Exception:
        return False
    got = 0
    for b in raw:
        got ^= b
    if got != want:
        return False
    lut = LUT
    for i in range(N * N):
        j = i * 3
        NP[lut[i]] = (raw[j], raw[j + 1], raw[j + 2])
    NP.write()
    STREAM["at"] = time.ticks_ms()
    return True


def save_states(payload):
    """Enregistre les reglages envoyes par le simulateur. Relus au demarrage.

    On valide AVANT d'ecrire : sinon une transmission tronquee laisserait un
    states.json illisible sur la carte, qui redemarrerait sur ses valeurs
    d'usine sans que rien ne l'explique.
    """
    try:
        d = json.loads(payload)
    except Exception:
        return False
    if not isinstance(d, dict) or not (("panel" in d) or ("dome" in d)):
        return False
    try:
        with open("states.json", "w") as f:
            f.write(payload)
        return True
    except Exception as exc:
        print("[save]", exc)
        return False


def load_states():
    global STATES, ANIMS
    try:
        with open("states.json") as f:
            d = json.load(f)
    except Exception:
        return False
    pack = d.get("dome" if C.MODE == "dome" else "panel")
    if not isinstance(pack, dict):
        return False
    avail = ANIMS_DOME if C.MODE == "dome" else ANIMS_PANEL
    for k, cfg in pack.items():
        if k in STATES and cfg.get("anim") in avail:
            cfg["stops"] = tuple(tuple(s) for s in cfg["stops"])
            STATES[k] = cfg
    print("[config] states.json charge")
    return True


# ---------------------------------------------------------------- Wi-Fi


async def wifi_task():
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    while True:
        if not wlan.isconnected():
            STATE["net"] = False
            try:
                wlan.connect(C.WIFI_SSID, C.WIFI_PASS)
            except Exception:
                pass
            for _ in range(40):
                if wlan.isconnected():
                    break
                await asyncio.sleep_ms(500)
            if wlan.isconnected():
                print("[wifi]", wlan.ifconfig()[0])
        else:
            STATE["net"] = True
        await asyncio.sleep(5)


async def hub_task():
    """Interroge focus-hub sur titan. Ne bloque jamais le rendu."""
    req = ("GET /state HTTP/1.0\r\nHost: %s\r\nAuthorization: Bearer %s\r\n"
           "Connection: close\r\n\r\n" % (C.HUB_HOST, C.HUB_TOKEN))
    while True:
        if STATE["net"]:
            r = w = None
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(C.HUB_HOST, C.HUB_PORT), 4)
                w.write(req.encode())
                await w.drain()
                raw = await asyncio.wait_for(r.read(1024), 4)
                body = raw.split(b"\r\n\r\n", 1)
                if len(body) == 2:
                    d = json.loads(body[1])
                    _apply(d.get("state", "offline"),
                           d.get("task", ""), d.get("progress", 1.0))
            except Exception:
                pass
            finally:
                if w:
                    try:
                        w.close()
                        await w.wait_closed()
                    except Exception:
                        pass
        await asyncio.sleep(C.POLL_S)


# ---------------------------------------------------------------- serie
# Repli quand le reseau est absent : meme protocole que la v1.
#   STATE:deep,0.62,Montage episode 12
#   PING


def handle_line(line):
    """Une commande. Renvoie une reponse a echoer, ou None."""
    if not line:
        return None

    # Les commandes en toutes lettres passent EN PREMIER : "PING" commence par
    # un P et serait sinon avale par la commande de progression ci-dessous.
    up = line.upper()
    if up == "PING":
        STATE["last"] = time.ticks_ms()
        return "PONG"
    if up.startswith("STATE:"):
        p = line[6:].split(",", 2)
        try:
            prog = float(p[1]) if len(p) > 1 else 1.0
        except ValueError:
            prog = 1.0
        _apply(p[0].strip().lower(), p[2] if len(p) > 2 else "", prog)
        return "OK"

    tag, rest = line[0], line[1:]

    if tag == "F":                      # trame complete, 384 caracteres hexa
        return "OK" if apply_frame(rest) else "ERR frame"
    if tag == "L":                      # niveau
        lvl = rest.strip().lower()
        if lvl not in VALID:
            return "ERR level"
        _apply(lvl, STATE["task"], STATE["progress"])
        return "OK " + lvl
    if tag == "B":                      # luminosite, 0-100
        try:
            C.MAX_BRIGHTNESS = _clamp(float(rest) / 100, 0.01, 1.0)
        except ValueError:
            return "ERR brightness"
        return "OK %.2f" % C.MAX_BRIGHTNESS
    if tag == "P":                      # progression, 0-100
        try:
            STATE["progress"] = _clamp(float(rest) / 100)
        except ValueError:
            return "ERR progress"
        return "OK"
    if tag == "C":                      # enregistrer les reglages
        if save_states(rest):
            load_states()
            return "OK saved"
        return "ERR save"
    if tag == "H":                      # maintien : 1 = garder l'affichage
        STATE["hold"] = rest.strip() not in ("0", "", "off", "false")
        STATE["last"] = time.ticks_ms()
        return "OK hold=%d" % (1 if STATE["hold"] else 0)
    if tag == "?":                      # identification, pour la detection
        return "FOCUS %s %s rot%d %s hold=%d" % (
            C.MODE, C.MAPPING, C.ROTATION, STATE["level"], 1 if STATE["hold"] else 0)

    return None


async def serial_task():
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)
    buf = ""
    while True:
        n = 0
        while poller.poll(0) and n < 3000:   # borne : ne pas affamer le rendu
            n += 1
            ch = sys.stdin.read(1)
            if ch is None:
                break
            if ch in ("\n", "\r"):
                line, buf = buf.strip(), ""
                resp = handle_line(line)
                if resp:
                    print(resp)
            else:
                buf += ch
                if len(buf) > 600:           # 384 hexa + marge
                    buf = ""
        await asyncio.sleep_ms(8)


# ---------------------------------------------------------------- boucle


async def render_task():
    has_imu = imu_init()
    print("[imu]", "OK" if has_imu else "absent")
    load_states()
    t0 = time.ticks_ms()
    last_imu = 0
    while True:
        now = time.ticks_ms()

        # Le navigateur diffuse : on ne calcule rien, il a deja tout dessine.
        # Des qu'il se tait plus de deux secondes, on reprend la main tout seul.
        if time.ticks_diff(now, STREAM["at"]) < STREAM_TIMEOUT_MS:
            await asyncio.sleep_ms(10)
            continue

        if has_imu and time.ticks_diff(now, last_imu) > 400:
            last_imu = now
            STATE["rot"] = orientation()

        # Le chien de garde evite de mentir quand l'hote s'endort. Le maintien
        # le neutralise volontairement : la carte tient son niveau jusqu'a
        # nouvel ordre, meme si plus personne ne lui parle.
        lvl = STATE["level"]
        if not STATE["hold"] and \
                time.ticks_diff(now, STATE["last"]) > C.WATCHDOG_S * 1000:
            lvl = "offline"

        draw(lvl, time.ticks_diff(now, t0) / 1000.0,
             STATE["progress"], STATE["rot"])
        await asyncio.sleep_ms(C.FRAME_MS)


async def main():
    # salut de demarrage : deux clignotements bleus
    for _ in range(2):
        for i in range(N * N):
            NP[i] = (0, 6, 24)
        NP.write()
        await asyncio.sleep_ms(130)
        clear()
        await asyncio.sleep_ms(130)

    tasks = [asyncio.create_task(render_task()), asyncio.create_task(serial_task())]
    if C.WIFI_SSID:
        tasks.append(asyncio.create_task(wifi_task()))
        tasks.append(asyncio.create_task(hub_task()))
    else:
        print("[wifi] non configure, pilotage serie uniquement")
    await asyncio.gather(*tasks)


# ---------------------------------------------------------------- calibration


def test_order():
    """Allume 3 LED. Note ce que tu vois vraiment pour regler ORDER."""
    clear()
    NP[0] = (30, 0, 0)
    NP[1] = (0, 30, 0)
    NP[2] = (0, 0, 30)
    NP.write()
    print("attendu rouge, vert, bleu sur les 3 premieres LED de la chaine")
    print("si vert, rouge, bleu  -> ORDER = (1,0,2,3)")
    print("si rouge, vert, bleu  -> ORDER = (0,1,2,3), c'est deja bon")


def test_mapping():
    """Ou tombe le vert ? A cote du bleu = serpentin, du rouge = lignes."""
    clear()
    NP[0] = (30, 0, 0)    # debut de chaine
    NP[7] = (0, 0, 30)    # fin de la premiere rangee
    NP[8] = (0, 30, 0)    # debut de la deuxieme rangee
    NP.write()
    print("vert colle au bleu   -> MAPPING = 'snake'")
    print("vert colle au rouge  -> MAPPING = 'row'")


def test_chase(delay_ms=220):
    """Chenillard, a comparer a la case du meme nom dans le simulateur."""
    try:
        i = 0
        while True:
            clear()
            NP[i % (N * N)] = (40, 40, 40)
            NP.write()
            i += 1
            time.sleep_ms(delay_ms)
    except KeyboardInterrupt:
        clear()


def preview(level="deep", seconds=12):
    """Affiche un niveau sans reseau, pour juger a l'oeil."""
    t0 = time.ticks_ms()
    try:
        while time.ticks_diff(time.ticks_ms(), t0) < seconds * 1000:
            draw(level, time.ticks_diff(time.ticks_ms(), t0) / 1000.0, .62)
            time.sleep_ms(C.FRAME_MS)
    except KeyboardInterrupt:
        pass
    clear()


def benchmark(level="deep", frames=60):
    """Images par seconde reellement atteintes. Sous 15, monte FRAME_MS."""
    gc.collect()
    t0 = time.ticks_ms()
    for i in range(frames):
        draw(level, i / 25.0, .62)
    dt = time.ticks_diff(time.ticks_ms(), t0)
    clear()
    fps = frames * 1000 / dt
    print("%d images en %d ms -> %.1f fps brutes" % (frames, dt, fps))
    print("memoire libre : %d octets" % gc.mem_free())
    return fps


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        clear()
        print("arrete. Outils : test_order() test_mapping() test_chase() "
              "preview('editing') benchmark()")
