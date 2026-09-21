# Déploiement

> **Les identifiants de ce document sont des espaces réservés.**
> Remplacez `<HUB_TOKEN>`, `<MOT_DE_PASSE_CALDAV>` et `<tailnet>` par vos
> valeurs, et gardez-les hors de git. Voir `CONTRIBUTING.md`.

## Ce qui tourne déjà sur titan

Installé et testé, en espace utilisateur (aucun paquet système touché) :

| Service | Où | Port | État |
|---|---|---|---|
| Radicale 3.7.8 | pipx, `~/.local/bin/radicale` | 127.0.0.1:5232 | actif, `systemctl --user` |
| focus-hub | venv, `~/focus-hub/` | 127.0.0.1:8787 | actif, `systemctl --user` |

Collections CalDAV créées sous `~/.local/share/radicale/collections/collection-root/user/` :

- **`focus`** (VEVENT) — les blocs de deep work. Un événement en cours ⇒ rouge.
- **`agenda`** (VEVENT) — ton agenda normal, sans effet sur la tige.
- **`taches`** (VTODO) — tâches, lisibles par tout client CalDAV.

Secrets à mettre dans ton gestionnaire de mots de passe :

```
CalDAV   user / <MOT_DE_PASSE_CALDAV>
HUB_TOKEN  <HUB_TOKEN>
```

Le mot de passe CalDAV est en clair dans `~/focus-hub/env` (chmod 600) et haché
en bcrypt dans `~/.config/radicale/users`. Le `HUB_TOKEN` est le même pour la
PWA, les Raccourcis iOS et l'agent jupiter — si tu veux les cloisonner plus
tard, il faudra passer à un jeton par client.

---

## 1. Trois commandes root, à passer toi-même

Je n'ai pas ton mot de passe sudo, et c'est très bien ainsi.

```bash
# a) les services --user survivent à la déconnexion SSH
sudo loginctl enable-linger user

# b) tailscale utilisable sans sudo
sudo tailscale set --operator=user

# c) exposition HTTPS sur le tailnet, avec vrai certificat Let's Encrypt
tailscale serve --bg --set-path /dav  http://127.0.0.1:5232
tailscale serve --bg --set-path /focus http://127.0.0.1:8787
tailscale serve status
```

Le point (a) n'est pas cosmétique : sans lui, Radicale et focus-hub s'arrêtent
quand ta session SSH se ferme, et tu passeras une soirée à te demander pourquoi
ton calendrier a disparu.

Après ça :
- CalDAV → `https://titan.<tailnet>.ts.net/dav/`
- Hub / PWA → `https://titan.<tailnet>.ts.net/focus/`

Rien n'est exposé sur internet. Le certificat est valide, ce qui compte : iOS
est réticent avec le CalDAV en HTTP nu, et c'est la cause n°1 des « échec de la
vérification du compte CalDAV » qu'on trouve dans les issues Radicale.

---

## 2. iPhone — le calendrier

Réglages → Apps → Calendrier → Comptes → Ajouter → Autre → **Ajouter un compte CalDAV**

```
Serveur         titan.<tailnet>.ts.net
Nom d'utilisateur   user
Mot de passe    <MOT_DE_PASSE_CALDAV>
Avancé → URL du compte   https://titan.<tailnet>.ts.net/dav/user/
```

Les calendriers `Focus` et `Agenda` apparaissent dans l'app Calendrier native.
Tu poses un bloc « Refacto API 14h–16h » dans **Focus** depuis ton iPhone, et la
tige passe au rouge à 14h toute seule.

Rappel du bloqueur : les tâches (VTODO) de la collection `taches` **n'apparaîtront
pas** dans l'app Rappels. C'est une limite Apple, pas un défaut de config. Elles
sont là pour être lues par titan et par des clients CalDAV tiers.

---

## 3. iPhone — les Rappels et le mode Concentration

Dans l'app **Rappels**, crée une liste nommée exactement `Focus`. La convention :

| Rappels | Tige |
|---|---|
| Une entrée non cochée dans la liste `Focus` | rouge |
| Une échéance aujourd'hui ailleurs | orange |
| Rien | vert |

Tu peux la remplir à la voix : « Dis Siri, ajoute Refacto API à Focus. » La
synchro iPhone → jupiter passe par iCloud, donc quelques secondes de latence.

**L'automatisation qui change tout.** Raccourcis → Automatisation → Concentration
→ *Travail* → « Est activé » → Exécuter immédiatement :

> Obtenir le contenu de `https://titan.<tailnet>.ts.net/focus/override`
> Méthode **POST** · En-tête `Authorization: Bearer <HUB_TOKEN>`
> Corps JSON : `state` = `deep`, `minutes` = `50`

Duplique avec « Est désactivé » → `state` = `auto`. Tu bascules ton iPhone en
mode Travail, la tige passe au rouge instantanément — sans polling, sans app.

**La PWA.** Ouvre `https://titan.<tailnet>.ts.net/focus/?t=<HUB_TOKEN>` dans
Safari, puis Partager → Sur l'écran d'accueil. Le jeton est mémorisé en
localStorage au premier chargement ; ensuite l'URL sans `?t=` suffit.

---

## 4. jupiter — l'agent et la tige

```bash
# ekctl : le pont EventKit vers Rappels et Calendrier
curl -L -o ekctl.tar.gz https://github.com/schappim/ekctl/releases/download/v1.5.0/ekctl-v1.5.0.tar.gz
tar -xzf ekctl.tar.gz
xattr -d com.apple.quarantine ekctl      # binaire ad-hoc signé, non notarisé
sudo mv ekctl /usr/local/bin/

pip3 install pyserial requests

export HUB_URL=https://titan.<tailnet>.ts.net/focus
export HUB_TOKEN=<HUB_TOKEN>

python3 focus_agent.py --check     # diagnostic
python3 focus_agent.py             # en marche
```

Au premier `--check`, macOS demande l'autorisation d'accès aux Rappels. Si tu
lances depuis iTerm ou VS Code, c'est **à cette app** que la permission est
accordée, pas à Python — d'où des surprises si tu changes de terminal ensuite.

Vérifie le checksum publié à côté de l'archive avant de retirer la quarantaine.
Tu télécharges un binaire non notarisé auquel tu vas donner accès à tous tes
rappels et rendez-vous ; ça mérite trente secondes.

### Démarrage automatique

`~/Library/LaunchAgents/com.user.focus-agent.plist`, avec `RunAtLoad` et
`KeepAlive`, `EnvironmentVariables` pour les deux variables, puis
`launchctl load -w` le fichier.

---

## 5. Ordre de priorité des signaux

```
1. override manuel        Raccourci iOS ou PWA        expire tout seul
2. bloc calendrier Focus  en cours maintenant          → deep
3. Rappels via jupiter    liste Focus / échéances      → deep | working
4. rien                                                → free
5. titan injoignable                                   → tige éteinte
6. agent muet > 30 s                                   → tige éteinte (watchdog firmware)
```

Les deux derniers niveaux sont volontaires. Une tige verte pendant que jupiter
dort est pire qu'une tige éteinte : elle ment, et tes collègues cessent de la
regarder au bout d'une semaine.

---

## 6. Sauvegarde

Radicale stocke tout en `.ics` sur disque. La sauvegarde tient en une ligne :

```bash
tar czf ~/backup-caldav-$(date +%F).tgz ~/.local/share/radicale/collections
```

Encore mieux, un dépôt git dans le dossier des collections avec un commit
quotidien : tu récupères l'historique complet de tes calendriers gratuitement.
À brancher sur la routine de sauvegarde qui existe déjà sur titan.

---

## 7. Ce qui reste ouvert

- **Miroir tâches → titan.** L'agent lit les Rappels mais ne les recopie pas
  encore dans la collection `taches`. Une passe `ekctl list reminders --json`
  → `PUT` VTODO donnerait une archive interrogeable côté serveur. C'est le
  chaînon qui rendrait le « contrôle complet » réellement complet.
- **Jeton par client.** Un seul `HUB_TOKEN` partagé entre PWA, Raccourcis et
  agent : révoquer l'un révoque tout.
- **Radicale en 3.7.8 via pipx** n'est pas suivi par `apt`. Pense à
  `pipx upgrade radicale` de temps en temps.
- **Le mode Concentration iOS** est le meilleur déclencheur du lot. Si tu ne
  devais en garder qu'un, ce serait celui-là.
