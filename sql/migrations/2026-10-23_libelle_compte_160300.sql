-- ---------------------------------------------------------------------------
-- Correction du libelle du compte 160300 (23/10/2026).
--
-- Libelle en base (seed.sql, 28/08/2026) : "Avances recues de l'Etat /
-- autres emprunts". Aligne sur le sens retenu dans Sage ("AUTRES EMPRUNT",
-- tirage du 17/08/2026), avec l'accord au pluriel pour rester coherent avec
-- le style des autres libelles de l'application.
--
-- Seul ce compte est concerne. Idempotent.
-- ---------------------------------------------------------------------------

UPDATE comptes
SET intitule = 'Autres emprunts'
WHERE compte = '160300';
