# 6. La base de données PostgreSQL

Base de production : **`Hakili_compta`**, utilisateur **`hakili_admin`**, dans le conteneur `db` (PostgreSQL 16). Les données vivent dans le volume Docker externe **`hakili_gestion_caisse_pgdata`**.

Le principe de conception : tout ce que la base peut garantir, elle le garantit elle-même (clés, contraintes, triggers), pour qu'un script ou une erreur de code ne puisse pas casser la comptabilité. Les contrôles Python ne servent qu'à donner un message lisible avant.

## 6.1 Les tables métier

### `comptes` — plan comptable
`compte` (clé, 6 chiffres), `intitule`, `nature` (`charge`, `produit`, `tresorerie`, `bilan`, `tiers`), `tiers_obligatoire` (`oui`/`non`), `depense_courante` (`oui`/`non` : proposé dans « Dépense courante »), `nb_2024_2025` (fréquence historique, informative).

### `tiers` — plan tiers
`code_tiers` (clé, 17 caractères au plus), `intitule`, `compte_collectif` (→ `comptes`), `type` (`client`, `fournisseur`, `personnel`), `actif`, `actif_annee` (présent dans les listes de l'année en cours).

### `journaux`
`journal` (clé : `CP`, `CMD`, `Banque`, `BDU-BF`, `VTE`, `ACH`), `intitule`, `compte_contrepartie` (compte de caisse ou de banque, vide pour VTE/ACH), `type` (`tresorerie` ou `operations`), `prefixe_piece` (début des numéros définitifs : `CP`, `CMD`, `CBI`…), `solde_ouverture` (banque seulement), `caisse_physique` (`oui` pour CP et CMD), `actif`.

### `centres`
`code_centre` (clé : `SIA`, `TAM`, `SAA`, `PIS`, `NAG`, `SIE`), `intitule`, `section_analytique` (code Sage sur 4 caractères), `ordre` (ordre de numérotation), `actif`.

### `soldes_ouverture_centre`
Un solde d'ouverture par couple (centre, journal) pour CP et CMD. Saisi depuis Référentiel > Paramètres.

### `utilisateurs`
`identifiant` (clé), `nom`, `role` (`saisie` ou `validation`), `centre`, `code_acces` (hash bcrypt), `tentatives_echouees`, `verrouille_jusqu_a`, `doit_changer_code`, `actif`. Le comptable = rôle `validation` sur le centre `SIE`.

### `ecritures` — la table centrale
Une ligne d'écriture par enregistrement.

| Colonne | Rôle |
|---|---|
| `id_ligne` | clé, `{id_piece}-{n}` |
| `id_piece` | identifiant de la pièce : `{centre}-{horodatage}-{AAMM}{nnn}` |
| `id_lien` | pièces solidaires (approvisionnement, versement) : `L{horodatage}-{8 car. aléatoires}` |
| `num_provisoire` | `{centre}-{AAMM}-{nnn}` |
| `num_definitif` | `{préfixe}{AAMM}{nnn}`, donné à la validation |
| `num_reserve` | numéro gardé par une pièce renvoyée, rendu à la revalidation |
| `journal`, `centre`, `date_piece`, `compte`, `code_tiers`, `libelle` | |
| `debit`, `credit` | `numeric(14,2)`, positifs, jamais les deux sur une ligne |
| `modele` | id du modèle de saisie |
| `saisi_par`, `saisi_le`, `valide_par`, `valide_le`, `exporte_le` | traçabilité |
| `statut` | `saisie`, `a_corriger`, `validee`, `exportee` |
| `observation` | note libre ou motif de renvoi |
| `valeurs_json` | valeurs du formulaire (pour corriger la pièce, lire le motif d'un transfert) |
| `reference_transfert`, `centre_contrepartie` | transferts entre centres |

### Tables de service

| Table | Rôle |
|---|---|
| `compteurs` | numérotation atomique : clés `prov:{centre}:{AAAAMM}`, `def:{journal}:{AAAAMM}`, `trf:{AAAAMM}` |
| `suppressions_ecritures` | contenu complet (JSON) de toute pièce supprimée ou remplacée, avec qui et quand |
| `revision` | une ligne, deux compteurs (`valeur`, `referentiel`) sondés toutes les 2 s |
| `libelles_types` | libellés suggérés par compte |
| `periodes_cloturees` | mois clôturés (`AAAA-MM`) |
| `schema_migrations` | migrations déjà jouées |

### Tables du tableau de bord

| Table | Rôle |
|---|---|
| `rubriques_tableau` | les lignes du compte de résultat et leur bloc (`encaissement`, `charge`, `hors_exploitation`, `exclu`) |
| `classement_comptes` | règles qui rattachent un compte (par préfixe), éventuellement un mot du libellé ou un modèle, à une rubrique |
| `parametres_centre` | cible de marge (15 % par défaut) et de trésorerie (2 mois de charges) par centre |

### Tables de l'assistant IA

| Table | Rôle |
|---|---|
| `centres_alias` | façons d'écrire un centre (« saab », « tampuy ») |
| `categories_charge` | catégories de dépense, comptes et mots-clés associés |
| `journal_assistant` | chaque question : utilisateur, outils appelés, réponse, durée, jetons |

## 6.2 Les garde-fous en base

| Objet | Ce qu'il garantit |
|---|---|
| Clés étrangères | pas de compte, journal, centre ou collectif inconnu |
| `ck_montants_positifs` | débit et crédit ≥ 0, jamais les deux sur une ligne |
| `trg_equilibre_piece` (trigger différé) | chaque pièce est équilibrée au moment du commit |
| `trg_numero_unique` (trigger différé) | deux pièces d'un journal n'ont jamais le même numéro définitif |
| `uq_transfert_entree` (index unique partiel) | une sortie de transfert n'est rapprochée que d'une seule entrée |
| `trg_proteger_ecritures` | une ligne `exportee` ne se modifie ni ne se supprime ; un mois clôturé ne reçoit rien et ne change plus |
| `ck_tiers_longueur_sage` | code tiers ≤ 17 caractères (posée seulement si aucun code existant ne dépasse) |
| Rôle `hakili_lecture` | rôle sans connexion, qui ne lit que quelques tables ; la requête libre de l'assistant s'exécute sous ce rôle |

Les triggers d'équilibre et de numéro sont **différés** (`DEFERRABLE INITIALLY DEFERRED`) : une pièce n'est équilibrée qu'après l'insertion de toutes ses lignes.

Échappatoire volontaire pour un script de reprise exceptionnel, jamais utilisée par l'application :

```sql
BEGIN;
SET LOCAL hakili.autoriser_modif_protegee = 'oui';
-- modification exceptionnelle, réfléchie, sauvegardée avant
COMMIT;
```

## 6.3 Les fonctions SQL

| Fonction | Utilisée par | Rôle |
|---|---|---|
| `verifier_equilibre_piece()`, `verifier_numero_unique()`, `proteger_ecritures()` | triggers | voir ci-dessus |
| `bump_revision()`, `bump_revision_referentiel()`, `bump_revision_utilisateurs()` | triggers | incrémenter `revision` |
| `tb_normaliser(text)` | tableau de bord | majuscules sans accents |
| `flux_tableau_bord(debut, fin, centres[])` | tableau de bord, assistant | chaque ligne qui fait face à un mouvement de caisse ou de banque, avec sa rubrique, son sens et son montant (positif = argent entré) |
| `tb_rubrique_motif_transfert(motif)` | `flux_tableau_bord` | rubrique d'un transfert selon son motif |
| `soldes_tableau_bord(fin, centres[])` | tableau de bord | solde des caisses par centre et de la banque à une date |
| `soldes_fin_mois(debut, fin, centres[])` | tableau de bord | solde des caisses en fin de chaque mois |
| Vue `v_lignes` | assistant | écritures enrichies (noms, nature du compte, année scolaire, est_transfert) |

## 6.4 Les migrations

`sql/schema.sql` + `sql/seed.sql` créent une base **neuve** (ils sont joués automatiquement par l'image PostgreSQL uniquement quand le volume est vide). Toute évolution d'une base existante passe par un fichier dans **`sql/migrations/`**, nommé `AAAA-MM-JJ_sujet.sql` et joué dans l'ordre alphabétique.

`logic/migrations.py` les joue **au démarrage de l'application**, chacune dans sa transaction, et inscrit son nom dans `schema_migrations`. Une migration qui échoue empêche le démarrage.

Règles :

1. **Une migration déjà jouée ne se modifie jamais.** Pour corriger, on écrit une nouvelle migration (exemple : `2026-10-07b_motif_transfert.sql` à côté de `2026-10-07_camp_de_vacances.sql`).
2. Toute migration est **idempotente** : `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, `CREATE OR REPLACE`, contraintes testées dans `pg_constraint`.
3. Une migration ne supprime ni ne modifie d'écritures comptables.
4. Mettez aussi à jour `schema.sql` / `seed.sql` si une base neuve doit naître avec l'objet, et vérifiez que les deux chemins (base neuve, base migrée) donnent le même résultat.
5. Avant de déployer une migration qui pose une contrainte, vérifiez que les données de production la respectent (requête de contrôle en tête de fichier).

| Fichier | Contenu |
|---|---|
| `2026-09-05_durcissement_auth.sql` | verrouillage après échecs, table des suppressions |
| `2026-09-10_suppression_code_acces_centres.sql` | retrait d'un ancien code de centre en clair |
| `2026-09-11_soldes_par_centre_et_banque_cbi.sql` | soldes d'ouverture par centre, journal `Banque` (CBI, 521200), BDU-BF inactif |
| `2026-09-12_transferts_internes.sql` | colonnes de transfert entre centres |
| `2026-09-15_rattrapage_production.sql` | rattrapage des quatre migrations oubliées en production |
| `2026-09-22_correctifs_audit.sql` | contrainte de montants, trigger d'équilibre, index des transferts |
| `2026-09-23_sections_sage.sql` | sections analytiques sur 4 caractères |
| `2026-09-24_assistant_ia.sql` | alias de centres, catégories, journal de l'assistant, vue `v_lignes` |
| `2026-09-25_assistant_libelles.sql` | libellés des catégories dans les mots du directeur |
| `2026-09-25_numerotation_date_centre.sql` | ordre des centres, numéro réservé, unicité des numéros |
| `2026-10-02_tableau_bord.sql` | rubriques, classement, `flux_tableau_bord`, `soldes_tableau_bord` |
| `2026-10-03_tableau_bord_direction.sql` | cibles par centre, flux enrichi, `soldes_fin_mois` |
| `2026-10-03b_tableau_bord_equipement_camp.sql` | règles équipement et camp |
| `2026-10-07_camp_de_vacances.sql` | règle « CAMP » en mot entier |
| `2026-10-07b_motif_transfert.sql` | motif des transferts lu avant le libellé |
| `2026-10-08_correctifs_audit.sql` | clôtures, protection des pièces exportées, révisions séparées, 17 caractères, rôle de lecture, code à changer |

Les deux dernières **ne sont pas encore jouées en production** au 08/10/2026 (code non déployé).

## 6.5 Les scripts SQL hors migrations

| Fichier | Usage | Danger |
|---|---|---|
| `sql/schema.sql`, `sql/seed.sql` | base neuve | ne jamais rejouer en production |
| `sql/charger_plan_comptable.sql`, `sql/charger_plan_tiers.sql` | chargement des plans Sage (fait le 18/09/2026) | contiennent des noms réels, **hors Git**, copiés par `scp` puis effacés du serveur |
| `sql/seed_tiers.sql` | ancien jeu de tiers | hors Git |
| `sql/diagnostic_production.sql` | lecture seule : objets manquants | sans danger |
| `sql/production_reset.sql`, `sql/purge_avant_mise_en_service.sql` | vident les écritures (utilisés une fois avant la mise en service) | **détruisent la comptabilité réelle**, ne jamais lancer |

## 6.6 Se connecter à la base

En production (depuis le dossier `~/hakili_gestion_caisse`, `psql` n'est pas installé sur l'hôte) :

```bash
docker compose exec db psql -U hakili_admin -d Hakili_compta
```

Requêtes utiles :

```sql
-- état général
SELECT statut, count(DISTINCT id_piece) FROM ecritures GROUP BY statut;
-- pièces déséquilibrées (doit être vide)
SELECT id_piece FROM ecritures GROUP BY id_piece HAVING round(sum(debit),2) <> round(sum(credit),2);
-- migrations jouées
SELECT * FROM schema_migrations ORDER BY version;
-- codes tiers trop longs
SELECT code_tiers FROM tiers WHERE length(code_tiers) > 17;
-- pièces encore rattachées au Siège
SELECT DISTINCT id_piece, date_piece FROM ecritures WHERE centre = 'SIE';
```

En local, utilisez pgAdmin ou `psql` avec le `DATABASE_URL` de votre `.env`.
