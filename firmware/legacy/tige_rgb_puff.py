# main_rgb.py -- firmware "tige focus" pour LED RGB analogique recuperee
#
# Variante de main.py pour une LED RGB a anode commune (recuperee d'une puff),
# pilotee par trois MOSFET canal N cotes bas -- typiquement les FS8205A
# dessoudes de la carte de protection.
#
# Le protocole serie est STRICTEMENT identique a main.py :
#   RRGGBB,mode\n   avec mode = solid | pulse | off
#   PING\n          keepalive
# focus_agent.py et focus_light.py fonctionnent sans aucune modification.
#
# Cablage (voir RECUP-PUFF.md) :
#   VBUS 5V -> anode commune
#   GP2 -> grille MOSFET R -> cathode R via 150 ohm
#   GP3 -> grille MOSFET G -> cathode G via 91 ohm
#   GP4 -> grille MOSFET B -> cathode B via 91 ohm

import math
import select
import sys
import time

from machine import PWM, Pin

# ---------------------------------------------------------------- config

PIN_R, PIN_G, PIN_B = 2, 3, 4
PWM_FREQ = 1000
MAX_BRIGHTNESS = 0.85  # pas de contrainte de budget USB ici : ~60 mA au pire
WATCHDOG_S = 30
FRAME_MS = 20

# Correction de balance : une LED RGB bon marche tire fortement vers le vert,
# qui a le meilleur rendement lumineux. Sans ca, l'orange vire au jaune-vert.
GAIN = (1.00, 0.55, 0.70)

# Correction gamma : l'oeil percoit la luminosite de facon logarithmique.
# Sans elle, la respiration du mode pulse parait saccadee en haut de course.
#
# ATTENTION : la gamma s'applique a la LUMINOSITE (scale) uniquement, jamais au
# melange des canaux. L'appliquer aux composantes ecraserait les couleurs
# faibles -- l'orange FF5A00 verrait son vert divise par 10 et sortirait rouge,
# donc indiscernable du deep focus. C'est aussi ce qui garantit que ce firmware
# rend exactement les memes couleurs que la version WS2812 de main.py.
GAMMA = 2.2

_ch = [PWM(Pin(p)) for p in (PIN_R, PIN_G, PIN_B)]
for c in _ch:
    c.freq(PWM_FREQ)


def paint(r, g, b, scale=1.0):
    """Allume la LED. r/g/b sur 0-255, scale sur 0.0-1.0."""
    s = (MAX_BRIGHTNESS * min(max(scale, 0.0), 1.0)) ** GAMMA
    for chan, val, gain in zip(_ch, (r, g, b), GAIN):
        duty = int((val / 255.0) * s * gain * 65535)
        # anode commune + MOSFET cote bas : duty croissant = plus lumineux
        chan.duty_u16(min(max(duty, 0), 65535))


# ---------------------------------------------------------------- serie non bloquante

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
        if len(_pending) > 64:
            _pending = ""
    return None


def parse(line):
    parts = line.strip().split(",")
    hexcol = parts[0].lstrip("#")
    mode = parts[1].strip().lower() if len(parts) > 1 else "solid"
    if len(hexcol) != 6:
        return None
    try:
        v = int(hexcol, 16)
    except ValueError:
        return None
    return ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF), mode


# ---------------------------------------------------------------- bouton BOOTSEL

try:
    from rp2 import bootsel_button as _bootsel
except ImportError:
    _bootsel = None

OVERRIDES = (None, (255, 0, 0), (0, 255, 0))
_override_idx = 0
_btn_was_down = False
_btn_last_ms = 0


def poll_button(now):
    global _override_idx, _btn_was_down, _btn_last_ms
    if _bootsel is None:
        return
    if time.ticks_diff(now, _btn_last_ms) < 150:
        return
    _btn_last_ms = now
    down = bool(_bootsel())
    if down and not _btn_was_down:
        _override_idx = (_override_idx + 1) % len(OVERRIDES)
    _btn_was_down = down


# ---------------------------------------------------------------- boucle principale

color = (0, 0, 0)
mode = "off"
last_msg = time.ticks_ms()
started = time.ticks_ms()

for _ in range(2):
    paint(0, 60, 255, 1.0)
    time.sleep_ms(120)
    paint(0, 0, 0)
    time.sleep_ms(120)

while True:
    now = time.ticks_ms()

    line = read_line()
    if line is not None:
        last_msg = now
        if line.strip().upper() != "PING":
            parsed = parse(line)
            if parsed:
                color, mode = parsed

    poll_button(now)

    if time.ticks_diff(now, last_msg) > WATCHDOG_S * 1000:
        paint(0, 0, 0)
        time.sleep_ms(FRAME_MS)
        continue

    forced = OVERRIDES[_override_idx]
    if forced is not None:
        phase = (time.ticks_diff(now, started) % 4000) / 4000
        scale = 0.55 + 0.45 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
        paint(forced[0], forced[1], forced[2], scale)
    elif mode == "off":
        paint(0, 0, 0)
    elif mode == "pulse":
        phase = (time.ticks_diff(now, started) % 3000) / 3000
        scale = 0.35 + 0.65 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))
        paint(color[0], color[1], color[2], scale)
    else:
        paint(color[0], color[1], color[2], 1.0)

    time.sleep_ms(FRAME_MS)
