# 14. Historique et décisions

Ce chapitre explique **pourquoi** le code est comme il est. Avant de « simplifier » quelque chose qui paraît compliqué, cherchez ici : c'est souvent la correction d'un vrai problème.

## 14.1 Chronologie

| Date (2026) | Étape |
|---|---|
| Août | Première version en R sur classeurs Excel, puis portage en Python (Shiny for Python) sur PostgreSQL |
| 05/09 | Codes d'accès hachés bcrypt, verrouillage après 5 échecs, trace des suppressions, versions figées, Docker |
| 10/09 | Audit complet : droits refaits côté serveur sur dix actions ; écran instable corrigé (onglets construits une fois par connexion, `reactive.isolate`, montants envoyés en quittant le champ) ; export en cp1252 |
| 11/09 | Refonte visuelle (barre latérale marine, cartes blanches, bleu `#1A5FD0`) ; une caisse physique **par centre** avec ses propres soldes ; changement de banque BDU-BF → CBI (521200), l'ancien journal gardé inactif ; validateur local limité à son centre |
| 12/09 | Transferts entre centres par le compte 585000 avec référence de rapprochement ; la validation dit ce qu'elle a écarté et pourquoi |
| 15/09 | Remise en service : dépôt réaligné sur la production (port 8022, service `db`), migrations rattrapées, PostgreSQL refermé sur 127.0.0.1, `chatlas[anthropic]` ; une pièce exportée ne peut plus être renvoyée ; « exportée » seulement si validée ; double clic neutralisé |
| 16/09 | Décision : pas d'import des brouillards historiques, la production démarre vide |
| 18/09 | Plans comptable (1 040) et tiers (1 454) chargés depuis Sage ; session grisée corrigée (connexions mortes, sondage tolérant) ; saisie multi-mois ; filtre centre en validation |
| 22/09 | Correctifs de l'audit du 18/09 : équilibre et signe imposés par la base, correction de pièce atomique, migrations jouées au démarrage, double rapprochement des transferts impossible |
| 23/09 | Premiers essais d'import Sage (CRLF, sections sur 4 caractères, pièces équilibrées) ; création de comptes et de tiers ouverte à tous ; compte d'attente bloquant ; correction de toute pièce non validée ; nettoyage de la base de production ; virements internes à part dans le Brouillard |
| 24-25/09 | Assistant IA reconstruit (outils dans l'application, compréhension des fautes, une seule définition des chiffres), puis réorienté vers le directeur ; numérotation par date puis centre, numéro rendu à une pièce renvoyée ; règlement fournisseur réparti par mois ; « Tout sélectionner » en validation |
| 02-03/10 | Tableau de bord : d'abord trois chiffres et compte de résultat mensuel, puis version direction (vue d'ensemble + fiche centre), aux couleurs de l'application |
| 07/10 | Camp de vacances séparé ; cibles par centre ; motif obligatoire des transferts ; toutes les saisies passent désormais par l'application ; audit complet |
| 08/10 | Correctifs de l'audit du 07/10 (non déployés) ; rédaction de ce dossier |

## 14.2 Les décisions métier

| Décision | Date | Pourquoi |
|---|---|---|
| Sage reste le livre officiel ; l'application prépare et contrôle | dès le départ | Hakili Lab a déjà son dossier Sage et son comptable |
| La caissière ne voit jamais « débit » ni « crédit » | dès le départ | les caissières ne sont pas comptables ; les modèles traduisent |
| Chaque centre a sa caisse et ses soldes d'ouverture ; la banque est commune | 10-11/09 | confirmé par le comptable ; un solde commun masquait une caisse à sec |
| Pas d'import des brouillards historiques | 16/09 | trop d'erreurs dans les fichiers ; on repart propre |
| Création de comptes et de tiers ouverte à tous les rôles, tiers actif immédiatement | 23/09 | une caissière ne doit pas être bloquée ; le format est contrôlé à la création |
| Le compte d'attente 471000 bloque la validation | 23/09 | il n'existe pas dans Sage |
| Libellés : nature et mois d'abord, nom ensuite ; mois abrégés et tous cités (`OCT-NOV-DEC`) | 18 et 25/09 | le comptable veut lire chaque mois ; le code tiers identifie déjà la personne |
| Libellé envoyé entier à Sage (60 caractères), pas de coupe à 35 | 23/09 | demande d'Afiya, en attendant de mesurer la limite réelle de Sage |
| Numéro définitif à la validation, par date puis centre (SIAO, Tampouy, Saaba, Pissy, Nagrin) | 25/09 | les numéros se suivent dans Sage, qui lit par date |
| Ne pas donner le rôle validation aux centres | 25/09 | le comptable valide seul |
| L'assistant parle au directeur, en mots simples | 24/09 | c'est lui qui pose les questions |
| Tableau de bord en base caisse ; Résultat = argent reçu − charges d'exploitation payées ; caisses et banque séparées | 02/10 | même logique que l'analyse de Tampouy qui a servi de modèle |
| Le Siège n'est pas un centre ; la contribution au siège = contribution au SIAO | 02/10 | règle du propriétaire |
| Camp reconnu au libellé, jamais au mois | 03/10 | un cours de juillet reste un cours |
| Achats d'équipement hors exploitation | 03/10 | un achat de matériel n'est pas une dépense courante |
| Motif obligatoire et sans valeur par défaut pour les transferts | 07/10 | un choix prérempli est validé sans être lu ; un prêt était compté comme une charge |
| Toutes les saisies dans l'application, plus de brouillards | 07/10 | harmoniser les libellés, fiabiliser les chiffres |
| Comptable : centre concerné obligatoire | 08/10 | ses saisies partaient au Siège |
| Date d'opération au plus 7 jours après aujourd'hui | 08/10 | une faute de frappe (2062) ne doit pas passer |
| Écrans de travail : année en cours + pièces non exportées | 08/10 | rapidité ; l'historique se relit par période |
| Assistant = mêmes chiffres que le tableau de bord pour résultat, charges, marge | 08/10 | jamais deux réponses différentes à la direction |
| Code du comptable laissé tel quel | 08/10 | décision d'Afiya, voir chantiers |
| Impôts (64) en exploitation | reporté | à trancher avec la direction |
| Une pièce exportée ne peut être réexportée qu'avec un consentement explicite | 08/10 | éviter les doublons dans Sage |

## 14.3 Les décisions techniques

| Décision | Pourquoi |
|---|---|
| PostgreSQL plutôt qu'Excel ; contraintes et triggers en base | plusieurs postes en même temps, et aucune erreur de code ne doit pouvoir déséquilibrer la comptabilité |
| Numérotation par compteur `INSERT … ON CONFLICT … RETURNING` | atomique sans verrou applicatif |
| Validation sous `SELECT … FOR UPDATE` | deux validateurs simultanés perdaient des numéros |
| Sondage d'une ligne `revision` toutes les 2 s | voir les saisies des autres postes sans tout relire |
| Révisions séparées écritures / référentiel ; connexion sans effet | une simple connexion relançait tous les calculs de toutes les sessions |
| Onglets construits une fois par connexion | une saisie ailleurs effaçait le formulaire en cours |
| Migrations jouées au démarrage, échec = pas de démarrage | la panne du 15/09 venait de migrations oubliées |
| Export Sage : retour à l'écran d'avant (pas de lots), pièces déjà exportées exclues par défaut, alerte, double case pour les renvoyer (08/10, Afiya) | garder l'écran connu du comptable sans pouvoir renvoyer une pièce à Sage par oubli |
| Trigger de protection des pièces exportées et des mois clôturés | seules les règles Python protégeaient le passé |
| Contrôles vectorisés, seules les pièces non exportées | 54 s → moins d'une seconde à 25 000 pièces |
| Outils de l'assistant dans l'application (plus de sous-processus MCP) | démarrage fragile, secrets transmis, réponses sans outils |
| Requête libre de l'assistant sous un rôle PostgreSQL de lecture | le filtre par nom de table était contournable |
| Sauvegarde par `docker compose exec db pg_dump` | pas de `pg_dump` ni de `sudo` sur l'hôte |
| Icônes et polices servies localement | les postes de caisse peuvent perdre Internet |

## 14.4 Les audits

Les rapports complets sont dans le projet claude.ai « tu » :

| Audit | Points principaux | État |
|---|---|---|
| 10/09 | droits côté serveur, écran instable | corrigés |
| 15/09 | dépôt ≠ production, migrations, PostgreSQL exposé | corrigés |
| 18/09 | équilibre en base, correction non atomique, migrations, export, sauvegardes, HTTPS | corrigés sauf HTTPS (administrateur) |
| 22/09 et 25/09 | suivi, dette technique | intégrés |
| 07/10 | sauvegardes, export, code 9999, codes tiers, performance, numéros perdus, clôture, dates, transferts, assistant ≠ tableau de bord, Siège, SQL de l'assistant, codes d'accès | corrigés le 08/10 (non déployés) sauf code 9999 (décision), impôts (reporté), A2/A3/A5, interface, dette |
