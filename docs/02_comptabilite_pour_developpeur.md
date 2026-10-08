# 2. La comptabilité qu'il faut connaître (pour développeur)

Vous n'avez pas besoin d'être comptable pour maintenir cette application. Il faut en revanche comprendre une dizaine de notions, parce que le code les applique partout et que les tests vérifient qu'elles sont respectées. Ce chapitre les explique avec les exemples réels de Hakili Lab.

## 2.1 La partie double

Chaque opération s'écrit sur **au moins deux comptes**. Un compte reçoit (on écrit le montant au **débit**), un autre donne (on écrit le montant au **crédit**). La somme des débits est **toujours** égale à la somme des crédits. C'est la règle de base, et la base de données la vérifie elle-même (trigger `trg_equilibre_piece`).

Exemple : un élève paie 15 000 F de frais d'octobre en espèces à la caisse principale de Pissy.

| Compte | Intitulé | Débit | Crédit |
|---|---|---|---|
| 571100 | Caisse principale | 15 000 | |
| 411000 (tiers `411KABORE`) | Clients (élèves) | | 15 000 |

La caisse **augmente** (débit), et la dette de l'élève envers Hakili Lab est soldée (crédit sur son compte client).

Moyen mnémotechnique côté trésorerie : **l'argent qui entre en caisse est au débit de la caisse, l'argent qui sort est au crédit de la caisse.**

Dans la base, une ligne a soit un débit, soit un crédit, jamais les deux, et jamais négatif (contrainte `ck_montants_positifs`).

## 2.2 Pièce, ligne, écriture

- Une **ligne** = un compte, un montant au débit ou au crédit, un libellé. Table `ecritures`, une ligne par enregistrement.
- Une **pièce** = l'ensemble des lignes d'une même opération (colonne `id_piece`). Elle doit être équilibrée.
- Deux pièces peuvent être **liées** (colonne `id_lien`) : c'est le cas quand une opération touche deux journaux, par exemple l'approvisionnement de la petite caisse (une pièce dans CP, une dans CMD). Elles sont validées, exportées et supprimées ensemble.

## 2.3 Le plan comptable SYSCOHADA

Le Burkina Faso applique le référentiel **SYSCOHADA** (système comptable de l'OHADA). Les comptes ont 6 chiffres chez Hakili Lab ; le premier chiffre est la **classe** :

| Classe | Nature | Exemples chez Hakili Lab |
|---|---|---|
| 1 | Capitaux, emprunts | 160100 Emprunts bancaires, 160200 Emprunts auprès des associés |
| 2 | Immobilisations | 244100 Matériel et mobilier de bureau, 272800 Prêts au personnel |
| 4 | Tiers (clients, fournisseurs, personnel, État) | 411000 Clients (élèves), 401000 Fournisseurs, 422000 Personnel, 447810 Retenues |
| 5 | Trésorerie | 571100 Caisse principale, 571200 Caisse menues dépenses, 521200 Banque CBI, 585000 Virements de fonds |
| 6 | Charges | 605300 Carburant, 622200 Loyer, 632710 Vacations, 646200 Timbres |
| 7 | Produits | 706110 Cours d'appui maths/PC, 707810 Frais de document |

Le plan complet (1 040 comptes) a été chargé en production le 18/09/2026 depuis l'export Sage (`Plan_comptable.xlsx`). Le fichier `sql/seed.sql` n'en contient qu'une soixantaine, pour une base de développement.

Dans la table `comptes`, chaque compte a une **nature** (`charge`, `produit`, `tresorerie`, `bilan`, `tiers`), un indicateur `tiers_obligatoire` (oui pour 401000, 411000, 422000) et un indicateur `depense_courante` (les comptes proposés dans le formulaire « Dépense courante »).

## 2.4 Les tiers et les comptes collectifs

Un **tiers** est une personne ou une entreprise avec qui Hakili Lab a un compte : un élève, un fournisseur, un enseignant. Plutôt que de créer un compte de classe 4 par élève, la comptabilité utilise un **compte collectif** (`411000` pour tous les élèves) et un **code tiers** qui précise qui (`411KABORE`).

Convention de Hakili Lab, respectée par les 1 454 tiers du plan Sage : **le code tiers commence par les trois chiffres de son collectif**, suivis du nom en majuscules sans espace ni accent.

| Collectif | Type | Exemple de code |
|---|---|---|
| 411000 | élève (client) | `411OUEDRAOGOAFIYA` |
| 401000 | fournisseur, vacataire, bailleur | `401SONABEL`, `401BAILLEURSAABA` |
| 422000 | personnel salarié | `422KABORE` |

**Longueur maximale : 17 caractères.** Le dossier Sage est réglé sur 17 et tronque sans prévenir au-delà ; deux élèves différents finiraient sur le même compte. L'application refuse tout code plus long (fonctions `ajouter_tiers`, `resoudre_tiers` dans `logic/donnees.py`).

Quand une caissière tape un nom d'élève absent de la liste, l'application **crée le tiers au moment de l'enregistrement** (`resoudre_tiers`). Conséquence importante pour l'export : ce tiers n'existe pas encore dans Sage. Il faut le créer dans Sage avant d'importer, sinon la ligne est rejetée (voir `10_export_sage.md`).

Chaque année, à la rentrée, le comptable clique sur « Nouvelle année académique » : les tiers de l'année passée disparaissent des listes de saisie (`actif_annee = 'non'`) sans être supprimés. Un élève qui revient est réactivé avec son ancien code dès qu'on retape son nom.

## 2.5 Les journaux

Un **journal** regroupe les pièces d'une même nature. Sage impose de travailler journal par journal.

| Journal | Intitulé | Compte de trésorerie | Type | Remarque |
|---|---|---|---|---|
| `CP` | Caisse principale | 571100 | trésorerie | une caisse physique par centre |
| `CMD` | Caisse menues dépenses | 571200 | trésorerie | une caisse physique par centre |
| `Banque` | CBI | 521200 en production | trésorerie | compte unique, commun à tous les centres |
| `BDU-BF` | Ancienne banque | 521100 | trésorerie | inactif depuis le 11/09/2026, historique seulement |
| `VTE` | Ventes | aucun | opérations | factures de cours d'appui |
| `ACH` | Achats | aucun | opérations | factures fournisseurs, états de vacation |

Attention : `sql/seed.sql` décrit encore le journal `Banque` sur 521100. La production et Sage sont sur **521200**. Sans conséquence tant qu'on ne recrée pas une base de zéro pour la production ; à corriger dans le seed (voir chantiers).

Un journal de **trésorerie** a un compte de contrepartie fixe : dans toute pièce de ce journal, l'application écrit elle-même la ligne de caisse ou de banque. Un journal d'**opérations** (VTE, ACH) n'a pas de caisse : ses modèles écrivent leurs deux comptes.

## 2.6 Les caisses physiques et les soldes

Chaque centre a sa propre CP et sa propre CMD. Le solde d'une caisse se calcule par centre :

```
solde = solde d'ouverture du centre (table soldes_ouverture_centre)
      + somme des débits du compte de caisse pour ce centre
      − somme des crédits du compte de caisse pour ce centre
```

La banque est unique : son solde d'ouverture est dans `journaux.solde_ouverture` et ses mouvements ne sont jamais ventilés par centre.

Un solde de caisse **négatif** est impossible dans la réalité (on ne peut pas sortir plus d'espèces qu'on n'en a). L'onglet Contrôles le signale : soit une pièce manque, soit un montant est faux, soit le solde d'ouverture n'a pas été saisi.

## 2.7 Le compte 585000 « Virements de fonds »

Quand de l'argent passe d'une caisse à une autre **sans quitter Hakili Lab**, ce n'est ni une recette ni une dépense. SYSCOHADA fait passer ce mouvement par un **compte de passage**, le 585000 : la caisse de départ le crédite, la caisse d'arrivée le débite, et le 585000 revient à zéro quand les deux côtés sont saisis.

Trois cas dans l'application :

| Opération | Côté départ | Côté arrivée | Saisie |
|---|---|---|---|
| Approvisionnement de la CMD | CP crédit 571100, débit 585000 | CMD débit 571200, crédit 585000 | une seule saisie, deux pièces liées |
| Versement d'espèces en banque | CP crédit 571100 (+ timbre), débit 585000 | Banque débit 521200, crédit 585000 | une seule saisie, deux pièces liées |
| Transfert entre centres (contribution, prêt…) | caisse du centre donateur | caisse du centre destinataire | **chaque centre saisit sa face**, rapprochées par une référence `TRF-AAAAMM-0001` |

Pour le transfert entre centres, chaque face est saisie par son propre centre parce que l'argent met parfois des semaines à arriver et qu'un centre ne doit jamais écrire dans les livres d'un autre. Le rapprochement se fait par la référence ; un écart de montant reste visible.

Les tableaux de bord excluent ces virements des recettes et des dépenses, **sauf** quand le motif en fait une charge pour le centre donateur (contribution au SIAO) ou un mouvement hors exploitation (prêt, impôt).

## 2.8 Le compte 471000 « Compte d'attente »

Quand une caissière ne sait pas sur quel compte passer une opération, elle peut utiliser le formulaire « Écriture libre » avec le **compte d'attente 471000**. C'est un compte provisoire, interne à l'application : il **n'existe pas dans Sage** et ne doit jamais y partir.

- Une pièce sur 471000 **ne peut pas être validée** (contrôle bloquant).
- Le comptable la **reclasse** depuis l'onglet Contrôles : il choisit le bon compte (et le tiers si besoin), la pièce repart en attente de validation.

## 2.9 Statuts d'une pièce et numérotation

```
 saisie ──valider──► validee ──export + marquage──► exportee
   ▲   ╲                │
   │    ╲──renvoyer──►  │
   │       a_corriger ◄─┘ (renvoi possible tant que non exportée)
   └──corriger (nouvelle pièce qui remplace l'ancienne)
```

- **Numéro provisoire** à la saisie : `{centre}-{AAMM}-{nnn}`, par centre et par mois (ex. `PIS-2610-012`).
- **Numéro définitif** à la validation : `{préfixe du journal}{AAMM}{nnn}`, par journal et par mois, **tous centres confondus** (ex. `CP2610003`). Dans un lot validé, les numéros suivent la **date**, puis l'**ordre des centres** (SIAO, Tampouy, Saaba, Pissy, Nagrin), puis l'heure de saisie. Une pièce oubliée et validée plus tard prend le numéro suivant, comme dans Sage.
- Une pièce **renvoyée** après validation garde son numéro de côté (`num_reserve`) et le retrouve à la revalidation : pas de trou.
- La numérotation continue sans trou est une obligation de l'Acte uniforme OHADA. La base refuse deux pièces avec le même numéro dans un journal (trigger `trg_numero_unique`), et la validation verrouille les lignes pour que deux validateurs simultanés ne perdent pas de numéros.

## 2.10 Une pièce exportée ne se modifie plus : l'extourne

Une fois dans Sage, une pièce fait partie du livre officiel. On ne la corrige plus en la modifiant : on passe une **écriture d'extourne** (la même écriture à l'envers, qui annule la première), puis la bonne écriture. Dans l'application, une pièce `exportee` ne peut être ni modifiée, ni supprimée, ni renvoyée ; la base l'interdit aussi (trigger `trg_proteger_ecritures`).

De même, un **mois clôturé** par le comptable ne reçoit plus aucune pièce et ses pièces ne changent plus. On ne clôture qu'un mois entièrement exporté.

## 2.11 Base caisse ou base engagement

Deux façons de compter le résultat d'un mois :

- **base caisse** : on compte l'argent à la date où il entre ou sort de la caisse. Un élève qui paie en mars ses cours d'avril compte en mars.
- **base engagement** (ou « rattachement ») : on compte le cours dans le mois où il est donné. Les frais d'avril payés en mars comptent en avril.

**Le tableau de bord est en base caisse** (décision du 02/10/2026, comme le fichier d'analyse de Tampouy qui a servi de modèle). L'assistant IA sait faire les deux, mais par défaut il donne les chiffres du tableau de bord pour « bénéfice, résultat, marge, charges », pour que la direction n'ait jamais deux réponses différentes.

## 2.12 Exploitation et hors exploitation

Le tableau de bord sépare :

- **les encaissements d'exploitation** : cours d'appui, camp de vacances, frais de document, contributions reçues (pour le SIAO) ;
- **les charges d'exploitation** : vacations et salaires, contribution au SIAO, loyer, eau, électricité, internet, fournitures, entretien, frais bancaires…
- **les sorties hors exploitation** : remboursements d'emprunts, prêts entre centres, achats d'équipement, avances au personnel, dossiers de conseil et, pour l'instant, les **impôts et taxes**.

**Résultat = encaissements d'exploitation − charges d'exploitation.** Les sorties hors exploitation sont affichées à part.

Point en suspens : en SYSCOHADA, les impôts et taxes (comptes 64) sont des charges d'exploitation. Les passer en exploitation est une ligne de SQL (`UPDATE rubriques_tableau SET bloc = 'charge' WHERE rubrique = 'impots';`), mais la décision a été **reportée** par Afiya le 08/10/2026. À trancher avec la direction.

## 2.13 Retenues à la source

Sur certaines factures, Hakili Lab retient une partie du montant pour la reverser à l'État :

- **état de vacation** : retenue de 2 % automatique (compte 447810) ;
- **gardiennage** : retenue de 5 % (447820) ;
- **loyer** : retenue IRF (447800), montant saisi à la main car le taux varie d'une pièce à l'autre.

Le fournisseur reçoit le net ; la charge est comptée en brut.

## 2.14 Sage 100 en deux phrases

Sage 100 Comptabilité i7 est le logiciel comptable officiel de Hakili Lab. L'application lui envoie un fichier texte qu'on importe par un **format paramétrable** nommé `HAKILI_ECRITURES` ; tout le détail, y compris les pièges de longueur des codes, est dans `10_export_sage.md`.
