-- ---------------------------------------------------------------------------
-- Codes tiers de plus de 17 caracteres (C4 de l'audit du 07/10/2026).
-- Le dossier Sage est regle sur 17 : au-dela, Sage tronque sans prevenir.
--
-- 1. Lister (sans rien modifier) :
--      docker compose exec -T db psql -U hakili_admin -d Hakili_compta -f - < outils/tiers_trop_longs.sql
-- ---------------------------------------------------------------------------
SELECT t.code_tiers, length(t.code_tiers) AS longueur, t.intitule,
       count(e.id_ligne) AS lignes,
       count(e.id_ligne) FILTER (WHERE e.statut = 'exportee') AS lignes_exportees
FROM tiers t LEFT JOIN ecritures e ON e.code_tiers = t.code_tiers
WHERE length(t.code_tiers) > 17
GROUP BY t.code_tiers, t.intitule ORDER BY t.code_tiers;

-- 2. Renommer un code (a faire pour chaque ligne ci-dessus, AVANT le prochain
--    export, et seulement si lignes_exportees = 0 : une ligne deja dans Sage
--    se corrige dans Sage). Exemple :
--
--   BEGIN;
--   INSERT INTO tiers (code_tiers, intitule, compte_collectif, type, actif, actif_annee)
--     SELECT '411OUEDRAOGOPENGD', intitule, compte_collectif, type, actif, actif_annee
--     FROM tiers WHERE code_tiers = '411OUEDRAOGOPENGDEWEN';
--   UPDATE ecritures SET code_tiers = '411OUEDRAOGOPENGD' WHERE code_tiers = '411OUEDRAOGOPENGDEWEN';
--   DELETE FROM tiers WHERE code_tiers = '411OUEDRAOGOPENGDEWEN';
--   COMMIT;
--
-- 3. Quand la requete 1 ne renvoie plus rien, poser la contrainte :
--   ALTER TABLE tiers ADD CONSTRAINT ck_tiers_longueur_sage CHECK (length(code_tiers) <= 17);
