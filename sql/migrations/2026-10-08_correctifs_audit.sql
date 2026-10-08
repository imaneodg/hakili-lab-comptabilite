-- ---------------------------------------------------------------------------
-- Correctifs de l'audit du 07/10/2026.
--
-- 1. (Lots d'export retires le 08/10/2026 a la demande d'Afiya : l'ecran
--    Export Sage garde son fonctionnement d'avant. Rien a creer en base.)
-- 2. periodes_cloturees : un mois cloture par le comptable ne recoit plus
--    aucune piece et aucune de ses pieces ne change de montant ni de compte.
--    Regle tenue par la base elle-meme (M3).
-- 3. Une ligne exportee ne se modifie plus et ne se supprime plus, sauf
--    dans un script qui le demande explicitement (M3).
-- 4. Revisions : le referentiel a sa propre revision, et une connexion
--    (compteur d'essais) ne fait plus tout recharger a tout le monde (M1).
-- 5. Codes tiers limites a 17 caracteres comme le dossier Sage (C4).
-- 6. Role hakili_lecture : la requete libre de l'assistant s'execute sous
--    ce role, qui ne lit que les tables prevues (M8).
-- 7. utilisateurs.doit_changer_code : code reinitialise par le comptable,
--    a changer a la connexion suivante (M9).
--
-- Idempotent.
-- ---------------------------------------------------------------------------

-- 2 et 3. Clotures et protection des pieces exportees -------------------------
CREATE TABLE IF NOT EXISTS periodes_cloturees (
    mois        text PRIMARY KEY CHECK (mois ~ '^[0-9]{4}-[0-9]{2}$'),
    cloture_par text NOT NULL,
    cloture_le  timestamptz NOT NULL DEFAULT now()
);

-- Une echappatoire volontaire et visible pour un script de reprise :
--   SET LOCAL hakili.autoriser_modif_protegee = 'oui';
-- Jamais utilisee par l'application.
CREATE OR REPLACE FUNCTION proteger_ecritures() RETURNS trigger AS $$
DECLARE
    m_old text;
    m_new text;
BEGIN
    IF coalesce(current_setting('hakili.autoriser_modif_protegee', true), '') = 'oui' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.statut = 'exportee' THEN
        RAISE EXCEPTION 'Piece % deja exportee vers Sage : elle ne se modifie plus. '
                        'Corriger par une ecriture d''extourne.', OLD.id_piece;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        m_old := to_char(OLD.date_piece, 'YYYY-MM');
    END IF;
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        m_new := to_char(NEW.date_piece, 'YYYY-MM');
    END IF;

    IF TG_OP = 'INSERT' AND EXISTS (SELECT 1 FROM periodes_cloturees WHERE mois = m_new) THEN
        RAISE EXCEPTION 'Le mois % est cloture : aucune piece ne peut y etre ajoutee.', m_new;
    END IF;
    IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM periodes_cloturees WHERE mois = m_old) THEN
        RAISE EXCEPTION 'Le mois % est cloture : ses pieces ne peuvent plus etre supprimees.', m_old;
    END IF;
    IF TG_OP = 'UPDATE'
       AND (NEW.date_piece, NEW.compte, NEW.code_tiers, NEW.debit, NEW.credit, NEW.journal,
            NEW.centre, NEW.libelle)
           IS DISTINCT FROM
           (OLD.date_piece, OLD.compte, OLD.code_tiers, OLD.debit, OLD.credit, OLD.journal,
            OLD.centre, OLD.libelle)
       AND EXISTS (SELECT 1 FROM periodes_cloturees WHERE mois IN (m_old, m_new)) THEN
        RAISE EXCEPTION 'Le mois % est cloture : ses pieces ne changent plus.',
            (SELECT mois FROM periodes_cloturees WHERE mois IN (m_old, m_new) LIMIT 1);
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_proteger_ecritures ON ecritures;
CREATE TRIGGER trg_proteger_ecritures
    BEFORE INSERT OR UPDATE OR DELETE ON ecritures
    FOR EACH ROW EXECUTE FUNCTION proteger_ecritures();


-- 4. Revisions -----------------------------------------------------------------
-- Le referentiel a sa propre revision (tiers, comptes, journaux, centres,
-- utilisateurs) : une ecriture n'oblige plus chaque session a relire le
-- referentiel et a tout recalculer derriere, ni l'inverse.
ALTER TABLE revision ADD COLUMN IF NOT EXISTS referentiel bigint NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION bump_revision_referentiel() RETURNS trigger AS $$
BEGIN
    UPDATE revision SET referentiel = referentiel + 1;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION bump_revision_utilisateurs() RETURNS trigger AS $$
BEGIN
    UPDATE revision SET valeur = valeur + 1, referentiel = referentiel + 1;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['comptes', 'tiers', 'journaux', 'centres', 'soldes_ouverture_centre']
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_revref_%1$s ON %1$s;
             CREATE TRIGGER trg_revref_%1$s AFTER INSERT OR UPDATE OR DELETE ON %1$s
             FOR EACH STATEMENT EXECUTE FUNCTION bump_revision_referentiel();', t);
    END LOOP;
END $$;

-- Utilisateurs : une connexion (compteur d'essais remis a zero) ne fait plus
-- tout recharger a toutes les sessions. Seuls les changements qui comptent
-- (activation, role, centre, nom) font avancer les revisions.
DROP TRIGGER IF EXISTS trg_rev_utilisateurs ON utilisateurs;
DROP TRIGGER IF EXISTS trg_rev_utilisateurs_ins_del ON utilisateurs;
DROP TRIGGER IF EXISTS trg_rev_utilisateurs_maj ON utilisateurs;
CREATE TRIGGER trg_rev_utilisateurs_ins_del AFTER INSERT OR DELETE ON utilisateurs
    FOR EACH STATEMENT EXECUTE FUNCTION bump_revision_utilisateurs();
CREATE TRIGGER trg_rev_utilisateurs_maj AFTER UPDATE ON utilisateurs
    FOR EACH ROW
    WHEN ((OLD.actif, OLD.role, OLD.centre, OLD.nom) IS DISTINCT FROM
          (NEW.actif, NEW.role, NEW.centre, NEW.nom))
    EXECUTE FUNCTION bump_revision_utilisateurs();


-- 5. Codes tiers : 17 caracteres -----------------------------------------------
-- La contrainte n'est posee que si aucun code existant ne la viole : sinon,
-- la mise a jour d'un tiers trop long (reactivation a la rentree) serait
-- refusee et bloquerait la saisie. Les codes trop longs se reperent avec
-- outils/tiers_trop_longs.sql ; une fois renommes, rejouer ce bloc.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_tiers_longueur_sage') THEN
        IF EXISTS (SELECT 1 FROM tiers WHERE length(code_tiers) > 17) THEN
            RAISE NOTICE 'Des codes tiers depassent 17 caracteres : contrainte non posee '
                         '(voir outils/tiers_trop_longs.sql).';
        ELSE
            ALTER TABLE tiers ADD CONSTRAINT ck_tiers_longueur_sage CHECK (length(code_tiers) <= 17);
        END IF;
    END IF;
END $$;


-- 6. Role de lecture de l'assistant ---------------------------------------------
-- NOLOGIN : on ne s'y connecte pas, l'application y bascule (SET LOCAL ROLE)
-- le temps d'une requete. Si le compte de la base n'a pas le droit de creer
-- un role, on le signale sans bloquer le demarrage : l'outil de requete
-- libre refusera simplement de s'executer (assistant/moteur.py).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hakili_lecture') THEN
        CREATE ROLE hakili_lecture NOLOGIN;
    END IF;
    EXECUTE format('GRANT hakili_lecture TO %I', current_user);
    REVOKE ALL ON ALL TABLES IN SCHEMA public FROM hakili_lecture;
    GRANT USAGE ON SCHEMA public TO hakili_lecture;
    GRANT SELECT ON v_lignes, centres, comptes, tiers, journaux, categories_charge,
                    centres_alias, soldes_ouverture_centre TO hakili_lecture;
EXCEPTION WHEN insufficient_privilege THEN
    RAISE NOTICE 'Role hakili_lecture non cree (droits insuffisants) : requete libre de l''assistant desactivee.';
END $$;


-- 7. Code a changer --------------------------------------------------------------
ALTER TABLE utilisateurs ADD COLUMN IF NOT EXISTS doit_changer_code boolean NOT NULL DEFAULT false;
