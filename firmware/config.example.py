# config.py -- calibration et secrets. Ne pas publier ce fichier.
#
# A copier sur la carte AVANT main.py :
#     mpremote connect /dev/cu.usbmodemXXXXX fs cp config.py :config.py

# ---------------------------------------------------------------- matrice

PIN_MATRIX = 14

# Ordre des octets. Ton test a montre du VERT alors que tu demandais du ROUGE :
# la matrice est cablee en RGB, pas en GRB comme le suppose MicroPython.
#   (0,1,2,3) = RGB   |   (1,0,2,3) = GRB (defaut MicroPython)
ORDER = (0, 1, 2, 3)

# Sens de chainage des 64 LED. A confirmer avec test_mapping() ci-dessous.
#   "row"   : chaque rangee repart du meme bord
#   "snake" : une rangee sur deux est inversee
MAPPING = "row"

# La LED d'index 0 etait en bas a droite chez toi, donc 180.
# Valeurs possibles : 0, 90, 180, 270
ROTATION = 180

# ---------------------------------------------------------------- rendu

MODE = "panel"          # "panel" (dalle nue) ou "dome" (diffuseur)

# LINEAIRE, surtout pas de gamma ici : une WS2812 est ~lineaire sur ses 8 bits.
# 64 LED en blanc plein tirent 3,8 A ; un port USB en donne 0,5.
#   0.35 -> environ 450 mA en mode dalle, 950 mA en mode dome
# Ne depasse 0.35 que si la carte est sur une alimentation externe.
MAX_BRIGHTNESS = 0.35

SHOW_RING = True        # anneau de progression, mode dalle uniquement
FRAME_MS = 40           # 25 images/s ; monte si benchmark() est trop bas

# ---------------------------------------------------------------- reseau

WIFI_SSID = ""
WIFI_PASS = ""

# titan, sur le meme LAN. focus-hub doit ecouter sur 0.0.0.0 et non 127.0.0.1
# (change --host dans focus-hub.service), sinon la carte ne le joindra pas.
HUB_HOST = "192.168.1.20"
HUB_PORT = 8787
HUB_TOKEN = ""

POLL_S = 2              # intervalle d'interrogation de titan
WATCHDOG_S = 30         # sans nouvelle de titan au-dela : on s'eteint

USE_IMU = True          # QMI8658C : garde le degrade vertical quoi qu'il arrive
