# 10. L'export vers Sage 100

Sage 100 Comptabilité i7 est le livre officiel. L'application lui envoie les pièces **validées** sous forme d'un fichier texte, importé par un format paramétrable. Ce chapitre réunit tout ce qui a été appris en septembre 2026, souvent à la dure.

## 10.1 Le fichier produit

Fonctions `format_sage()` et `texte_fichier_sage()` dans `logic/donnees.py`.

- Texte **Windows-1252** (cp1252), un caractère impossible devient `?` au lieu de faire planter l'export ;
- fins de ligne **CRLF** (`\r\n`). En LF, Sage lit tout le fichier comme une seule ligne et n'importe rien, sans aucun message ;
- séparateur **point-virgule**, pas d'en-tête, pas de guillemets ;
- **9 colonnes, dans cet ordre** :

| # | Colonne | Exemple | Remarque |
|---|---|---|---|
| 1 | Journal | `CP` | |
| 2 | Date | `01042026` | jjmmaaaa |
| 3 | Pièce | `CP2604008` | numéro définitif |
| 4 | Compte | `411000` | 6 chiffres |
| 5 | Tiers | `411FRANCELINE` | vide si aucun (d'où des `;;`) |
| 6 | Libellé | `FRAIS CA MAR - …` | `;`, `"` et retours à la ligne retirés |
| 7 | Débit | `0,00` | virgule décimale |
| 8 | Crédit | `36000,00` | |
| 9 | Section | `PSSY` | `centres.section_analytique` |

Une pièce est toujours exportée **entière et équilibrée** (la ligne de caisse globale des encaissements multi-mois est gardée : sans elle, Sage refusait la pièce).

## 10.2 Le dossier Sage : réglages indispensables

Sage impose des **longueurs fixes** décidées à la création du dossier. Trop court, il complète par des zéros ; trop long, il tronque ; **dans les deux cas sans prévenir**. Et la plupart de ces réglages se verrouillent dès qu'un enregistrement existe. D'où l'ordre : créer, régler, puis charger.

| Réglage | Valeur |
|---|---|
| Longueur des comptes généraux | 6 |
| Longueur des comptes tiers | **17** (sinon « La longueur du compte est incorrecte ») |
| Longueur des sections analytiques | 4 (`PSSY`, `TAMP`, `SAAB`, `SIAO`, `NAGR`, `SIEG`) |
| Analytique | « Ignorer la préventilation » ; plan renommé CENTRES |
| Natures de comptes (Client, Caisse, Banque, charges, produits) | « Autoriser la saisie analytique » cochée |
| Exercice | 01/01/2026 – 31/12/2026, franc CFA |
| Journaux | `CP`, `CMD`, `Banque` (521200), `BDU-BF` (521100), `VTE`, `ACH`. Vérifier que Sage accepte des codes de 6 caractères ; sinon renommer `Banque` en `CBI` ou `BQ` côté application |
| Compte 471000 | **N'existe pas dans Sage**, n'y envoyez jamais une pièce qui le porte |

**Format d'import `HAKILI_ECRITURES`** (Fichier > Format import/export paramétrable) :
- type « Écritures comptables », fichier « Délimité » ;
- les 9 champs dans l'ordre : Code journal, **Date de pièce** (format **`jjmmaaaa`**, pas `jjmmaa`), **N° pièce**, N° compte général, N° compte tiers, Libellé écriture, **Montant débit**, **Montant crédit**, N° section 1 ;
- origine Windows, enregistrement Retour-chariot, séparateur Point-virgule, identifiant de texte aucun, 2 décimales, séparateur décimal virgule, pas de séparateur de milliers, pas d'en-tête ;
- **« Interpréter les séparateurs identiques comme unique » : DÉCOCHÉ.** Cochée par défaut, elle fusionne les `;;` et décale toute la ligne.

Gardez une copie du fichier de format hors du dossier d'installation de Sage.

## 10.3 Les erreurs déjà rencontrées

| Message Sage | Cause | Correction |
|---|---|---|
| Rien, aucune écriture | fichier en fins de ligne LF | export en CRLF (fait) |
| Lignes décalées d'une colonne | « séparateurs identiques comme unique » cochée | décocher |
| « L'écriture n'appartient pas à un exercice ! » | format de date `jjmmaa` | `jjmmaaaa` |
| « La longueur du compte est incorrecte ! » | longueur des comptes tiers du dossier < 17 | recréer le dossier avec 17 |
| Section absente après import | l'export envoyait `Saaba` au lieu de `SAAB` | section analytique sur 4 caractères (fait) |
| Pièce refusée pour déséquilibre | ligne de caisse globale retirée | gardée (fait) |
| Ligne rejetée sur un tiers | tiers créé dans l'application, absent de Sage | créer le tiers dans Sage avant l'import |

Points encore ouverts : la longueur maximale réelle du **libellé** dans Sage i7 (35 caractères dans l'ancien modèle de données ; l'application envoie jusqu'à 60). À mesurer dans Sage (taper une longue phrase dans la colonne Libellé de la saisie), puis couper à l'export si besoin, en gardant le libellé complet dans l'application.

## 10.4 La boucle d'export

1. **Contrôles** : plus aucune pièce sur 471000, aucune anomalie bloquante.
2. **Tiers nouveaux** : vérifier que les tiers créés par les caissières depuis le dernier export existent dans Sage ; les créer sinon.
3. **Export Sage** : choisir la période et le journal, lire le bandeau (pièces, lignes, total au débit) et **noter les trois chiffres**.
4. Laisser la case « Inclure les pièces déjà exportées » **décochée**. Si un bandeau orange signale des pièces déjà exportées dans la période, c'est normal : elles ne sont pas dans le fichier.
5. **Télécharger le fichier Sage (.txt)**. Ne l'ouvrez qu'au Bloc-notes, **jamais avec Excel** (Excel réécrit dates et nombres). « Télécharger en Excel » sert à relire, jamais à importer.
6. **Sauvegarder le dossier Sage** (Fichier > Sauvegarde ou copie du `.mae`).
7. Sage : Fichier > Importer > Format paramétrable > `HAKILI_ECRITURES` > le fichier. Lire le compte rendu jusqu'au bout.
8. Contrôler : nombre de lignes intégrées, total débit de la balance sur la période, équilibre, numéros de pièces, soldes des tiers, sections.
9. Archiver le fichier et le compte rendu dans un dossier daté.
10. **Marquer comme exportées**, avec les mêmes filtres, tout de suite après l'import, en demandant aux validateurs de ne rien valider entre le téléchargement et le marquage (une pièce validée entre-temps serait marquée sans être dans le fichier). Le marquage ne touche que les pièces encore « validées ».
11. Quand le mois est entièrement dans Sage, le **clôturer** dans l'application (Référentiel > Paramètres > Clôture des mois).

**Ne jamais réimporter le même fichier** : Sage ne détecte pas les doublons. Si le dossier Sage a été recréé ou restauré et qu'il faut renvoyer des pièces déjà exportées : cocher « Inclure les pièces déjà exportées » puis « Je confirme vouloir les renvoyer à Sage ». Le fichier s'appelle alors `sage_AAAAMMJJ_AVEC_DEJA_EXPORTEES.txt` et l'application en garde une trace dans son journal.

**Ne pas lancer « Traitement > Validation des écritures » dans Sage** tant que les contrôles ne sont pas faits : avant validation, tout se corrige et se supprime dans Sage.

## 10.5 Pourquoi pas de « lots d'export »

Une version par lots (pièces, fichier et statut figés ensemble) a été écrite le 08/10/2026, puis retirée le même jour à la demande d'Afiya : le comptable garde l'écran qu'il connaît. Le risque qui reste est celui décrit au point 10 de la boucle (pièce validée entre le téléchargement et le marquage). Si cela arrive, la pièce est « exportée » dans l'application mais absente de Sage : la retrouver en comparant la balance, et la renvoyer avec les deux cases.

## 10.6 Après l'export : corriger une erreur

Une pièce exportée ne se modifie plus, ni dans l'application, ni en base. On passe une **écriture d'extourne** (l'écriture inverse) puis la bonne écriture, dans l'application (qui les exportera) et donc dans Sage. Si une erreur est trouvée dans Sage avant sa validation, on peut supprimer les écritures importées dans Sage, corriger la cause, et réimporter le **même fichier** (gardé dans le dossier d'archives daté du point 9).

## 10.7 Comptes et tiers : garder l'application et Sage alignés

- Le plan comptable et le plan tiers de l'application ont été chargés depuis Sage le 18/09/2026 (1 040 comptes, 1 454 tiers). 33 tiers douteux ont été volontairement écartés (intitulés tronqués par l'export Sage, collectifs 409100/419100 absents du plan, codes de brouillard absents de Sage) : à trancher avec le comptable.
- Un compte ou un tiers créé dans l'application doit être créé aussi dans Sage, avec le même code.
- Les comptes collectifs 409100 (avances fournisseurs) et 419100 (avances clients) n'existent pas dans le plan de l'application.
