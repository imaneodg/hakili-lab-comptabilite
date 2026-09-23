-- ---------------------------------------------------------------------------
-- Assistant IA : libelles des types de depense dans les mots du directeur
-- (accents, termes courants). Idempotent.
-- ---------------------------------------------------------------------------
UPDATE categories_charge SET libelle = v.libelle
FROM (VALUES
    ('vacations', 'Vacations des enseignants'),
    ('salaires', 'Salaires'),
    ('loyer', 'Loyer'),
    ('eau', 'Eau (ONEA)'),
    ('electricite', 'Électricité (SONABEL, Cash Power)'),
    ('gardiennage', 'Gardiennage'),
    ('internet_telephone', 'Internet et téléphone'),
    ('nettoyage', 'Entretien et nettoyage'),
    ('fournitures', 'Fournitures de bureau et pédagogiques'),
    ('carburant', 'Carburant'),
    ('impressions', 'Impressions et photocopies'),
    ('maintenance', 'Réparations et petit matériel'),
    ('eau_minerale', 'Eau à boire et réception'),
    ('frais_bancaires', 'Frais bancaires et mobile money')
) AS v(categorie, libelle)
WHERE categories_charge.categorie = v.categorie;
