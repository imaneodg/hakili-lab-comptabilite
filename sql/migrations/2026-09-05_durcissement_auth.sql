-- ---------------------------------------------------------------------------
-- Migration : durcissement de l'authentification + audit des suppressions
--
-- A appliquer UNE SEULE FOIS sur Hakili_compta (la base deja en service),
-- avant de deployer le code corrige. sql/schema.sql a deja ete mis a jour
-- pour qu'une base neuve (ex. poste de developpement) recree directement le
-- bon schema ; ce fichier ne sert qu'a mettre a niveau une base existante.
--
-- Usage (depuis la racine du projet, avec les identifiants de Hakili_compta) :
--   psql "$DATABASE_URL" -f sql/migrations/2026-09-05_durcissement_auth.sql
-- ---------------------------------------------------------------------------

ALTER TABLE utilisateurs
    ADD COLUMN IF NOT EXISTS tentatives_echouees integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS verrouille_jusqu_a timestamptz;

CREATE TABLE IF NOT EXISTS suppressions_ecritures (
    id             serial PRIMARY KEY,
    id_piece       text NOT NULL,
    contenu        jsonb NOT NULL,
    supprime_par   text NOT NULL,
    supprime_le    timestamptz NOT NULL DEFAULT now()
);

-- Rien a faire pour les codes d'acces existants : ils restent lisibles tels
-- quels par verifier_code_acces() (qui reconnait un hash bcrypt de son
-- prefixe $2b$/$2a$/$2y$) et sont hashes automatiquement des le prochain
-- login reussi de chaque utilisateur. Aucune coupure de service, aucun
-- reset de code a organiser.
