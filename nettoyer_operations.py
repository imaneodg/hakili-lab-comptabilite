import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DSN = os.environ.get("DATABASE_URL")

if not DSN:
    raise RuntimeError("DATABASE_URL introuvable dans le fichier .env")


def compter(cur, table):
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    return cur.fetchone()[0]


conn = psycopg2.connect(DSN)

try:
    cur = conn.cursor()

    # Etat AVANT nettoyage
    ecritures_avant = compter(cur, "ecritures")
    suppressions_avant = compter(cur, "suppressions_ecritures")
    compteurs_avant = compter(cur, "compteurs")
    tiers_avant = compter(cur, "tiers")

    print()
    print("========== AVANT NETTOYAGE ==========")
    print(f"Ecritures              : {ecritures_avant}")
    print(f"Suppressions           : {suppressions_avant}")
    print(f"Compteurs              : {compteurs_avant}")
    print(f"Tiers                  : {tiers_avant}")
    print()

    print("ATTENTION : les opérations vont être supprimées.")
    confirmation = input("Tape OUI pour continuer : ")

    if confirmation.strip().upper() != "OUI":
        print("Nettoyage annulé.")
        conn.rollback()
        raise SystemExit

    # Supprimer les opérations
    cur.execute("DELETE FROM ecritures")

    # Supprimer également l'historique des suppressions
    cur.execute("DELETE FROM suppressions_ecritures")

    # Réinitialiser les numéros provisoires/définitifs
    cur.execute("DELETE FROM compteurs")

    conn.commit()

    # Etat APRES nettoyage
    ecritures_apres = compter(cur, "ecritures")
    suppressions_apres = compter(cur, "suppressions_ecritures")
    compteurs_apres = compter(cur, "compteurs")
    tiers_apres = compter(cur, "tiers")

    print()
    print("========== APRES NETTOYAGE ==========")
    print(f"Ecritures              : {ecritures_apres}")
    print(f"Suppressions           : {suppressions_apres}")
    print(f"Compteurs              : {compteurs_apres}")
    print(f"Tiers                  : {tiers_apres}")
    print()

    if tiers_apres != tiers_avant:
        raise RuntimeError(
            "ERREUR : le nombre de tiers a changé ! "
            "La transaction doit être vérifiée."
        )

    print("======================================")
    print("NETTOYAGE TERMINE AVEC SUCCES")
    print("======================================")
    print()
    print("Les écritures ont été supprimées.")
    print("Les tiers ont été conservés.")
    print("Le plan de comptes n'a pas été touché.")
    print()

except Exception as e:
    conn.rollback()
    print()
    print("ERREUR :", e)
    print("Aucune modification n'a été validée.")
    raise

finally:
    conn.close()