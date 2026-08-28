\# HAKILI LAB — Application de saisie des opérations de caisse



Application interne de gestion et de saisie des opérations de caisse pour les différents centres de \*\*Hakili Lab\*\*.



L'application permet aux centres d'enregistrer leurs opérations, au comptable de les contrôler et de les valider, puis de générer les écritures destinées à être importées dans \*\*Sage 100\*\*, qui reste le logiciel comptable de référence.



L'application utilise \*\*Shiny for Python\*\* pour l'interface et \*\*PostgreSQL\*\* pour le stockage des données.



\---



\## Présentation du projet



HAKILI LAB centralise la saisie des opérations de caisse de plusieurs centres dans une base de données PostgreSQL commune.



Les utilisateurs ne saisissent pas directement des écritures comptables débit/crédit. Ils utilisent des \*\*formulaires adaptés au type d'opération\*\*.



À partir des informations renseignées dans le formulaire, l'application applique les règles comptables prévues pour le type d'opération sélectionné, construit les lignes comptables correspondantes et effectue différents contrôles avant validation.



Les écritures validées peuvent ensuite être exportées dans un format compatible avec \*\*Sage 100\*\*.



> \*\*Important :\*\* HAKILI LAB est un outil de préparation et de contrôle des écritures. Sage 100 reste le logiciel comptable officiel.



\---



\## Fonctionnalités principales



\### Saisie des opérations



L'application propose plusieurs modèles d'opérations permettant notamment de gérer :



\* les encaissements ;

\* les dépenses courantes ;

\* les salaires et vacations ;

\* les loyers ;

\* le gardiennage ;

\* les achats ;

\* les ventes ;

\* les versements en banque ;

\* les transferts entre caisses ;

\* ainsi que d'autres opérations courantes.



Chaque modèle possède ses propres règles de traitement comptable.



\### Gestion des tiers



L'application permet de gérer les différents tiers liés aux opérations :



\* élèves ;

\* fournisseurs ;

\* professeurs ;

\* autres tiers.



Lors de la saisie, l'application recherche les tiers déjà enregistrés afin d'éviter les doublons.



\### Validation des opérations



Les opérations suivent un circuit de traitement :



\*\*Saisie → Contrôle → Validation → Export\*\*



Le centre saisit l'opération.



Le comptable contrôle les informations et valide ou demande une correction.



Après validation, un numéro définitif est attribué à la pièce.



\### Contrôles comptables



Plusieurs contrôles sont réalisés avant la validation d'une opération, notamment :



\* équilibre débit/crédit ;

\* cohérence des comptes ;

\* existence des comptes dans le plan comptable ;

\* présence des tiers lorsque cela est nécessaire ;

\* cohérence des opérations de trésorerie ;

\* contrôle des transferts entre caisses ;

\* contrôle du solde de caisse.



\### Gestion multi-centres



L'application est conçue pour permettre à plusieurs centres de travailler sur une même base PostgreSQL.



Les centres concernés comprennent notamment :



\* Pissy ;

\* Saaba ;

\* SIAO ;

\* Tampouy ;

\* Nagrin ;

\* ainsi que le siège.



Les opérations sont centralisées dans une même base de données.



\### Numérotation des pièces



La numérotation définitive des pièces est attribuée lors de la validation.



La génération du numéro est réalisée directement au niveau de PostgreSQL afin d'éviter les doublons lorsque plusieurs utilisateurs travaillent simultanément.



\### Export vers Sage 100



Les opérations validées peuvent être exportées dans un fichier destiné à être importé dans \*\*Sage 100\*\*.



L'application ne remplace donc pas Sage : elle prépare les données comptables nécessaires à leur intégration.



\### Sauvegarde PostgreSQL



Un script de sauvegarde est fourni dans :



```text

backup/pg\_backup.py

```



Il permet de réaliser des sauvegardes de la base PostgreSQL sous forme de fichiers `.dump`.



\---



\## Technologies utilisées



| Technologie      | Utilisation                                  |

| ---------------- | -------------------------------------------- |

| Python           | Langage principal                            |

| Shiny for Python | Interface et serveur de l'application        |

| PostgreSQL       | Base de données                              |

| psycopg2         | Connexion à PostgreSQL                       |

| pandas           | Manipulation des données                     |

| python-dotenv    | Gestion de la configuration                  |

| openpyxl         | Gestion de fichiers Excel lorsque nécessaire |



\---



\## Architecture du projet



```text

HAKILI\_LAB\_postgres\_2/

│

├── app.py

│

├── logic/

│   ├── \_\_init\_\_.py

│   ├── donnees.py

│   └── modeles.py

│

├── sql/

│   ├── schema.sql

│   └── seed.sql

│

├── backup/

│   └── pg\_backup.py

│

├── requirements.txt

├── .env.example

├── .gitignore

├── .dockerignore

├── Dockerfile

└── README.md

```



\### Description des principaux fichiers



\*\*app.py\*\*



Contient l'interface et le fonctionnement principal de l'application Shiny.



\*\*logic/donnees.py\*\*



Gère notamment l'accès aux données PostgreSQL, les requêtes, les contrôles, la numérotation et les opérations liées aux données comptables.



\*\*logic/modeles.py\*\*



Contient les différents modèles d'opérations utilisés par l'application.



\*\*sql/schema.sql\*\*



Contient la structure de la base de données : tables, contraintes, relations et mécanismes nécessaires au fonctionnement de l'application.



\*\*sql/seed.sql\*\*



Contient les données initiales nécessaires au démarrage de l'application : plan comptable, journaux, centres, libellés et autres données de référence.



\*\*backup/pg\_backup.py\*\*



Permet de réaliser les sauvegardes de la base PostgreSQL.



\---



\## Installation en local



\### Prérequis



Avant d'installer l'application, il faut disposer de :



\* Python ;

\* PostgreSQL ;

\* Git.



\### 1. Cloner le projet



```bash

git clone URL\_DU\_DEPOT

cd HAKILI\_LAB\_postgres\_2

```



\### 2. Créer l'environnement virtuel



Sous Windows :



```powershell

python -m venv .venv

```



Activer l'environnement :



```powershell

.\\.venv\\Scripts\\Activate.ps1

```



\### 3. Installer les dépendances



```powershell

pip install -r requirements.txt

```



\---



\## Configuration de PostgreSQL



Créer la base de données PostgreSQL puis charger le schéma.



Le fichier :



```text

sql/schema.sql

```



contient la structure de la base.



Le fichier :



```text

sql/seed.sql

```



contient les données initiales nécessaires à l'application.



La connexion à PostgreSQL est configurée à l'aide du fichier :



```text

.env

```



Le fichier `.env` n'est \*\*pas envoyé sur GitHub\*\*, car il peut contenir des informations sensibles.



Un modèle de configuration est disponible dans :



```text

.env.example

```



\---



\## Lancer l'application



Après activation de l'environnement virtuel :



```powershell

shiny run --reload app.py

```



L'application sera normalement accessible à l'adresse :



```text

http://127.0.0.1:8000

```



\---



\## Gestion des utilisateurs



L'application distingue notamment les utilisateurs des centres et le comptable.



Le comptable dispose des fonctions de contrôle et de validation des opérations.



Les utilisateurs des centres saisissent les opérations correspondant à leur centre.



Les codes d'accès doivent être configurés et protégés avant toute utilisation réelle.



\---



\## Gestion des données



Les données opérationnelles sont stockées dans PostgreSQL.



L'application ne dépend pas d'un fichier Excel pour stocker les opérations comptables.



La base de données constitue le stockage principal de l'application.



Les sauvegardes PostgreSQL doivent être conservées dans un emplacement différent de celui de la base de production afin de limiter les risques de perte de données.



\---



\## Sauvegarde



Une sauvegarde peut être réalisée avec :



```powershell

python backup/pg\_backup.py

```



Les fichiers de sauvegarde sont destinés au dossier :



```text

backup/sauvegardes/

```



Ce dossier est volontairement exclu de Git afin de ne pas envoyer les sauvegardes de la base de données dans le dépôt GitHub.



\---



\## Docker



Le projet contient également un fichier :



```text

Dockerfile

```



permettant de préparer la conteneurisation de l'application.



La mise en place de Docker et le déploiement seront réalisés séparément après la validation du fonctionnement du projet en local.



\---



\## Git et GitHub



Le projet est versionné avec Git.



Les éléments sensibles et temporaires suivants ne doivent pas être envoyés sur GitHub :



\* `.env` ;

\* environnement virtuel `.venv/` ;

\* fichiers `\_\_pycache\_\_/` ;

\* fichiers `.log` ;

\* sauvegardes PostgreSQL ;

\* autres fichiers temporaires.



Le fichier `.gitignore` du projet contient les règles nécessaires pour les exclure.



\---



\## État du projet



Le projet est actuellement organisé autour de :



\* Python ;

\* Shiny for Python ;

\* PostgreSQL ;

\* une architecture séparant l'interface, la logique métier et la base de données ;

\* un système de validation des opérations ;

\* un système d'export vers Sage 100 ;

\* un système de sauvegarde PostgreSQL ;

\* une préparation à la conteneurisation avec Docker.



\---



\## Limites actuelles



Certaines améliorations pourront être ajoutées progressivement, notamment :



\* amélioration de la gestion et du hachage des mots de passe ;

\* gestion des pièces justificatives numériques ;

\* amélioration des mécanismes de sécurité ;

\* déploiement sur un serveur ;

\* supervision de l'application ;

\* automatisation avancée des sauvegardes ;

\* amélioration des mécanismes d'alerte.



\---



\## Objectif du déploiement



L'objectif est de permettre à HAKILI LAB de disposer d'une application centralisée accessible aux différents utilisateurs, tout en conservant :



\* une base PostgreSQL centralisée ;

\* un contrôle des opérations par le comptable ;

\* une traçabilité des validations ;

\* une préparation des écritures pour Sage 100 ;

\* des sauvegardes régulières ;

\* une architecture pouvant être déployée sur un serveur.



\---



\## Auteur



Projet développé dans le cadre du stage de comptabilité et d'informatisation des opérations de caisse de \*\*Hakili Lab\*\*.



\*\*HAKILI LAB — Application de saisie et de préparation des opérations de caisse.\*\*



