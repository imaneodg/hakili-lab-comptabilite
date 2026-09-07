# HAKILI LAB — version de déploiement

Application de saisie, contrôle, validation et export comptable de Hakili Lab. Cette version est **sans assistant IA, sans MCP et sans Chatlas**. Elle utilise Shiny for Python et PostgreSQL.

## Fonctionnalités

- saisie des opérations par modèles ;
- plan comptable, journaux, centres et comptes tiers ;
- contrôle et validation des pièces ;
- export Sage ;
- authentification et mots de passe hachés avec bcrypt ;
- rafraîchissement réactif multi-postes via PostgreSQL ;
- listes déroulantes des élèves et vacataires alimentées par le plan tiers ;
- journal bancaire **CBI** (compte 521100) à la place de l'ancien journal BDU-BF.

## Structure

```text
app.py
logic/
  donnees.py
  modeles.py
sql/
  schema.sql
  seed.sql
  production_reset.sql
  migrations/
www/
backup/
Dockerfile
docker-compose.yml
.env.example
requirements.txt
tests/
```

Aucun `.env`, log, environnement virtuel, cache Python, brouillard Excel ou fichier de données transactionnelles n'est livré dans cette version. Les modules MCP/IA ont été retirés.

## Prérequis

- Python 3.14 recommandé ;
- PostgreSQL 17 recommandé ;
- une base PostgreSQL `Hakili_compta` accessible par l'application ;
- Docker/Compose si déploiement conteneurisé.

## Configuration locale

1. Copier `.env.example` vers `.env`.
2. Renseigner uniquement `DATABASE_URL` (ou les variables `PG*`).
3. Installer les dépendances :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

4. Préparer la base :

```powershell
psql "$env:DATABASE_URL" -f sql/schema.sql
psql "$env:DATABASE_URL" -f sql/seed.sql
```

Pour une base existante contenant le référentiel et des données de test, utiliser **une seule fois** `sql/production_reset.sql` sur la base concernée. Ce script conserve le référentiel et les autres tiers.

### Important sur les élèves/vacataires

Le code de l'application ne fabrique plus de tiers à partir d'un texte saisi. Les listes sont construites à partir des lignes déjà présentes dans `tiers` :

- élèves : tiers dont le code commence par `411`, actifs pour l'année ;
- vacataires/bénéficiaires : tiers dont le code commence par `422`, actifs pour l'année.

Le choix renvoie le **code tiers**, puis ce code est reconfirmé au moment de l'enregistrement de l'écriture. Le formulaire « Frais de document » utilise également le compte tiers élève `411`.

Le fichier `seed.sql` fourni dans l'archive ne contient pas la liste réelle des élèves/vacataires : il contient le référentiel comptable générique. Il faut donc conserver/importer les vrais tiers de votre base de production avant la saisie. **Aucun nom de tiers réel n'est inventé ici.**

## Lancer l'application

```powershell
shiny run --reload app.py
```

Puis ouvrir `http://127.0.0.1:8000`.

## Docker

Construire et lancer l'application :

```powershell
docker build -t hakili-lab .
docker run --rm -p 8000:8000 --env-file .env hakili-lab
```

Ou avec Compose :

```powershell
docker compose up -d --build
```

Le PostgreSQL n'est pas inclus dans ce Compose : `DATABASE_URL` doit pointer vers votre PostgreSQL de production. Le reverse proxy Nginx fourni doit être configuré avec un vrai certificat TLS avant exposition Internet.

## Sécurité

- `.env` est ignoré par Git ;
- aucune clé API n'est nécessaire dans cette version ;
- ne jamais mettre de mot de passe PostgreSQL dans `app.py`, `Dockerfile`, `seed.sql` ou le dépôt Git ;
- utiliser TLS via Nginx ou un reverse proxy équivalent ;
- sauvegarder PostgreSQL indépendamment de l'application.

## Remise à zéro avant production

`sql/production_reset.sql` :

- supprime toutes les lignes de `ecritures` ;
- supprime la trace des suppressions de pièces ;
- réinitialise les compteurs ;
- supprime le tiers de test `Ouedraogo Afiya` ;
- remplace le journal bancaire `BDU-BF` par `CBI` s'il existe encore ;
- met à jour l'intitulé du compte bancaire `521100` en `Banques (CBI)` ;
- remet le watermark `revision` à zéro ;
- **ne supprime pas** les comptes, journaux, centres, libellés, utilisateurs ni les autres tiers.

Exécuter :

```powershell
psql "$env:DATABASE_URL" -f sql/production_reset.sql
```

Puis vérifier :

```sql
SELECT count(*) FROM ecritures;
SELECT count(*) FROM suppressions_ecritures;
SELECT count(*) FROM compteurs;
SELECT count(*) FROM tiers WHERE lower(btrim(intitule)) = lower('Ouedraogo Afiya');
```

Les trois premiers résultats doivent être `0` et le dernier également `0`.

## Tests

Les tests d'authentification et utilitaires nécessitent un PostgreSQL configuré via `.env`.

```powershell
pytest tests -v
```

## GitHub

Avant le premier commit, vérifier :

```powershell
git status
git diff --check
```

Le dépôt ne doit contenir ni `.env`, ni mot de passe, ni clé API, ni données transactionnelles de test.
