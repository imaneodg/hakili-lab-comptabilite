# HAKILI LAB

**Application de gestion comptable, de saisie, de contrôle et de validation des opérations financières.**

HAKILI LAB est une application web développée pour faciliter la gestion des opérations comptables, le suivi des écritures et leur préparation pour l'export vers **Sage**.

L'application permet notamment de gérer les opérations liées aux différents centres, aux élèves, aux fournisseurs, au personnel et aux autres tiers enregistrés dans le référentiel comptable.

---

## Fonctionnalités

### Gestion comptable

* Saisie des opérations comptables à partir de modèles prédéfinis
* Gestion des recettes et des dépenses
* Gestion des journaux comptables
* Gestion des centres
* Gestion du plan comptable
* Gestion du plan de tiers
* Attribution des comptes et des tiers aux opérations
* Numérotation des pièces
* Consultation des écritures

### Gestion des tiers

Les formulaires permettent de rechercher et sélectionner les tiers directement à partir du plan de tiers.

L'application prend notamment en charge :

* les élèves ;
* les fournisseurs ;
* les vacataires ;
* le personnel ;
* les autres tiers comptables.

Un tiers existant peut être recherché par son nom ou son code.

Lorsqu'un tiers n'existe pas encore dans le référentiel, il peut être ajouté directement depuis le formulaire concerné.

### Contrôle et validation

Les opérations peuvent suivre différents états :

* **En attente de validation**
* **Validée**
* **À corriger**
* **Exportée vers Sage**

Ce fonctionnement permet de distinguer les opérations saisies des opérations définitivement validées.

### Export comptable

Les opérations validées peuvent être préparées pour leur export vers **Sage** selon le format défini par l'application.

### Authentification

L'application intègre une gestion des utilisateurs avec authentification sécurisée et stockage des mots de passe sous forme de hash.

---

## Technologies utilisées

* **Python 3.14**
* **Shiny for Python**
* **PostgreSQL 17**
* **Pandas**
* **Psycopg2**
* **OpenPyXL**
* **python-dotenv**
* **bcrypt**
* **Docker**
* **Docker Compose**
* **Nginx**

---

## Architecture du projet

```text
HAKILI_LAB_postgres_2_DEPLOIEMENT/
│
├── app.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
│
├── logic/
│   ├── donnees.py
│   ├── modeles.py
│   └── ...
│
├── sql/
│   ├── schema.sql
│   ├── seed.sql
│   └── ...
│
├── tests/
│   └── ...
│
├── www/
│   └── ressources web et éléments visuels
│
├── nginx/
│   └── configuration du serveur
│
└── backup/
    └── sauvegardes
```

---

## Prérequis

Avant d'installer HAKILI LAB, il est nécessaire de disposer de :

* Python 3.14 ou version compatible
* PostgreSQL 17
* Git
* Docker et Docker Compose, si le déploiement par conteneurs est utilisé

---

# Installation en local

## 1. Cloner le projet

```powershell
git clone https://github.com/imaneodg/hakili-lab-comptabilite.git
cd hakili-lab-comptabilite
```

---

## 2. Créer l'environnement virtuel

Sous Windows :

```powershell
python -m venv .venv
```

Activer l'environnement :

```powershell
.\.venv\Scripts\Activate.ps1
```

---

## 3. Installer les dépendances

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

# Configuration de PostgreSQL

HAKILI LAB utilise PostgreSQL comme système de gestion de base de données.

Créer une base de données dédiée à l'application, puis configurer la connexion dans le fichier `.env`.

Exemple :

```env
DATABASE_URL=postgresql://UTILISATEUR:MOT_DE_PASSE@localhost:5432/Hakili_compta
```

**Ne jamais publier le fichier `.env` sur GitHub.**

Le fichier `.env.example` peut être utilisé comme modèle de configuration.

---

# Initialisation de la base de données

Après avoir configuré PostgreSQL, les scripts SQL permettent de préparer la base de données.

Exemple :

```powershell
psql "$env:DATABASE_URL" -f sql/schema.sql
```

Puis :

```powershell
psql "$env:DATABASE_URL" -f sql/seed.sql
```

Le script `seed.sql` initialise les données de référence nécessaires au fonctionnement de l'application.

---

# Lancer HAKILI LAB

Une fois l'environnement virtuel activé et les dépendances installées :

```powershell
shiny run --reload app.py
```

L'application est ensuite accessible depuis le navigateur à l'adresse indiquée par Shiny.

---

# Utilisation

L'application est organisée autour des principales étapes du traitement comptable :

1. Sélection du modèle d'opération
2. Saisie des informations
3. Sélection du compte ou du tiers
4. Enregistrement de l'opération
5. Contrôle des écritures
6. Validation
7. Préparation de l'export comptable

Les listes de comptes, journaux, centres et tiers sont alimentées à partir des données de référence enregistrées dans PostgreSQL.

---

# Données de référence

Le référentiel comptable comprend notamment :

* les comptes ;
* les journaux ;
* les centres ;
* les tiers ;
* les types de libellés ;
* les utilisateurs.

Les données opérationnelles sont séparées des données de référence afin de préserver la structure comptable de l'application.

---

# Tests

Les tests du projet se trouvent dans le dossier :

```text
tests/
```

Pour lancer les tests :

```powershell
pytest
```

---

# Déploiement avec Docker

HAKILI LAB peut également être exécuté avec Docker.

Construire l'image :

```powershell
docker build -t hakili-lab .
```

Lancer les services :

```powershell
docker compose up -d
```

Vérifier les conteneurs :

```powershell
docker compose ps
```

Consulter les journaux :

```powershell
docker compose logs -f
```

Arrêter les services :

```powershell
docker compose down
```

---

# Sécurité

Les informations sensibles ne doivent jamais être versionnées dans Git.

Le dépôt ne doit notamment pas contenir :

* le fichier `.env` ;
* les mots de passe PostgreSQL ;
* les clés ou secrets d'authentification ;
* l'environnement virtuel `.venv` ;
* les fichiers Python temporaires ;
* les données comptables confidentielles.

Les paramètres sensibles doivent être configurés dans l'environnement de déploiement.

---

# Sauvegarde de la base de données

La base PostgreSQL doit être sauvegardée régulièrement afin de préserver les données comptables.

Exemple de sauvegarde PostgreSQL :

```powershell
pg_dump "$env:DATABASE_URL" > backup.sql
```

La procédure de restauration doit être réalisée avec précaution et après vérification de la sauvegarde.

---

# Développement

Pour contribuer au développement :

```powershell
git status
```

Vérifier les modifications :

```powershell
git diff
```

Puis, après validation :

```powershell
git add .
git commit -m "Description de la modification"
git push
```

---

# Dépôt GitHub

Projet :

**HAKILI LAB — Comptabilité**

Dépôt GitHub :

https://github.com/imaneodg/hakili-lab-comptabilite

La branche principale utilisée pour la version actuelle du projet est :

```text
main
```

---

## Licence

Projet développé dans le cadre de la conception et du déploiement d'une solution de gestion comptable.

---

## Auteur

**HAKILI LAB**

Application de gestion comptable développée avec Python, Shiny et PostgreSQL.
