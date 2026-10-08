# HAKILI LAB – Gestion Comptable : dossier de passation

*Rédigé le 8 octobre 2026, à la reprise du projet par une nouvelle développeuse ou un nouveau développeur.*

Ce dossier explique tout le projet à quelqu'un qui n'en a jamais entendu parler : pourquoi il existe, comment s'en sert Hakili Lab, la comptabilité qu'il faut comprendre, le code fichier par fichier, la base de données, le serveur et ce qui reste à faire. Une fois lu, vous n'aurez plus besoin de personne pour continuer.

## Par où commencer

Lisez dans l'ordre. Comptez une journée pour tout lire et une deuxième pour faire tourner l'application chez vous.

| Ordre | Fichier | Ce que vous y apprenez |
|---|---|---|
| 1 | `01_le_projet.md` | Hakili Lab, ses centres, le problème que l'application résout |
| 2 | `02_comptabilite_pour_developpeur.md` | La comptabilité minimale à connaître (partie double, comptes, journaux, Sage) |
| 3 | `03_utiliser_l_application.md` | Chaque écran, vu par la caissière, le validateur et le comptable |
| 4 | `04_modeles_de_saisie.md` | Les formulaires et les écritures exactes qu'ils produisent |
| 5 | `05_architecture.md` | Comment le code est organisé et comment Shiny rafraîchit les écrans |
| 6 | `06_base_de_donnees.md` | Les tables, les triggers, les fonctions SQL, les migrations |
| 7 | `07_carte_des_fichiers.md` | À quoi sert chaque fichier du dossier, y compris ceux qu'il ne faut pas toucher |
| 8 | `08_tableau_de_bord.md` | Le tableau de bord du comptable et de la direction |
| 9 | `09_assistant_ia.md` | L'assistant qui répond aux questions en français |
| 10 | `10_export_sage.md` | Comment les écritures partent dans Sage 100, et les pièges de Sage |
| 11 | `11_serveur_et_deploiement.md` | Le serveur, s'y connecter, déployer, sauvegarder, restaurer |
| 12 | `12_developper_en_local.md` | Installer le projet sur votre poste, lancer les tests, Git |
| 13 | `13_etat_actuel_et_chantiers.md` | Où en est le projet le 08/10/2026 et ce qu'il faut faire ensuite, par priorité |
| 14 | `14_historique_des_decisions.md` | Les décisions prises en cours de route et pourquoi |
| 15 | `15_glossaire_et_faq.md` | Les mots du métier et les questions qu'on se pose la première semaine |

Le même contenu existe en un seul livre Word et PDF (`HAKILI_LAB_Dossier_de_passation`), à lire d'une traite.

## Ce qu'il faut retenir si vous ne lisez qu'une page

- **L'application** remplace les cahiers de caisse Excel (les « brouillards ») des cinq centres de Hakili Lab. Les caissières saisissent des opérations simples (« un élève paie ses frais »), l'application écrit l'écriture comptable, le comptable la valide, puis l'exporte dans **Sage 100**, qui reste le logiciel comptable officiel.
- **La technique** : Python, Shiny for Python pour l'interface, PostgreSQL pour les données, Docker sur un serveur Linux. L'assistant IA utilise l'API d'Anthropic.
- **Le serveur** : `167.233.234.219`, compte `imane`, dossier `~/hakili_gestion_caisse`, application sur le port 8022. Le compte n'a pas les droits administrateur : tout passe par Docker.
- **La règle d'or en production** : on déploie du code, jamais des données. Ne lancez jamais `docker compose down -v`, ni `schema.sql`, `seed.sql`, `production_reset.sql` ou `purge_avant_mise_en_service.sql` sur la base de production.
- **L'état au 08/10/2026** : les correctifs de l'audit du 07/10 sont écrits et testés (299 tests) mais **ni commités ni déployés**. Le tableau de bord est sur la branche `tableau-bord-v2`, pas encore fusionnée dans `main`. Voir `13_etat_actuel_et_chantiers.md`.

## À compléter par Afiya avant la remise du dossier

Certaines informations ne doivent pas être écrites dans un fichier, ou n'étaient pas connues au moment de la rédaction. Afiya les remet **en main propre** (jamais par e-mail ni dans le dépôt).

| Information | Où elle sert | Statut |
|---|---|---|
| Mot de passe SSH du compte `imane` (ou mieux : un compte propre au repreneur, créé par l'administrateur) | Se connecter au serveur | À remettre en main propre |
| Contact de l'administrateur du serveur (nom, téléphone) | HTTPS, nginx, sudo, création de compte | À compléter : ……………… |
| Adresse web à laquelle les caissières ouvrent l'application | Tests en production, support | À compléter : ……………… |
| Fichier `.env` du serveur (mot de passe PostgreSQL, clé Anthropic) | Il reste sur le serveur, on ne le copie pas | Expliquer où il est, ne pas l'envoyer |
| Code d'accès actuel du compte `comptable` en production | Administrer l'application | À remettre en main propre, puis à changer |
| Compte GitHub : ajout du repreneur comme collaborateur sur `imaneodg/hakili-lab-comptabilite` | Pousser le code | À faire sur GitHub |
| Compte Anthropic qui porte la clé de l'assistant (qui paie, qui peut régénérer la clé) | Assistant IA | À compléter : ……………… |
| Emplacement du dossier Sage 100 et du format d'import `HAKILI_ECRITURES` | Export vers Sage | À compléter : ……………… |
| Nom et contact du comptable de Hakili Lab | Toute question de classement comptable | À compléter : ……………… |
