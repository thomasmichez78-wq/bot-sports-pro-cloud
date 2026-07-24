# Bot Sports Pro

Socle propre et durable du futur bot multisport.

Cette première étape ne produit volontairement aucun pronostic. Elle fournit :

- une configuration centralisée ;
- des modèles de données communs à tous les sports ;
- des journaux rotatifs ;
- un stockage atomique des données brutes ;
- un diagnostic de configuration ;
- des tests sans dépendance externe.
- une collecte API-Football par date ;
- une normalisation contrôlée des rencontres ;
- un rapport séparant éléments reçus, normalisés et rejetés.

## Prérequis

- Windows 10 ou 11
- Python 3.11 ou plus récent

## Installation sous Windows

1. Décompresser le projet dans `C:\bot-sports-pro`.
2. Double-cliquer sur `install.bat`.
3. Copier `.env.example` en `.env`.
4. Renseigner les clés API dans `.env` sans ajouter de guillemets.
5. Double-cliquer sur `run_status.bat`.

Le statut doit indiquer que les dossiers existent et préciser quelles clés sont
configurées. Une clé absente n'empêche pas le diagnostic de fonctionner.

## Commandes manuelles

```powershell
cd C:\bot-sports-pro
python app.py init
python app.py status
python app.py collect-football --days 2
python app.py discover-odds-football --days 2
python app.py collect-odds-football --days 2 --max-credits 12
python app.py analyze-odds-football --days 2
python app.py collect-football-data --days 2 --history-days 180 --max-requests 20
python app.py collect-training-data --date 2026-07-23 --days 2 --season 2024 --max-requests 20
python app.py backtest-football --season 2024 --min-team-matches 5
python app.py compare-football-models --development-season 2023 --validation-season 2024
python app.py update-live-football-history
python app.py analyze-live-football --days 2
python app.py evaluate-live-football-value --days 2 --max-credits 3
python -m unittest discover -s tests -v
```

## Règles d'architecture

- Un collecteur collecte ; il ne choisit jamais un pari.
- Un analyseur estime des probabilités sportives ; il ne formate pas Telegram.
- Un sélecteur compare probabilités, cotes, qualité et risques.
- Les petites cotes ne sont jamais rejetées par principe.
- Les Paris Fun sont séparés des performances principales.
- Les réponses brutes des sources sont conservées avant transformation.
- Une fonction n'a qu'une seule définition.
- Aucun fichier `FINAL`, `FIX`, `V2` ou équivalent n'est créé.

## Collecte football actuelle

La commande suivante collecte aujourd'hui et demain :

```powershell
python app.py collect-football --days 2
```

Chaque réponse complète est d'abord enregistrée dans `storage/raw`. Les
rencontres normalisées vont dans `storage/processed` et le diagnostic dans
`storage/reports`.

## Collecte contrôlée des cotes

La commande `discover-odds-football` récupère le catalogue actif et les
événements sans cote, puis mesure les rapprochements avec API-Football. Ces
points d'accès ne consomment pas de crédit de cotes.

La commande `collect-odds-football` redécouvre gratuitement les événements,
regroupe uniquement les compétitions possédant une rencontre rapprochée, puis
calcule le coût. Elle refuse de démarrer si ce coût dépasse `--max-credits`.

La première collecte utilise uniquement le marché `h2h/1N2` et la région Europe.
Toutes les cotes décimales valides sont conservées, y compris les cotes de 1,20
ou 1,30. Aucun pronostic n'est produit à cette étape.

La commande `analyze-odds-football` utilise uniquement `winamax_fr` comme
bookmaker cible. Pinnacle sert de référence : ses probabilités implicites sont
corrigées de la marge avant comparaison. Un match sans cote Winamax est classé
`odds_to_check`. Ce rapport de marché ne constitue pas un modèle sportif.

La commande `collect-football-data` collecte un historique par compétition et
un classement par compétition. Son coût maximal est vérifié avant le premier
appel. Les réponses sont mises en cache jusqu'au lendemain afin qu'une seconde
exécution identique ne consomme pas à nouveau le quota. Cette couche ne calcule
encore aucune probabilité.

Sur un forfait API-Football gratuit qui bloque la saison courante, la commande
`collect-training-data` récupère une saison historique accessible. Ces fichiers
sont étiquetés `development_and_backtest_only` et stockés dans un cache
permanent. Ils ne doivent jamais alimenter directement un pronostic actuel.

Les appels API-Football sont espacés automatiquement de 6,2 secondes afin de
respecter la limite du forfait gratuit. Si la source répond malgré tout avec
une erreur HTTP 429, le collecteur attend puis réessaie jusqu'à deux fois. Les
réponses déjà réussies restent dans le cache permanent : une relance ne demande
que les éléments encore manquants.

## Premier backtest football

La commande `backtest-football` applique un modèle de Poisson simple à la base
historique. Tous les calculs sont chronologiques : un match ne peut utiliser que
les résultats commencés auparavant. Les rencontres simultanées sont analysées
en lot avant la mise à jour de l'historique.

Le backtest :

- exclut les statuts AET et PEN du marché 1N2 réglementaire ;
- réserve les premiers matchs de chaque équipe au démarrage du modèle ;
- n'utilise jamais les classements finaux de la saison ;
- compare le moteur à une référence chronologique de championnat ;
- produit des probabilités auditables et des métriques par compétition ;
- ne calcule ni value ni ROI en l'absence de cotes historiques.

Cette étape sert à mesurer le modèle. Elle ne produit aucun pari réel et ne
valide pas à elle seule son utilisation en production.

## Comparaison et validation des modèles

La commande `compare-football-models` sépare strictement les rôles des saisons :

- 2023 sert à comparer Poisson, Elo et forme récente, puis à choisir les poids ;
- les poids sont figés avant la lecture des métriques 2024 ;
- 2024 sert uniquement de validation indépendante ;
- la combinaison retenue est enregistrée avec le statut `experimental`.

Les paramètres internes Elo et forme restent fixes. Seuls les poids, par pas de
10 %, sont choisis sur la saison de développement selon la log loss. La
configuration ne devient pas automatiquement un moteur de paris : les cotes,
la value et le rendement doivent encore être testés séparément.

## Historique direct gratuit

Le forfait API-Football gratuit ne donne accès qu'à une fenêtre de dates très
courte. La commande `update-live-football-history` archive donc chaque matin les
résultats terminés de la veille et construit progressivement une base 2026.

Règles de sécurité :

- exécuter la commande chaque jour après 06h00, heure de Paris ;
- une seule date est autorisée : la veille ;
- une journée déjà archivée est relue depuis le cache sans nouvelle requête ;
- les rencontres sont fusionnées par identifiant, sans doublon ;
- seuls les dix championnats du modèle expérimental sont conservés ;
- aucune probabilité n'est produite avant cinq matchs observés par équipe ;
- les bases historiques 2023/2024 ne sont jamais mélangées à cette base directe.

Le fichier `run_live_history_daily.bat` permet de planifier cette commande dans
le Planificateur de tâches Windows. L'heure recommandée est 06h15. Le PC doit
être allumé et connecté à Internet ; avec le forfait gratuit, une journée
manquée ne peut pas être récupérée plus tard.

## Analyse directe des matchs à venir

La commande `analyze-live-football` ne collecte aucune cote et ne consomme
aucun crédit The Odds API. Elle charge :

- le fichier de rencontres produit par `collect-football` pour les mêmes dates ;
- l'historique direct accumulé depuis la version 0.8 ;
- la configuration expérimentale gelée à 50 % Poisson et 50 % Elo.

Chaque match ciblé reçoit l'un des statuts suivants :

- `MODEL_PROBABILITY_ONLY` lorsque les deux équipes ont au moins cinq matchs et
  que la compétition possède au moins trente résultats ;
- `insufficient_history` avec le détail exact des seuils manquants ;
- `invalid_fixture` lorsqu'un identifiant technique est absent.

Séquence de test :

```powershell
python app.py collect-football --days 2
python app.py analyze-live-football --days 2
```

La première commande utilise une requête API-Football par date. La seconde ne
fait aucun appel externe. Même lorsqu'une probabilité est disponible, cette
étape ne calcule encore ni cote, ni value, ni pari.

## Value Winamax et suivi papier

La commande `evaluate-live-football-value` doit être lancée après
`analyze-live-football`, avec exactement les mêmes dates. Elle commence par lire
les probabilités déjà calculées.

Si aucun match n'est prêt, elle s'arrête immédiatement :

- aucun collecteur The Odds API n'est créé ;
- aucun appel catalogue ou événement n'est effectué ;
- aucun crédit de cotes n'est consommé ;
- un rapport vide et auditable est tout de même enregistré.

Lorsqu'au moins un match est prêt, seules les rencontres prêtes sont rapprochées
avec le fournisseur, puis seules les compétitions réellement reliées peuvent
déclencher une collecte payante. Le coût prévu est comparé à `--max-credits`
avant le premier appel de cotes.

La décision utilise exclusivement les prix `winamax_fr` :

```text
probabilité implicite = 1 / cote
espérance de rendement = probabilité modèle × cote - 1
```

- `VALIDATED` : espérance au moins égale à +5 % ;
- `OPPORTUNITY` : espérance strictement positive mais inférieure à +5 % ;
- `NO_BET` : espérance nulle ou négative ;
- `ODDS_TO_CHECK` : prix Winamax absent ou rapprochement non validé.

Il n'existe aucune cote minimale. Une cote à 1,20 peut être retenue si son
espérance est positive et atteint le seuil. Une cote plus élevée est refusée si
son espérance est négative.

Les sélections positives sont enregistrées dans
`storage/processed/football_paper_bets.json`. Une relance ne duplique pas la
même sélection. Tout reste en mode papier : aucun pari réel et aucun message
Telegram ne sont envoyés.

## Collecte distante

Le workflow `.github/workflows/live-history-cloud.yml` permet à un dépôt GitHub
privé d'archiver les résultats même lorsque le PC Windows est éteint. Il
s'exécute à 06h27, heure de Paris, et peut également être lancé manuellement.

Seule la clé `API_FOOTBALL_KEY` est nécessaire dans les secrets du dépôt. Le
workflow ne demande aucune cote et ne connaît pas les identifiants Telegram.
Les instructions complètes se trouvent dans `CLOUD_SETUP.md`.
