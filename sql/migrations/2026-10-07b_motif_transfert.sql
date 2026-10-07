-- ---------------------------------------------------------------------------
-- Motif des transferts entre centres (07/10/2026).
--
-- Le formulaire « Transfert entre centres » demande desormais le motif
-- (contribution, pret, remboursement d'un pret, impots payes par le siege),
-- garde dans valeurs_json. flux_tableau_bord() le lit AVANT les regles de
-- libelle : un pret libelle « APPROV SIAO » n'est plus compte comme une
-- contribution (charge d'exploitation du centre).
--
-- Un transfert saisi avant cette date n'a pas de motif : la fonction renvoie
-- NULL et les regles du libelle s'appliquent comme avant. Rien n'est
-- reecrit dans les ecritures.
--
-- Fichier separe de 2026-10-07_camp_de_vacances.sql, deja joue sur les
-- bases : une migration jouee ne se modifie jamais. Idempotent.
-- ---------------------------------------------------------------------------

-- Rubrique du tableau de bord de chaque motif. Les cles sont celles de
-- logic.modeles.MOTIFS_TRANSFERT (un test verifie qu'aucune ne manque).
CREATE OR REPLACE FUNCTION tb_rubrique_motif_transfert(p_motif text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE p_motif
        WHEN 'contribution'  THEN 'contribution'
        WHEN 'pret'          THEN 'prets_siege'
        WHEN 'remboursement' THEN 'prets_siege'
        WHEN 'impot'         THEN 'impots'
    END
$$;


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
           coalesce(CASE WHEN l.modele = 'transfert_interne' AND l.compte LIKE '585%'
                         THEN tb_rubrique_motif_transfert(l.valeurs_json ->> 'motif') END,
                    r.rubrique, 'non_classe'),
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
                          WHERE tb_normaliser(l.libelle) || ' ' LIKE '%' || tb_normaliser(m) || '%'))
        ORDER BY cardinality(c.motifs) > 0 DESC, c.modele <> '' DESC,
                 length(c.prefixe) DESC, c.ordre
        LIMIT 1
    ) r ON true
    WHERE l.compte NOT IN (SELECT compte FROM tresorerie)
      AND l.credit <> l.debit
$$;
