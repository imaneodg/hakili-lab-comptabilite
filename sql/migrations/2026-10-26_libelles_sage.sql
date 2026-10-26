-- ---------------------------------------------------------------------------
-- Alignement sur Sage de 13 libelles avec un vrai ecart de sens (26/10/2026).
--
-- Suite au comptage des ecarts entre l'application et le plan comptable
-- Sage (tirage du 17/08/2026, reconfirme sur un tirage du 23/10/2026), ces
-- 13 comptes ont ete tranches par Afiya en faveur du libelle Sage : le sens
-- differait reellement, pas seulement l'accentuation ou une troncature
-- d'export.
--
-- Volontairement exclus de cette migration :
--   - 521100 (Banque / BDU) : garde le libelle de l'application ;
--   - 160300 : deja corrige par 2026-10-23_libelle_compte_160300.sql ;
--   - tous les autres ecarts constates dans sql/charger_plan_comptable.sql,
--     qui ne sont que des accents ou des troncatures Sage a 35 caracteres,
--     laisses tels quels.
--
-- Idempotent.
-- ---------------------------------------------------------------------------

UPDATE comptes SET intitule = 'EMPRUNT ASSOCIE N°1' WHERE compte = '160100';
UPDATE comptes SET intitule = 'EMPRUNT ASSOCIE N°2' WHERE compte = '160200';
UPDATE comptes SET intitule = 'Personnel remuneration due' WHERE compte = '422300';
UPDATE comptes SET intitule = 'RETENUE A LA SOURCE 2%' WHERE compte = '447810';
UPDATE comptes SET intitule = 'Matières consommables' WHERE compte = '604100';
UPDATE comptes SET intitule = 'Autres énergies' WHERE compte = '605300';
UPDATE comptes SET intitule = 'Hygiène et services assimilés' WHERE compte = '624330';
UPDATE comptes SET intitule = 'Catalogues, imprimés publicitaires' WHERE compte = '627200';
UPDATE comptes SET intitule = 'Frais de télex' WHERE compte = '628200';
UPDATE comptes SET intitule = 'Droits de mutation' WHERE compte = '646100';
UPDATE comptes SET intitule = 'Autres charges sociales' WHERE compte = '664800';
UPDATE comptes SET intitule = 'Autres produits accessoires' WHERE compte = '707800';
UPDATE comptes SET intitule = 'Autres produits' WHERE compte = '707810';
