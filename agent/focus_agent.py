#!/usr/bin/env python3
"""focus-agent — tourne sur jupiter (macOS).

Trois roles en un seul processus :
  1. lit l'app Rappels via ekctl (EventKit) et pousse l'etat vers titan
  2. interroge titan pour l'etat consolide (calendrier + overrides iOS)
  3. pilote la tige LED USB

Convention Rappels, volontairement minimale :
  - liste "Focus"   : une entree non cochee = deep focus     -> ROUGE
  - autres listes   : au moins une echeance aujourd'hui      -> ORANGE
  - rien            :                                         -> VERT

C'est un compromis assume : Rappels n'a aucune notion de "je travaille
la-dessus maintenant". La liste Focus sert de bascule deguisee en tache.
Tu y glisses ce que tu fais, tu la coches en sortant.

Prerequis :
  brew install python@3.12 && pip3 install pyserial requests
  ekctl : https://github.com/schappim/ekctl  (binaire universel precompile)
  Autoriser l'acces a Rappels au premier lancement (invite macOS).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date

try:
    import requests
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("dependances manquantes :  pip3 install pyserial requests")

HUB = os.environ.get("HUB_URL", "https://titan.<tailnet>.ts.net/focus")
TOKEN = os.environ.get("HUB_TOKEN", "")
EKCTL = os.environ.get("EKCTL", shutil.which("ekctl") or "/usr/local/bin/ekctl")
FOCUS_LIST = os.environ.get("FOCUS_LIST", "Focus")

RP2040_VID = 0x2E8A
POLL_S = 2.0
REMINDERS_EVERY = 15.0  # ekctl est plus lourd, on l'interroge moins souvent
KEEPALIVE_S = 10.0

PALETTE = {
    "deep": ("FF0000", "solid"),
    "working": ("FF5A00", "solid"),
    "free": ("00FF00", "solid"),
    "offline": ("000000", "off"),
}


# ---------------------------------------------------------------- Rappels


def ekctl_json(*args) -> dict | list | None:
    """Appelle ekctl et renvoie son JSON, ou None si quoi que ce soit rate."""
    if not os.path.exists(EKCTL):
        return None
    try:
        out = subprocess.run(
            [EKCTL, *args], capture_output=True, text=True, timeout=20, check=False
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


def _reminders(payload) -> list[dict]:
    if isinstance(payload, dict):
        return payload.get("reminders", [])
    return payload if isinstance(payload, list) else []


def reminders_state() -> tuple[str, str]:
    """('deep'|'working'|'free', explication lisible)."""
    focus = _reminders(
        ekctl_json("list", "reminders", "--list", FOCUS_LIST, "--completed", "false")
    )
    if focus:
        titre = focus[0].get("title", "sans titre")
        extra = f" (+{len(focus) - 1})" if len(focus) > 1 else ""
        return "deep", f"Rappels/{FOCUS_LIST} : {titre}{extra}"

    today = date.today().isoformat()
    due = [
        r
        for r in _reminders(ekctl_json("list", "reminders", "--completed", "false"))
        if str(r.get("dueDate") or "")[:10] <= today and r.get("dueDate")
    ]
    if due:
        return "working", f"{len(due)} rappel(s) a echeance aujourd'hui"
    return "free", "aucun rappel actif"


# ---------------------------------------------------------------- titan


class Hub:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {TOKEN}"
        self.s.trust_env = False  # ne jamais fuiter le jeton dans un proxy

    def push(self, state: str, reason: str) -> None:
        try:
            self.s.post(
                f"{HUB}/agent", json={"state": state, "reason": reason}, timeout=4
            )
        except requests.RequestException:
            pass

    def state(self) -> dict | None:
        try:
            r = self.s.get(f"{HUB}/state", timeout=4)
            return r.json() if r.ok else None
        except requests.RequestException:
            return None


# ---------------------------------------------------------------- la tige


class Wand:
    def __init__(self, port: str | None = None):
        self.forced, self.ser = port, None

    def connect(self) -> bool:
        port = self.forced or next(
            (p.device for p in list_ports.comports() if p.vid == RP2040_VID), None
        )
        if not port:
            return False
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.2, write_timeout=1)
            time.sleep(0.3)
            print(f"[agent] tige sur {port}", flush=True)
            return True
        except (serial.SerialException, OSError):
            self.ser = None
            return False

    def send(self, hexcolor: str, mode: str) -> bool:
        if self.ser is None and not self.connect():
            return False
        try:
            self.ser.write(f"{hexcolor},{mode}\n".encode())
            self.ser.flush()
            return True
        except (serial.SerialException, OSError):
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            return False


# ---------------------------------------------------------------- boucle


def run(args):
    if not TOKEN:
        sys.exit("HUB_TOKEN manquant. export HUB_TOKEN=…")

    hub, wand = Hub(), Wand(args.port)
    last_state = last_send = last_rem = None
    last_send_t = last_rem_t = 0.0

    while True:
        now = time.monotonic()

        if now - last_rem_t > REMINDERS_EVERY:
            last_rem_t = now
            st, why = reminders_state()
            if (st, why) != last_rem:
                last_rem = (st, why)
                print(f"[agent] Rappels -> {st} · {why}", flush=True)
            hub.push(st, why)

        data = hub.state()
        if data is None:
            state, reason = "offline", "titan injoignable"
        else:
            state, reason = data.get("state", "free"), data.get("reason", "")

        if state != last_state or now - last_send_t > KEEPALIVE_S:
            hexcolor, mode = PALETTE.get(state, PALETTE["offline"])
            if wand.send(hexcolor, mode):
                last_send_t = now
                if state != last_state:
                    print(f"[agent] tige -> {state} · {reason}", flush=True)
                    last_state = state

        if args.once:
            return
        time.sleep(POLL_S)


def main():
    ap = argparse.ArgumentParser(description="focus-agent (macOS)")
    ap.add_argument("--port", help="port serie force, ex /dev/cu.usbmodem1101")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--check", action="store_true", help="diagnostic puis sortie")
    args = ap.parse_args()

    if args.check:
        print(f"ekctl      : {EKCTL} {'OK' if os.path.exists(EKCTL) else 'ABSENT'}")
        print(f"Rappels    : {reminders_state()}")
        ports = [(p.device, hex(p.vid or 0)) for p in list_ports.comports()]
        print(f"ports serie: {ports or 'aucun'}")
        print(f"hub        : {Hub().state()}")
        return

    try:
        run(args)
    except KeyboardInterrupt:
        Wand(args.port).send("000000", "off")
        print("\n[agent] bye")


if __name__ == "__main__":
    main()
