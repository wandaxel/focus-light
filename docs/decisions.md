# Décisions mesurées

Ce fichier existe pour une raison précise : plusieurs réglages de ce projet
ressemblent à des choix arbitraires alors qu'ils viennent de mesures. Les
« corriger » de bonne foi casserait des propriétés qu'on a mis du temps à
obtenir. Chaque entrée dit ce qui a été mesuré et ce qu'on perd en revenant en
arrière.

Si vous changez l'un de ces points, ajoutez votre mesure ici.

---

## 1. La luminosité maîtresse est linéaire, sans gamma

**Ne pas** écrire `gain = brightness ** 2.2`.

Une WS2812 est à peu près linéaire en lumière sur ses 8 bits. Élever la
luminosité à la puissance 2,2 divise la sortie par dix : à 14 %, on obtient
3/255 au lieu de 36/255. Toute la dalle paraît noire et tous les états se
ressemblent.

La gamma a sa place pour lisser une rampe perçue, jamais pour atténuer un niveau
global. Ce bug a coûté une session entière de débogage.

## 2. Superposition de l'horloge : dy = 3, dx = 1

Mesuré sur les 1440 minutes de la journée.

| Décalage | Recouvrement moyen | Pire cas | Heures seules (min) | Minutes seules (min) |
|---|---|---|---|---|
| dy=0, dx=0 | 16,0 px | 25 | **0** | **0** |
| dy=3, dx=0 | 5,2 px | 8 | 10 | 9 |
| **dy=3, dx=1** | **3,0 px** | **6** | **11** | **10** |
| dy=3, dx=-1 | 2,8 px | 4 | 12 | 9 |

`dx=-1` semble meilleur mais tronque les minutes hors grille **à chaque
affichage**. Éliminé.

Le chiffre qui compte est la dernière colonne : en superposition exacte, le pire
cas tombe à zéro pixel dans la couleur propre. Le nombre disparaît entièrement
dans la couleur de recouvrement et l'heure devient illisible plusieurs fois par
jour.

## 3. Ambre et bleu, jamais rouge et vert

Distance perceptuelle minimale entre les trois couleurs du mode superposé :

| Triplet | Normal | Deutéranopie | Protanopie |
|---|---|---|---|
| rouge / vert → jaune | 289 | **162** | **164** |
| rouge / cyan → blanc | 366 | 332 | 282 |
| **ambre / bleu → blanc** | **378** | **351** | **359** |

L'axe bleu-jaune est préservé en deutéranopie comme en protanopie, qui touchent
8 % des hommes. C'est le seul triplet qui tienne dans tous les cas.

## 4. Sous un dôme, seules les animations radialement symétriques

Un dôme diffusant intègre la lumière. Écart de luminosité perçue entre huit
positions autour du dôme :

| Animation | Écart |
|---|---|
| uniforme, respiration, anneaux | 0–3 % |
| spirale, houle | 25–28 % |
| aurore, dérive, braises, plasma, dégradé | 48–60 % |
| balayage | 80 % |

Au-delà de ~12 %, un collègue au nord et un au sud **lisent deux états
différents**, ce qui ruine l'intérêt du 360°. D'où deux packs séparés :
`ANIMS_PANEL` pour la dalle nue, `ANIMS_DOME` pour le diffuseur.

Corollaire : aucun emoji n'est lisible sous un dôme. La diffusion détruit toute
structure fine.

## 5. Le deep focus est le niveau le plus sombre

Contre-intuitif. En partant d'un rouge vif, la distance colorimétrique avec
l'ambre du niveau « travail » ne dépassait pas 11,8 — indiscernable à cinq
mètres. Pousser l'ambre vers le jaune ne gagnait que 11 points et faisait monter
la consommation à 464 mA.

Assombrir le rouge porte la distance à 24,2 **et** divise sa consommation par
deux. C'est aussi meilleur en conception : quand on se concentre, on ne veut pas
une boîte lumineuse sur son bureau. Le niveau le plus intense doit être celui
qui appelle l'attention, pas celui qui demande le silence.

## 6. Le protocole série est en hexadécimal, avec somme de contrôle

**Ne pas** passer en binaire pour « gagner de la place ».

Un octet 0x03 dans un flux binaire est interprété comme un Ctrl-C par
MicroPython et tue le programme en pleine diffusion. Le surcoût du texte est de
9,4 ko/s, négligeable sur USB CDC.

La somme de contrôle XOR n'est pas du zèle non plus. Quand le navigateur passe
en arrière-plan, le système gèle l'écriture au milieu d'une ligne : elle part
tronquée et se recolle à la suivante. Si le recollement fait par hasard 384
caractères hexadécimaux valides, la dalle affiche du bruit saturé — elle
devient toute blanche. Reproduit en test, corrigé par la somme.

## 7. Les commandes en toutes lettres sont traitées avant les préfixes d'une lettre

`PING` commence par un P et se faisait avaler par la commande de progression
`P<valeur>`. Le keepalive était cassé, et avec lui le chien de garde. Garder
l'ordre actuel dans `handle_line`.

## 8. Le chien de garde, et pourquoi il est désactivable

Sans nouvelle de l'hôte pendant 30 s, la dalle s'éteint. C'est délibéré : une
dalle verte alors que le Mac dort depuis quarante minutes est pire qu'une dalle
éteinte, parce qu'elle ment et que les collègues cessent de la regarder au bout
d'une semaine.

La commande `H1` le neutralise pour que l'affichage survive au changement
d'onglet. Compromis assumé : un niveau affiché en mode maintien n'est plus une
information vérifiée, c'est la dernière chose déclarée.

## 9. Changement d'heure calculé à bord

MicroPython n'embarque aucune base de fuseaux. La règle européenne — dernier
dimanche de mars et d'octobre à 01:00 UTC — est calculée dans le firmware et
vérifiée sans écart contre la base système sur cinq ans : 01:59 devient 03:00 en
mars, 02:59 redevient 02:00 en octobre.

## 10. La carte n'a pas de pile RTC

Coupure de courant, heure perdue. Deux sources : NTP si le Wi-Fi est configuré,
ou la commande `T<epoch>` envoyée par la page. Ne pas supposer que l'heure est
juste au démarrage.

## 11. MicroPython ≥ 1.26, variante standard

L'ESP32-S3FH4R2 a 4 Mo de flash et 2 Mo de PSRAM **quad**. La variante
`spiram-oct` provoque un redémarrage en boucle. Avant la 1.26, les images
standard dépassaient la taille de flash sur les S3 de 4 Mo ; c'est corrigé
depuis.

Diagnostic : `os.statvfs('/')` qui ne renvoie que des zéros signifie que le
système de fichiers n'a pas été créé — mauvaise variante.

## 12. Les trames partent en ordre logique

La page envoie les pixels de gauche à droite et de haut en bas. Rotation et
serpentin sont appliqués par la table `LUT` du firmware. La calibration ne vit
ainsi qu'à un seul endroit, `config.py`, et le navigateur n'a pas besoin de la
connaître.
