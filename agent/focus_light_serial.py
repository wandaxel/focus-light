#!/usr/bin/env python3
"""focus-light — relie Super Productivity a une tige LED USB.

Logique :
  tache en cours portant le tag "deep"   -> ROUGE fixe    (deep focus, ne pas deranger)
  tache en cours sans ce tag             -> ORANGE fixe   (je bosse, mais interruptible)
  aucune tache en cours                  -> VERT fixe     (dispo)
  Super Productivity injoignable         -> tige eteinte  (pas de signal menteur)

Prerequis :
  - Super Productivity desktop, Settings > Misc > Enable local REST API
  - le token affiche juste en dessous (Settings > Misc > Access Token)
  - pip install pyserial

Usage :
  export SP_TOKEN=xxxxx
  python3 focus_light.py                 # tourne en boucle
  python3 focus_light.py --once          # une seule mise a jour (debug)
  python3 focus_light.py --test red      # force une couleur, ignore SP
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("pyserial manquant :  pip install pyserial")

SP_BASE = "http://127.0.0.1:3876"
RP2040_VID = 0x2E8A  # Raspberry Pi (Pico, XIAO RP2040, QT Py RP2040...)
POLL_S = 2.0
KEEPALIVE_S = 10.0

# etat -> (couleur hex, mode)
PALETTE = {
    "deep": ("FF0000", "solid"),
    "working": ("FF5A00", "solid"),
    "free": ("00FF00", "solid"),
    "offline": ("000000", "off"),
}

# Important : urllib respecte http_proxy / ALL_PROXY meme pour 127.0.0.1.
# Sans ca, un proxy d'entreprise recevrait ton token en clair.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ------------------------------------------------------------------ config


def load_config(explicit: str | None) -> dict:
    if explicit:
        return json.loads(Path(explicit).read_text())
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / "focus-light" / "config.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


# ------------------------------------------------------------------ Super Productivity


class SuperProductivity:
    def __init__(self, token: str, deep_tag: str = "deep"):
        self.token = token
        self.deep_tag = deep_tag.lower()
        self._deep_tag_ids: set[str] = set()
        self._tags_fetched_at = 0.0

    def _get(self, path: str, timeout: float = 3.0):
        req = urllib.request.Request(
            SP_BASE + path, headers={"Authorization": f"Bearer {self.token}"}
        )
        with _opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error", {}).get("message", "erreur SP"))
        return payload.get("data")

    def _refresh_deep_tags(self):
        """Les IDs de tags sont opaques, on les resout par titre. Cache 60 s."""
        if time.monotonic() - self._tags_fetched_at < 60 and self._deep_tag_ids:
            return
        tags = self._get("/tags") or []
        self._deep_tag_ids = {
            t["id"]
            for t in tags
            if isinstance(t, dict)
            and self.deep_tag in str(t.get("title", "")).lower()
        }
        self._tags_fetched_at = time.monotonic()

    def state(self) -> str:
        """'deep' | 'working' | 'free'. Leve une exception si SP injoignable."""
        data = self._get("/task-control/current")
        # l'API a renvoye soit la tache, soit un objet l'encapsulant, soit null
        task = data
        if isinstance(data, dict) and "task" in data and "id" not in data:
            task = data["task"]
        if not task:
            return "free"
        try:
            self._refresh_deep_tags()
        except Exception:
            pass  # pas de tags -> on degrade en "working", pas grave
        tag_ids = set(task.get("tagIds") or [])
        title = str(task.get("title", ""))
        is_deep = bool(tag_ids & self._deep_tag_ids) or f"#{self.deep_tag}" in title.lower()
        return "deep" if is_deep else "working"


# ------------------------------------------------------------------ la tige


class Wand:
    """Connexion serie a la tige, avec reconnexion automatique."""

    def __init__(self, port: str | None = None):
        self.forced_port = port
        self.ser: serial.Serial | None = None

    @staticmethod
    def discover() -> str | None:
        for p in list_ports.comports():
            if p.vid == RP2040_VID:
                return p.device
        return None

    def connect(self) -> bool:
        port = self.forced_port or self.discover()
        if not port:
            return False
        try:
            self.ser = serial.Serial(port, 115200, timeout=0.2, write_timeout=1)
            time.sleep(0.3)  # laisse le CDC s'etablir
            print(f"[focus-light] tige connectee sur {port}", flush=True)
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
            print("[focus-light] tige debranchee", flush=True)
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            return False


# ------------------------------------------------------------------ boucle


def run(args):
    cfg = load_config(args.config)
    token = args.token or os.environ.get("SP_TOKEN") or cfg.get("token")
    deep_tag = args.deep_tag or cfg.get("deepTag", "deep")
    port = args.port or cfg.get("port")

    wand = Wand(port)

    if args.test:
        color = {"red": "FF0000", "green": "00FF00", "orange": "FF5A00"}.get(
            args.test, args.test.lstrip("#")
        )
        if not wand.send(color, "solid"):
            sys.exit("tige introuvable — verifie le cable USB (donnees, pas juste charge)")
        print(f"[focus-light] test : {color}. Ctrl-C pour sortir.")
        try:
            while True:
                time.sleep(KEEPALIVE_S)
                wand.send(color, "solid")
        except KeyboardInterrupt:
            wand.send("000000", "off")
        return

    if not token:
        sys.exit(
            "Token manquant. Super Productivity > Settings > Misc > Access Token,\n"
            "puis :  export SP_TOKEN=<token>"
        )

    sp = SuperProductivity(token, deep_tag)
    last_state = None
    last_send = 0.0

    while True:
        try:
            state = sp.state()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, RuntimeError) as exc:
            state = "offline"
            if last_state != "offline":
                print(f"[focus-light] Super Productivity injoignable ({exc})", flush=True)

        now = time.monotonic()
        if state != last_state or now - last_send > KEEPALIVE_S:
            hexcolor, mode = PALETTE[state]
            if wand.send(hexcolor, mode):
                last_send = now
                if state != last_state:
                    print(f"[focus-light] {last_state} -> {state}", flush=True)
                    last_state = state

        if args.once:
            return
        time.sleep(POLL_S)


def main():
    ap = argparse.ArgumentParser(description="Super Productivity -> tige LED USB")
    ap.add_argument("--token", help="token REST local (sinon $SP_TOKEN ou config.json)")
    ap.add_argument("--port", help="port serie force, ex /dev/ttyACM0 ou COM4")
    ap.add_argument("--deep-tag", help="nom du tag qui declenche le rouge (defaut: deep)")
    ap.add_argument("--config", help="chemin d'un config.json")
    ap.add_argument("--once", action="store_true", help="une seule iteration")
    ap.add_argument("--test", help="force une couleur : red | green | orange | RRGGBB")
    args = ap.parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        Wand(args.port).send("000000", "off")
        print("\n[focus-light] bye")


if __name__ == "__main__":
    main()
