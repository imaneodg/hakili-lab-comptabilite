-- ---------------------------------------------------------------------------
-- Tableau de bord direction (03/10/2026) : complement de la migration
-- 2026-10-02_tableau_bord.sql (rien n'y est retire).
--
-- 1. parametres_centre : cible de marge, cible de tresorerie (en mois de
--    charges) et mois du camp de vacances, modifiables par centre.
-- 2. flux_tableau_bord() : memes flux qu'avant, avec en plus la date, le
--    tiers, le libelle et le centre de contrepartie d'un transfert interne
--    (pour ne pas compter deux fois un flux entre deux centres choisis).
-- 3. soldes_fin_mois() : solde des caisses de chaque centre a la fin de
--    chaque mois de la periode (graphique de l'onglet Caisse).
--
-- Idempotent (IF NOT EXISTS / ON CONFLICT / DROP ... IF EXISTS).
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS parametres_centre (
    centre                 text PRIMARY KEY REFERENCES centres(code_centre),
    -- Marge visee, en part des encaissements (0,15 = 15 %).
    cible_marge            numeric(5, 4) NOT NULL DEFAULT 0.15
                           CHECK (cible_marge >= 0 AND cible_marge < 1),
    -- Argent a garder en caisse, en mois de charges d'exploitation.
    cible_tresorerie_mois  numeric(4, 1) NOT NULL DEFAULT 2
                           CHECK (cible_tresorerie_mois >= 0),
    -- Mois ou un frais d'eleve sans mois de cours cite est un frais de camp.
    mois_camp              integer[] NOT NULL DEFAULT '{6,7,8}',
    updated_at             timestamptz NOT NULL DEFAULT now()
);

INSERT INTO parametres_centre (centre)
SELECT code_centre FROM centres
ON CONFLICT (centre) DO NOTHING;


DROP FUNCTION IF EXISTS flux_tableau_bord(date, date, text[]);
CREATE FUNCTION flux_tableau_bord(p_debut date, p_fin date, p_centres text[])
RETURNS TABLE (centre text, mois text, id_piece text, statut text, compte text,
               rubrique text, sens text, montant numeric,
               date_piece date, code_tiers text, libelle text, contrepartie text)
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
           l.credit - l.debit,
           l.date_piece, l.code_tiers, l.libelle, l.centre_contrepartie
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


-- Solde des caisses physiques de chaque centre a la fin de chaque mois
-- (ou a p_fin pour le dernier mois). Meme regle que soldes_tableau_bord().
DROP FUNCTION IF EXISTS soldes_fin_mois(date, date, text[]);
CREATE FUNCTION soldes_fin_mois(p_debut date, p_fin date, p_centres text[])
RETURNS TABLE (centre text, mois text, solde numeric)
LANGUAGE sql STABLE AS $$
    WITH fins AS (
        SELECT least((date_trunc('month', m) + interval '1 month - 1 day')::date, p_fin) AS jour
        FROM generate_series(date_trunc('month', p_debut), p_fin, interval '1 month') m
    ), caisses AS (
        SELECT journal, compte_contrepartie AS compte FROM journaux
        WHERE type = 'tresorerie' AND actif = 'oui' AND caisse_physique = 'oui'
    )
    SELECT c.code_centre, to_char(f.jour, 'YYYY-MM'),
           coalesce((SELECT sum(s.solde_ouverture) FROM soldes_ouverture_centre s
                     WHERE s.centre = c.code_centre
                       AND s.journal IN (SELECT journal FROM caisses)), 0)
         + coalesce((SELECT sum(e.debit - e.credit) FROM ecritures e
                     WHERE e.centre = c.code_centre AND e.date_piece <= f.jour
                       AND e.compte IN (SELECT compte FROM caisses)), 0)
    FROM fins f CROSS JOIN centres c
    WHERE c.code_centre = ANY(p_centres)
$$;
