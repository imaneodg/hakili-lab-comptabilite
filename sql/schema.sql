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

-- Registre des migrations jouees (M4 de l'audit du 18/09, corrige le
-- 22/09/2026) : creee ici pour qu'une base neuve naisse deja avec, et
-- lue/alimentee au demarrage par logic/migrations.py. Une base existante
-- migree depuis avant cette date l'a deja (voir
-- sql/migrations/2026-09-15_rattrapage_production.sql) ; CREATE ... IF NOT
-- EXISTS rend les deux cas inoffensifs.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version      text PRIMARY KEY,
    applied_at   timestamptz NOT NULL DEFAULT now()
);

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

-- caisse_physique distingue une caisse en especes reellement detenue par un
-- centre (CP, CMD - chacun des cinq centres a son propre tiroir-caisse) d'un
-- compte partage entre tous les centres (la banque) : c'est ce qui decide si
-- un solde d'ouverture se ventile par centre (table soldes_ouverture_centre
-- ci-dessous) ou reste unique (solde_ouverture ci-dessous). actif retire un
-- journal de la circulation (ancienne banque apres changement d'etablissement,
-- par exemple) sans jamais toucher a son historique : les ecritures qui le
-- referencent restent intactes et consultables, seule la creation de
-- nouvelles pieces sur ce journal n'est plus proposee.
CREATE TABLE IF NOT EXISTS journaux (
    journal              text PRIMARY KEY,
    intitule              text NOT NULL,
    compte_contrepartie   text REFERENCES comptes(compte),
    type                  text NOT NULL DEFAULT 'tresorerie' CHECK (type IN ('tresorerie', 'operations')),
    prefixe_piece         text NOT NULL,
    -- Solde d'ouverture global : n'a de sens que pour un journal qui n'est
    -- pas une caisse physique (la banque). Pour CP/CMD, le solde reel se lit
    -- desormais dans soldes_ouverture_centre - cette colonne y reste a titre
    -- de compatibilite mais n'est plus lue pour eux.
    solde_ouverture       numeric(14, 2) NOT NULL DEFAULT 0,
    caisse_physique       text NOT NULL DEFAULT 'non' CHECK (caisse_physique IN ('oui', 'non')),
    actif                 text NOT NULL DEFAULT 'oui' CHECK (actif IN ('oui', 'non')),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Pas de code_acces ici (retire le 10/09/2026, voir
-- sql/migrations/2026-09-10_suppression_code_acces_centres.sql) : la
-- connexion ne s'appuie que sur utilisateurs.code_acces (un code personnel
-- par personne, hache bcrypt) - un code de centre partage n'a jamais ete lu
-- par le code applicatif, mais restait en base en clair, ce qui aurait pu
-- induire en erreur ou etre reutilise par erreur plus tard.
CREATE TABLE IF NOT EXISTS centres (
    code_centre          text PRIMARY KEY,
    intitule              text NOT NULL,
    section_analytique    text NOT NULL,
    actif                 text NOT NULL DEFAULT 'oui' CHECK (actif IN ('oui', 'non')),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

-- Solde d'ouverture d'une caisse physique (CP, CMD), par centre : chacun des
-- cinq centres a sa propre caisse reelle, donc son propre encaisse de
-- depart - un seul solde_ouverture par journal (ci-dessus) melangeait a tort
-- les cinq tiroirs-caisses en un seul chiffre, ce qui faussait le solde
-- affiche a chaque centre et pouvait masquer une caisse reellement a sec
-- pendant qu'une autre etait excedentaire (voir sql/migrations/2026-09-11_*).
-- Ne concerne jamais un journal ou caisse_physique = 'non' (la banque) : ce
-- compte est unique et partage, son solde reste dans journaux.solde_ouverture.
CREATE TABLE IF NOT EXISTS soldes_ouverture_centre (
    centre           text NOT NULL REFERENCES centres(code_centre),
    journal          text NOT NULL REFERENCES journaux(journal),
    solde_ouverture  numeric(14, 2) NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (centre, journal)
);

CREATE TABLE IF NOT EXISTS utilisateurs (
    identifiant          text PRIMARY KEY,
    nom                   text NOT NULL,
    role                  text NOT NULL CHECK (role IN ('saisie', 'validation')),
    centre                text NOT NULL REFERENCES centres(code_centre),
    -- Hache bcrypt (colonne historiquement en clair : les comptes crees
    -- avant la migration du 05/09/2026 sont mis a niveau automatiquement au
    -- premier login reussi, voir logic.donnees.verifier_code_acces).
    code_acces            text NOT NULL,
    -- Anti brute-force : voir logic.donnees.tenter_connexion.
    tentatives_echouees   integer NOT NULL DEFAULT 0,
    verrouille_jusqu_a    timestamptz,
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
    valeurs_json           jsonb,
    -- Transferts internes entre centres (voir
    -- sql/migrations/2026-09-12_transferts_internes.sql). Vides sur toute
    -- ecriture qui n'est pas un transfert. Presents ici pour qu'une base
    -- creee de zero (verifier.py, nouveau deploiement) soit complete sans
    -- avoir a rejouer les migrations ; la migration reste necessaire pour
    -- les bases deja en service.
    reference_transfert    text NOT NULL DEFAULT '',
    centre_contrepartie    text NOT NULL DEFAULT '',
    -- M2 de l'audit du 18/09, corrige le 22/09/2026 : avant, l'equilibre et
    -- le signe des montants n'etaient verifies que par logic/modeles.py, cote
    -- application - un appel direct a enregistrer_operation() (ou un import
    -- comme import_historique.py) pouvait inserer une ligne des deux sens a
    -- la fois, ou negative. Ce CHECK porte sur une seule ligne (le signe) ;
    -- l'equilibre PAR PIECE (somme des debits = somme des credits) est
    -- impose plus bas par un trigger de contrainte differable, parce qu'une
    -- piece n'est equilibree qu'une fois toutes ses lignes inserees.
    CONSTRAINT ck_montants_positifs
        CHECK (debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0))
);
CREATE INDEX IF NOT EXISTS idx_ecritures_piece   ON ecritures(id_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_lien     ON ecritures(id_lien) WHERE id_lien <> '';
CREATE INDEX IF NOT EXISTS idx_ecritures_centre   ON ecritures(centre, date_piece);
CREATE INDEX IF NOT EXISTS idx_ecritures_statut   ON ecritures(statut);
CREATE INDEX IF NOT EXISTS idx_ecritures_num_def  ON ecritures(journal, num_definitif);
CREATE INDEX IF NOT EXISTS idx_ecritures_transfert ON ecritures(reference_transfert)
    WHERE reference_transfert <> '';

-- M6 de l'audit du 18/09, corrige le 22/09/2026 : une seule entree peut
-- s'apparier a une reference de transfert donnee (compte 585000, au credit,
-- cote centre destinataire). Sans cet index, deux entrees saisies au meme
-- instant par deux postes du meme centre pouvaient s'apparier a la MEME
-- sortie (voir logic.donnees._sortie_a_apparier, qui verrouille desormais
-- la ligne choisie avec FOR UPDATE ... SKIP LOCKED - cet index reste le
-- garde-fou qui rend l'anomalie impossible meme si le code applicatif
-- change plus tard).
CREATE UNIQUE INDEX IF NOT EXISTS uq_transfert_entree ON ecritures (reference_transfert)
    WHERE reference_transfert <> '' AND compte = '585000' AND credit > 0;

-- M2 (suite) : equilibre PAR PIECE. DEFERRABLE INITIALLY DEFERRED est
-- indispensable : l'equilibre d'une piece n'est vrai qu'une fois toutes ses
-- lignes inserees, jamais apres la premiere. import_historique.py et tout
-- script futur en beneficient sans rien y changer.
CREATE OR REPLACE FUNCTION verifier_equilibre_piece() RETURNS trigger AS $$
DECLARE
    p text;
    d numeric;
    c numeric;
BEGIN
    p := CASE WHEN TG_OP = 'DELETE' THEN OLD.id_piece ELSE NEW.id_piece END;
    SELECT COALESCE(SUM(debit), 0), COALESCE(SUM(credit), 0) INTO d, c
    FROM ecritures WHERE id_piece = p;
    IF round(d, 2) <> round(c, 2) THEN
        RAISE EXCEPTION 'Piece % desequilibree : debit=%, credit=%', p, d, c;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_equilibre_piece ON ecritures;
CREATE CONSTRAINT TRIGGER trg_equilibre_piece
    AFTER INSERT OR UPDATE OR DELETE ON ecritures
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION verifier_equilibre_piece();

-- Compteurs de numerotation. Remplace le verrou de repertoire de la version
-- Excel : ici, l'atomicite vient d'un UPSERT (INSERT ... ON CONFLICT DO
-- UPDATE ... RETURNING), qui est protege par Postgres lui-meme meme sous
-- forte concurrence, sans qu'aucun verrou applicatif ne soit necessaire.
--   cle "prov:{centre}:{aaaamm}"  -> dernier numero provisoire du centre/mois
--   cle "def:{journal}:{aaaamm}"  -> dernier numero definitif du journal/mois
-- Trace des pieces supprimees (seules les pieces non encore validees
-- peuvent l'etre, voir supprimer_piece) : contenu integral conserve, avec
-- qui a supprime et quand - une pièce non validee reste ainsi retracable
-- meme apres suppression, ce que le DELETE seul ne permettait pas.
CREATE TABLE IF NOT EXISTS suppressions_ecritures (
    id             serial PRIMARY KEY,
    id_piece       text NOT NULL,
    contenu        jsonb NOT NULL,
    supprime_par   text NOT NULL,
    supprime_le    timestamptz NOT NULL DEFAULT now()
);

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
    FOREACH t IN ARRAY ARRAY['comptes', 'tiers', 'journaux', 'centres', 'utilisateurs', 'ecritures',
                              'soldes_ouverture_centre']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_rev_%1$s ON %1$s;
             CREATE TRIGGER trg_rev_%1$s AFTER INSERT OR UPDATE OR DELETE ON %1$s
             FOR EACH STATEMENT EXECUTE FUNCTION bump_revision();', t);
    END LOOP;
END $$;
