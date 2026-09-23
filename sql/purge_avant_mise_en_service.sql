-- ---------------------------------------------------------------------------
-- Remise a zero des mouvements avant mise en service reelle - 16/09/2026
--
-- Efface les ecritures de TEST saisies pendant la mise au point, pour que
-- l'application demarre sur une comptabilite vierge. Ne touche a rien d'autre :
-- le plan comptable, les journaux, les centres, les utilisateurs, les libelles
-- types et le plan tiers restent intacts.
--
-- A N'EXECUTER QU'UNE FOIS, avant que les caissieres ne commencent a saisir.
-- Passe cette date, il supprimerait de la vraie comptabilite.
--
-- AVANT :
--   docker compose exec -T db pg_dump -U hakili_admin -d Hakili_compta \
--       > ~/sauvegarde_avant_purge_$(date +%F).sql
--
-- USAGE :
--   docker compose exec -T db psql -U hakili_admin -d Hakili_compta \
--       -v ON_ERROR_STOP=1 < sql/purge_avant_mise_en_service.sql
-- ---------------------------------------------------------------------------

\set ON_ERROR_STOP on

\echo ''
\echo '=== ETAT AVANT PURGE ==='
SELECT (SELECT count(*) FROM ecritures)               AS lignes,
       (SELECT count(DISTINCT id_piece) FROM ecritures) AS pieces,
       (SELECT count(*) FROM suppressions_ecritures)  AS suppressions,
       (SELECT count(*) FROM compteurs)               AS compteurs,
       (SELECT count(*) FROM tiers)                   AS tiers;

BEGIN;

-- Les mouvements et leur historique de suppression.
DELETE FROM ecritures;
DELETE FROM suppressions_ecritures;

-- Les compteurs de numerotation : sans cette remise a zero, la premiere
-- vraie piece de la caissiere ne porterait pas le numero 001 mais reprendrait
-- la suite des pieces de test. Un brouillard qui commence a "SAA-2609-004"
-- laisse croire a trois pieces disparues.
DELETE FROM compteurs;

-- Les references de transfert inter-centres suivent les ecritures : rien a
-- faire de plus, elles vivent dans ecritures.reference_transfert.

COMMIT;

\echo ''
\echo '=== ETAT APRES PURGE ==='
SELECT (SELECT count(*) FROM ecritures)               AS lignes,
       (SELECT count(DISTINCT id_piece) FROM ecritures) AS pieces,
       (SELECT count(*) FROM suppressions_ecritures)  AS suppressions,
       (SELECT count(*) FROM compteurs)               AS compteurs,
       (SELECT count(*) FROM tiers)                   AS tiers;

\echo ''
\echo '=== CE QUI A ETE CONSERVE ==='
SELECT (SELECT count(*) FROM comptes)       AS comptes,
       (SELECT count(*) FROM journaux)      AS journaux,
       (SELECT count(*) FROM centres)       AS centres,
       (SELECT count(*) FROM utilisateurs)  AS utilisateurs,
       (SELECT count(*) FROM libelles_types) AS libelles_types,
       (SELECT count(*) FROM soldes_ouverture_centre) AS soldes_ouverture;

\echo ''
\echo 'Purge terminee. Prochaine etape : renseigner l''encaisse reelle de chaque'
\echo 'centre dans Referentiel > Soldes d''ouverture, sinon les soldes affiches'
\echo 'partiront de zero et l''onglet Controles signalera des caisses negatives.'
