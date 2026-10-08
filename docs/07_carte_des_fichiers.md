# 7. Carte des fichiers du projet

Dossier de travail sur le PC d'Afiya : `C:\Users\USER\Desktop\STAGE_COMPTABILITE\HAKILI_LAB_postgres_2`. Dépôt Git : `https://github.com/imaneodg/hakili-lab-comptabilite`. Sur le serveur : `~/hakili_gestion_caisse`.

Légende : **Git** = versionné ; **local** = ignoré par Git, ne quitte pas le poste.

## 7.1 Racine

| Fichier | Git | Rôle |
|---|---|---|
| `app.py` | Git | L'application Shiny : interface, connexion, droits, tous les onglets sauf le tableau de bord. ~3 750 lignes. |
| `composants.py` | Git | Petites briques d'interface (`titre_page`, `carte_bandeau`, `filtre`, `stat`, `hk_info`, `format_montant`). Aucune logique. |
| `tableau_bord.py` | Git | Interface et serveur du module Tableau de bord (module Shiny `tb`). |
| `requirements.txt` | Git | Dépendances Python, versions figées. |
| `Dockerfile` | Git | Image de l'application (Python 3.14 slim, port 8022). |
| `docker-compose.yml` | Git | Production réelle : services `db` (postgres:16) et `app`, volume externe. |
| `.env.example` | Git | Modèle de configuration, sans aucune vraie valeur. |
| `.env` | **local** | Vraie configuration (base, clé Anthropic). Ne jamais versionner. |
| `.gitignore`, `.dockerignore` | Git | Exclusions. Très commenté : lisez-le, il explique pourquoi les classeurs Excel et certains scripts SQL sont exclus (noms réels d'élèves). |
| `conftest.py` | Git | Configuration pytest : charge `.env`, fixe la date du jour des tests au 01/01/2100 (les pièces de test sont datées 2098-2099). |
| `README.md` | Git | Ancienne présentation. **En partie périmée** (parle du port 8000 et d'un compose sans base). Ce dossier `docs/` la remplace. |
| `import_historique.py` | Git | Importe les brouillards Excel 2026 dans une base. Servait à construire la base de démonstration locale. **Pas pour la production** (décision du 16/09/2026). |
| `verifier.py` | Git | Recrée une base de test jetable `hakili_test` depuis `schema.sql` + `seed.sql`, puis lance toute la suite pytest. Ne touche jamais `Hakili_compta`. |
| `verifier_donnees.py` | Git | Importe les brouillards dans une base `hakili_verif` et contrôle la chaîne d'analyse et les graphiques. |
| `nettoyer_operations.py` | Git | Vieux script qui vide les écritures d'une base. **Dangereux**, à supprimer ou à ne jamais lancer. |
| `demo_manuel.py`, `mock_ocr_server.py` | Git | **Vides** : restes d'un essai d'intégration OCR abandonné. À supprimer. |
| `logo_Hakili_Lab.jpeg` | Git | Logo d'origine. |
| `HAKILI_LAB_postgres_2.code-workspace` | local | Espace de travail VS Code d'Afiya. |
| `hakili.log` | local | Journal de l'application en local. |
| `Plan_comptable.xlsx`, `Plan_tiers.xlsx` | **local** | Exports Sage du plan comptable (1 039 comptes) et du plan tiers (1 454 tiers). Noms réels : jamais sur GitHub. |
| `BROUILLARD_*_2026.xlsx` | **local** | Brouillards de caisse 2026 de Saaba et Tampouy (CP et CMD). Données personnelles. |
| `.venv/`, `__pycache__/`, `.pytest_cache/` | local | Environnement Python et caches. |

## 7.2 `logic/` — le métier

| Fichier | Rôle |
|---|---|
| `modeles.py` | Les modèles de saisie et leur traduction en écritures. Pas d'accès à la base. Voir chapitre 4. |
| `donnees.py` | Toute la couche base : pool de connexions, référentiel, écritures, enregistrement et correction, tiers, authentification et codes, numérotation, validation, renvoi, suppression, soldes, contrôles, export Sage (format du fichier, marquage), clôtures, révisions. ~2 000 lignes. |
| `migrations.py` | Joue `sql/migrations/*.sql` au démarrage. |
| `tableau_bord.py` | Calculs du tableau de bord (fonction unique `calculer()`). |
| `analyse.py` | Anciennes fonctions d'analyse financière déterministes (recettes, dépenses, masse salariale…). Encore utilisées par l'assistant (`assistant/semantique.py` en reprend les règles de transfert et de charges). |

## 7.3 `assistant/` — l'assistant IA

| Fichier | Rôle |
|---|---|
| `__init__.py` | Description des couches. |
| `config.py` | Réglages lus dans l'environnement (modèle, longueur des réponses, historique, bornes SQL). |
| `comprehension.py` | Texte libre → centre, période, tiers, catégorie (fautes tolérées : « saab », « fevirer »). |
| `semantique.py` | Écritures → faits (encaissements, décaissements, charges) avec une seule définition par chiffre. |
| `indicateurs.py` | Les indicateurs disponibles, dont ceux repris du tableau de bord. |
| `moteur.py` | Les calculs : analyser, comparer, soldes, lister, contrôles, personnel, point financier, requête SQL en lecture. |
| `outils.py` | Les 12 outils exposés au modèle d'IA, avec la portée de l'utilisateur. |
| `rendu.py` | Tableaux et graphiques (matplotlib) affichés dans les cartes du chat. |
| `prompt.py` | Consignes données au modèle, reconstruites à chaque question. |
| `session.py` | Une conversation par utilisateur : client Anthropic, historique borné, verrou, journal, messages d'erreur lisibles. |
| `questions.py` | Questions suggérées. |
| `referentiel.py` | Lecture du référentiel pour l'assistant. |
| `texte.py` | Dates et mois en français. |
| `journal.py` | Écriture dans `journal_assistant`. |

## 7.4 `sql/`

Voir chapitre 6 : `schema.sql`, `seed.sql`, `migrations/`, `diagnostic_production.sql`, et les scripts dangereux `production_reset.sql` et `purge_avant_mise_en_service.sql`. Les scripts de chargement des plans (`charger_plan_*.sql`, `seed_tiers.sql`) sont locaux.

## 7.5 `outils/` — scripts d'administration

| Fichier | Usage |
|---|---|
| `charger_plans.py` | Exécute les scripts de chargement des plans sans `psql` (Windows). |
| `comparer_plans.py` | Lecture seule : compare la base aux classeurs Sage. |
| `verifier_referentiel.py` | Lecture seule : ce que contient vraiment le référentiel. |
| `corriger_camp_2026.py` | Remet la marque du camp sur les pièces importées des brouillards (base de démo). Simulation par défaut, `--appliquer` pour écrire. |
| `definir_code.py` | Pose le code d'un utilisateur depuis le serveur, sans connaître l'ancien. Seul moyen de reprendre la main si plus personne ne connaît le code du comptable : `docker compose exec app python outils/definir_code.py comptable`. |
| `evaluer_assistant.py` | Pose une série de vraies questions à l'assistant (vrai modèle, vraie base) et affiche outils, réponses et durées. Coûte quelques centimes. |
| `tiers_trop_longs.sql` | Liste les codes tiers > 17 caractères et explique comment les renommer. |

## 7.6 `backup/`

| Fichier | Git | Rôle |
|---|---|---|
| `sauvegarde.sh` | à commiter | **La sauvegarde à utiliser** : `pg_dump` via `docker compose exec db`, contrôle du fichier, conservation 30 jours, copie rclone optionnelle. À mettre dans le crontab du compte `imane`. |
| `restauration_essai.sh` | à commiter | Restaure le dernier dump dans une base temporaire, compare les comptes, supprime la base temporaire. |
| `pg_backup.py`, `cron_sauvegarde_host.sh` | Git | Ancienne méthode, **inutilisable** sur ce serveur (exige `pg_dump` sur l'hôte et sudo). Gardés pour mémoire, à supprimer à terme. |
| `donnees_avant_correctifs_sage_2026-09-23.py` | Git | Copie de code versionnée par erreur. À supprimer. |
| `app_avant_*.py`, `avant_*/`, `ancien_tableau_bord_*/` | local | Copies de sécurité faites avant de grosses modifications. Inutiles maintenant que tout est dans Git. |
| `sauvegardes/` | local | Dumps de base. Jamais dans Git. |

## 7.7 `mcp_server/`, `services/`, `nginx/`, `www/`, `tests/`

| Chemin | Rôle |
|---|---|
| `mcp_server/server.py` | Façade MCP facultative sur les outils de l'assistant (non utilisée par l'application). |
| `services/ocr_client.py`, `services/__init__.py` | **Vides.** Projet d'OCR des factures abandonné (voir chapitre 13). |
| `nginx/hakili.conf` | Modèle de reverse proxy HTTPS. **Pas utilisé** : le nginx de production est celui de l'hôte, géré par l'administrateur. Utile comme base à lui transmettre. |
| `www/app.css` | Toute la charte : variables `--hk-*`, barre latérale marine, cartes blanches, boutons. |
| `www/tableau_bord.css` | Styles du tableau de bord. |
| `www/fonts/`, `www/bootstrap-icons/` | Polices (Inter, Public Sans) et icônes, servies localement pour fonctionner sans Internet. |
| `www/*.png`, `favicon.ico` | Logos et icônes. |
| `tests/` | ~300 tests pytest (voir chapitre 12). `test_ocr_client.py` est vide. |

## 7.8 `Claude outputs/` — à manipuler avec précaution

Dossier **local** où ont été déposés les rapports d'audit, des captures d'écran, des fichiers de test Sage et des études de design. Il contient aussi un fichier **`env` avec le mot de passe PostgreSQL de production en clair**.

- Ne le copiez pas, ne l'envoyez pas, ne le versionnez jamais.
- Les documents utiles qu'il contient sont repris dans ce dossier `docs/` et dans le projet claude.ai « tu ».
- Recommandation : supprimer ce fichier `env` une fois la passation faite, puis changer le mot de passe de la base (chapitre 11).

## 7.9 Hors du dossier

- Le **projet claude.ai « tu »** contient l'historique détaillé du travail : audits (18/09, 22/09, 25/09, 07/10), comptes rendus de correctifs, de déploiements, de l'import Sage, du tableau de bord et de l'assistant. Ce dossier en est la synthèse ; les originaux restent utiles pour le détail d'une décision.
- Le **dossier Sage 100** « HAKILI LAB SARL COMPTABILITE DEFINITIF 2026 » et son format d'import `HAKILI_ECRITURES` sont sur le poste du comptable (emplacement à préciser par Afiya).
