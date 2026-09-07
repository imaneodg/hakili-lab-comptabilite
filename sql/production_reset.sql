-- HAKILI LAB - remise a zero avant mise en production
--
-- ATTENTION : executer uniquement sur la base de production voulue.
-- Ce script ne supprime pas le plan comptable, les journaux, les centres,
-- les libelles de saisie ni les autres comptes tiers. Il supprime seulement
-- les ecritures/suppressions/compteurs transactionnels et le tiers de test
-- explicitement demande.
--
-- Il ne contient aucun identifiant de connexion.

BEGIN;

-- Toutes les pieces et ecritures historiques/test sont retirees.
DELETE FROM ecritures;
DELETE FROM suppressions_ecritures;
DELETE FROM compteurs;

-- Retirer le compte tiers de test demande.
DELETE FROM tiers
WHERE lower(btrim(intitule)) = lower('Ouedraogo Afiya');

-- Mise a jour de la banque : l'ancien journal BDU-BF devient CBI.
-- Les ecritures ayant ete supprimees ci-dessus, le changement de cle est sans
-- historique a conserver dans ecritures. Si CBI existe deja, on conserve CBI.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM journaux WHERE journal = 'BDU-BF')
       AND NOT EXISTS (SELECT 1 FROM journaux WHERE journal = 'CBI') THEN
        UPDATE journaux
        SET journal = 'CBI', intitule = 'CBI', prefixe_piece = 'CBI', updated_at = now()
        WHERE journal = 'BDU-BF';
    ELSE
        UPDATE journaux
        SET intitule = 'CBI', prefixe_piece = 'CBI', updated_at = now()
        WHERE journal = 'CBI';
    END IF;
END $$;

UPDATE comptes
SET intitule = 'Banques (CBI)', updated_at = now()
WHERE compte = '521100';

-- Reinitialiser le watermark de rafraichissement.
UPDATE revision SET valeur = 0 WHERE id = true;

COMMIT;

-- Verification attendue apres execution :
-- SELECT count(*) AS ecritures FROM ecritures;
-- SELECT count(*) AS suppressions FROM suppressions_ecritures;
-- SELECT count(*) AS compteurs FROM compteurs;
-- SELECT count(*) AS afiya FROM tiers WHERE lower(btrim(intitule)) = lower('Ouedraogo Afiya');
