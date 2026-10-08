# 8. Le tableau de bord

Fichiers : `tableau_bord.py` (interface), `logic/tableau_bord.py` (calculs), `www/tableau_bord.css`, migrations `2026-10-02_tableau_bord.sql`, `2026-10-03_tableau_bord_direction.sql`, `2026-10-03b_…`, `2026-10-07_…`, `2026-10-07b_…`. Tests : `tests/test_tableau_bord.py`, `tests/test_camp_cibles_forces.py`.

**État** : sur la branche `tableau-bord-v2` (poussée sur GitHub), pas encore fusionnée dans `main` ni déployée au 08/10/2026.

## 8.1 À quoi il sert

Le directeur voulait, pour chaque centre, l'analyse de « santé financière » qu'on avait faite à la main sur le brouillard de Tampouy : combien le centre reçoit, combien il dépense, s'il gagne de l'argent, s'il paie trop de salaires, combien d'élèves paient, combien il reste en caisse, et si les chiffres sont fiables. Le tableau de bord refait ces calculs pour **tous les centres, avec les mêmes règles**, directement sur les écritures saisies.

Il est **réservé au comptable** pour l'instant (vérifié côté serveur par `req(autorise())`). Une version pour le directeur est prévue.

## 8.2 Ce qu'on voit

En haut, toujours visibles : la **période** (du… au…, par défaut du 1er janvier à la fin du dernier mois avec des opérations) et les **centres** (un ou plusieurs ; le Siège n'en fait jamais partie).

**Vue d'ensemble**
- un bandeau par centre avec **trois chiffres** : Résultat, Sorties hors exploitation, Argent disponible (caisses ; la banque est affichée à part, elle est commune) ;
- les **points à regarder** : alertes automatiques classées par gravité ;
- un **comparatif des centres** avec des pastilles (Correct, À surveiller, Attention, Repère — toujours un mot, jamais la couleur seule) ;
- le **compte de résultat mensuel en encaissements** (replié), avec le détail par rubrique.

**Fiche centre**, quatre onglets :
- **Résultat** : compte de résultat mois par mois, salaires comparés au plafond salarial ;
- **Élèves** : élèves payants par mois, frais moyen, seuil de rentabilité en élèves, retards de paiement ;
- **Caisse** : solde fin de mois, mois de charges couverts, capital de base, écart entre caisse attendue et caisse constatée ;
- **Fiabilité** : pièces validées, semaines sans écriture, encaissements sans élève, dates impossibles, compte d'attente, comptes non classés, pièces non validées — avec la liste des opérations concernées.

Les **cibles** de chaque centre (marge visée, capital de base en mois de charges) se règlent depuis l'écran et sont gardées dans `parametres_centre`. Bornes : 0 à 50 % de marge, 0 à 12 mois.

## 8.3 Les règles de calcul

**Base caisse** : on compte l'argent à la date où il entre ou sort d'une caisse ou de la banque. Une seule source : la fonction SQL `flux_tableau_bord(début, fin, centres)`.

Pour chaque pièce qui touche une caisse ou la banque, la fonction renvoie chaque ligne **en face** de la trésorerie (le compte de contrepartie), avec :
- son montant signé (positif = argent entré) ;
- sa **rubrique**, trouvée dans `classement_comptes`.

**Le classement** (`classement_comptes`) rattache un compte à une rubrique par **préfixe** (`6`, `62`, `622200`…), éventuellement conditionné par un **mot du libellé** (`motifs`) ou un **modèle de saisie**. Ordre de priorité quand plusieurs règles correspondent :
1. une règle avec motif passe avant une règle sans motif ;
2. une règle liée à un modèle passe avant une règle générale ;
3. le préfixe le plus long gagne ;
4. puis le champ `ordre`.

Exceptions :
- un **transfert entre centres** saisi depuis le 07/10/2026 est classé par son **motif** (`valeurs_json->>'motif'`), avant toute règle de libellé ;
- le **camp de vacances** est reconnu **uniquement au libellé** (`CAMP ` suivi d'un espace, `FRAIS CV`, `AVANCE CV`, `SOLDE CV`), jamais au mois : un cours donné en juillet reste un cours ;
- les virements CP → CMD et caisse → banque sont exclus (rubrique `transfert`).

**Les rubriques** (`rubriques_tableau`) et leur bloc :

| Bloc | Rubriques |
|---|---|
| Encaissements d'exploitation | Cours d'appui, Camp de vacances, Frais de document, Contributions reçues des centres (SIAO) |
| Charges d'exploitation | Vacations et salaires, Contribution au SIAO, Loyer, Produits d'entretien, Électricité et eau, Internet et communication, Fournitures et impressions, Autres charges courantes, Frais financiers |
| Hors exploitation | Impôts et taxes, Remboursements d'emprunts / Emprunts reçus, Prêts entre centres, Dossiers de conseil, Achats d'équipement, Avances au personnel |
| Contrôle | Sorties/encaissements en attente de classement (471), non classés |
| Exclu | Transferts entre caisses |

**Un centre est toujours vu seul** : sa contribution au SIAO est une charge, quels que soient les autres centres choisis. **L'ensemble**, lui, ne compte pas deux fois un flux entre deux centres sélectionnés (colonne `centre_contrepartie`).

**Les indicateurs**

| Indicateur | Formule |
|---|---|
| Résultat | encaissements d'exploitation − charges d'exploitation |
| Marge | résultat ÷ encaissements |
| Plafond salarial | encaissements − (charges − salaires) − marge cible × encaissements : ce qu'on peut payer en salaires en gardant la marge visée |
| Capital de base | cible en mois × charges d'exploitation moyennes par mois (2 mois par défaut) |
| Reste à constituer / disponible pour distribuer | écart entre l'argent en caisse et le capital de base |
| Élèves payants « typiques » | médiane des mois scolaires (hors mois où le camp fait plus de la moitié des recettes) |
| Seuil de rentabilité en élèves | charges moyennes mensuelles ÷ frais moyen par élève |
| Mois du cours | lu dans le libellé (`assistant.semantique.mois_du_libelle`), un paiement multi-mois réparti à parts égales |
| Caisse attendue | caisse de début + résultat − hors exploitation + transferts − versements en banque ; l'écart avec la caisse constatée révèle une pièce manquante |

Toutes les pièces comptent, y compris celles pas encore validées ; leur nombre est affiché dans Fiabilité.

## 8.4 Modifier le classement

Le classement est **dans la base**, pas dans le code : pour qu'un nouveau mot-clé ou un nouveau compte tombe dans la bonne rubrique, on ajoute une ligne à `classement_comptes` par une **nouvelle migration** (jamais à la main en production sans trace). Un éditeur dans l'interface a été écarté volontairement : trop facile de casser le classement par erreur.

Exemple :

```sql
INSERT INTO classement_comptes (prefixe, motifs, modele, rubrique, ordre)
VALUES ('401', '{GARDIENNAGE}', '', 'vacations', 15)
ON CONFLICT (prefixe, motifs, modele) DO NOTHING;
```

## 8.5 Les limites connues

- **Mots-clés en sous-chaîne** : `CANAL` reconnaît « CANALISATION », `MEGA` « OMEGA », `PRET` « INTERPRETE ». Seul `CAMP` est traité en mot entier. La solution générale est une recherche par mot entier (`~ '\m…\M'`) dans `flux_tableau_bord`.
- **Règle à motif sur préfixe court** : `6` + `CONSEIL` passe avant `632710` vacations. Une vacation libellée « CONSEIL DE CLASSE » part en dossiers de conseil.
- **Règlement fournisseur** : la nature de la charge n'existe que dans le libellé libre ; le classement la devine. Un champ « Nature » dans le formulaire réglerait le problème à la source.
- **Impôts et taxes** en hors exploitation, alors qu'en SYSCOHADA ce sont des charges d'exploitation : décision reportée, une ligne SQL à jouer quand la direction aura tranché.
- La description du contrôle « Dates aberrantes » à l'écran (`tableau_bord.py`, liste `CONTROLES`) parle encore de « plus d'un an avant la période » alors que la règle est maintenant fixe (avant le 01/01/2025 ou dans le futur). Texte à corriger.
- Un calcul prend environ 5 secondes sur deux ans de données, pendant lesquelles le processus unique est occupé.
- À venir (demandé) : version directeur, prévision de trésorerie sur 3 mois.

## 8.6 Chiffres de référence (base de démonstration)

Sur la base locale construite à partir des brouillards 2026, janvier à août 2026 : Tampouy reçoit 6 509 450 F, résultat 714 567 F (11,0 %), qui passe à 839 567 F (12,9 %) une fois le prêt de juin au SIAO corrigé en prêt ; Saaba reçoit 4 613 590 F, résultat 191 605 F (4,2 %). Utile pour vérifier qu'une modification ne change pas les chiffres sans raison.
