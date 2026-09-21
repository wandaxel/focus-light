#!/usr/bin/env python3
"""focus-hub — calcule l'etat "focus" et l'expose sur le tailnet.

Sources, par ordre de priorite decroissante :
  1. override manuel  (POST /override, ex. depuis un Raccourci iOS)
  2. evenement en cours dans le calendrier CalDAV "focus"
  3. etat pousse par l'agent macOS  (POST /agent, lit Rappels via ekctl)
  4. rien -> free

Endpoints :
  GET  /state              -> {"state":"deep","reason":"calendar:Refacto API", ...}
  GET  /health
  POST /override           {"state":"deep","minutes":50}   state: deep|working|free|auto
  POST /agent              {"state":"working","reason":"3 taches ouvertes"}
  GET  /                   -> PWA minimale (a ajouter a l'ecran d'accueil)

Auth : jeton Bearer partage, lu dans $HUB_TOKEN. Le service n'ecoute que sur
127.0.0.1 ; c'est Tailscale Serve qui l'expose en HTTPS sur le tailnet.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import caldav
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

CALDAV_URL = os.environ.get("CALDAV_URL", "http://127.0.0.1:5232")
CALDAV_USER = os.environ.get("CALDAV_USER", "user")
CALDAV_PASS = os.environ.get("CALDAV_PASS", "")
FOCUS_CALENDAR = os.environ.get("FOCUS_CALENDAR", "focus")
HUB_TOKEN = os.environ.get("HUB_TOKEN", "")
CAL_TTL = 30.0  # secondes de cache sur la requete CalDAV

VALID = {"deep", "working", "free", "auto"}

app = FastAPI(title="focus-hub", docs_url=None, redoc_url=None)

_override: dict | None = None
_agent: dict = {"state": "free", "reason": "aucun agent", "at": 0.0}
_cal_cache: tuple[float, str | None] = (0.0, None)


def auth(authorization: str = Header(default="")) -> None:
    if not HUB_TOKEN:
        raise HTTPException(500, "HUB_TOKEN non configure sur le serveur")
    if authorization != f"Bearer {HUB_TOKEN}":
        raise HTTPException(401, "jeton invalide")


class Override(BaseModel):
    state: str
    minutes: int = Field(default=60, ge=1, le=600)


class AgentPush(BaseModel):
    state: str
    reason: str = ""


def current_focus_event() -> str | None:
    """Titre de l'evenement en cours dans le calendrier focus, sinon None."""
    global _cal_cache
    now_mono = time.monotonic()
    if now_mono - _cal_cache[0] < CAL_TTL:
        return _cal_cache[1]

    title = None
    try:
        client = caldav.DAVClient(
            url=CALDAV_URL, username=CALDAV_USER, password=CALDAV_PASS
        )
        principal = client.principal()
        for cal in principal.calendars():
            if FOCUS_CALENDAR not in str(cal.url).lower():
                continue
            now = datetime.now(timezone.utc)
            for ev in cal.date_search(
                start=now - timedelta(hours=1), end=now + timedelta(hours=1)
            ):
                comp = ev.icalendar_component
                start, end = comp.get("dtstart"), comp.get("dtend")
                if not (start and end):
                    continue
                s, e = start.dt, end.dt
                if not isinstance(s, datetime):  # evenement journee entiere : ignore
                    continue
                if s.tzinfo is None:
                    s = s.replace(tzinfo=timezone.utc)
                if e.tzinfo is None:
                    e = e.replace(tzinfo=timezone.utc)
                if s <= now < e:
                    title = str(comp.get("summary", "bloc focus"))
                    break
            break
    except Exception as exc:  # CalDAV muet : on degrade, on ne casse pas
        print(f"[hub] CalDAV injoignable: {exc}", file=sys.stderr, flush=True)

    _cal_cache = (now_mono, title)
    return title


def resolve() -> dict:
    now = time.time()

    if _override and now < _override["until"]:
        return {
            "state": _override["state"],
            "reason": "override manuel",
            "source": "override",
            "expires_in": int(_override["until"] - now),
        }

    title = current_focus_event()
    if title:
        return {
            "state": "deep",
            "reason": f"bloc calendrier : {title}",
            "source": "calendar",
        }

    if now - _agent["at"] < 120:
        return {"state": _agent["state"], "reason": _agent["reason"], "source": "agent"}

    return {"state": "free", "reason": "rien en cours", "source": "default"}


@app.get("/health")
def health():
    return {"ok": True, "caldav": CALDAV_URL}


@app.get("/state", dependencies=[Depends(auth)])
def state():
    return resolve()


@app.post("/override", dependencies=[Depends(auth)])
def set_override(body: Override):
    global _override
    if body.state not in VALID:
        raise HTTPException(400, f"state doit etre parmi {sorted(VALID)}")
    if body.state == "auto":
        _override = None
        return {"ok": True, "cleared": True}
    _override = {"state": body.state, "until": time.time() + body.minutes * 60}
    return {"ok": True, "state": body.state, "minutes": body.minutes}


@app.post("/agent", dependencies=[Depends(auth)])
def agent_push(body: AgentPush):
    if body.state not in VALID - {"auto"}:
        raise HTTPException(400, "state invalide")
    _agent.update(state=body.state, reason=body.reason, at=time.time())
    return {"ok": True}


PWA = """<!doctype html><html lang=fr><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=apple-mobile-web-app-capable content=yes>
<meta name=apple-mobile-web-app-status-bar-style content=black-translucent>
<title>Focus</title><style>
:root{color-scheme:dark}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;padding:max(28px,env(safe-area-inset-top)) 20px 40px;
 font:16px/1.5 -apple-system,system-ui,sans-serif;background:#0b0d10;color:#e8eaed}
h1{font-size:15px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
 color:#8b9199;margin:0 0 20px}
#dot{width:104px;height:104px;border-radius:50%;margin:0 auto 18px;
 background:#2a2f36;transition:background .35s,box-shadow .35s}
#lbl{text-align:center;font-size:27px;font-weight:600;margin-bottom:4px}
#why{text-align:center;color:#8b9199;font-size:14px;margin-bottom:32px;min-height:21px}
button{width:100%;padding:16px;margin-bottom:10px;border:0;border-radius:14px;
 font-size:17px;font-weight:600;color:#fff;background:#1c2126}
button:active{transform:scale(.985)}
.deep{background:#c2373c}.free{background:#1e7a43}.auto{background:#2a3038}
</style>
<h1>Focus</h1><div id=dot></div><div id=lbl>…</div><div id=why></div>
<button class=deep onclick="ov('deep',50)">Deep focus · 50 min</button>
<button class=free onclick="ov('free',30)">Dispo · 30 min</button>
<button class=auto onclick="ov('auto',1)">Rendre la main à l'auto</button>
<script>
const C={deep:['#e5484d','Deep focus'],working:['#f0883e','Au travail'],
         free:['#2ea043','Disponible']};
const T=new URLSearchParams(location.search).get('t')||localStorage.t||'';
if(T)localStorage.t=T;
const H={'Authorization':'Bearer '+T,'Content-Type':'application/json'};
async function refresh(){try{
  const r=await fetch('state',{headers:H}); const d=await r.json();
  const [c,l]=C[d.state]||['#2a2f36','?'];
  dot.style.background=c; dot.style.boxShadow='0 0 60px -10px '+c;
  lbl.textContent=l; why.textContent=d.reason||'';
}catch(e){why.textContent='hors ligne'}}
async function ov(s,m){
  await fetch('override',{method:'POST',headers:H,
    body:JSON.stringify({state:s,minutes:m})});
  refresh();
}
refresh(); setInterval(refresh,5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
</script></html>"""


@app.get("/", response_class=HTMLResponse)
def pwa():
    return PWA
