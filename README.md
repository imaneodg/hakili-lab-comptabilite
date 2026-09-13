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



\## Docker et déploiement en production



Le projet contient :



```text

Dockerfile          — image de l'application (Shiny + assistant IA)

docker-compose.yml  — orchestration app + reverse proxy TLS

nginx/hakili.conf   — configuration nginx (a adapter : domaine, certificats)

```



Le Dockerfile copie désormais bien tout ce dont l'application a besoin pour fonctionner en conteneur, y compris `mcp\_server/` et `chat\_config.py` (l'assistant IA plantait auparavant en conteneur, faute de ces deux éléments — corrigé le 05/09/2026).



Pour un premier déploiement réel :



\1. compléter `.env` à la racine (voir `.env.example`) ;

\2. mettre un certificat TLS réel dans `nginx/certs/` (`fullchain.pem`, `privkey.pem` — un certificat Let's Encrypt via certbot convient) ;

\3. `docker compose up -d --build`.



PostgreSQL n'est volontairement pas inclus dans `docker-compose.yml` : la base `Hakili\_compta` reste gérée séparément (locale ou serveur dédié), `DATABASE\_URL` dans `.env` pointe simplement vers elle.



Ne jamais exposer le port 8000 de l'application directement en dehors d'un réseau local de confiance : sans le reverse proxy TLS devant elle, les codes d'accès et toutes les données comptables circuleraient en clair sur le réseau.



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



Corrigé le 05/09/2026 (voir `audit\_architecture\_hakili\_lab.md`) :



\* hachage bcrypt des codes d'accès, avec migration automatique et transparente des comptes existants ;

\* verrouillage temporaire après plusieurs tentatives de connexion incorrectes ;

\* image Docker complète (l'assistant IA ne plantait plus en local mais aurait planté en conteneur) ;

\* dépendances figées à des versions précises, doublons supprimés ;

\* trace d'audit sur la suppression d'une pièce (auteur, horodatage, contenu conservé) ;

\* journalisation des opérations financières et des événements de connexion ;

\* copie hors site optionnelle des sauvegardes (`HAKILI\_BACKUP\_RCLONE\_REMOTE`) ;

\* modèle de déploiement Docker + reverse proxy TLS (`docker-compose.yml`, `nginx/`).



Corrigé le 10/09/2026 (voir `audit\_complet\_hakili\_lab\_2026-09-10.md`) :



\* contrôle du rôle comptable refait côté serveur sur les dix actions qui n'en avaient aucun (validation, export Sage, création/désactivation d'utilisateur, plan comptable, plan tiers, soldes d'ouverture, nouvelle année) — auparavant, seul l'affichage du bouton protégeait ces actions ;

\* verrouillage anti brute-force sécurisé contre les tentatives de connexion envoyées en parallèle (`FOR UPDATE` sur la ligne utilisateur pendant la vérification) ;

\* longueur minimale du code d'accès relevée de 4 à 6 caractères pour les comptes créés à partir de maintenant ;

\* colonne `centres.code\_acces` supprimée (jamais lue par le code applicatif, reliquat en clair d'un modèle antérieur — voir `sql/migrations/2026-09-10\_suppression\_code\_acces\_centres.sql` pour une base déjà en service) ;

\* enregistrement des soldes d'ouverture (`\_soldes`) : un échec sur un journal était auparavant avalé silencieusement et le message affiché restait "Soldes d'ouverture enregistrés" comme si tout avait réussi — les échecs sont désormais listés nommément et distingués d'un succès ;

\* quatre indicateurs financiers de l'assistant IA (poste de dépense principal, part des charges fixes, part loyer/eau/électricité, dépenses anormales) sous-estimaient les charges dès qu'un salaire (modèle "rémunération", compte 422000) était versé, ce compte étant de nature `tiers` et non `charge` — corrigé en réutilisant partout le même élargissement déjà appliqué à `part\_masse\_salariale` ;

\* export Sage (`.txt`) en `latin1` : un caractère comme « œ », un guillemet typographique ou un tiret cadratin dans un libellé faisait planter le téléchargement de tout le lot de pièces sélectionné — passage à `cp1252` (plus large) avec un filet de sécurité (`errors="replace"`) qui empêche désormais tout plantage, même pour un caractère encore hors de cette table ;

\* composition du libellé d'une avance de paiement (`PREFIXE NOM/MOIS`) : un nom de tiers un peu long faisait couper silencieusement le `/MOIS` final par la troncature à 60 caractères, cassant sans erreur la suggestion automatique du mois suivant — c'est maintenant le nom qui est raccourci en priorité, jamais le mois ;

\* un modèle de saisie qui lève une exception interne (`construire\_lignes`) était totalement invisible pour l'utilisateur comme pour le développeur — l'incident est désormais journalisé ;

\* écran instable ("écrans roses", onglets qui sautent, formulaire de Saisie impossible à remplir) : `page()` reconstruisait la totalité de l'application (tous les onglets, `m\_modele`, `m\_journal`...) à chaque écriture comptable enregistrée n'importe où sur les 5 centres, via sa dépendance indirecte à `\_disque()` (sondage Postgres toutes les 0,5 s). La structure des onglets est désormais construite une seule fois par connexion (nouvelle sortie `corps()`, lecture du référentiel sous `reactive.isolate()`) ; `m\_champs()` (champs Élève/Compte/Montant du formulaire) isole de la même façon sa lecture du référentiel. Les données affichées (tableaux, soldes...) continuent de se rafraîchir normalement — seule la structure et les champs en cours de remplissage sont désormais protégés ;

\* avertissement "Le modèle « ... » n'existe que sur le journal ..." affiché à tort à chaque connexion sur le modèle par défaut ("Encaissement de frais de scolarité") : le sélecteur de journal caché (`m\_journal`) démarre sans valeur explicite, donc sur le premier journal de la table (`ACH`), qui ne correspond pas au journal imposé par ce modèle (`CP`) ; comme `@reactive.event()` s'exécute par défaut dès la connexion, l'avertissement se déclenchait une fois à chaque session avant toute action de l'utilisateur — corrigé avec `ignore_init=True` sur ce déclencheur, qui ne réagit plus qu'aux changements réels de journal ;

\* panneau "Écriture générée" instable pendant la Saisie, à deux niveaux distincts : (1) `valeurs()`, `operation()`, `m\_apercu()` et `m\_ruban()` lisaient `ref()`/`donnees()` directement, donc tout écriture enregistrée sur n'importe quel des 5 centres reconstruisait ce panneau même sans y toucher — corrigé par le même `reactive.isolate()` que pour `m\_champs()` ; (2) les champs de montant (`ch\_montant`, `m\_rep\_montant\_*`) renvoyaient leur valeur au serveur à chaque frappe, donc chaque chiffre tapé reconstruisait tout le panneau — corrigé avec `update\_on="blur"` (natif à Shiny), qui n'envoie la valeur qu'en quittant le champ, sans rien changer au résultat final. Les deux causes ont été vérifiées séparément par un test Playwright avec `MutationObserver` sur `#m\_apercu`/`#m\_ruban` (0 reconstruction en écriture externe ou en pleine frappe, une seule juste après avoir quitté le champ) ;

\* tableau de répartition mois/nature/montant (modèle "Encaissement") qui se reconstruisait en entier dès qu'une seule ligne changeait, détruisant aussi les champs des autres lignes non touchées (`_ligne\_repartition\_ui()` lisait ses valeurs sans `reactive.isolate()`, alors qu'elle est appelée par `m\_bloc\_repartition()` qui définit ces mêmes champs) — vérifié par un marqueur posé sur une ligne, perdu après modification d'une autre ligne avant correctif, conservé après. Voir `tests/test\_reactivite\_saisie.py` ;

\* flash sombre et brutal au clic sur les boutons "discrets" (`Vider`, `Supprimer`, boutons "+" et boutons-texte du Référentiel) : ces classes maison (`.btn-icone`, `.btn-texte`, `.btn-discret`, `.btn-danger-discret`) ne définissaient pas les variables `--bs-btn-active-*`, donc l'état pressé (`:active`) retombait sur la règle `.btn-outline-default, .btn-default:not(.btn-primary, ...)` de Bootstrap, plus spécifique (à cause du `:not()`) que nos classes seules, qui met le bouton en gris très foncé (`#404040`) le temps du clic — confirmé pixel par pixel (`getComputedStyle` pendant un vrai `mousedown` Playwright) après avoir écarté, sur l'enregistrement vidéo fourni, toute reconstruction intempestive du panneau "Écriture générée" (chaque mise à jour y reste unique et propre). Corrigé en fixant ces trois variables avec `!important` — seul moyen de battre la spécificité de la règle Bootstrap — pour que l'état pressé reste dans les tons discrets de chaque bouton au lieu de virer au noir. Voir `tests/test\_reactivite\_saisie.py`.



Reste à faire, notamment :



\* gestion des pièces justificatives numériques ;

\* décision définitive sur l'architecture des 5 centres (bases locales synchronisées ou connexion directe à `Hakili\_compta`) ;

\* supervision applicative (alertes automatiques en cas d'erreur, au-delà du fichier de log) ;

\* test de restauration documenté des sauvegardes ;

\* couverture de tests plus large (`tests/` ne couvre pour l'instant que l'authentification et quelques utilitaires purs).



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



