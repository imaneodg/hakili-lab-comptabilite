-- ---------------------------------------------------------------------------
-- Tableau de bord (02/10/2026) : classement des flux de caisse et de banque.
--
-- 1. rubriques_tableau : les lignes du tableau « Compte de résultat mensuel
--    en encaissements » et leur famille (exploitation / hors exploitation /
--    exclu), modifiable ici sans toucher au code.
-- 2. classement_comptes : rattache un compte (ou un prefixe de compte) a une
--    rubrique. Le prefixe le plus long gagne ; une regle avec motif (mot du
--    libelle) ou modele de saisie passe avant une regle sans condition.
-- 3. flux_tableau_bord() : les flux reels de tresorerie, classes ligne par
--    ligne. Seule source des bandeaux et du tableau.
-- 4. soldes_tableau_bord() : caisses par centre et banque a une date.
--
-- Idempotent (IF NOT EXISTS / ON CONFLICT / CREATE OR REPLACE).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rubriques_tableau (
    rubrique        text PRIMARY KEY,
    libelle         text NOT NULL,
    -- bloc : ou la ligne s'affiche. encaissement et charge = exploitation.
    -- Pour faire passer les impots en exploitation : bloc = 'charge'.
    bloc            text NOT NULL CHECK (bloc IN ('encaissement', 'charge',
                                                  'hors_exploitation', 'exclu')),
    -- Si renseignes, l'argent qui ENTRE sur cette rubrique a sa propre ligne
    -- (emprunt recu a cote du remboursement, contribution recue par le SIAO
    -- a cote de la contribution versee).
    libelle_entree  text,
    bloc_entree     text CHECK (bloc_entree IN ('encaissement', 'charge', 'hors_exploitation')),
    toujours_affichee boolean NOT NULL DEFAULT true,
    ordre           integer NOT NULL DEFAULT 100
);

INSERT INTO rubriques_tableau (rubrique, libelle, bloc, libelle_entree, bloc_entree, toujours_affichee, ordre) VALUES
    ('cours_appui',      'Cours d''appui',             'encaissement', NULL, NULL, true, 10),
    ('camp',             'Camp de vacances',           'encaissement', NULL, NULL, true, 20),
    ('frais_document',   'Frais de document',          'encaissement', NULL, NULL, true, 30),
    ('vacations',        'Vacations et salaires',      'charge', NULL, NULL, true, 110),
    ('contribution',     'Contribution au SIAO',       'charge',
        'Contributions reçues des centres', 'encaissement', true, 120),
    ('loyer',            'Loyer',                      'charge', NULL, NULL, true, 130),
    ('entretien',        'Produits d''entretien',      'charge', NULL, NULL, true, 140),
    ('eau_electricite',  'Électricité et eau',         'charge', NULL, NULL, true, 150),
    ('internet',         'Internet et communication',  'charge', NULL, NULL, true, 160),
    ('fournitures',      'Fournitures et impressions', 'charge', NULL, NULL, true, 170),
    ('autres_charges',   'Autres charges courantes',   'charge', NULL, NULL, true, 180),
    ('frais_financiers', 'Frais financiers',           'charge', NULL, NULL, true, 190),
    ('impots',           'Impôts et taxes',            'hors_exploitation', NULL, NULL, true, 210),
    ('emprunts',         'Remboursements d''emprunts', 'hors_exploitation',
        'Emprunts reçus', 'hors_exploitation', true, 220),
    ('prets_siege',      'Prêts entre centres versés', 'hors_exploitation',
        'Prêts entre centres reçus', 'hors_exploitation', true, 230),
    ('conseil',          'Dossiers de conseil',        'hors_exploitation', NULL, NULL, true, 240),
    ('equipement',       'Achats d''équipement',       'hors_exploitation', NULL, NULL, false, 250),
    ('avances_personnel','Avances au personnel',       'hors_exploitation',
        'Avances remboursées par le personnel', 'hors_exploitation', false, 260),
    ('attente',          'Sorties en attente de classement', 'charge',
        'Encaissements en attente de classement', 'encaissement', false, 900),
    ('non_classe',       'Sorties non classées',       'charge',
        'Encaissements non classés', 'encaissement', false, 910),
    ('transfert',        'Transferts entre caisses',   'exclu', NULL, NULL, false, 990)
ON CONFLICT (rubrique) DO NOTHING;

CREATE TABLE IF NOT EXISTS classement_comptes (
    id        serial PRIMARY KEY,
    prefixe   text NOT NULL,
    motifs    text[] NOT NULL DEFAULT '{}',   -- un seul mot trouve suffit
    modele    text NOT NULL DEFAULT '',        -- modele de saisie, '' = tous
    rubrique  text NOT NULL REFERENCES rubriques_tableau(rubrique),
    ordre     integer NOT NULL DEFAULT 100,    -- departage deux regles a motif
    UNIQUE (prefixe, motifs, modele)
);


-- Classement de depart, etabli le 02/10/2026 sur le plan comptable charge et
-- sur les brouillards 2026 de Saaba et Tampouy. Modifiable en base.
INSERT INTO classement_comptes (prefixe, motifs, modele, rubrique, ordre) VALUES
    -- encaissements d'exploitation
    ('411',    '{}',                     '', 'cours_appui',      100),
    ('411',    '{CAMP,FRAIS CV,AVANCE CV,SOLDE CV}', '', 'camp',  10),
    ('411',    '{DOCUMENT}',             '', 'frais_document',    20),
    ('411',    '{CONTRIBUTION}',         '', 'contribution',       5),
    ('706',    '{}',                     '', 'cours_appui',      100),
    ('706',    '{CAMP,FRAIS CV,AVANCE CV,SOLDE CV}', '', 'camp',  10),
    ('7078',   '{}',                     '', 'frais_document',   100),
    ('471',    '{}',                     '', 'attente',          100),
    -- charges d'exploitation
    ('632710', '{}',                     '', 'vacations',        100),
    ('632720', '{}',                     '', 'vacations',        100),
    ('66',     '{}',                     '', 'vacations',        100),
    ('422',    '{}',                     '', 'vacations',        100),
    ('43',     '{}',                     '', 'vacations',        100),
    ('401',    '{}',                     '', 'autres_charges',   100),
    ('401',    '{VACATION,HONORAIRE,SALAIRE,REMUNERATION,CORRECTION,GARDIEN,CAMP}', '', 'vacations', 10),
    ('401',    '{LOYER,BAIL}',           '', 'loyer',             20),
    ('401',    '{ONEA,SONABEL,CASH POWER,ELECTRICITE}', '', 'eau_electricite', 30),
    ('401',    '{NETTOYAGE,ENTRETIEN}',  '', 'entretien',         40),
    ('401',    '{INTERNET,CANAL,FIBRE,MEGA}', '', 'internet',     50),
    ('401',    '{IMPRESSION,PHOTOCOPIE,FOURNITURE}', '', 'fournitures', 60),
    ('622',    '{}',                     '', 'loyer',            100),
    ('605100', '{}',                     '', 'eau_electricite',  100),
    ('605200', '{}',                     '', 'eau_electricite',  100),
    ('624330', '{}',                     '', 'entretien',        100),
    ('628',    '{}',                     '', 'internet',         100),
    ('604',    '{}',                     '', 'fournitures',      100),
    ('6055',   '{}',                     '', 'fournitures',      100),
    ('6056',   '{}',                     '', 'fournitures',      100),
    ('632800', '{}',                     '', 'fournitures',      100),
    ('632800', '{VACATION,CORRECTION}',  '', 'vacations',         20),
    ('632800', '{PARKING}',              '', 'autres_charges',    30),
    ('631',    '{}',                     '', 'frais_financiers', 100),
    ('67',     '{}',                     '', 'frais_financiers', 100),
    ('6',      '{}',                     '', 'autres_charges',   100),
    -- hors exploitation
    ('6',      '{QUITTANCE,SOUMISSION,FAILLITE,INSD,NON ENGAGEMENT,CONSEIL}', '', 'conseil', 10),
    ('64',     '{}',                     '', 'impots',           100),
    ('44',     '{}',                     '', 'impots',           100),
    ('89',     '{}',                     '', 'impots',           100),
    ('16',     '{}',                     '', 'emprunts',         100),
    ('17',     '{}',                     '', 'emprunts',         100),
    ('27',     '{}',                     '', 'prets_siege',      100),
    ('2',      '{}',                     '', 'equipement',       100),
    ('421',    '{}',                     '', 'avances_personnel',100),
    ('4223',   '{}',                     '', 'avances_personnel',100),
    -- virements de fonds (585) : transferts exclus, sauf ce qui part au siege
    ('585',    '{}',                     '', 'transfert',        100),
    ('585',    '{}',      'transfert_interne', 'contribution',   100),
    ('585',    '{APPROV CMD}',           '', 'transfert',          5),
    ('585',    '{PRET}',                 '', 'prets_siege',       10),
    ('585',    '{IMPOT,TAXE,SPECIALE}',  '', 'impots',            20),
    ('585',    '{INSD,SOUMISSION,CONSEIL}', '', 'conseil',        30),
    ('585',    '{SIAO,SIEGE,CONTRIBUTION}', '', 'contribution',   40)
ON CONFLICT (prefixe, motifs, modele) DO NOTHING;


-- Libelle en majuscules sans accents, pour comparer aux motifs.
CREATE OR REPLACE FUNCTION tb_normaliser(t text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT upper(translate(coalesce(t, ''),
        'àâäáãéèêëíìîïóòôöõúùûüçÀÂÄÁÃÉÈÊËÍÌÎÏÓÒÔÖÕÚÙÛÜÇ',
        'aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC'))
$$;


-- Une ligne par ligne d'ecriture qui fait face a un mouvement de caisse ou de
-- banque. montant > 0 : argent entre ; < 0 : argent sorti. La somme des
-- montants d'une piece est egale au mouvement de tresorerie de la piece.
-- Les lignes de tresorerie entre elles (approvisionnement direct, versement
-- en banque) n'ont pas de contrepartie : elles ne produisent aucun flux.
DROP FUNCTION IF EXISTS flux_tableau_bord(date, date, text[]);
CREATE FUNCTION flux_tableau_bord(p_debut date, p_fin date, p_centres text[])
RETURNS TABLE (centre text, mois text, id_piece text, statut text, compte text,
               rubrique text, sens text, montant numeric)
LANGUAGE sql STABLE AS $$
    WITH tresorerie AS (
        SELECT DISTINCT compte_contrepartie AS compte FROM journaux
        WHERE type = 'tresorerie' AND compte_contrepartie IS NOT NULL
    ), lignes AS (
        SELECT e.* FROM ecritures e
        WHERE e.centre = ANY(p_centres) AND e.date_piece BETWEEN p_debut AND p_fin
    ), pieces AS (
        SELECT DISTINCT l.id_piece FROM lignes l JOIN tresorerie t ON t.compte = l.compte
    )
    SELECT l.centre, to_char(l.date_piece, 'YYYY-MM'), l.id_piece, l.statut, l.compte,
           coalesce(r.rubrique, 'non_classe'),
           CASE WHEN l.credit >= l.debit THEN 'entree' ELSE 'sortie' END,
           l.credit - l.debit
    FROM lignes l
    JOIN pieces p ON p.id_piece = l.id_piece
    LEFT JOIN LATERAL (
        SELECT c.rubrique FROM classement_comptes c
        WHERE l.compte LIKE c.prefixe || '%'
          AND (c.modele = '' OR c.modele = l.modele)
          AND (cardinality(c.motifs) = 0
               OR EXISTS (SELECT 1 FROM unnest(c.motifs) m
                          WHERE tb_normaliser(l.libelle) LIKE '%' || tb_normaliser(m) || '%'))
        ORDER BY cardinality(c.motifs) > 0 DESC, c.modele <> '' DESC,
                 length(c.prefixe) DESC, c.ordre
        LIMIT 1
    ) r ON true
    WHERE l.compte NOT IN (SELECT compte FROM tresorerie)
      AND l.credit <> l.debit
$$;


-- Solde de chaque caisse a une date : caisses physiques par centre (solde
-- d'ouverture du centre + mouvements), banque une seule fois (centre NULL).
-- Meme regle que logic.donnees.solde_caisse ; toutes les pieces comptent.
DROP FUNCTION IF EXISTS soldes_tableau_bord(date, text[]);
CREATE FUNCTION soldes_tableau_bord(p_fin date, p_centres text[])
RETURNS TABLE (centre text, journal text, intitule text, physique boolean, solde numeric)
LANGUAGE sql STABLE AS $$
    SELECT c.code_centre, j.journal, j.intitule, true,
           coalesce((SELECT s.solde_ouverture FROM soldes_ouverture_centre s
                     WHERE s.centre = c.code_centre AND s.journal = j.journal), 0)
         + coalesce((SELECT sum(e.debit - e.credit) FROM ecritures e
                     WHERE e.centre = c.code_centre AND e.compte = j.compte_contrepartie
                       AND e.date_piece <= p_fin), 0)
    FROM journaux j CROSS JOIN centres c
    WHERE j.type = 'tresorerie' AND j.actif = 'oui' AND j.caisse_physique = 'oui'
      AND c.code_centre = ANY(p_centres)
    UNION ALL
    SELECT NULL, j.journal, j.intitule, false,
           j.solde_ouverture
         + coalesce((SELECT sum(e.debit - e.credit) FROM ecritures e
                     WHERE e.compte = j.compte_contrepartie AND e.date_piece <= p_fin), 0)
    FROM journaux j
    WHERE j.type = 'tresorerie' AND j.actif = 'oui' AND j.caisse_physique = 'non'
$$;
