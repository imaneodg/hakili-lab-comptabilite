# 3. L'application, écran par écran

Ce chapitre décrit ce que voit chaque utilisateur. Faites ce tour vous-même sur votre base locale (chapitre 12) avant de lire le code : la moitié des choix techniques s'expliquent en voyant l'écran.

## 3.1 La connexion

L'écran de connexion demande trois choses : le **centre**, le **nom d'utilisateur** et le **code personnel**.

- Un identifiant appartient à une personne, pas à un centre : c'est ce qui permet de savoir qui a saisi et qui a validé (colonnes `saisi_par`, `valide_par`).
- Le nom d'utilisateur n'est pas sensible à la casse.
- Le code est haché avec **bcrypt** en base. Six caractères au minimum ; les codes trop faciles (`123456`, `000000`…) sont refusés.
- Après **5 essais faux**, le compte est bloqué **15 minutes**.
- Un code **provisoire** donné par le comptable doit être changé à la connexion : une fenêtre s'ouvre et la session ne démarre qu'une fois le nouveau code enregistré.
- Le navigateur retient le dernier centre choisi sur ce poste (stockage local).
- Si le comptable désactive un compte pendant qu'il est connecté, la session se ferme d'elle-même dans les deux secondes.

Après connexion, la barre latérale à gauche affiche le logo, les onglets autorisés, puis en bas le centre, le nom et le rôle, avec « Fermer la session ».

## 3.2 Qui voit quoi

| Onglet | Caissière (`saisie`) | Validateur local (`validation`, centre réel) | Comptable (`validation`, Siège) |
|---|---|---|---|
| Saisie | oui, pour son centre | oui, pour son centre | oui, pour le centre qu'il choisit |
| Brouillard | son centre | son centre | tous les centres |
| Validation | non | son centre | tous les centres, filtre par centre |
| Export Sage | non | consultation de son centre | fichier Sage, marquage « exportée » |
| Contrôles | son centre, sans la banque | son centre, sans la banque | tout, banque comprise |
| Tableau de bord | non | non | oui |
| Assistant IA | non | non | oui |
| Référentiel | création de comptes et de tiers, changement de son code | idem | tout : utilisateurs, soldes d'ouverture, nouvelle année, clôtures |

Ces droits sont **vérifiés côté serveur** à chaque action, pas seulement par l'absence d'un bouton. C'est un point sur lequel le projet a été audité plusieurs fois (voir `14_historique_des_decisions.md`) : masquer un widget ne protège rien, un client peut envoyer n'importe quelle valeur d'input à Shiny.

## 3.3 Saisie

L'écran a deux cartes côte à côte.

**À gauche, « Informations sur l'opération »** :

1. le **modèle d'opération**, regroupé par journal (CP, CMD, Banque, VTE, ACH, puis « Autres ») ;
2. la **date** de l'opération (refusée si elle dépasse aujourd'hui de plus de 7 jours, ou si le mois est clôturé) ;
3. pour le comptable seulement : le **centre concerné**, obligatoire ;
4. le journal, affiché en texte (il est imposé par le modèle ; seul « Écriture libre » le laisse choisir) ;
5. les champs propres au modèle (élève, montant, répartition par mois, nature de la dépense, etc.).

**À droite, « Écriture générée »** : l'écriture comptable telle qu'elle sera enregistrée, construite en direct, avec un ruban vert si elle est équilibrée et complète, ou un message qui dit ce qui manque. Puis les boutons **Enregistrer la pièce** et **Vider**.

Le bouton Enregistrer est désactivé pendant l'enregistrement, pour qu'un double-clic ne crée pas deux pièces.

Détails qui comptent pour la caissière :

- les champs « élève », « fournisseur » ou « bénéficiaire » proposent la liste des tiers existants et acceptent un nom nouveau, qui deviendra un tiers à l'enregistrement ;
- le tableau de **répartition** (encaissement, règlement fournisseur) permet de couvrir plusieurs mois en un paiement : une ligne par nature (Frais / Avance / Solde, ou Paiement / Avance / Solde), avec un ou plusieurs mois et un montant. L'écran affiche ce qui reste à répartir. Pour une avance, l'application propose le mois qui suit le dernier mois déjà payé par ce tiers ;
- le choix **Activité** (Cours d'appui / Camp de vacances) reste d'une pièce à l'autre : pendant le camp, la caissière n'a pas à le rechoisir à chaque fois ;
- les montants ne sont envoyés au serveur qu'en quittant le champ, pour que l'écriture ne se reconstruise pas à chaque chiffre tapé.

Le détail de chaque modèle et des écritures produites est au chapitre 4.

## 3.4 Brouillard

La liste des pièces, avec trois filtres : statut, journal, période (du 1er du mois à aujourd'hui par défaut). Une période qui commence avant le 1er janvier de l'année en cours va relire l'historique en base.

Au-dessus du tableau, un bandeau d'indicateurs : pièces affichées, entrées en caisse, sorties de caisse, virements internes (les mouvements via 585000, comptés une seule fois), puis le solde de chaque caisse visible. Les soldes portent toujours sur **tout l'historique**, quel que soit le filtre.

Actions sur la pièce sélectionnée :

- **Corriger la pièce** : rouvre la pièce dans Saisie, avec toutes ses valeurs d'origine (elles sont gardées dans `valeurs_json`). À l'enregistrement, la nouvelle pièce remplace l'ancienne dans la même transaction. Possible tant que la pièce n'est pas validée. Un bandeau rappelle qu'une correction est en cours, avec « Annuler la correction ».
- **Supprimer** : seulement une pièce non validée. Le contenu est archivé dans `suppressions_ecritures` (qui, quand, quoi) avant suppression.

Une pièce liée (approvisionnement, versement en banque) est toujours supprimée ou corrigée avec sa jumelle.

## 3.5 Validation

La file des pièces au statut « en attente de validation » ou « à corriger ». Le comptable peut filtrer par centre.

- **Tout sélectionner / Tout désélectionner** : ne prend que les lignes affichées (filtres compris). La grille ne garde qu'une ligne sur un clic simple ; Ctrl+clic ajoute, Maj+clic prend une plage. Le compteur à droite des boutons dit combien de pièces sont réellement choisies.
- **Valider les pièces choisies** : contrôle d'abord les anomalies bloquantes (une fenêtre les liste si besoin), puis attribue les numéros définitifs. Le message dit ce qui a été validé **et** ce qui a été écarté, avec la raison (pièce à corriger, compte d'attente à reclasser, déjà validée…).
- **Renvoyer pour correction** : motif obligatoire. La pièce repasse « à corriger » dans le brouillard du centre. Une pièce déjà exportée ne peut pas être renvoyée.
- **Corriger la pièce** : le validateur corrige lui-même au lieu de renvoyer.

## 3.6 Export Sage

Une seule carte, « Fichier d'import Sage ». Filtres : période (du… au…, par défaut du 1er du mois à aujourd'hui), journal, et la case **« Inclure les pièces déjà exportées »**. Le bandeau vert donne le nombre de pièces, de lignes et le total au débit. Trois boutons : **Télécharger le fichier Sage (.txt)**, **Télécharger en Excel** (pour relire), **Marquer comme exportées** (comptable seulement, avec confirmation ; ne touche que les pièces encore « validées »).

**Pièces déjà exportées** (décision d'Afiya du 08/10/2026) : par défaut elles ne sont jamais dans le fichier. Si la période en contient, un bandeau orange le dit (« Cette période contient N pièces déjà exportées vers Sage. Elles ne sont pas dans le fichier. »). Pour les renvoyer quand même, il faut cocher **deux** cases : « Inclure les pièces déjà exportées », puis, dans le bandeau rouge qui apparaît, « Je confirme vouloir les renvoyer à Sage ». Tant que la seconde n'est pas cochée, le fichier ne les contient pas. Les deux cases se décochent dès que la période ou le journal change. Le fichier porte alors le nom `sage_AAAAMMJJ_AVEC_DEJA_EXPORTEES.txt` et le journal de l'application (`hakili.log`) garde une ligne d'avertissement (qui, quelle période, combien de pièces).

Le protocole complet d'import dans Sage est au chapitre 10.

## 3.7 Contrôles

Le tableau des anomalies sur les pièces **non encore exportées** (une pièce exportée se corrige par extourne, pas ici). Deux gravités : **bloquante** (empêche la validation) et **à vérifier**.

| Anomalie | Gravité |
|---|---|
| Pièce déséquilibrée | bloquante |
| Pièce de caisse ou de banque sans ligne de trésorerie | bloquante |
| Compte absent du plan comptable | bloquante |
| Compte à tiers obligatoire sans code tiers (le lettrage serait impossible dans Sage) | bloquante |
| Même compte débité et crédité pour le même tiers (la pièce n'a aucun effet) | bloquante |
| Tiers inconnu du référentiel | bloquante |
| Code tiers de plus de 17 caractères | bloquante |
| Compte d'attente 471000 sur une pièce non validée | bloquante |
| Approvisionnement sans sa pièce jumelle | bloquante |
| Numéro définitif incohérent avec le journal | à vérifier |
| Ligne sans libellé | à vérifier |
| Solde de caisse négatif (par centre), ou de banque pour le comptable | à vérifier |

En sélectionnant une pièce sur 471000, un panneau **« Attribuer le compte et le tiers »** permet de la reclasser ; elle retourne dans la file de validation.

Si des pièces citent un tiers absent du référentiel (cas d'une restauration partielle), le comptable voit un bouton pour recréer les fiches manquantes.

## 3.8 Tableau de bord (comptable)

En haut : la période et les centres. Deux sous-pages : **Vue d'ensemble** (trois chiffres par centre, alertes, comparatif des centres, compte de résultat mensuel) et **Fiche centre** (Résultat, Élèves, Caisse, Fiabilité). Les cibles de marge et de trésorerie se règlent par centre. Détails au chapitre 8.

## 3.9 Assistant IA (comptable)

Une conversation : on pose une question en français (« combien saab a encaissé en fevirer », « fais-moi le point »), l'assistant répond en deux phrases avec le chiffre, et affiche sous la réponse des cartes dépliables avec le détail ou un graphique. Six questions essentielles sont proposées en pastilles à l'ouverture, et un menu « Questions fréquentes » en propose d'autres. Détails au chapitre 9.

## 3.10 Référentiel

- **Plan de comptes** et **Comptes de tiers** : listes complètes (repliées à 8 lignes, filtrables), bouton « + » pour créer. La création est ouverte à tous les rôles depuis le 23/09/2026, pour qu'une caissière ne soit pas bloquée par un tiers manquant ; le format est vérifié (compte sur 6 chiffres, code tiers préfixé par son collectif, 17 caractères au plus).
- **Utilisateurs** (comptable) : créer (identifiant, nom, rôle, centre, code de 6 caractères au moins), désactiver (rien n'est supprimé), réinitialiser un code oublié avec un code provisoire.
- **Paramètres** (comptable) :
  - **Soldes d'ouverture des caisses** : un montant par centre pour CP et CMD, un seul pour la banque. À saisir à la mise en service, sinon les soldes sont faux et souvent négatifs ;
  - **Nouvelle année académique** : une fois par an, à la rentrée ;
  - **Clôture des mois** : clôturer ou rouvrir un mois. Refusé s'il reste des pièces non exportées dans le mois.
- **Mon code d'accès** (tout le monde) : changer son code en donnant l'ancien.

## 3.11 Le rythme normal d'un mois

1. Chaque jour, les caissières saisissent leurs opérations.
2. Plusieurs fois par semaine, le comptable regarde Contrôles, reclasse les 471000, puis valide.
3. En début de mois, il saisit ou vérifie les transferts (contribution de chaque centre au SIAO, avec le bon motif des deux côtés).
4. Une fois le mois validé, il télécharge le fichier Sage, l'importe dans Sage, vérifie les totaux, puis marque les pièces comme exportées.
5. Quand Sage est à jour, il clôture le mois dans le Référentiel.
6. Il présente le tableau de bord à la direction.
