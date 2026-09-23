-- ---------------------------------------------------------------------------
-- Correctifs de l'audit du 18/09/2026, partie base de donnees (M2, M6) -
-- 22/09/2026.
--
-- Jouee automatiquement au demarrage de app.py par logic/migrations.py (voir
-- ce fichier, ajoute par ce meme lot - M4). Sur une base neuve, ces memes
-- objets sont deja crees par sql/schema.sql : les gardes (IF NOT EXISTS,
-- DO $$ ... exception) rendent cette migration inoffensive dans les deux cas.
--
-- AVANT DE DEPLOYER SUR LA PRODUCTION : verifier qu'aucune piece existante ne
-- viole deja l'equilibre, sans quoi le trigger ci-dessous la signalera des la
-- premiere modification de cette piece (jamais sur les pieces anciennes qui
-- ne bougent plus, le trigger n'etant pas retroactif) :
--
--   SELECT id_piece, sum(debit), sum(credit) FROM ecritures
--   GROUP BY id_piece HAVING round(sum(debit), 2) <> round(sum(credit), 2);
--
-- Une ligne qui ressort ici doit etre corrigee AVANT ce deploiement.
-- ---------------------------------------------------------------------------

-- M2 : signe et exclusivite debit/credit, par ligne. ADD CONSTRAINT ne
-- supporte pas IF NOT EXISTS : on verifie via pg_constraint.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_montants_positifs'
    ) THEN
        ALTER TABLE ecritures ADD CONSTRAINT ck_montants_positifs
            CHECK (debit >= 0 AND credit >= 0 AND NOT (debit > 0 AND credit > 0));
    END IF;
END $$;

-- M2 : equilibre par piece. DEFERRABLE INITIALLY DEFERRED est indispensable :
-- une piece n'est equilibree qu'une fois TOUTES ses lignes inserees.
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

-- M6 : une seule entree possible par reference de transfert interne (voir
-- logic.donnees._sortie_a_apparier, qui verrouille desormais aussi la ligne
-- choisie avec FOR UPDATE ... SKIP LOCKED - cet index rend l'anomalie
-- impossible meme si le code applicatif change plus tard).
CREATE UNIQUE INDEX IF NOT EXISTS uq_transfert_entree ON ecritures (reference_transfert)
    WHERE reference_transfert <> '' AND compte = '585000' AND credit > 0;
