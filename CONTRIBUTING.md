# Contribuer

Merci de passer par ici avant d'ouvrir une pull request. Ce projet pilote du
matériel réel dans un bureau partagé : une régression ne se voit pas dans une
console, elle se voit quand un collègue se fait interrompre en pleine
concentration.

## Avant tout : lisez `docs/decisions.md`

Plusieurs réglages ressemblent à des valeurs arbitraires et sont en réalité le
résultat de mesures. La luminosité linéaire, les décalages de l'horloge, le
couple ambre/bleu, la séparation des deux packs d'animation. Les « corriger »
casse des propriétés payées cher.

Si vous changez l'un de ces points, **ajoutez votre mesure au fichier**. Une
décision non documentée sera défaite par quelqu'un d'autre dans six mois.

## Ne jamais commiter

- `firmware/config.py` — il contient votre Wi-Fi et vos jetons. Utilisez
  `config.example.py` comme modèle.
- Un mot de passe, un jeton, une adresse de tailnet, une adresse MAC.
- Un identifiant réel de machine ou de personne dans la documentation.

Git n'oublie rien. Un secret poussé une fois reste dans l'historique même
après suppression, et un dépôt privé peut devenir public. En cas d'accident,
révoquez le secret immédiatement — ne vous contentez pas d'un commit de
correction.

## Tester avant de proposer

Le matériel n'est pas toujours sous la main, mais l'essentiel se vérifie sans.

**Firmware** — il s'importe avec des modules simulés :

```bash
python3 -c "import ast; ast.parse(open('firmware/main.py').read())"
```

Les fonctions pures — `_ramp`, `field`, `led_index`, `_build_ring`, `handle_line`
— se testent en stubant `machine`, `neopixel` et `time`. Vérifiez en
particulier que **aucune commande malformée ne lève d'exception** : le parseur
série tourne dans la boucle de rendu, une exception éteint la dalle.

**Page web** — le script doit parser et tous les identifiants exister :

```bash
node -e "const h=require('fs').readFileSync('web/controle.html','utf8');
new Function(h.split('<script>')[1].split('</'+'script>')[0]);
console.log('ok')"
```

**Toute nouvelle animation** doit rester bornée entre 0 et 1 sur au moins
150 images, sinon elle sature ou clignote. Mesurez aussi son pic de courant :
au-delà de 500 mA à 35 %, précisez-le dans la PR.

## Ajouter une animation

1. Dans le bon pack. `ANIMS_PANEL` pour la dalle nue, `ANIMS_DOME` **uniquement
   si elle est radialement symétrique** — sinon deux personnes placées de part
   et d'autre du dôme liront deux états différents.
2. Signature `(x, y, t, amp) -> 0..1`, sans état interne : elle doit rendre la
   même image pour le même `t`.
3. Dans les deux fichiers, `firmware/main.py` et `web/controle.html`, avec un
   calcul identique. C'est ce qui garantit que l'aperçu ne ment pas.
4. Un nom dans `FR` pour l'interface.

## Ajouter un glyphe

Huit lignes de huit caractères, `.` pour éteint, un chiffre hexadécimal pour un
index de palette. La palette compte au plus 16 entrées. Un glyphe animé est une
liste d'images.

Attention à la consommation : un glyphe qui remplit la dalle en jaune monte à
735 mA. Préférez les formes ajourées.

## Style

- Français dans les commentaires et l'interface, le projet est francophone.
- Les commentaires expliquent **pourquoi**, pas quoi. `# somme de controle` n'a
  aucun intérêt ; « sans elle, une trame recollée affiche du bruit saturé » en a.
- Pas d'accent dans le code MicroPython : l'encodage du REPL est capricieux.
- Le firmware doit tourner sans réseau, sans IMU et sans `states.json`. Toute
  dépendance optionnelle va dans un `try` avec une valeur de repli.

## Pull requests

Une PR par sujet. Décrivez ce que vous avez mesuré, pas seulement ce que vous
avez changé. Si vous avez testé sur du matériel, dites lequel et quelle
révision — le brochage Waveshare varie.
