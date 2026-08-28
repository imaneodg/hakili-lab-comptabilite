-- ---------------------------------------------------------------------------
-- HAKILI LAB - schema PostgreSQL
--
-- Concu directement pour Postgres (pas une migration depuis Excel) : les
-- contraintes d'unicite et de coherence qu'un classeur Excel ne pouvait que
-- verifier a la lecture sont ici imposees par la base elle-meme (cles
-- primaires, cles etrangeres, CHECK). Deux consequences concretes :
--   - un code compte, tiers, journal, centre ou utilisateur en double est
--     rejete a l'ecriture, jamais decouvert plus tard dans un controle ;
--   - une ecriture qui reference un compte, un journal ou un centre inconnu
--     est refusee par la base avant meme d'atteindre logic/donnees.py.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS comptes (
    compte              text PRIMARY KEY,
    intitule            text NOT NULL,
    nature              text NOT NULL CHECK (nature IN ('charge', 'produit', 'tresorerie', 'bilan', 'tiers')),
    tiers_obligatoire   text NOT NULL DEFAULT 'non' CHECK (tiers_obligatoire IN ('oui', 'non')),
    nb_2024_2025        integer NOT NULL DEFAULT 0,
    depense_courante    text NOT NULL DEFAULT 'non' CHECK (depense_courante IN ('oui', 'non')),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tiers (
    code_tiers          text PRIMARY KEY,
    intitule            text NOT NULL,
    compte_collectif    text NOT NULL REFERENCES comptes(compte),
    type                text NOT NULL,
    actif               text NOT NULL DEFAULT 'oui' CHECK (actif IN ('oui', 'non')),
    actif_annee         text NOT NULL DEFAULT 'oui' CHECK (actif_annee IN ('oui', 'non')),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tiers_collectif ON tiers(compte_collectif);

CREATE TABLE IF NOT EXISTS libelles_types (
    id                  serial PRIMARY KEY,
    compte              text NOT NULL REFERENCES comptes(compte),
    libelle             text NOT NULL,
    frequence           integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_libelles_compte ON libelles_types(compte);

CREATE TABLE IF NOT EXISTS journaux (
    journal              text PRIMARY KEY,
    intitule              text NOT NULL,
    compte_contrepartie   text REFERENCES comptes(compte),
    type                  text NOT NULL DEFAULT 'tresorerie' CHECK (type IN ('tresorerie', 'operations')),
    prefixe_piece         text NOT NULL,
    solde_ouverture       numeric(14, 2) NOT NULL DEFAULT 0,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS centres (
    code_centre          text PRIMARY KEY,
    intitule              text NOT NULL,
    section_analytique    text NOT NULL,
    actif                 text NOT NULL DEFAULT 'oui' CHECK (actif IN ('oui', 'non')),
    code_acces            text NOT NULL,
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS utilisateurs (
    identifiant          text PRIMARY KEY,
    nom                   text NOT NULL,
    role                  text NOT NULL CHECK (role IN ('saisie', 'validation')),
    centre                text NOT NULL REFERENCES centres(code_centre),
    code_acces            text NOT NULL,
    actif                 text NOT NULL DEFAULT 'oui' CHECK (actif IN ('oui', 'non')),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Une ligne d'ecriture. La piece est le regroupement de plusieurs lignes qui
-- partagent id_piece ; id_lien regroupe a son tour les pieces solidaires
-- (transfert entre caisses), exactement comme dans la version Excel.
CREATE TABLE IF NOT EXISTS ecritures (
    id_ligne             text PRIMARY KEY,
    id_piece             text NOT NULL,
    id_lien              text NOT NULL DEFAULT '',
    num_provisoire        text NOT NULL DEFAULT '',
    num_definitif         text NOT NULL DEFAULT '',
    journal               text NOT NULL REFERENCES journaux(journal),
    centre                text NOT NULL REFERENCES centres(code_centre),
    date_piece            date NOT NULL,
    compte                text NOT NULL REFERENCES comptes(compte),
    code_tiers            text NOT NULL DEFAULT '',
    libelle               text NOT NULL DEFAULT '',
    debit                 numeric(14, 2) NOT NULL DEFAULT 0,
    credit                numeric(14, 2) NOT NULL DEFAULT 0,
    modele                text NOT NULL DEFAULT '',
    saisi_par             text NOT NULL DEFAULT '',
    saisi_le              timestamptz NOT NULL DEFAULT now(),
    statut                text NOT NULL DEFAULT 'saisie'
                           CHECK (statut IN ('saisie', 'a_corriger', 'validee', 'exportee')),
    valide_par            text NOT NULL DEFAULT '',
    valide_le             timestamptz,
    exporte_le            timestamptz,
    observation           text NOT NULL DEFAULT '',
    valeurs_json           jsonb
);
CREATE INDEX IF NOT EXISTS idx_ecritures_piece   ON ecritures(id_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_lien     ON ecritures(id_lien) WHERE id_lien <> '';
CREATE INDEX IF NOT EXISTS idx_ecritures_centre   ON ecritures(centre, date_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_statut   ON ecritures(statut);
CREATE INDEX IF NOT EXISTS idx_ecritures_num_def  ON ecritures(journal, num_definitif);

-- Compteurs de numerotation. Remplace le verrou de repertoire de la version
-- Excel : ici, l'atomicite vient d'un UPSERT (INSERT ... ON CONFLICT DO
-- UPDATE ... RETURNING), qui est protege par Postgres lui-meme meme sous
-- forte concurrence, sans qu'aucun verrou applicatif ne soit necessaire.
--   cle "prov:{centre}:{aaaamm}"  -> dernier numero provisoire du centre/mois
--   cle "def:{journal}:{aaaamm}"  -> dernier numero definitif du journal/mois
CREATE TABLE IF NOT EXISTS compteurs (
    cle      text PRIMARY KEY,
    valeur   integer NOT NULL DEFAULT 0
);

-- Watermark de synchronisation entre postes. La version Excel guettait la
-- date de modification des fichiers sur le disque ; ici, un seul entier
-- incremente par trigger a chaque ecriture sur une table metier joue le
-- meme role, interroge par un reactive.poll cote application.
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

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['comptes', 'tiers', 'journaux', 'centres', 'utilisateurs', 'ecritures']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_rev_%1$s ON %1$s;
             CREATE TRIGGER trg_rev_%1$s AFTER INSERT OR UPDATE OR DELETE ON %1$s
             FOR EACH STATEMENT EXECUTE FUNCTION bump_revision();', t);
    END LOOP;
END $$;
