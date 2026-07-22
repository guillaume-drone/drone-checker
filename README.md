# drone-checker

App perso pour Guillaume (pilote DJI Air 3S, basé à Lavaur/Tarn) : aide à savoir où/si il est légal de faire voler un drone en France.

- App live : https://guillaume-drone.github.io/drone-checker/
- Fichier source (unique) : `index.html` (HTML/CSS/JS tout-en-un), édité via l'éditeur web GitHub.

## Feature "Spot Drone"

Liste de spots intéressants à filmer en drone, triés région > département, dans le tableau JS `SPOTS_DRONE`.

Critères de sélection : garder patrimoine (tours, châteaux, églises/abbayes isolées), lieux insolites, curiosités naturelles/techniques remarquables. Exclure les lieux génériques sans intérêt particulier.

### Pipeline pour un nouveau département

1. Lister TOUS les spots communautaires sur drone-spot.tech pour le département (page `spots-drone-par-departements.aspx?id=XX`, ou la vue visuelle avec photos `carte-des-spots...`) — pas une sélection partielle.
2. Dédupliquer, filtrer selon les critères ci-dessus, présenter la shortlist complète à Guillaume et attendre une validation EXPLICITE avant de continuer (un "ok" sur un point voisin ne vaut pas validation de la liste).
3. Pour chaque spot retenu, récupérer les coordonnées EXACTES de la fiche drone-spot.tech (GoogleMaps: lat,lon) — jamais de géocodage approximatif par nom, jamais de décalage arbitraire (type +1km) sauf si le point exact est prouvé inconstructible et qu'un point de rechange proche (quelques centaines de mètres, justifié) est trouvé.
4. Vérifier chaque point :
   - DGAC : WFS `data.geopf.fr` (couche `TRANSPORTS.DRONES.RESTRICTIONS:carte_restriction_drones_lf`) avec un vrai test point-dans-polygone sur la géométrie complète (une intersection de bbox n'est PAS un test de containment — ça donne des faux positifs si on ne teste que ça).
   - RTBA : la carte officielle AZBA (https://www.sia.aviation-civile.gouv.fr/azbaEx/?lang=fr) fait foi pour les couloirs RTBA — ne pas se fier uniquement au WFS DGAC, qui reflète surtout les restrictions temporaires actives au moment de la requête, pas le RTBA statique. En pratique l'app AZBA (Ionic/Angular) n'expose pas de couche facilement automatisable (API bo-prod-sofia-vac.sia-france.fr protégée) : vérification par clic manuel sur la carte au point exact, ou via le fichier `data/uas_r.json` (zones R nationales, dont familles RTBA) déjà utilisé par l'app elle-même comme repli.
5. Si un spot est en interdiction permanente sans mécanisme de vérification en temps réel (ex. zone militaire hors réseau RTBA) : le RETIRER de la liste plutôt que de le garder avec un avertissement vague. Pas de conseil bidon type "contacter le gestionnaire de zone".
6. Intégrer dans `SPOTS_DRONE`, avec un champ `verif` clair et utile pour l'utilisateur final (pas de jargon de méthodo interne type "test précédent", "ancien test", "intersection de boîte" — juste "zone dégagée" / "hauteur plafonnée à X m").
7. Committer avec un message clair, vérifier l'app live après le commit (cache-buster sur l'URL raw/Pages, propagation possible 10s à quelques minutes).

### Travailler en visuel

Ouvrir dans des onglets Chrome visibles (pas de fetch invisible en arrière-plan quand Guillaume suit le travail) :
- la carte AZBA (azbaEx) pour le RTBA,
- la page drone-spot.tech du département (idéalement la vue visuelle avec photos, `spots-drone-par-departements.aspx?id=XX`, comme affichée à l'écran),
- l'éditeur GitHub du fichier en cours de modification.

### Astuces éditeur GitHub

- Le champ "Commit message" est parfois pré-rempli par une suggestion Copilot ("Update fmt.Println...", "Hello/Goodbye"...) — toujours vérifier la valeur réelle du champ juste avant de valider, pas seulement après l'avoir tapée (un clic sur "Commit changes..." peut rouvrir une nouvelle instance de dialogue et perdre la saisie précédente).
- Après avoir tapé dans CodeMirror ou dans les champs du dialogue de commit, revérifier par lecture directe de la valeur (`.value`) avant de cliquer sur le bouton final.
- Naviguer vers la page d'édition réinitialise le contexte `window.*` : refaire fetch + transformation + injection dans le même appel de script après navigation.

## Départements traités (113 spots au total)

| Dept | Nom | Spots |
|---|---|---|
| 82 | Tarn-et-Garonne | 4 |
| 81 | Tarn | 13 |
| 31 | Haute-Garonne | 27 |
| 09 | Ariège | 15 |
| 11 | Aude | 23 |
| 12 | Aveyron | 31 |

Prochains départements Occitanie possibles : Gers (32), Lot (46), Lozère (48), Hautes-Pyrénées (65), Gard (30), Hérault (34), Pyrénées-Orientales (66).
