# 5. Architecture du code

## 5.1 Les technologies

| Élément | Choix | Version figée |
|---|---|---|
| Langage | Python | 3.14 (image Docker `python:3.14-slim`, poste d'Afiya 3.14.3) |
| Interface et serveur web | Shiny for Python | `shiny==1.7.0`, `shinychat==0.6.1` |
| Base de données | PostgreSQL | 16 (image `postgres:16`) |
| Accès base | psycopg2 + pandas | `psycopg2-binary==2.9.12`, `pandas==3.0.5` |
| Assistant IA | chatlas + API Anthropic | `chatlas[anthropic]==0.23.0` |
| Graphiques de l'assistant | matplotlib | `>=3.8,<4` |
| Fautes de frappe (assistant) | rapidfuzz | `>=3.0,<4` |
| Codes d'accès | bcrypt | `>=4.0` |
| Configuration | python-dotenv | `.env` |
| Tests | pytest, httpx | |
| Déploiement | Docker Compose sur Linux | |

Les versions sont **figées volontairement** dans `requirements.txt` : une dépendance qui change seule ne doit pas casser un déploiement. On les met à jour exprès, jamais par un `pip install --upgrade` en passant.

Shiny for Python est le portage Python de Shiny (R). Il faut connaître ses trois idées : les **inputs** (valeurs envoyées par le navigateur, `input.m_modele()`), les **calculs réactifs** (`@reactive.calc`, recalculés quand ce qu'ils lisent change) et les **sorties** (`@render.ui`, `@render.data_frame`, redessinées automatiquement). Le navigateur et le serveur restent connectés par un websocket.

Historique utile : l'application a d'abord été écrite en R (`R/modeles.R`) avec des classeurs Excel comme stockage, puis portée en Python sur PostgreSQL. Certains commentaires parlent encore de « la version Excel » ou « la version R ».

## 5.2 Les couches

```
 navigateur ──websocket──► app.py  (interface, droits, réactivité)
                              │
          ┌───────────────────┼─────────────────────┬──────────────────────┐
          ▼                   ▼                     ▼                      ▼
   logic/modeles.py     logic/donnees.py      tableau_bord.py        assistant/
   (opération →         (base : lecture,      + logic/tableau_bord   (IA : compréhension,
    écriture ;           écriture, contrôles,   (calculs)              moteur, outils)
    aucune base)         numérotation, export)       │                      │
                              │                      │                      │
                              ▼                      ▼                      ▼
                         PostgreSQL : tables, triggers, fonctions SQL du tableau de bord
```

- **`logic/modeles.py`** ne connaît pas la base. Il transforme des valeurs de formulaire en lignes d'écriture (DataFrame pandas). On peut le tester sans PostgreSQL.
- **`logic/donnees.py`** est la seule porte d'entrée vers la base pour l'application : pool de connexions, lecture du référentiel et des écritures, enregistrement, validation, renvoi, suppression, contrôles, soldes, export Sage, authentification.
- **`app.py`** construit l'interface, applique les droits et branche le tout. Il ne contient pas de SQL.
- **`tableau_bord.py`** (interface) et **`logic/tableau_bord.py`** (calculs) forment un module Shiny isolé, branché dans `app.py` par deux lignes.
- **`assistant/`** est un paquet indépendant, utilisé par l'onglet Assistant IA.
- **`composants.py`** : petites fonctions qui fabriquent des morceaux d'interface (titre de page, carte, filtre, indicateur).
- **`www/`** : CSS, polices, icônes, logos servis tels quels.

## 5.3 Démarrage

Au lancement de `app.py` :

1. `load_dotenv()` lit le `.env` (avant tout import de `logic.donnees`, qui crée le pool de connexions à l'import) ;
2. la journalisation est configurée (`hakili.log` + sortie standard) ;
3. **`logic/migrations.py` joue les migrations SQL manquantes.** Si l'une échoue, l'application **refuse de démarrer** et nomme le fichier fautif. C'est voulu : une panne au déploiement vaut mieux qu'une panne découverte par une caissière ;
4. l'interface (`app_ui`) et le serveur (`server`) sont créés : `app = App(app_ui, server, static_assets=www/)`.

## 5.4 Une session utilisateur

`server(input, output, session)` est appelée une fois par onglet de navigateur ouvert. Elle contient tout l'état de cette session :

- `util` : l'utilisateur connecté (ou `None`) ;
- `ref()` : le référentiel (comptes, tiers, journaux, centres, utilisateurs, soldes d'ouverture) ;
- `donnees()` : les écritures de la **fenêtre de travail** (depuis le 1er janvier de l'année + toute pièce non exportée) ;
- `tresorerie()` : les mouvements cumulés par compte de trésorerie et par centre, pour les soldes (quelques dizaines de lignes, quel que soit l'historique) ;
- `correction` : la pièce en cours de correction ;
- l'objet de conversation de l'assistant.

`page()` affiche soit l'écran de connexion, soit la coquille de l'application. Les onglets sont construits **une seule fois par connexion** dans `corps()`, en lisant le référentiel sous `reactive.isolate()`. Sans cette précaution (corrigée le 10/09/2026), chaque pièce enregistrée par n'importe quel centre reconstruisait tous les onglets et effaçait le formulaire en cours de saisie.

## 5.5 Plusieurs postes en même temps : la table `revision`

Les cinq centres et le comptable travaillent en même temps. Pour qu'un écran voie ce qu'un autre poste vient d'enregistrer, PostgreSQL tient un compteur :

- la table `revision` a une seule ligne avec deux colonnes : `valeur` (écritures) et `referentiel` ;
- des triggers les incrémentent à chaque modification des tables concernées ;
- chaque session interroge cette ligne **toutes les 2 secondes** (`reactive.poll`) ;
- tant que les valeurs ne bougent pas, rien n'est relu ; quand `valeur` change, `donnees()` est relue ; quand `referentiel` change, `ref()` est relu.

Une coupure de la base pendant ce sondage est absorbée : la dernière valeur connue est gardée et un avertissement va au journal (sinon Shiny fermait la session et l'écran devenait gris).

Le même sondage vérifie que le compte connecté est toujours actif.

## 5.6 Les règles qui protègent la réactivité

Ces règles ont chacune coûté un bug. Gardez-les :

- **Lire le référentiel sous `reactive.isolate()`** dans tout ce qui construit un formulaire (`m_champs`, `valeurs`, `operation`, `m_apercu`, `m_ruban`, `_ligne_repartition_ui`), sinon une écriture d'un autre centre reconstruit le formulaire et efface ce que la caissière tape.
- **Montants avec `update_on="blur"`** : la valeur n'est envoyée qu'en quittant le champ.
- **Identifiants de champs Shiny** : lettres, chiffres et `_` uniquement. Un code journal avec un tiret (`BDU-BF`) passe par `_id_journal()`.
- **Effets créés dynamiquement** (lignes de répartition) : détruire ceux d'une ligne retirée (`rep_effets_crees`), sinon ils s'accumulent.
- **Tout contrôle d'accès se refait dans l'effet serveur** (`_valider`, `_rejeter`, `_supprimer`, `_creer_lot`…), jamais seulement en cachant un bouton.
- **Élargir aux pièces liées avant le contrôle de centre** (`dl.avec_liees()` puis `_hors_centre()`), sinon on peut agir sur la moitié d'un autre centre.

## 5.7 Accès à la base

- Un `ThreadedConnectionPool` (1 à 20 connexions) créé à l'import de `logic/donnees.py`, avec `DATABASE_URL`.
- Tout passe par le gestionnaire de contexte `_connexion()` : commit si le bloc réussit, rollback sinon, et une connexion morte est retirée du pool au lieu d'y être rendue.
- Les opérations qui touchent plusieurs lignes (validation, correction, export) se font **dans une seule transaction**, avec `SELECT … FOR UPDATE` sur les lignes concernées pour qu'un autre utilisateur attende au lieu d'écrire en même temps.
- Les compteurs de numérotation sont des `INSERT … ON CONFLICT DO UPDATE … RETURNING` : atomiques sans verrou applicatif.
- Les requêtes sont toujours paramétrées (`%s`), jamais construites par concaténation de valeurs saisies.

## 5.8 Un seul processus

En production, Shiny tourne dans **un seul processus** (`shiny run --host 0.0.0.0 --port 8022 app.py`). Un calcul long bloque tout le monde pendant sa durée. C'est pour ça que les contrôles ont été vectorisés (52 s → 0,7 s sur 25 000 pièces) et que le tableau de bord calcule le flux une seule fois par appel (35 s → 5 s). Si l'application ralentit un jour, c'est le premier endroit à regarder (voir chantiers : `reactive.extended_task`, plusieurs workers avec sessions collantes côté nginx).

## 5.9 Journalisation

`logging` écrit dans `hakili.log` (ou `HAKILI_LOG_FILE`) et sur la sortie standard. Loggers : `hakili.app`, `hakili.donnees`, `hakili.modeles`, `hakili.migrations`, `hakili.assistant`, `hakili.tableau_bord`. Sont tracés : connexions et échecs, verrouillages, pièces enregistrées, corrigées, supprimées, validées, renvoyées, exports Sage contenant des pièces déjà exportées, créations de comptes et de tiers, clôtures.

En production, lisez-les avec `docker compose logs app`. Le fichier `hakili.log` dans le conteneur est perdu à chaque reconstruction (pas de rotation) : voir chantiers.

## 5.10 Le serveur MCP (facultatif)

`mcp_server/server.py` expose les outils de l'assistant au protocole MCP, pour interroger la base depuis un autre client (Claude Desktop par exemple). **L'application ne l'utilise plus** depuis le 24/09/2026 : l'assistant appelle ses outils directement. Il peut être ignoré, ou supprimé si personne ne s'en sert.
