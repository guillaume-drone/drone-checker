# Drone Checker — Contexte projet complet

Document de suivi consolidé, à relire en entier au début d'un nouveau chat.

## Contexte général

Guillaume (pilote DJI Air 3S) développe "Drone Checker", une app web d'aide à la décision pour savoir où/si il est légal de faire voler un drone en France. Il est basé en Occitanie / Nouvelle-Aquitaine et se rend aussi en Bretagne (Côtes-d'Armor) en juillet.

- App live : https://guillaume-drone.github.io/drone-checker/
- Repo GitHub : https://github.com/guillaume-drone/drone-checker
- Fichier source unique : `index.html` (HTML/CSS/JS tout-en-un), édité exclusivement via l'éditeur web GitHub (`.../edit/main/index.html`) — le sandbox de l'agent n'a pas d'accès direct git/réseau au repo.

### Deux volets du projet

1. **Météo & réglementation Bretagne** (Côtes-d'Armor) — développé lors de sessions précédentes :
   - Météo calibrée Air 3S (vent, rafales, nébulosité, lever/coucher soleil, prévisions, indice Kp).
   - Zones réglementaires Bretagne codées en dur (Saint-Brieuc, Lannion, Rennes, Brest, Coëtquidan/R17, Parc Armorique).
   - NOTAMs intégrés (SUP AIP), connexion live DGAC WFS (`data.geopf.fr`, couche `TRANSPORTS.DRONES.RESTRICTIONS`), carte `cartes.gouv.fr` en iframe.
   - Bug connu non confirmé résolu : `reverseGeo`/Nominatim renvoyait parfois le polygone France entière comme "zone habitée" au-dessus de l'eau — fix prévu : filtrer par taille de bounding box (< 0.5°).
   - Spots Côtes-d'Armor identifiés mais non intégrés en base : Pointe du Roselier, Lac de Guérlédan, Château de la Hunaudaye, Sillon de Talbert, Cap Fréhel, Fort La Latte, Gouffre de Plougrescant, Côte de Granit Rose, Île de Bréhat, Cap d'Erquy.

2. **Feature "Spot Drone"** : liste de spots à filmer, triés région > département, dans le tableau JS `SPOTS_DRONE`, département par département en Occitanie.

## Pipeline pour un nouveau département (Spot Drone)

1. Lister TOUS les spots communautaires sur drone-spot.tech pour le département — page `spots-drone-par-departements.aspx?id=XX` (liste texte) ou vue visuelle avec photos `carte-des-spots-pour-faire-voler-son-drone.aspx` filtrée par département. Pas une sélection partielle : la liste complète d'abord.
2. Dédupliquer (plusieurs fiches pointent parfois le même lieu), filtrer selon les critères (garder patrimoine/insolite/naturel remarquable, exclure le générique), présenter la shortlist complète à Guillaume et **attendre une validation explicite** avant de continuer — une réponse sur un point voisin ne vaut pas validation de la liste entière. En cas de doute sur l'intérêt d'un spot (patrimoine/insolite/naturel remarquable vs générique), vérifier sur Google Maps le nombre et la positivité des avis du lieu avant de trancher.
3. Coordonnées EXACTES de la fiche drone-spot.tech (`GoogleMaps: lat,lon`) pour chaque spot retenu. Jamais de géocodage approximatif par nom (Nominatim), jamais de décalage arbitraire type +1km. Si un point exact est prouvé inconstructible, chercher un point de rechange proche (quelques centaines de mètres, justifié) plutôt que déplacer loin.
4. Vérifier chaque point sur DEUX couches distinctes, ne pas se contenter d'une seule :
   - **DGAC** : WFS `data.geopf.fr` (couche `TRANSPORTS.DRONES.RESTRICTIONS:carte_restriction_drones_lf`) avec un vrai test point-dans-polygone sur la géométrie complète (`GeoJSON Polygon/MultiPolygon`, coordonnées `[lon,lat]`). Une intersection de bbox n'est PAS un test de containment. Attention aussi aux propriétés `limite` (hauteur/interdiction) et `remarque` du GeoJSON retourné : certaines zones ont `limite:null` avec pour seule `remarque` « Notification préalable obligatoire pour les aéronefs de masse supérieure à 900g » (aucune mention d'interdiction) — ce n'est PAS une restriction floue à traiter comme telle, c'est la règle standard catégorie ouverte A3, qui ne concerne pas le DJI Air 3S (724 g, sous le seuil de 900 g). Le popup `dgacPopup()` de l'app distingue ce cas précis (regex sur `remarque`, absence du mot « interdit ») d'une vraie ambiguïté avant d'afficher « Restriction imprécise ». Pour vérifier une zone signalée comme imprécise : requêter le WFS DGAC en direct (`data.geopf.fr`) sur le point ou une petite bbox autour, lire `properties.limite` et `properties.remarque` — si le motif ci-dessus apparaît, c'est une fausse alerte pour l'Air 3S.
   - **RTBA / zones nationales R-D-P-CTR** : fichiers `data/uas_r.json`, `uas_d.json`, `uas_p.json`, `uas_ctr.json` de l'app elle-même. Structure `zone.geom = [{t:"poly", c:[ring0, ring1, ...]}]` où **chaque ring est LUI-MÊME un tableau de points `[lon,lat]`** — donc pour tester un point il faut `zone.geom[i].c[0]` (le premier ring), PAS `zone.geom[i].c` directement (qui est le tableau de rings, un niveau au-dessus). Voir "Bug critique" plus bas.
   - La carte officielle AZBA (https://www.sia.aviation-civile.gouv.fr/azbaEx/?lang=fr) reste la référence humaine ultime pour le RTBA, mais c'est une appli Ionic/Angular sans carte scriptable facilement (pas de Leaflet standard, API `bo-prod-sofia-vac.sia-france.fr` protégée par token non reproductible en fetch simple). En pratique : utiliser `uas_r.json` (avec le bug ci-dessus corrigé) comme méthode principale, recouper visuellement sur AZBA ou sur le bouton "AZBA" intégré à l'app elle-même (qui affiche le même popup avec nom de zone + explication RTBA vs permanent) en cas de doute.
5. RTBA vs zone permanente : `RTBA_R_CODES` (dans `index.html`) liste les codes de zones RTBA officielles (45,46,56,57,69,139,142-145,147,149,152,165,166,191,193,589-593). Si une zone R touchée a un code dans cette liste → RTBA, vérification AZBA du jour requise, spot gardé avec badge `rtbaZone`. Si le code n'y est PAS (ex. R108 Istres) → zone permanente hors réseau RTBA, n'apparaît pas sur AZBA, vol interdit sauf accord du gestionnaire de zone (accord peu réaliste pour un pilote loisir) → **retirer le spot**, pas de badge d'avertissement vague.
6. Un spot en interdiction permanente sans mécanisme de vérification en temps réel = retiré de la liste, pas gardé avec un avertissement. Pas de conseil bidon type "contacter le gestionnaire de zone" comme option réaliste.
7. Champ `verif` de chaque spot = message clair et utile pour l'utilisateur final de l'app (ex. "✅ Zone dégagée (DGAC + RTBA vérifiés)." ou "⚠️ Hauteur plafonnée à X m à cet endroit"). Jamais de jargon de méthodo interne dans ce champ (pas de "test précédent", "ancien test", "intersection de boîte", comparaisons avant/après — ça n'a aucune valeur pour l'utilisateur de l'app).
8. Committer avec un message clair reflétant vraiment ce qui a changé, vérifier l'app live après coup (cache-buster sur l'URL, propagation possible de quelques secondes à plusieurs minutes).

### Travailler en visuel

Ouvrir dans des onglets Chrome visibles (pas de fetch invisible quand Guillaume suit le travail) :
- la carte AZBA (azbaEx) pour le RTBA,
- la page drone-spot.tech du département (vue liste ou vue visuelle avec photos),
- l'éditeur GitHub du fichier en cours de modification.

### Pièges techniques connus (éditeur GitHub)

- Le champ "Commit message" est très souvent écrasé par une suggestion Copilot aléatoire ("Update fmt.Println...", "Hello/Goodbye"...), y compris APRÈS l'avoir rempli correctement (effet retardé/asynchrone). Toujours revérifier `.value` juste avant de cliquer sur "Commit changes", avec un court délai d'attente (~1-1.5s) après avoir tapé, puis re-vérifier.
- Le bouton "Commit changes" de la modale ne réagit pas toujours à un simple `.click()` — utiliser une séquence complète d'événements (`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`) avec les bonnes coordonnées si le premier essai ne navigue pas vers la vue blob.
- Naviguer vers la page d'édition réinitialise tout le contexte `window.*` : refaire fetch + transformation + injection dans le même appel de script après une navigation.
- Le cache de l'API GitHub Contents / raw.githubusercontent.com peut avoir quelques secondes de retard juste après un commit — si une vérification semble montrer l'ancien contenu, réessayer une fois avant de conclure à un échec.
- Certaines requêtes fetch avec du texte de test contenant des motifs qui ressemblent à des cookies/tokens sont bloquées par un filtre de sécurité interne à l'environnement de l'agent ("BLOCKED: Cookie/query string data") — reformuler la requête (par ex. ne pas dumper de larges portions de `outerHTML`).

## État des départements (SPOTS_DRONE)

| Dept | Nom | Spots |
|---|---|---|
| 82 | Tarn-et-Garonne | 4 |
| 81 | Tarn | 13 |
| 31 | Haute-Garonne | 27 |
| 09 | Ariège | 15 |
| 11 | Aude | 23 |
| 12 | Aveyron | 21 |

Total : 103 spots. Prochains départements Occitanie possibles : Gers (32), Lot (46), Lozère (48), Hautes-Pyrénées (65), Gard (30), Hérault (34), Pyrénées-Orientales (66).

## Journal du dernier chat — travail sur l'Aveyron (12)

Point de départ : 9 spots Aveyron déjà en ligne, avec un historique de corrections dues à un bug de test DGAC (intersection de bbox au lieu de point-dans-polygone), déjà corrigé avant ce chat.

1. **Audit de la couverture communautaire** : constat que la liste complète des 65 fiches drone-spot.tech du département 12 n'avait jamais été récupérée en entier lors d'une session précédente. Récupération complète, dédoublonnage → shortlist de 22 nouveaux spots.
2. **Vérification DGAC + national R/D/P/CTR** sur les 22 : tous testés "CLEAR" à ce moment — **ce résultat s'est avéré faux plus tard (voir bug critique ci-dessous)**.
3. Intégration des 22 spots avec coordonnées réelles des fiches (aucun décalage arbitraire), commit. Aveyron : 9 → 31 spots.
4. Nettoyage des champs `verif` : suppression du jargon de méthodo interne, sur demande explicite de Guillaume.
5. **Correction manuelle "Viaduc du Viaur"** : Guillaume avait réellement volé sur ce spot et signalé que le point drone-spot.tech ne correspondait pas à son point de décollage réel. Identification du lieu réel : **Aire de Malphettes / Halte Paul Bodin**, Tauriac-de-Naucelle (44.125823, 2.331607) — point de vue aménagé officiel juste à côté du viaduc et de la rivière Viaur. Source changée en "vérifié en vol par l'utilisateur".
6. **Rédaction et commit du `README.md`** du repo pour documenter le pipeline et la méthodo — pour que ces règles persistent entre sessions.
7. **BUG CRITIQUE trouvé et corrigé** : Guillaume a repéré via l'app elle-même (bouton "AZBA" sur la fiche "Le Belvédère de Caylus") que ce spot est en réalité en zone "Vol interdit" `[R 108 RT] ISTRES` — alors que la vérification de l'étape 2 l'avait donné "CLEAR". Cause : la fonction de containment testait `zone.geom[i].c` (le tableau de rings) au lieu de `zone.geom[i].c[0]` (le ring lui-même) — un niveau d'imbrication non dépaqueté, qui faisait TOUJOURS retourner "aucune zone" quel que soit le point testé. Ce bug a invalidé silencieusement toutes les vérifications R/D/P/CTR de ce chat.
8. **Re-vérification complète** des 26 spots concernés. Résultat : 10 spots réellement en zone `[R108] ISTRES` (permanente, hors réseau RTBA) → **retirés** : Belvédère de Caylus, Colombier du Capelier, Tour de Peyrebrune, Cascade de Creissels, Château de Montaigut, Château de Cabrières, Château de Lugagnac, Mostuejouls, Église orthodoxe de Sylvanès, Église des Fadarelles.
9. Corrections annexes : Cascade du Déroc confirmé DANS le couloir RTBA R590A (pas juste à proximité) → badge `rtbaZone` ajouté. Cascade de la Roque confirmé dans la CTR de l'aérodrome de Rodez → avertissement de coordination ajouté. Estaing, Peyrusse-le-Roc, Najac re-testés : confirmés CLEAR.
10. Commit final : Aveyron 31 → 21 spots, avec message de commit expliquant la cause racine du bug.

### Erreurs de méthode à ne pas répéter

- Ne pas se contenter de vérifier un échantillon de spots communautaires : toujours lister la page département complète en premier.
- Ne pas conclure "shortlist validée" sur une réponse qui porte sur un sujet voisin — demander une validation explicite avant de lancer la vérification + le commit d'un lot entier.
- Champ `verif` = message pour l'utilisateur final, pas un journal de bord de la méthode de vérification employée.
- Toujours garder les onglets AZBA / drone-spot.tech / GitHub ouverts et visibles pendant le travail.
- Un test "CLEAR" programmatique doit être considéré comme une hypothèse à confirmer, pas un résultat définitif tant qu'il n'a pas été recoupé (ex. via le bouton AZBA intégré à l'app) — ce chat a montré qu'un bug silencieux peut donner un faux "CLEAR" systématique.

## Prochaines étapes possibles

- Choisir le prochain département Occitanie (Gers, Lot, Lozère, Hautes-Pyrénées, Gard, Hérault, ou Pyrénées-Orientales) et appliquer le pipeline ci-dessus depuis le début.
- Éventuellement reprendre le volet Bretagne (Côtes-d'Armor) : vérifier si le bug `reverseGeo`/Nominatim a été corrigé, et si les spots Côtes-d'Armor identifiés doivent être intégrés dans `SPOTS_DRONE`.
