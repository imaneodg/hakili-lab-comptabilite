-- ---------------------------------------------------------------------------
-- Camp de vacances (07/10/2026).
--
-- 1. Camp : le formulaire d'encaissement ecrit desormais FRAIS CV / AVANCE CV
--    / SOLDE CV quand la caissiere choisit « Camp de vacances », et les
--    depenses du camp portent le mot CAMP en tete de libelle. La regle du
--    camp cherche « CAMP » suivi d'un espace (ou en fin de libelle) : un
--    libelle « CAMPAGNE ... » n'est plus pris pour le camp.
--
-- 2. Le mot CAMP ne classe plus une depense du 401 en salaires. Le camp est
--    une activite, pas une nature de charge : un achat de fournitures pour
--    le camp reste une fourniture, une vacation du camp reste une vacation
--    (reconnue a VACATION, HONORAIRE, SALAIRE...).
--
-- 3. flux_tableau_bord() : le libelle est compare aux motifs avec un espace
--    ajoute a la fin, pour que « CAMP » en dernier mot soit reconnu par le
--    motif « CAMP ». Sans effet sur les autres motifs (une sous-chaine
--    trouvee le reste).
--
-- Idempotent.
-- ---------------------------------------------------------------------------

-- Remplacement par insertion puis suppression (et non UPDATE) : rejouer une
-- migration precedente qui reinsere l'ancienne regle ne bloque jamais celle-ci.
INSERT INTO classement_comptes (prefixe, motifs, modele, rubrique, ordre)
SELECT prefixe, '{"CAMP ","FRAIS CV","AVANCE CV","SOLDE CV"}', modele, rubrique, ordre
FROM classement_comptes
WHERE rubrique = 'camp' AND 'CAMP' = ANY(motifs)
ON CONFLICT (prefixe, motifs, modele) DO NOTHING;
DELETE FROM classement_comptes WHERE rubrique = 'camp' AND 'CAMP' = ANY(motifs);

INSERT INTO classement_comptes (prefixe, motifs, modele, rubrique, ordre)
SELECT prefixe, array_remove(motifs, 'CAMP'), modele, rubrique, ordre
FROM classement_comptes
WHERE rubrique = 'vacations' AND prefixe = '401' AND 'CAMP' = ANY(motifs)
ON CONFLICT (prefixe, motifs, modele) DO NOTHING;
DELETE FROM classement_comptes WHERE rubrique = 'vacations' AND prefixe = '401' AND 'CAMP' = ANY(motifs);


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
                          WHERE tb_normaliser(l.libelle) || ' ' LIKE '%' || tb_normaliser(m) || '%'))
        ORDER BY cardinality(c.motifs) > 0 DESC, c.modele <> '' DESC,
                 length(c.prefixe) DESC, c.ordre
        LIMIT 1
    ) r ON true
    WHERE l.compte NOT IN (SELECT compte FROM tresorerie)
      AND l.credit <> l.debit
$$;
