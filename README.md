# focus-light

Un signal de disponibilité pour open space : une matrice 8×8 RGB posée sur le
bureau qui indique, d'un coup d'œil et à cinq mètres, si on peut vous
interrompre. Cinq niveaux, deux optiques, six modes d'horloge, et une page de
contrôle qui pilote la carte par USB sans rien installer.

![état](https://img.shields.io/badge/état-alpha-orange) ![licence](https://img.shields.io/badge/licence-MIT-blue)

---

## Ce que ça fait

| Niveau | Couleur | Sens |
|---|---|---|
| Deep focus | rouge sombre | ne pas déranger |
| Montage | violet | travail en flux, interruption coûteuse |
| Travail | ambre | occupé mais interruptible |
| Dispo | vert | venez |
| Éteint | — | machine absente, le signal ne ment pas |

La dalle peut aussi afficher 25 glyphes 8×8 et une horloge à six modes, dont un
mode superposé où heures et minutes cohabitent dans deux couleurs distinctes.

## Matériel

- **Waveshare ESP32-S3-Matrix** — ESP32-S3FH4R2, 8×8 WS2812B sur GPIO14,
  QMI8658C en I²C (SDA 11, SCL 12, adresse 0x6B)
- MicroPython **≥ 1.26**, variante `ESP32_GENERIC_S3` standard (surtout pas
  `spiram-oct` : la PSRAM de cette puce est quad, pas octale)
- Un câble USB-C **données**, et une alimentation externe si vous montez la
  luminosité (voir la section consommation)

Des variantes pour tige LED WS2812 et pour LED RGB récupérée sur cigarette
électronique jetable sont dans `firmware/legacy/`.

## Démarrage

```bash
# 1. flasher MicroPython
pipx install esptool mpremote
esptool --chip esp32s3 erase-flash
esptool --chip esp32s3 write-flash 0 ESP32_GENERIC_S3-*.bin

# 2. configurer
cp firmware/config.example.py firmware/config.py
$EDITOR firmware/config.py          # Wi-Fi, hôte, jeton, calibration

# 3. déployer
mpremote fs cp firmware/config.py :config.py
mpremote fs cp firmware/main.py :main.py + reset
```

Deux clignotements bleus signalent que ça tourne.

Ouvrez ensuite `web/controle.html` dans **Chrome ou Edge** — Safari ne gère pas
Web Serial — et cliquez sur la pastille de connexion.

### Calibrer la matrice

Le sens de chaînage des 64 LED et l'ordre des octets varient entre révisions
Waveshare. Trois outils dans le REPL :

```python
import main
main.test_order()     # RGB ou GRB ?
main.test_mapping()   # lignes ou serpentin ?
main.test_chase()     # à comparer au chenillard de la page web
main.benchmark()      # images par seconde réelles
```

Reportez les résultats dans `config.py`.

## Architecture

```
navigateur (Chrome)  ──USB série──▶  ESP32-S3 + matrice 8×8
   page de contrôle                    rendu autonome si le navigateur se tait

serveur focus-hub    ──HTTP/LAN──▶  ESP32-S3
   état consolidé                      calendrier + rappels + override

agent macOS (EventKit) ──▶ focus-hub
   lit Google Agenda et Rappels par le Mac, sans clé API
```

La page peut **diffuser les trames** à 25 images/s : la dalle affiche alors
exactement ce que montre l'aperçu. Dès que l'onglet passe en arrière-plan, la
page rend la main et la carte poursuit seule.

## Consommation

64 LED en blanc plein tirent **3,8 A**. Un port USB en fournit 0,5. Le plafond
de luminosité n'est pas de la prudence, c'est une condition de fonctionnement.

| Affichage | Pic mesuré @35 % |
|---|---|
| Horloge, mode aiguilles | 61 mA |
| Animations, dalle nue | 497 mA |
| Horloge, mode superposé | 632 mA |
| Animations, dôme diffusant | 954 mA |

Au-delà de ~500 mA il faut un hub USB alimenté ou une alimentation externe.

## Contribuer

Lisez d'abord **[docs/decisions.md](docs/decisions.md)**. Plusieurs choix qui
paraissent arbitraires sont en réalité mesurés, et les « corriger » casse des
propriétés qu'on a payées cher. Puis [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. Voir [LICENSE](LICENSE).
