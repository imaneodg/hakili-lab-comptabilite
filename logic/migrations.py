# ---------------------------------------------------------------------------
# Lanceur de migrations - joue au demarrage de app.py (et peut etre appele
# depuis un shell) les fichiers de sql/migrations/ non encore inscrits dans
# schema_migrations, chacun dans sa propre transaction.
#
# Ajoute le 22/09/2026 (M4 de l'audit du 18/09) : la panne du 15/09/2026
# venait de quatre migrations jamais jouees sur la production. Le correctif
# du 15/09 avait cree la table schema_migrations et y avait inscrit les
# versions rattrapees - mais aucune ligne de code ne la relisait depuis. Le
# jour ou une nouvelle migration serait ecrite et le code deploye sans elle,
# l'application aurait replante exactement pareil, avec le meme message
# Postgres illisible pour une caissiere ("relation ... does not exist").
#
# Principe : si une migration echoue, l'application REFUSE DE DEMARRER, avec
# un message qui nomme le fichier fautif. C'est volontairement plus strict
# qu'un simple avertissement dans le journal : un ecran d'erreur au demarrage,
# vu par la personne qui vient de deployer, vaut infiniment mieux qu'une
# panne decouverte plus tard par un utilisateur qui n'y peut rien.
# ---------------------------------------------------------------------------

import logging
import os
from pathlib import Path

import psycopg2

logger = logging.getLogger("hakili.migrations")

_DOSSIER_MIGRATIONS = Path(__file__).resolve().parent.parent / "sql" / "migrations"


def appliquer(dsn=None):
    """Joue les migrations manquantes. Idempotent : sans nouveau fichier dans
    sql/migrations/, ne fait rien d'autre que creer schema_migrations si elle
    n'existe pas encore (cas d'une base tres ancienne, jamais migree)."""
    dsn = dsn or os.environ.get("DATABASE_URL")
    if not dsn:
        # Pas de base configuree (ex. import d'un module en environnement de
        # test qui ne se connecte jamais) : rien a faire, ce n'est pas une
        # erreur de migrations.
        return

    fichiers = sorted(_DOSSIER_MIGRATIONS.glob("*.sql")) if _DOSSIER_MIGRATIONS.is_dir() else []

    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        conn.commit()

        if not fichiers:
            return

        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            deja_jouees = {r[0] for r in cur.fetchall()}

        for chemin in fichiers:
            version = chemin.name
            if version in deja_jouees:
                continue
            sql = chemin.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
                conn.commit()
                logger.info("Migration appliquee : %s", version)
            except Exception as e:
                conn.rollback()
                raise RuntimeError(
                    f"Migration '{version}' en echec, l'application ne demarre pas. "
                    f"Corriger ce fichier (ou l'etat de la base) avant de redeployer. "
                    f"Erreur Postgres : {e}"
                ) from e
    finally:
        conn.close()
