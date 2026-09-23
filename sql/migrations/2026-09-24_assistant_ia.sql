-- ---------------------------------------------------------------------------
-- Assistant IA - reconstruction du 24/09/2026
--
-- 1. centres_alias      : les facons dont les gens ecrivent vraiment un centre
--                         ("saab", "tampuy", "pisi"...). Completable depuis la
--                         base sans toucher au code.
-- 2. categories_charge  : le rattachement des comptes de charge (et des
--                         reglements passes par 401000) a une categorie de
--                         gestion. Remplace les constantes Python de
--                         logic/analyse.py pour l'assistant.
-- 3. journal_assistant  : trace de chaque question posee (qui, quoi, quels
--                         outils, combien de temps, combien de jetons).
-- 4. v_lignes           : vue de lecture enrichie, seule table interrogeable
--                         par l'outil requete_sql de l'assistant.
--
-- Tout est idempotent (IF NOT EXISTS / ON CONFLICT / CREATE OR REPLACE).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS centres_alias (
    alias        text PRIMARY KEY,
    code_centre  text NOT NULL REFERENCES centres(code_centre) ON DELETE CASCADE
);

-- Seuls les alias des centres existants sont inseres (jointure sur centres) :
-- une base qui n'aurait pas encore Nagrin ne plante pas.
INSERT INTO centres_alias (alias, code_centre)
SELECT v.alias, v.code
FROM (VALUES
    ('saab', 'SAA'), ('saba', 'SAA'), ('sabaa', 'SAA'), ('saaaba', 'SAA'), ('sab', 'SAA'),
    ('tampuy', 'TAM'), ('tanpouy', 'TAM'), ('tampui', 'TAM'), ('tampoui', 'TAM'), ('tamp', 'TAM'),
    ('pisi', 'PIS'), ('pisy', 'PIS'), ('pissi', 'PIS'), ('pissy ouaga', 'PIS'),
    ('siyao', 'SIA'), ('siao ouaga', 'SIA'),
    ('nagreen', 'NAG'), ('nagrine', 'NAG'), ('nagri', 'NAG'),
    ('siege', 'SIE'), ('bureau', 'SIE'), ('direction', 'SIE'), ('administration', 'SIE')
) AS v(alias, code)
JOIN centres c ON c.code_centre = v.code
ON CONFLICT (alias) DO NOTHING;


-- groupe : 'masse_salariale' et 'charges_fixes' alimentent les indicateurs du
-- meme nom ; 'courante' et 'autre' ne servent qu'au regroupement.
-- comptes : numeros (ou prefixes) SYSCOHADA ; le prefixe le plus long gagne.
-- motifs  : mots cherches dans le libelle d'un reglement passe directement par
--           le collectif fournisseur 401000 (cas courant a Hakili Lab pour les
--           vacations et les loyers). L'ordre compte : la plus petite valeur
--           de "ordre" est testee en premier.
CREATE TABLE IF NOT EXISTS categories_charge (
    categorie   text PRIMARY KEY,
    libelle     text NOT NULL,
    groupe      text NOT NULL DEFAULT 'courante'
                CHECK (groupe IN ('masse_salariale', 'charges_fixes', 'courante', 'autre')),
    comptes     text[] NOT NULL DEFAULT '{}',
    motifs      text[] NOT NULL DEFAULT '{}',
    ordre       integer NOT NULL DEFAULT 100
);

INSERT INTO categories_charge (categorie, libelle, groupe, comptes, motifs, ordre) VALUES
    ('vacations',   'Vacations et honoraires',         'masse_salariale', '{632710}',
        '{VACATION,HONORAIRE}', 10),
    ('salaires',    'Salaires et remunerations',       'masse_salariale', '{422000,661,662,663,664}',
        '{SALAIRE,REMUNERATION}', 20),
    ('loyer',       'Loyer',                           'charges_fixes',   '{622200}',
        '{LOYER,BAIL}', 30),
    ('eau',         'Eau (ONEA)',                      'charges_fixes',   '{605100}',
        '{ONEA}', 40),
    ('electricite', 'Electricite (SONABEL, Cash Power)', 'charges_fixes', '{605200}',
        '{SONABEL,CASH POWER}', 50),
    ('gardiennage', 'Gardiennage',                     'charges_fixes',   '{632720}',
        '{GARDIEN}', 60),
    ('internet_telephone', 'Internet et telephone',    'courante',        '{628810,628820}',
        '{INTERNET,CANAL,CREDIT COMMUNICATION}', 70),
    ('nettoyage',   'Entretien et nettoyage',          'courante',        '{624330}',
        '{NETTOYAGE}', 80),
    ('fournitures', 'Fournitures de bureau et pedagogiques', 'courante',  '{605500}',
        '{FOURNITURE}', 90),
    ('carburant',   'Carburant',                       'courante',        '{605300}',
        '{CARBURANT}', 100),
    ('impressions', 'Impressions et photocopies',      'courante',        '{632800}',
        '{IMPRESSION,PHOTOCOPIE}', 110),
    ('maintenance', 'Maintenance et petits equipements', 'courante',      '{624300,605600}',
        '{MAINTENANCE,REPARATION}', 120),
    ('eau_minerale', 'Eau minerale et reception',      'courante',        '{605101,638300}',
        '{}', 130),
    ('frais_bancaires', 'Frais bancaires et mobile money', 'courante',    '{631700}',
        '{}', 140)
ON CONFLICT (categorie) DO NOTHING;


CREATE TABLE IF NOT EXISTS journal_assistant (
    id             bigserial PRIMARY KEY,
    horodatage     timestamptz NOT NULL DEFAULT now(),
    utilisateur    text NOT NULL DEFAULT '',
    centre         text NOT NULL DEFAULT '',
    question       text NOT NULL DEFAULT '',
    outils         jsonb NOT NULL DEFAULT '[]'::jsonb,
    reponse        text NOT NULL DEFAULT '',
    duree_ms       integer,
    jetons_entree  integer,
    jetons_sortie  integer,
    erreur         text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_journal_assistant_date ON journal_assistant(horodatage);


-- Une ligne d'ecriture avec tout ce qu'il faut pour la lire sans jointure.
-- est_transfert : la piece touche deux comptes de tresorerie distincts
-- (caisse, banque, 585000) - meme critere que logic.analyse.pieces_transfert_interne.
CREATE OR REPLACE VIEW v_lignes AS
WITH tresorerie AS (
    SELECT compte FROM comptes WHERE nature = 'tresorerie'
), pieces AS (
    SELECT e.id_piece,
           count(DISTINCT e.compte) FILTER (WHERE e.compte IN (SELECT compte FROM tresorerie)) AS nb_tresorerie
    FROM ecritures e
    GROUP BY e.id_piece
)
SELECT e.id_piece,
       e.num_definitif,
       e.date_piece,
       to_char(e.date_piece, 'YYYYMM') AS mois,
       CASE WHEN extract(month FROM e.date_piece) >= 9
            THEN extract(year FROM e.date_piece)::int || '-' || (extract(year FROM e.date_piece)::int + 1)
            ELSE (extract(year FROM e.date_piece)::int - 1) || '-' || extract(year FROM e.date_piece)::int
       END AS annee_scolaire,
       e.centre,
       c.intitule AS centre_nom,
       e.journal,
       e.compte,
       co.intitule AS compte_intitule,
       co.nature AS compte_nature,
       left(e.compte, 1) AS classe,
       e.code_tiers,
       t.intitule AS tiers_nom,
       t.type AS tiers_type,
       e.libelle,
       e.debit,
       e.credit,
       e.statut,
       e.modele,
       (p.nb_tresorerie >= 2
        OR e.modele IN ('approvisionnement', 'versement_banque', 'transfert_interne')) AS est_transfert
FROM ecritures e
JOIN centres c ON c.code_centre = e.centre
LEFT JOIN comptes co ON co.compte = e.compte
LEFT JOIN tiers t ON t.code_tiers = e.code_tiers AND e.code_tiers <> ''
JOIN pieces p ON p.id_piece = e.id_piece;
