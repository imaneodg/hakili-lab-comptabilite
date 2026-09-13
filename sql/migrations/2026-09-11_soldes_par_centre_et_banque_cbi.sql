-- ---------------------------------------------------------------------------
-- Migration : soldes de caisse par centre + changement de banque (BDU-BF -> CBI)
--
-- A appliquer UNE SEULE FOIS sur Hakili_compta (la base deja en service),
-- avant de deployer le code corrige. sql/schema.sql a deja ete mis a jour
-- pour qu'une base neuve (ex. poste de developpement) recree directement le
-- bon schema ; ce fichier ne sert qu'a mettre a niveau une base existante.
--
-- Pourquoi (deux corrections independantes, livrees ensemble) :
--
-- 1. Le comptable a confirme que chacun des cinq centres a sa propre caisse
--    physique (CP et CMD), avec son propre encaisse reel. journaux.
--    solde_ouverture etait un seul chiffre par journal, partage entre les
--    cinq centres : le solde affiche a un centre melangeait donc l'encaisse
--    des autres, et le controle d'anomalie (controler_soldes) sommait tous
--    les centres avant de verifier le signe - une caisse reellement a sec
--    dans un centre pouvait rester invisible, masquee par l'excedent d'un
--    autre. Cette migration ajoute une table soldes_ouverture_centre (un
--    solde d'ouverture par couple centre/journal) pour CP et CMD ; le
--    journal de banque, lui, reste un compte unique partage par tous les
--    centres (caisse_physique = 'non'), son solde global ne change pas de
--    mecanisme.
--
-- 2. L'entreprise a change de banque : BDU-BF est remplacee par CBI. Par
--    exactitude comptable (piste d'audit), l'ancien journal BDU-BF n'est ni
--    renomme ni fusionne : il est marque inactif (actif = 'non') et conserve
--    tel quel, avec tout son historique (compte 521100, ecritures passees,
--    export Sage deja effectues) - rien n'y est modifie ni supprime. Un
--    nouveau journal, "Banque" (compte 521200 - Banques (CBI), solde
--    d'ouverture 0 a renseigner par le comptable une fois le releve initial
--    de CBI connu), le remplace pour toute nouvelle piece. "actif" empeche
--    desormais qu'une piece soit encore creee sur un journal retire.
--
-- Usage (depuis la racine du projet, avec les identifiants de Hakili_compta) :
--   psql "$DATABASE_URL" -f sql/migrations/2026-09-11_soldes_par_centre_et_banque_cbi.sql
-- ---------------------------------------------------------------------------

-- --- 1. caisse_physique / actif sur journaux, et table par centre ----------

ALTER TABLE journaux
    ADD COLUMN IF NOT EXISTS caisse_physique text NOT NULL DEFAULT 'non'
        CHECK (caisse_physique IN ('oui', 'non')),
    ADD COLUMN IF NOT EXISTS actif text NOT NULL DEFAULT 'oui'
        CHECK (actif IN ('oui', 'non'));

UPDATE journaux SET caisse_physique = 'oui' WHERE journal IN ('CP', 'CMD');

CREATE TABLE IF NOT EXISTS soldes_ouverture_centre (
    centre           text NOT NULL REFERENCES centres(code_centre),
    journal          text NOT NULL REFERENCES journaux(journal),
    solde_ouverture  numeric(14, 2) NOT NULL DEFAULT 0,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (centre, journal)
);

-- Demarre chaque centre a 0 pour CP et CMD : le comptable renseigne ensuite
-- l'encaisse reelle de chacun depuis Referentiel > Soldes d'ouverture,
-- exactement comme il l'aurait fait pour le solde global avant cette
-- migration. ON CONFLICT DO NOTHING rend cette migration rejouable sans
-- ecraser un solde deja renseigne si elle est executee une seconde fois par
-- erreur.
INSERT INTO soldes_ouverture_centre (centre, journal, solde_ouverture)
SELECT c.code_centre, j.journal, 0.0
FROM centres c
CROSS JOIN (SELECT journal FROM journaux WHERE journal IN ('CP', 'CMD')) j
ON CONFLICT (centre, journal) DO NOTHING;

DROP TRIGGER IF EXISTS trg_rev_soldes_ouverture_centre ON soldes_ouverture_centre;
CREATE TRIGGER trg_rev_soldes_ouverture_centre AFTER INSERT OR UPDATE OR DELETE
    ON soldes_ouverture_centre FOR EACH STATEMENT EXECUTE FUNCTION bump_revision();

-- --- 2. nouvelle banque CBI, ancienne BDU-BF retiree mais intacte ----------

-- Nouveau compte de contrepartie, distinct du compte historique 521100
-- (BDU-BF) : les deux comptes cohabitent, l'ancien continue de porter
-- l'historique BDU-BF tel qu'exporte vers Sage, le nouveau ne porte que les
-- mouvements CBI a venir.
INSERT INTO comptes (compte, intitule, nature, tiers_obligatoire, depense_courante)
VALUES ('521200', 'Banques (CBI)', 'tresorerie', 'non', 'non')
ON CONFLICT (compte) DO NOTHING;

-- Le nouveau journal : code stable "Banque" (independant du nom de
-- l'etablissement, qui ne vit que dans intitule/prefixe_piece - voir le
-- commentaire de sql/schema.sql). Solde d'ouverture a 0, a renseigner par le
-- comptable des que le releve initial du compte CBI est connu.
INSERT INTO journaux (journal, intitule, compte_contrepartie, type, prefixe_piece,
                       solde_ouverture, caisse_physique, actif)
VALUES ('Banque', 'CBI', '521200', 'tresorerie', 'CBI', 0.0, 'non', 'oui')
ON CONFLICT (journal) DO NOTHING;

-- L'ancien journal reste en base avec tout son historique (ecritures,
-- exports Sage passes) : seul actif passe a 'non', ce qui le retire des
-- listes de creation de nouvelles pieces (Saisie, "Ecriture libre") sans
-- rien retirer des ecrans de consultation (Brouillard, Export), qui doivent
-- pouvoir continuer a le filtrer et l'exporter au besoin.
UPDATE journaux SET actif = 'non' WHERE journal = 'BDU-BF';
