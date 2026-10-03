-- ---------------------------------------------------------------------------
-- Tableau de bord (03/10/2026, suite) : equipement et camp de vacances.
--
-- 1. Achats d'equipement payes par le collectif fournisseur (ex.
--    « INSTALLATION VENTILATION », 146 000 F a Saaba en mars 2026) : mis a
--    part, hors exploitation, comme l'assistant le fait deja pour les comptes
--    de classe 2. Un achat de materiel n'est pas une depense courante.
-- 2. Camp de vacances : reconnu uniquement au libelle, ligne masquee quand
--    le centre n'en a pas.
--
-- Fichier separe pour qu'une base ou la migration precedente est deja jouee
-- recoive aussi ces regles. Idempotent (ON CONFLICT / UPDATE).
-- ---------------------------------------------------------------------------

-- Equipement : reconnu au libelle, avant les autres regles du 401 et du 6.
INSERT INTO classement_comptes (prefixe, motifs, modele, rubrique, ordre) VALUES
    ('401', '{INSTALLATION,VENTILAT,CLIMATIS,ACHAT ORDINATEUR,ACHAT IMPRIMANTE,MOBILIER}', '',
        'equipement', 5),
    ('6',   '{VENTILAT,CLIMATIS}', '', 'equipement', 5)
ON CONFLICT (prefixe, motifs, modele) DO NOTHING;

-- Camp de vacances : reconnu uniquement au libelle (CAMP, FRAIS CV...),
-- jamais au mois. Ligne affichee seulement si le centre en a.
UPDATE rubriques_tableau SET toujours_affichee = false WHERE rubrique = 'camp';
