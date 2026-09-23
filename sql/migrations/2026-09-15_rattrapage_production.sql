-- ---------------------------------------------------------------------------
-- RATTRAPAGE DE PRODUCTION - 15/09/2026
--
-- Motif : le code des 5, 10, 11 et 12 septembre a ete deploye sur le serveur
-- sans qu'aucune des quatre migrations correspondantes n'ait ete jouee sur la
-- base. L'application demarre, puis echoue des la lecture du referentiel :
--     Error: relation "soldes_ouverture_centre" does not exist
--
-- Ce fichier rejoue les QUATRE migrations en attente, dans l'ordre, dans une
-- seule transaction. Il est integralement idempotent (IF NOT EXISTS /
-- ON CONFLICT DO NOTHING) : le relancer une seconde fois ne fait rien et
-- n'ecrase aucune donnee deja saisie.
--
-- AVANT DE LANCER :
--   1. pg_dump "$DATABASE_URL" > sauvegarde_avant_rattrapage.sql
--   2. psql "$DATABASE_URL" -f sql/diagnostic_production.sql   (pour voir l'etat)
--
-- LANCER :
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f sql/migrations/2026-09-15_rattrapage_production.sql
--
-- APRES :
--   redemarrer l'application, puis Referentiel > Soldes d'ouverture pour
--   renseigner l'encaisse reelle de chaque centre (CP et CMD demarrent a 0).
-- ---------------------------------------------------------------------------


-- --- 0. prerequis : watermark de synchronisation ----------------------------
-- Recree seulement s'il manque. La fonction est indispensable aux triggers
-- poses plus bas ; sur une base issue de sql/schema.sql elle existe deja et
-- CREATE OR REPLACE la laisse identique.

CREATE TABLE IF NOT EXISTS revision (
    id       boolean PRIMARY KEY DEFAULT true CHECK (id),
    valeur   bigint NOT NULL DEFAULT 0
);
INSERT INTO revision (id, valeur) VALUES (true, 0) ON CONFLICT (id) DO NOTHING;

CREATE OR REPLACE FUNCTION bump_revision() RETURNS trigger AS $$
BEGIN
    UPDATE revision SET valeur = valeur + 1;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS compteurs (
    cle      text PRIMARY KEY,
    valeur   integer NOT NULL DEFAULT 0
);


-- --- 1. migration 2026-09-05 : durcissement de l'authentification -----------

ALTER TABLE utilisateurs
    ADD COLUMN IF NOT EXISTS tentatives_echouees integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verrouille_jusqu_a timestamptz;

CREATE TABLE IF NOT EXISTS suppressions_ecritures (
    id             serial PRIMARY KEY,
    id_piece       text NOT NULL,
    contenu        jsonb NOT NULL,
    supprime_par   text NOT NULL,
    supprime_le    timestamptz NOT NULL DEFAULT now()
);


-- --- 2. migration 2026-09-10 : suppression de centres.code_acces ------------

ALTER TABLE centres DROP COLUMN IF EXISTS code_acces;


-- --- 3. migration 2026-09-11 : soldes par centre + banque CBI ---------------

ALTER TABLE journaux
    ADD COLUMN IF NOT EXISTS caisse_physique text NOT NULL DEFAULT 'non'
        CHECK (caisse_physique IN ('oui', 'non')),
    ADD COLUMN IF NOT EXISTS actif text NOT NULL DEFAULT 'oui'
        CHECK (actif IN ('oui', 'non'));

UPDATE journaux SET caisse_physique = 'oui' WHERE journal IN ('CP', 'CMD');

CREATE TABLE IF NOT EXISTS soldes_ouverture_centre (
    centre           text NOT NULL REFERENCES centres(code_centre),
    journal          text NOT NULL REFERENCES journaux(journal),
    solde_ouverture  numeric(14, 2) NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (centre, journal)
);

INSERT INTO soldes_ouverture_centre (centre, journal, solde_ouverture)
SELECT c.code_centre, j.journal, 0.0
FROM centres c
CROSS JOIN (SELECT journal FROM journaux WHERE journal IN ('CP', 'CMD')) j
ON CONFLICT (centre, journal) DO NOTHING;

DROP TRIGGER IF EXISTS trg_rev_soldes_ouverture_centre ON soldes_ouverture_centre;
CREATE TRIGGER trg_rev_soldes_ouverture_centre AFTER INSERT OR UPDATE OR DELETE
    ON soldes_ouverture_centre FOR EACH STATEMENT EXECUTE FUNCTION bump_revision();

INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, depense_courante)
VALUES ('521200', 'Banques (CBI)', 'tresorerie', 'non', 'non')
ON CONFLICT (compte) DO NOTHING;

INSERT INTO journaux (journal, intitule, compte_contrepartie, type, prefixe_piece,
                       solde_ouverture, caisse_physique, actif)
VALUES ('Banque', 'CBI', '521200', 'tresorerie', 'CBI', 0.0, 'non', 'oui')
ON CONFLICT (journal) DO NOTHING;

UPDATE journaux SET actif = 'non' WHERE journal = 'BDU-BF';


-- --- 4. migration 2026-09-12 : transferts internes entre centres ------------

ALTER TABLE ecritures
    ADD COLUMN IF NOT EXISTS reference_transfert text NOT NULL DEFAULT '';
ALTER TABLE ecritures
    ADD COLUMN IF NOT EXISTS centre_contrepartie text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_ecritures_transfert
    ON ecritures(reference_transfert) WHERE reference_transfert <> '';

INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, nb_2024_2025, depense_courante)
VALUES ('585000', 'Virements de fonds (caisse / banque)', 'tresorerie', 'non', 0, 'non')
ON CONFLICT (compte) DO NOTHING;

INSERT INTO libelles_types (compte, libelle, frequence)
SELECT '585000', v.lib, 0
FROM (VALUES ('TRANSFERT INTERNE'), ('CONTRIBUTION SIAO'), ('APPROV SIAO'),
              ('DEPOT SIAO')) AS v(lib)
WHERE NOT EXISTS (SELECT 1 FROM libelles_types l
                   WHERE l.compte = '585000' AND l.libelle = v.lib);


-- --- 5. index et triggers du schema de base, s'ils manquent -----------------

CREATE INDEX IF NOT EXISTS idx_ecritures_piece  ON ecritures(id_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_lien   ON ecritures(id_lien) WHERE id_lien <> '';
CREATE INDEX IF NOT EXISTS idx_ecritures_centre ON ecritures(centre, date_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_statut ON ecritures(statut);
CREATE INDEX IF NOT EXISTS idx_ecritures_num_def ON ecritures(journal, num_definitif);

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['comptes', 'tiers', 'journaux', 'centres', 'utilisateurs',
                              'ecritures', 'soldes_ouverture_centre']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_rev_%1$s ON %1$s;
             CREATE TRIGGER trg_rev_%1$s AFTER INSERT OR UPDATE OR DELETE ON %1$s
             FOR EACH STATEMENT EXECUTE FUNCTION bump_revision();', t);
    END LOOP;
END $$;


-- --- 6. journal des migrations : pour que ce probleme ne se reproduise pas --
--
-- La cause premiere de cette panne n'est pas une migration oubliee, c'est
-- qu'aucune trace n'existait de ce qui avait ete applique ou non. Cette table
-- enregistre desormais chaque migration jouee, avec sa date.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version      text PRIMARY KEY,
    applique_le  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version) VALUES
    ('2026-09-05_durcissement_auth'),
    ('2026-09-10_suppression_code_acces_centres'),
    ('2026-09-11_soldes_par_centre_et_banque_cbi'),
    ('2026-09-12_transferts_internes'),
    ('2026-09-15_rattrapage_production')
ON CONFLICT (version) DO NOTHING;



-- --- verification finale ----------------------------------------------------
-- (23/09/2026) Les commandes psql (set ON_ERROR_STOP, echo) et la requete de
-- verification finale ont ete retirees : ce fichier est desormais joue au
-- demarrage par logic/migrations.py, qui l'envoie tel quel a Postgres via
-- psycopg2 - une commande psql y provoquait une erreur de syntaxe et
-- l'application refusait de demarrer. De meme BEGIN/COMMIT : le lanceur
-- ouvre deja sa propre transaction. En ligne de commande, lancer avec
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -1 -f <ce fichier>
