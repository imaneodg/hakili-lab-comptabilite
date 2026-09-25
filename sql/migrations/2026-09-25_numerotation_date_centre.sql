-- ---------------------------------------------------------------------------
-- Numerotation definitive par date puis par centre (25/09/2026).
--
-- 1. centres.ordre : ordre dans lequel les centres sont numerotes a une meme
--    date (SIAO, Tampouy, Saaba, Pissy, Nagrin, puis le siege). Un centre
--    absent d'un lot est simplement saute : aucun numero ne lui est reserve.
-- 2. ecritures.num_reserve : numero definitif garde par une piece renvoyee
--    pour correction. Elle le retrouve a la revalidation, au lieu d'en
--    prendre un nouveau et de laisser un trou dans le journal.
-- 3. trg_numero_unique : deux pieces d'un meme journal ne peuvent jamais
--    porter le meme numero definitif.
--
-- Idempotent. Controle conseille avant de deployer (doit ne rien renvoyer) :
--   SELECT journal, num_definitif, count(DISTINCT id_piece) FROM ecritures
--   WHERE num_definitif <> '' GROUP BY 1, 2 HAVING count(DISTINCT id_piece) > 1;
-- ---------------------------------------------------------------------------

ALTER TABLE centres ADD COLUMN IF NOT EXISTS ordre integer NOT NULL DEFAULT 99;

UPDATE centres SET ordre = v.ordre
FROM (VALUES ('SIA', 1), ('TAM', 2), ('SAA', 3), ('PIS', 4), ('NAG', 5), ('SIE', 6)) AS v(code, ordre)
WHERE centres.code_centre = v.code AND centres.ordre <> v.ordre;

ALTER TABLE ecritures ADD COLUMN IF NOT EXISTS num_reserve text NOT NULL DEFAULT '';

CREATE OR REPLACE FUNCTION verifier_numero_unique() RETURNS trigger AS $$
BEGIN
    IF NEW.num_definitif <> '' AND EXISTS (
        SELECT 1 FROM ecritures
        WHERE journal = NEW.journal AND num_definitif = NEW.num_definitif
          AND id_piece <> NEW.id_piece) THEN
        RAISE EXCEPTION 'Numero de piece % deja attribue dans le journal %',
            NEW.num_definitif, NEW.journal;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_numero_unique ON ecritures;
CREATE CONSTRAINT TRIGGER trg_numero_unique
    AFTER INSERT OR UPDATE OF num_definitif, journal ON ecritures
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION verifier_numero_unique();
