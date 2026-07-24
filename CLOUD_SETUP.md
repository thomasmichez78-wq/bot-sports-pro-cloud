# Collecte distante pendant l'absence

Cette configuration exécute uniquement l'archivage des résultats de la veille.
Elle ne collecte aucune cote, ne calcule aucun pari et n'envoie rien sur
Telegram.

## Garanties

- dépôt GitHub obligatoirement privé ;
- clé API-Football enregistrée dans les secrets GitHub, jamais dans le code ;
- une seule requête API-Football lors d'une journée nouvelle ;
- exécution quotidienne à 06h27, heure de Paris ;
- démarrage manuel disponible pour le test initial ;
- historique, rapport et cache du jour conservés dans le dépôt ;
- aucun crédit The Odds API consommé.

## Mise en place

1. Créer ou ouvrir un compte sur `https://github.com`.
2. Créer un nouveau dépôt nommé `bot-sports-pro-cloud`.
3. Choisir **Private**.
4. Ne pas ajouter de README, de fichier `.gitignore` ou de licence.
5. Décompresser l'archive cloud fournie.
6. Importer tout son contenu dans la branche principale du dépôt.
7. Dans le dépôt, ouvrir **Settings > Secrets and variables > Actions**.
8. Choisir **New repository secret**.
9. Nommer le secret exactement `API_FOOTBALL_KEY`.
10. Coller uniquement la clé API-Football comme valeur.
11. Ouvrir l'onglet **Actions**.
12. Choisir **Historique football quotidien**.
13. Cliquer sur **Run workflow**, puis confirmer.

## Contrôle du premier test

Le travail doit devenir vert. Sa sortie doit afficher :

```text
MISE À JOUR HISTORIQUE FOOTBALL EN DIRECT
```

Le dépôt doit ensuite contenir une nouvelle modification automatique avec le
message :

```text
Historique football quotidien
```

Le fichier principal à récupérer au retour est :

```text
storage/processed/football_live_history.json
```

Il remplacera le fichier local du même nom après création d'une copie de
sauvegarde.

## Ce qui ne doit jamais être importé

- le fichier `.env` ;
- une clé API écrite dans un fichier ;
- les jetons Telegram ;
- la clé The Odds API.

Le dépôt doit rester privé pendant toute la durée d'utilisation.
