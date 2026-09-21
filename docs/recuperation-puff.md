# Variante « récup puff » — construire la tige à partir de déchets

Cadre légal : loi n° 2025-175 du 24 février 2025, en vigueur depuis le 26 février
2025. Fabrication, vente et distribution gratuite de puffs interdites en France
(100 000 € d'amende, 200 000 € en récidive). **La détention et le démontage par
un particulier ne sont pas visés.** Ton gisement légitime : bacs DEEE, points de
collecte en bureau de tabac, appareils déjà achetés avant l'interdiction.

---

## 1. Sécurité — à lire avant d'ouvrir quoi que ce soit

Deux dangers, dont un largement sous-estimé.

**La nicotine.** Le pod contient du e-liquide aux sels de nicotine, qui traverse
la peau. C'est le risque le plus probable et le plus négligé du démontage.
Gants nitrile, travaille sur du papier absorbant, ne coupe jamais dans la
cartouche, lave-toi les mains ensuite. Le risque batterie est plus spectaculaire,
celui-là est plus fréquent.

**La cellule lithium.** Mesure sa tension **avant tout autre geste** :

| Tension à vide | Verdict |
|---|---|
| > 3,0 V | saine, exploitable |
| 2,5 – 3,0 V | limite, à charger sous surveillance |
| **< 2,5 V** | **recyclage, pas de récupération** |

Le seuil de 2,5 V n'est pas arbitraire : c'est le seuil de coupure en décharge
du DW01A, avec un rétablissement à 2,9 V. Une cellule restée longtemps sous ce
seuil voit son collecteur de courant en cuivre se dissoudre puis se redéposer en
dendrites à la recharge. Résultat : court-circuit interne, éventuellement
plusieurs heures après la charge, quand tu n'es plus devant. C'est précisément
le scénario qui rend cette récup dangereuse quand on la fait à l'aveugle.

Autres règles : jamais de perçage, jamais de cellule gonflée, première charge
dans un contenant ininflammable et sous surveillance, pas de soudure prolongée
sur le corps de la cellule.

---

## 2. Ce qui vaut la peine — et ce qui ne la vaut pas

| Pièce | Verdict | Pourquoi |
|---|---|---|
| **Guide de lumière** (tube acrylique translucide) | **le meilleur morceau** | c'est exactement le diffuseur à 5 € de la v1, en gratuit et déjà à la bonne longueur |
| **LED RGB** (SMD 4 broches, anode commune) | **oui** | suffisante pour du rouge/orange/vert fixe |
| **FS8205A** (double MOSFET N du BMS) | **oui, usage détourné** | deux canaux de commutation en SOT-23-6, parfaits en driver LED côté bas |
| **TP4056 / DW01A** (charge + protection) | à garder en pièce détachée | utile ailleurs, pas ici |
| **Cellule LiPo** | **non, pas pour cette tige** | voir ci-dessous |
| MCU d'origine | non | ROM masquée, pas de pads de debug, inutilisable |

### Pourquoi ne pas réutiliser la batterie ici

C'est contre-intuitif, donc je détaille. La tige de l'open space est pilotée par
jupiter en USB, et le firmware coupe délibérément la lumière après 30 s de
silence de l'hôte. Une batterie permettrait à la tige de **continuer à briller
alors que ton Mac est fermé et que tu es parti déjeuner**. Elle rendrait le
signal capable de mentir — exactement le défaut qu'on a passé la v1 à éliminer.

L'autonomie n'est pas une fonctionnalité ici, c'est une régression. Garde la
cellule et son BMS pour un autre projet, ou recycle-la.

---

## 3. Le FS8205A en driver LED

C'est la réutilisation la plus élégante du BMS. Le FS8205A contient **deux
MOSFET canal N** en boîtier SOT-23-6, montés tête-bêche par le constructeur pour
couper le courant dans les deux sens. Dessoudé et utilisé séparément, chaque
MOSFET devient un interrupteur côté bas parfaitement adapté à un canal de LED.

Deux FS8205A récupérés = quatre canaux, tu n'en as besoin que de trois.

L'intérêt réel : les GPIO du RP2040 sont limités à 12 mA, ce qui donne une tige
terne à cinq mètres dans un open space éclairé. Passer par un MOSFET permet
d'alimenter les LED en 5 V depuis VBUS tout en gardant une commande en 3,3 V.

```
VBUS 5V ──┬── [R rouge 150Ω] ── anode commune LED RGB
          │
   (les 3 cathodes descendent vers les drains)

GP2 ──[100Ω]──┤ grille   MOSFET 1  drain ── cathode R
GP3 ──[100Ω]──┤ grille   MOSFET 2  drain ── cathode G
GP4 ──[100Ω]──┤ grille   MOSFET 3  drain ── cathode B
                          sources ── GND commun
```

Résistances de limitation, pour 20 mA par canal sous 5 V :

| Canal | Vf typique | Résistance |
|---|---|---|
| Rouge | 2,0 V | 150 Ω |
| Vert | 3,2 V | 91 Ω |
| Bleu | 3,2 V | 91 Ω |

Le bleu ne sert qu'au double clignotement de démarrage — rouge, orange et vert
n'en utilisent pas un lumen.

### Identifier la LED RGB au multimètre

Mode diode. La broche commune est celle qui conduit vers les trois autres.
Si elle conduit quand la **pointe rouge** y est posée, c'est une **anode
commune** (le cas courant, et celui du câblage ci-dessus). Si c'est l'inverse,
c'est une cathode commune : il faut alors inverser le montage et piloter côté
haut, ce qui complique. Trie tes LED récupérées, garde les anodes communes.

---

## 4. Le guide de lumière

C'est la pièce qui justifie à elle seule le démontage. Beaucoup de puffs
« lumineuses » embarquent un tube acrylique translucide sur toute leur longueur,
soit 8 à 12 cm — dans la fourchette visée.

Pour qu'il diffuse au lieu de faire un point brillant à une extrémité :

- **Dépolir la surface** au papier de verre 400 puis 800, à sec. Les micro-rayures
  extraient la lumière tout au long du tube au lieu de la laisser filer.
- **Une LED à chaque extrémité**, dirigées vers l'intérieur. Ça double le flux et
  supprime le dégradé qu'on obtient avec une seule source.
- **Peindre l'extrémité opposée en blanc** si tu n'as qu'une LED : elle renvoie
  la lumière au lieu de la perdre.

Colle les LED au contact du tube, sans lame d'air : le moindre interstice divise
le couplage optique par deux ou trois.

---

## 5. Bilan

| Poste | v1 achetée | variante récup |
|---|---|---|
| Diffuseur | 5 € | 0 € |
| LED | 6 € (bandeau) | 0 € |
| Driver | — | 0 € (FS8205A) |
| Résistances | — | ~0 € |
| **RP2040** | **5–8 €** | **5–8 €** (incompressible) |
| Câble USB | — | à récupérer aussi |

Environ 6 € au lieu de 20 €, et surtout trois déchets électroniques détournés de
l'incinérateur. Le microcontrôleur reste le seul achat obligatoire.

Firmware correspondant : `firmware/main_rgb.py`, qui remplace le pilotage WS2812
par trois canaux PWM. Le protocole série est identique, donc `focus_agent.py`
fonctionne sans modification.
