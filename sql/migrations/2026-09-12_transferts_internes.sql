-- ---------------------------------------------------------------------------
-- Transferts internes entre centres (12/09/2026)
--
-- Chaque centre a sa propre caisse. Quand un centre remet des especes a un
-- autre - le cas courant etant le depot mensuel au centre SIAO, qui paie
-- ensuite pour le compte de tous (impots, contribution sur les benefices) -
-- l'argent ne fait que changer de tiroir. Ce n'est ni une recette ni une
-- depense pour Hakili Lab.
--
-- Compte retenu : 585000 "Virements de fonds", deja present dans le plan Sage
-- de HAKILISSO et deja utilise par la comptable pour ces operations. C'est un
-- compte de PASSAGE : il doit revenir a zero des que le transfert est termine.
--
-- Comptes ecartes, et pourquoi :
--   * 401000 / 411000 : impossible, les cinq centres sont une seule societe -
--     on ne peut etre ni son propre client ni son propre fournisseur. Une
--     ecriture de ce type existe pourtant dans les brouillards (tiers
--     411CONTRIBUTIONSIAO), a regulariser.
--   * 186000 / 187000 (comptes de liaison des etablissements) : ce sont des
--     comptes de BILAN - le plan Sage les declare en nature "Capitaux". Les
--     utiliser ne produirait donc aucune charge chez le centre payeur ni aucun
--     produit chez SIAO, contrairement a ce qu'on pourrait croire de leur
--     intitule. Ils servent a relier des comptabilites SEPAREES qu'on fusionne
--     ensuite ; Hakili tient une seule comptabilite avec un axe analytique par
--     centre, il n'y a donc rien a relier.
--   * 182000 / 183000 : deja pris dans le plan Sage par "Dettes liees a des
--     societes en participation" et "Interets courus" - sans aucun rapport.
--
-- Les deux colonnes ci-dessous permettent le rapprochement par operation. Le
-- seul solde du 585000 ne suffit pas : plusieurs transferts peuvent se
-- compenser entre eux et masquer une remise manquante.
--
-- Rejouable sans risque.
-- ---------------------------------------------------------------------------

-- Reference partagee par les deux faces d'un meme transfert (TRF-202609-0001).
-- Vide pour toutes les ecritures existantes : l'historique deja saisi sans
-- reference ressort dans le panier "a regulariser" du rapprochement.
ALTER TABLE ecritures
    ADD COLUMN IF NOT EXISTS reference_transfert text NOT NULL DEFAULT '';

-- L'autre centre concerne. La colonne `centre` porte deja celui qui saisit ;
-- celle-ci dit vers ou (ou d'ou) va l'argent. Necessaire avant meme que la
-- seconde face existe : sans elle, on ne saurait pas a qui un centre destinait
-- une remise que personne n'a encore enregistree.
ALTER TABLE ecritures
    ADD COLUMN IF NOT EXISTS centre_contrepartie text NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_ecritures_transfert
    ON ecritures(reference_transfert) WHERE reference_transfert <> '';

-- Le compte de virements de fonds doit exister dans le referentiel applicatif
-- (il est deja dans Sage). Nature 'tresorerie' : c'est ce qui fait reconnaitre
-- une piece de transfert par logic.analyse.pieces_transfert_interne, et donc
-- l'exclure des recettes et des depenses.
INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, nb_2024_2025, depense_courante)
VALUES ('585000', 'Virements de fonds (caisse / banque)', 'tresorerie', 'non', 0, 'non')
ON CONFLICT (compte) DO NOTHING;

-- Libelles suggeres a la saisie. Ce sont ceux reellement employes dans les
-- brouillards 2026 : Tampouy ecrit "CONTRIBUTION SIAO", Saaba "APPROV SIAO".
-- Le champ reste libre (le caissier peut taper autre chose) : le rapprochement
-- ne lit jamais le libelle, il travaille sur la reference et les centres.
INSERT INTO libelles_types (compte, libelle, frequence)
SELECT '585000', v.lib, 0
FROM (VALUES ('TRANSFERT INTERNE'), ('CONTRIBUTION SIAO'), ('APPROV SIAO'),
              ('DEPOT SIAO')) AS v(lib)
WHERE NOT EXISTS (SELECT 1 FROM libelles_types l
                   WHERE l.compte = '585000' AND l.libelle = v.lib);
