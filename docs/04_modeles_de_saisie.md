# 4. Les modèles de saisie et les écritures qu'ils produisent

Tout est dans `logic/modeles.py`, dans la liste `MODELES`. Un modèle décrit une opération **telle que la caisse la vit** (« un élève paie ses frais »), et sa fonction `lignes` la traduit en écriture comptable. C'est le cœur métier de l'application : lisez ce fichier en entier, il est très commenté.

## 4.1 Comment un modèle est construit

```python
{
    "id": "depense",                     # identifiant stable, enregistré dans ecritures.modele
    "titre": "Depense courante",         # texte du menu
    "aide": "Carburant, impression...",  # sous-titre
    "journal": "CMD",                    # journal imposé (None = au choix)
    "champs": [ {...}, {...} ],          # les questions posées
    "libelle": lambda v: ...,            # le libellé de la pièce
    "lignes": lambda v, cc: _df(...),    # les lignes d'écriture ; cc = compte de caisse du journal
}
```

Types de champ (`"t"`) : `tiers`, `compte`, `libelle`, `texte`, `montant`, `mois`, `choix`, `centre`, `repartition`. Options utiles :

- `"pref"` et `"collectif"` sur un champ tiers (`"411"`, `"411000"`) ;
- `"filtre": "depense_courante"` ou `"choix": [...]` sur un champ compte, pour limiter la liste ;
- `"defaut"` sur un montant (timbre à 50 F) ;
- `"garde": True` pour garder le choix d'une pièce à l'autre ;
- `"lie": "CMD"` : l'opération produit une seconde pièce dans ce journal, liée à la première ;
- `"retire": True` : le modèle disparaît du menu mais reste connu pour relire et corriger les anciennes pièces.

**Ajouter un modèle** : copier un bloc existant, changer l'id, les champs et la fonction `lignes`. L'interface (`app.py`, sorties `m_champs`, `m_apercu`) se construit toute seule à partir de cette description. Ajoutez un test dans `tests/`.

Tous les libellés sont mis en majuscules et coupés à **60 caractères** (`LIBELLE_MAX`). Quand il faut couper, l'application coupe toujours le **nom** en premier, jamais la nature ni les mois : le code tiers de la ligne identifie déjà la personne.

## 4.2 Les modèles, un par un

Dans les tableaux, `caisse` désigne le compte de trésorerie du journal (571100 en CP, 571200 en CMD, 521200 en banque).

### Encaissement de frais de scolarité (`encaissement`, journal CP)

Le formulaire le plus utilisé. Champs : élève (411), activité (Cours d'appui / Camp de vacances), montant total reçu, tableau de répartition (nature Frais / Avance / Solde, un ou plusieurs mois, montant ; 6 lignes au plus).

| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| caisse | `FRAIS CA - NOM` | total | |
| 411000 + tiers | `FRAIS CA OCT - NOM` | | ligne 1 |
| 411000 + tiers | `AVANCE CA NOV-DEC - NOM` | | ligne 2 |

Pour le camp : `FRAIS CV`, `AVANCE CV`, `SOLDE CV`. C'est ce libellé qui permet au tableau de bord de séparer le camp des cours. Les mois sont toujours écrits dans l'ordre de l'année scolaire (septembre → août), abrégés et tous cités (`OCT-NOV-DEC`). Si la somme des lignes ne fait pas le total, la pièce est déséquilibrée et ne s'enregistre pas.

Pourquoi « SOLDE » et pas « RATTRAPAGE » : c'est le mot du comptable quand un mois partiellement payé est enfin réglé.

### Frais de document (`document`, CP)

Champs : nom de l'élève (texte libre), montant.

| Compte | Débit | Crédit |
|---|---|---|
| caisse | montant | |
| 707810 Frais de dossier et de documents | | montant |

### Approvisionnement de la CMD (`approvisionnement`, CP, lié à CMD)

Champ : montant. Une saisie, deux pièces liées. Libellé `APPROV CMD`.

| Pièce | Compte | Débit | Crédit |
|---|---|---|---|
| CP | 585000 | montant | |
| CP | 571100 | | montant |
| CMD | 571200 | montant | |
| CMD | 585000 | | montant |

Le sens est toujours CP → CMD (596 pièces dans l'historique, jamais l'inverse).

### Versement d'espèces en banque (`versement_banque`, CP, lié à Banque)

Champs : montant versé, timbre (50 F par défaut, compte 646200).

| Pièce | Compte | Débit | Crédit |
|---|---|---|---|
| CP | 585000 | montant | |
| CP | 646200 (`TIMBR/…`) | timbre | |
| CP | 571100 | | montant + timbre |
| Banque | 521200 | montant | |
| Banque | 585000 | | montant |

### Transfert entre centres (`transfert_interne`, journal au choix : CP, CMD ou banque)

Champs : centre qui remet, centre qui reçoit (le SIAO par défaut), **motif obligatoire sans valeur par défaut**, montant, libellé facultatif.

Motifs (`MOTIFS_TRANSFERT`) :

| Clé | Texte | Rubrique au tableau de bord |
|---|---|---|
| `contribution` | Contribution au fonctionnement du siège | charge d'exploitation du donateur, encaissement du SIAO |
| `pret` | Prêt (à rembourser) | hors exploitation |
| `remboursement` | Remboursement d'un prêt | hors exploitation |
| `impot` | Impôts payés par le siège pour le centre | impôts |

Il n'y a pas de champ « sens » : le sens se déduit du centre de la personne connectée. Si elle est le donateur, elle enregistre une **sortie** (585000 au débit, caisse au crédit) et reçoit une nouvelle référence `TRF-AAAAMM-nnnn`. Si elle est le destinataire, elle enregistre une **entrée** (caisse au débit, 585000 au crédit), rattachée à la plus ancienne sortie qui l'attend (premier entré, premier sorti, sans regarder le montant, pour qu'un écart reste visible). Le destinataire doit choisir **le même motif** que le donateur, sinon l'enregistrement est refusé. Un centre ne peut pas saisir un transfert entre deux autres centres.

Le libellé commence par le mot du motif (`CONTRIBUTION TAM>SIA`, `PRET APPROV SIAO`) ; la caissière peut garder son propre vocabulaire derrière, le rapprochement ne lit jamais le libellé.

### Dépense courante (`depense`, CMD)

Champs : nature (seuls les comptes marqués `depense_courante = 'oui'` : eau minérale, électricité, carburant, fournitures, petits équipements, maintenance, entretien, téléphone, internet, frais mobile money, impressions, réception…), libellé, montant.

| Compte | Débit | Crédit |
|---|---|---|
| compte de charge choisi | montant | |
| caisse | | montant |

### Règlement d'un fournisseur (`fournisseur`, CMD) et par banque (`fournisseur_banque`, Banque)

Champs : fournisseur (401), libellé, activité, montant payé, répartition (Paiement / Avance / Solde, mois, montant), timbre (en caisse seulement).

| Compte | Libellé | Débit | Crédit |
|---|---|---|---|
| 401000 + tiers | `PAIEMENT ETAT VACATION OCT - NOM` | ligne 1 | |
| 401000 + tiers | `AVANCE LOYER NOV-DEC - NOM` | ligne 2 | |
| 646200 | `TIMBR/…` | timbre | |
| caisse ou banque | | | total + timbre |

Pour le camp, le mot `CAMP` est ajouté en tête du libellé tapé. Une faiblesse connue : la nature de la charge n'est que dans le libellé libre, le tableau de bord la devine par mots-clés (voir chapitre 8 et chantiers).

### Salaire ou vacation (`remuneration`, CMD)

Champs : bénéficiaire (422), activité, mois, montant. Libellé `REMUNERATION OCTOBRE/NOM` (ou `REMUNERATION CAMP …`).

| Compte | Débit | Crédit |
|---|---|---|
| 422000 + tiers | montant | |
| caisse | | montant |

### Frais bancaires ou règlement d'impôt (`frais_bancaires`, Banque)

Champs : nature parmi 631800 (frais bancaires), 447100, 447200, 447800, 447810 (impôts et retenues), libellé, montant. Écriture : compte choisi au débit, banque au crédit.

### Facture de cours d'appui (`facture`, VTE)

Champs : élève, prestation (706110, 706120 ou 706130), numéro de facture, montant. Libellé repris de la forme utilisée depuis 2020 : `FACT N*057/NOV/26 NOM`.

| Compte | Débit | Crédit |
|---|---|---|
| 411000 + tiers | montant | |
| 706xxx | | montant |

La facture crée la créance ; l'encaissement la solde plus tard.

### État de vacation (`vacation`, ACH)

Champs : vacataire (401), mois, montant brut. Retenue de 2 % automatique.

| Compte | Débit | Crédit |
|---|---|---|
| 632710 Honoraires et vacations | brut | |
| 447810 (`RETENUE 2%/…`) | | 2 % |
| 401000 + tiers | | brut − 2 % |

### Facture fournisseur (`achat`, ACH)

Champs : fournisseur, nature de la charge (loyer, gardiennage, eau, électricité, entretien, internet, formation, t-shirts, petit matériel, carburant, fournitures), libellé, montant brut, retenue (montant, 0 par défaut). Le compte de retenue se déduit de la charge : loyer → 447800, gardiennage → 447820, vacations → 447810.

### Écriture libre (`libre`, journal au choix)

La soupape pour les cas qu'aucun modèle ne couvre. Les questions dépendent du type de journal :

- **journal de trésorerie** : sens (entrée ou sortie), autre compte (471000 si on ne sait pas), libellé, montant. La caisse est l'autre côté ;
- **journal d'opérations** (VTE, ACH) : sens, compte concerné, libellé, montant. **Le 471000 est toujours l'autre côté.** Ainsi toute écriture libre de ce type apparaît dans les Contrôles et ne peut pas inverser silencieusement le sens d'une opération.

Une note libre peut accompagner la pièce (`observation`).

Les comptes à tiers obligatoire sont exclus de l'écriture libre : elle n'a pas de champ tiers.

### Avance de paiement multi-mois (`avance_paiement_multimois`) — retiré

Remplacé par la répartition du modèle Encaissement. Gardé avec `"retire": True` pour relire et corriger les anciennes pièces.

## 4.3 Le chemin d'une saisie dans le code

1. `app.py::valeurs()` rassemble les valeurs des champs (`ch_*`, `m_rep_*`).
2. `app.py::operation()` appelle `md.construire_operation(id_modele, valeurs, journal, journaux)`, qui :
   - trouve le compte de caisse du journal (`compte_contrepartie`) ;
   - normalise les valeurs (montants en float, répartition en liste) ;
   - compose le libellé ;
   - appelle la fonction `lignes` et, si le modèle a un `"lie"`, recommence pour le second journal.
3. `m_apercu()` et `m_ruban()` affichent le résultat ; `md.operation_equilibree()` et `md.comptes_annules()` disent s'il est enregistrable.
4. Au clic sur Enregistrer, `_enregistrer_piece()` :
   - vérifie le centre (comptable) ;
   - transforme chaque nom de tiers en code réel avec `dl.resoudre_tiers()` (création si nouveau) ;
   - reconstruit l'opération avec les codes définitifs ;
   - appelle `dl.enregistrer_operation()` (ou `dl.remplacer_piece()` pour une correction).
5. `logic/donnees.py` contrôle la date, numérote, insère les lignes dans une transaction ; la base vérifie l'équilibre au commit.

Les valeurs saisies sont gardées en JSON dans `ecritures.valeurs_json` : c'est ce qui permet de rouvrir une pièce dans le formulaire pour la corriger, et au tableau de bord de lire le motif d'un transfert.
