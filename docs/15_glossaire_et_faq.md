# 15. Glossaire et questions fréquentes

## 15.1 Glossaire

| Mot | Sens |
|---|---|
| **Brouillard** | cahier de caisse : liste chronologique des opérations. Avant, un classeur Excel par caisse ; aujourd'hui, l'onglet du même nom |
| **CP / CMD** | caisse principale / caisse menues dépenses, deux caisses physiques par centre |
| **Approvisionnement (APPROV CMD)** | passage d'argent de la CP vers la CMD |
| **Pièce** | une opération enregistrée (plusieurs lignes équilibrées) |
| **Pièces liées** | deux pièces d'une même opération sur deux journaux (approvisionnement, versement en banque) |
| **Numéro provisoire / définitif** | donné à la saisie (`PIS-2610-012`) / à la validation (`CP2610003`) |
| **Journal** | regroupement des pièces par nature (CP, CMD, Banque, VTE, ACH) |
| **Compte collectif** | compte qui regroupe tous les tiers d'un type (411000 élèves, 401000 fournisseurs, 422000 personnel) |
| **Tiers** | élève, fournisseur, enseignant, avec un code propre (`411KABORE`) |
| **Compte d'attente (471000)** | compte provisoire quand on ne sait pas encore ; à reclasser avant validation ; n'existe pas dans Sage |
| **Virements de fonds (585000)** | compte de passage de l'argent qui change de caisse sans quitter Hakili Lab |
| **Transfert entre centres** | remise d'argent d'un centre à un autre (contribution, prêt, remboursement, impôt), saisie par chacun des deux centres |
| **Contribution au SIAO (au siège)** | somme envoyée chaque mois par chaque centre au SIAO, jamais remboursée |
| **Section analytique** | code du centre dans Sage (`PSSY`, `TAMP`…), sur 4 caractères |
| **Pièce déjà exportée** | pièce au statut « exportée » ; ne repart vers Sage qu'avec les deux cases « Inclure les pièces déjà exportées » et « Je confirme vouloir les renvoyer à Sage » |
| **Extourne** | écriture inverse qui annule une écriture déjà dans Sage |
| **Clôture d'un mois** | le mois ne reçoit plus de pièce et ses pièces ne changent plus |
| **Frais CA / CV** | frais de cours d'appui / de camp de vacances |
| **Vacation, état de vacation** | rémunération d'un enseignant à l'heure ; l'état de vacation est la facture correspondante (retenue de 2 %) |
| **Retenue à la source** | part retenue sur un paiement et reversée à l'État (2 % vacations, 5 % gardiennage, IRF loyers) |
| **Base caisse** | compter à la date du paiement (règle du tableau de bord) |
| **Exploitation / hors exploitation** | activité courante / emprunts, prêts, équipement, impôts (pour l'instant) |
| **Plafond salarial** | salaires maximum pour garder la marge visée |
| **Capital de base** | argent à garder en caisse, en mois de charges (2 par défaut) |
| **SYSCOHADA** | référentiel comptable des pays de l'OHADA, dont le Burkina Faso |
| **Sage 100 (i7)** | logiciel comptable officiel de Hakili Lab |
| **`HAKILI_ECRITURES`** | nom du format d'import paramétré dans Sage |
| **Seed** | données de départ d'une base neuve (`sql/seed.sql`) |
| **Migration** | script SQL qui fait évoluer une base existante (`sql/migrations/`) |

## 15.2 Questions fréquentes

**Une caissière dit que l'écriture ne se construit pas.**
Le ruban sous l'écriture dit ce qui manque : un compte non choisi, un montant à zéro, une répartition qui ne fait pas le total, un motif de transfert absent. Si tout semble rempli, cherchez « Echec de construction des lignes » dans les journaux : un modèle a levé une exception.

**« Le mois de … est clôturé ».**
Le comptable a clôturé ce mois. Dater l'opération dans un mois ouvert, ou rouvrir le mois (Référentiel > Paramètres > Clôture des mois) si l'opération doit vraiment y être et que Sage sera corrigé en conséquence.

**Une caisse affiche un solde négatif.**
Soit le solde d'ouverture n'a pas été saisi pour ce centre, soit une entrée manque (souvent un approvisionnement CMD saisi d'un seul côté ou un transfert reçu non saisi), soit un montant est faux.

**Une pièce ne veut pas se valider.**
Le message dit pourquoi : anomalie bloquante (onglet Contrôles), compte 471000 à reclasser, pièce « à corriger » qui attend la caissière, ou déjà validée.

**Un élève n'apparaît pas dans la liste.**
Taper son nom : il sera créé à l'enregistrement. S'il existait l'année précédente, retaper exactement son nom ou son code le réactive. Vérifier ensuite qu'il existe dans Sage avant l'export.

**Sage rejette des lignes à l'import.**
Lire le compte rendu : tiers absent de Sage (le créer), compte absent, date hors exercice, longueur de code. Voir le tableau du chapitre 10.3. Ne jamais importer « seulement les lignes manquantes » à la main : supprimer dans Sage les écritures importées, corriger, réimporter le fichier entier.

**L'application ne démarre plus après un déploiement.**
`docker compose logs --tail=100 app`. Si c'est une migration, le message nomme le fichier et l'erreur PostgreSQL. Corriger par un commit, ou revenir au commit précédent (chapitre 11.4).

**L'écran se grise.**
La session Shiny est tombée (redémarrage du serveur, coupure réseau). Recharger la page. Si ça se répète, regarder les journaux à l'heure indiquée.

**L'assistant répond « la clé est refusée » ou « modèle introuvable ».**
`ANTHROPIC_API_KEY` ou `HAKILI_MODELE_IA` dans le `.env` du serveur, puis `docker compose up -d --force-recreate app`.

**Le tableau de bord classe une dépense dans la mauvaise rubrique.**
Regarder son compte et son libellé, puis la règle de `classement_comptes` qui l'a attrapée. Corriger par une nouvelle migration (chapitre 8.4), jamais en changeant le libellé des pièces exportées.

**Plus personne ne connaît le code du comptable.**
Sur le serveur : `docker compose exec app python outils/definir_code.py comptable`.

**Comment ajouter un centre ?**
Une migration : `INSERT INTO centres` (code de 3 lettres, intitulé, section analytique de 4 caractères, ordre, actif), les lignes de `soldes_ouverture_centre` pour CP et CMD, `parametres_centre`, des alias dans `centres_alias`. Créer la section dans Sage. Puis créer les utilisateurs du centre dans l'application.

**Comment ajouter un modèle de saisie ?**
Chapitre 4.1, avec un test.

**Où sont les vraies données pour tester ?**
Les brouillards 2026 (fichiers Excel locaux, non versionnés) et `import_historique.py` sur une base locale. Jamais la base de production.
