-- ---------------------------------------------------------------------------
-- DIAGNOSTIC (lecture seule) - etat du schema de la base de production
--
-- N'ecrit rien, ne modifie rien. A lancer AVANT le rattrapage pour voir
-- exactement ce qui manque :
--   psql "$DATABASE_URL" -f sql/diagnostic_production.sql
--
-- Chaque ligne "MANQUANT" correspond a une migration non appliquee.
-- ---------------------------------------------------------------------------

\echo '=== TABLES ==='
SELECT 'suppressions_ecritures' AS objet,
       CASE WHEN to_regclass('public.suppressions_ecritures') IS NULL
            THEN 'MANQUANT (migration 2026-09-05)' ELSE 'ok' END AS etat
UNION ALL
SELECT 'soldes_ouverture_centre',
       CASE WHEN to_regclass('public.soldes_ouverture_centre') IS NULL
            THEN 'MANQUANT (migration 2026-09-11)' ELSE 'ok' END
UNION ALL
SELECT 'compteurs',
       CASE WHEN to_regclass('public.compteurs') IS NULL
            THEN 'MANQUANT (schema de base)' ELSE 'ok' END
UNION ALL
SELECT 'revision',
       CASE WHEN to_regclass('public.revision') IS NULL
            THEN 'MANQUANT (schema de base)' ELSE 'ok' END
ORDER BY 1;

\echo ''
\echo '=== COLONNES ==='
SELECT objet, etat FROM (
    SELECT 'utilisateurs.tentatives_echouees' AS objet,
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'utilisateurs' AND column_name = 'tentatives_echouees')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-05)' END AS etat
    UNION ALL
    SELECT 'utilisateurs.verrouille_jusqu_a',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'utilisateurs' AND column_name = 'verrouille_jusqu_a')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-05)' END
    UNION ALL
    SELECT 'journaux.caisse_physique',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'journaux' AND column_name = 'caisse_physique')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-11)' END
    UNION ALL
    SELECT 'journaux.actif',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'journaux' AND column_name = 'actif')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-11)' END
    UNION ALL
    SELECT 'ecritures.reference_transfert',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'ecritures' AND column_name = 'reference_transfert')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-12)' END
    UNION ALL
    SELECT 'ecritures.centre_contrepartie',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'ecritures' AND column_name = 'centre_contrepartie')
                THEN 'ok' ELSE 'MANQUANT (migration 2026-09-12)' END
    UNION ALL
    SELECT 'centres.code_acces (doit avoir DISPARU)',
           CASE WHEN EXISTS (SELECT 1 FROM information_schema.columns
                             WHERE table_name = 'centres' AND column_name = 'code_acces')
                THEN 'ENCORE PRESENT (migration 2026-09-10)' ELSE 'ok' END
) t ORDER BY 1;

\echo ''
\echo '=== COMPTES ATTENDUS PAR LE CODE ==='
SELECT '585000 (virements de fonds)' AS objet,
       CASE WHEN EXISTS (SELECT 1 FROM comptes WHERE compte = '585000')
            THEN 'ok' ELSE 'MANQUANT (migration 2026-09-12)' END AS etat
UNION ALL
SELECT '471000 (compte d''attente)',
       CASE WHEN EXISTS (SELECT 1 FROM comptes WHERE compte = '471000')
            THEN 'ok' ELSE 'MANQUANT (seed)' END;

\echo ''
\echo '=== VOLUMETRIE (a noter avant toute intervention) ==='
SELECT (SELECT count(*) FROM ecritures)     AS lignes_ecritures,
       (SELECT count(DISTINCT id_piece) FROM ecritures) AS pieces,
       (SELECT count(*) FROM tiers)          AS tiers,
       (SELECT count(*) FROM comptes)        AS comptes,
       (SELECT count(*) FROM utilisateurs)   AS utilisateurs;
