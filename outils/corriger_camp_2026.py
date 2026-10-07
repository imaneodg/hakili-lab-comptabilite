"""
corriger_camp_2026.py - remet la marque du camp de vacances sur les pieces
deja importees des brouillards 2026 (07/10/2026).

Pourquoi : a l'import, la colonne LIBELLE HARMONISE avait ramene les frais du
camp a la forme des cours d'appui ("AVANCE FRAIS CV KABRE CHARLES/S1" est
devenu "AVANCE FRAIS CA KABRE CHARLES ELIEL"). Le tableau de bord comptait
donc le camp dans les cours d'appui. Le libelle d'origine des brouillards,
lui, le dit : ce script le relit et corrige le libelle des pieces en base,
avec la meme regle que l'import (import_historique.libelle_camp).

Ce qui est corrige : seulement les pieces HIST-... dont le libelle est encore
celui de l'import. Une piece modifiee depuis est laissee telle quelle et
signalee. Les montants, comptes et tiers ne sont jamais touches.

Ce qui est seulement signale :
  - une sortie d'argent passee sur le compte eleves (411) avec un libelle du
    camp : c'est un paiement (probablement des vacations du camp) mal impute,
    a reclasser a la main ;
  - une depense du camp dont la nature n'est pas lisible (ni VACATION, ni
    FOURNITURE...) : elle reste en "autres charges", a preciser.

Usage (depuis la racine du projet) :
    python outils/corriger_camp_2026.py              # simulation, n'ecrit rien
    python outils/corriger_camp_2026.py --appliquer  # corrige pour de vrai

Rejouable : une piece deja corrigee n'est plus proposee.
"""
import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(RACINE / ".env")    # avant logic.donnees (pool de connexions)

import import_historique as ih  # noqa: E402
import logic.donnees as dl      # noqa: E402
import logic.modeles as md      # noqa: E402

MOTS_NATURE = ("VACATION", "HONORAIRE", "SALAIRE", "REMUNERATION", "CORRECTION", "GARDIEN",
               "FOURNITURE", "IMPRESSION", "PHOTOCOPIE", "LOYER", "INTERNET")


def _a_corriger():
    """(id_piece, ancien libelle, nouveau libelle, ligne source) des pieces a
    corriger, et la liste des cas seulement signales."""
    corrections, signales = [], []
    for conf in ih.FICHIERS:
        chemin = RACINE / conf["chemin"]
        if not chemin.exists():
            signales.append(f"Fichier absent, ignore : {conf['chemin']}")
            continue
        for l in ih.lire_lignes(chemin):
            if not ih.CAMP_DANS_ORIGINAL.search(l["original"]):
                continue
            idp = ih.id_piece_historique(conf["centre"], conf["journal"], l)
            montant = l["debit"] or l["credit"]
            if not montant:          # ligne sans montant : aucune ecriture a corriger
                continue
            ou = f"{conf['centre']} {conf['journal']} {l['date_piece']:%d/%m/%Y} {dl.fcfa(montant)} F"
            if l["compte"].startswith("411") and not l["debit"] > 0:
                signales.append(f"{ou} - sortie sur le compte eleves : « {l['original']} » "
                                "(paiement du camp mal impute, a reclasser)")
                continue
            ancien = md.ligne("", l["libelle_fichier"])["libelle"]
            nouveau = md.ligne("", l["libelle"])["libelle"]
            if not l["compte"].startswith("411") and not any(m in nouveau for m in MOTS_NATURE):
                signales.append(f"{ou} - nature de la depense a preciser : « {l['original']} » "
                                "(comptee en autres charges)")
            if ancien != nouveau:
                corrections.append((idp, ancien, nouveau, ou))
    return corrections, signales


def corriger(appliquer=False):
    corrections, signales = _a_corriger()
    faites, deja, modifiees, absentes, exportees = [], 0, [], 0, 0
    with dl._connexion() as c, c.cursor() as cur:
        for idp, ancien, nouveau, ou in corrections:
            cur.execute("SELECT id_ligne, libelle, statut FROM ecritures WHERE id_piece = %s", (idp,))
            lignes = cur.fetchall()
            if not lignes:
                absentes += 1
                continue
            libelles = {r[1] for r in lignes}
            if libelles == {nouveau}:
                deja += 1
                continue
            if ancien not in libelles:
                modifiees.append(f"{ou} - libelle modifie depuis l'import, laisse tel quel")
                continue
            exportees += any(r[2] == "exportee" for r in lignes)
            faites.append(f"{ou} : {ancien}  ->  {nouveau}")
            if appliquer:
                cur.execute("UPDATE ecritures SET libelle = %s WHERE id_piece = %s AND libelle = %s",
                            (nouveau, idp, ancien))
        if not appliquer:
            c.rollback()

    titre = "CORRECTION APPLIQUEE" if appliquer else "SIMULATION (rien n'a ete ecrit)"
    print(f"\n=== {titre} ===")
    print(f"Pieces {'corrigees' if appliquer else 'a corriger'} : {len(faites)}")
    for x in faites:
        print("  " + x)
    if exportees:
        print(f"Dont {exportees} deja exportee(s) vers Sage : le libelle y reste l'ancien "
              "(sans effet sur les montants).")
    print(f"Deja corrigees : {deja}")
    if absentes:
        print(f"Absentes de la base (brouillard non importe) : {absentes}")
    for titre_liste, liste in (("Laissees telles quelles", modifiees), ("A verifier a la main", signales)):
        if liste:
            print(f"\n{titre_liste} : {len(liste)}")
            for x in liste:
                print("  " + x)
    if not appliquer and faites:
        print("\nPour corriger : python outils/corriger_camp_2026.py --appliquer")
    return faites


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--appliquer", action="store_true", help="corrige pour de vrai (sinon simulation)")
    args = parser.parse_args()
    try:
        corriger(appliquer=args.appliquer)
    except Exception as e:
        print(f"Correction interrompue : {e}", file=sys.stderr)
        sys.exit(1)
