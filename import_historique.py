"""
import_historique.py — integre les brouillards Excel historiques dans Hakili_compta.

Toutes les lignes (VERT, ORANGE, ROUGE) suivent desormais le meme chemin :
import direct avec le compte et le tiers indiques dans le fichier Excel,
statut "validee", visibles tout de suite dans Export Sage.

Les lignes ROUGE ont ete corrigees a la main dans les fichiers Excel avant
cet import (compte et tiers definitifs deja renseignes) : elles n'ont donc
plus besoin de passer par le compte d'attente 471000 ni par le circuit de
correction. La distinction de couleur ne sert plus qu'a etre tracee dans
l'observation de la piece, pour garder un historique de ce qui a ete
verifie a la main.

Rejouable sans risque : chaque ligne source recoit un identifiant stable
(fichier + feuille + position), verifie en base avant toute insertion. Relancer
le script sur les memes fichiers ne duplique donc rien.

Usage :
    python import_historique.py                # importe pour de vrai
    python import_historique.py --dry-run       # simule, n'ecrit rien, affiche le resume
"""
import argparse
import sys
from datetime import date

import openpyxl
import pandas as pd
from dotenv import load_dotenv

load_dotenv()  # avant l'import de logic.donnees : c'est la que le pool de
                # connexions Postgres est cree, il a besoin de DATABASE_URL
                # (meme ordre que dans app.py).

import logic.donnees as dl
import logic.modeles as md

# --- correspondance fichier -> centre / journal -----------------------------
#
# Le nom de fichier ne porte pas le code_centre exact (3 lettres) utilise en
# base, seulement un nom lisible. Cette table est volontairement explicite et
# fermee : un fichier absent d'ici fait echouer l'import plutot que de
# deviner un centre au hasard. A completer si d'autres brouillards
# historiques doivent etre importes plus tard.
FICHIERS = [
    {"chemin": "BROUILLARD_CAISSE_PRINCIPALE_SAABA_2026.xlsx", "centre": "SAA", "journal": "CP"},
    {"chemin": "BROUILLARD_CMD_SAABA_2026.xlsx", "centre": "SAA", "journal": "CMD"},
    {"chemin": "BROUILLARD_TAMPOUY_CMD_2026.xlsx", "centre": "TAM", "journal": "CMD"},
    {"chemin": "BROUILLARD_TAMPOUY_CP_2026.xlsx", "centre": "TAM", "journal": "CP"},
]

UTILISATEUR_IMPORT = "import_historique"

# Confiances reconnues dans les fichiers Excel. Toutes les trois suivent
# desormais le meme traitement (voir importer_fichier) ; seule la mention
# gardee dans l'observation de la piece differe, pour garder une trace de
# ce qui a ete verifie/corrige a la main.
CONFIANCES_VALIDES = {"VERT", "ORANGE", "ROUGE"}


# --- lecture des fichiers Excel ---------------------------------------------
#
# Format fixe sur les 4 fichiers fournis : DATE, LIBELLES, DEBIT, CREDIT,
# SOLDE, LIBELLE HARMONISE, N° COMPTE, COMPTE TIERS, CONFIANCE,
# NOTE / A VERIFIER - en-tete a la ligne 3, donnees a partir de la ligne 4.
# Les lignes "SOLDE AU ..." (report d'ouverture) n'ont pas de date : elles
# sont ignorees, ce ne sont pas des ecritures.

def lire_lignes(chemin):
    wb = openpyxl.load_workbook(chemin, data_only=True)
    lignes = []
    for feuille in wb.sheetnames:
        ws = wb[feuille]
        for i, row in enumerate(ws.iter_rows(min_row=4, values_only=True), start=4):
            row = (row + (None,) * 10)[:10]
            date_, lib, deb, cred, _solde, lib_h, compte, tiers, conf, note = row
            if date_ is None:
                continue
            lignes.append({
                "feuille": feuille, "position": i,
                "date_piece": date_.date() if hasattr(date_, "date") else date_,
                "libelle": str(lib_h or lib or "").strip().upper(),
                "debit": float(deb or 0), "credit": float(cred or 0),
                "compte": str(compte).strip() if compte else "",
                "tiers": str(tiers).strip() if tiers else "",
                "confiance": str(conf or "").strip().upper(),
                "note": str(note or "").strip(),
            })
    return lignes


# --- import des lignes -------------------------------------------------------

def id_piece_historique(centre, journal, ligne):
    """Identifiant stable : deux executions sur le meme fichier donnent le
    meme id pour la meme ligne source. C'est ce qui rend l'import
    idempotent, verifie par deja_importee() avant chaque insertion."""
    feuille = ligne["feuille"].strip().replace(" ", "_")
    return f"HIST-{centre}-{journal}-{feuille}-{ligne['position']}"


def deja_importee(cur, id_piece):
    cur.execute("SELECT 1 FROM ecritures WHERE id_piece = %s LIMIT 1", (id_piece,))
    return cur.fetchone() is not None


def construire_lignes_piece(ligne, cc):
    """Deux lignes d'ecriture, logique cahier de caisse classique : un
    montant au DEBIT du brouillard est une entree de caisse (compte caisse
    debite, contrepartie creditee) ; au CREDIT, une sortie (l'inverse).

    Le compte et le tiers pris ici sont toujours ceux du fichier Excel,
    quelle que soit la couleur d'origine de la ligne (VERT, ORANGE ou
    ROUGE desormais corrigee) : il n'y a plus de compte de remplacement.

    "APPROV CMD" (178 lignes, 89 par fichier CP et CMD) utilise le compte
    585000 comme contrepartie : c'est le compte SYSCOHADA 585 "Virements de
    fonds", le compte de passage standard pour un virement entre deux
    caisses tenues sur des journaux distincts (cf. AUDCIF, commentaire du
    compte 58). Il est deja utilise ainsi par le modele "Approvisionnement
    de la CMD" de l'application (modeles.py). Aucune correction n'est donc
    necessaire ici : chaque ligne, prise telle quelle, mouvemente sa propre
    caisse (cc du journal) contre ce compte de passage - jamais deux fois le
    meme compte, jamais de piece blanche."""
    if ligne["debit"] > 0:
        m = ligne["debit"]
        return [md.ligne(cc, ligne["libelle"], debit=m),
                md.ligne(ligne["compte"], ligne["libelle"], credit=m, code_tiers=ligne["tiers"])]
    m = ligne["credit"]
    return [md.ligne(cc, ligne["libelle"], credit=m),
            md.ligne(ligne["compte"], ligne["libelle"], debit=m, code_tiers=ligne["tiers"])]


def inserer_piece(cur, id_piece, centre, journal, date_piece, lignes, observation):
    """Insertion brute, en reprenant exactement le schema utilise par
    enregistrer_operation (donnees.py) : numero provisoire tire du meme
    compteur atomique que les saisies normales, num_definitif laisse vide
    (valider_pieces s'en charge juste apres, pour toutes les pieces
    desormais - il n'y a plus de branche rejeter_pieces)."""
    mois = dl.mois_de(date_piece)
    n = dl._prochain_numero(cur, f"prov:{centre}:{mois}")
    num_provisoire = f"{centre}-{mois[2:6]}-{n:03d}"
    for i, ligne_ecr in enumerate(lignes):
        cur.execute(
            "INSERT INTO ecritures (id_ligne, id_piece, id_lien, num_provisoire, num_definitif, "
            "journal, centre, date_piece, compte, code_tiers, libelle, debit, credit, "
            "modele, saisi_par, saisi_le, statut, observation, valeurs_json) VALUES "
            "(%s,%s,'',%s,'',%s,%s,%s,%s,%s,%s,%s,%s,'libre',%s,now(),'saisie',%s,NULL)",
            (f"{id_piece}-{i + 1}", id_piece, num_provisoire, journal, centre, str(date_piece),
             ligne_ecr["compte"], ligne_ecr["code_tiers"], ligne_ecr["libelle"],
             ligne_ecr["debit"], ligne_ecr["credit"], UTILISATEUR_IMPORT, observation))


# --- orchestration -----------------------------------------------------------

def importer_fichier(cur, cc_par_journal, fichier_conf, dry_run, resultats):
    centre, journal = fichier_conf["centre"], fichier_conf["journal"]
    cc = cc_par_journal.get(journal)
    if not cc:
        raise ValueError(f"Journal {journal} introuvable dans la table journaux (compte_contrepartie manquant).")
    for ligne in lire_lignes(fichier_conf["chemin"]):
        idp = id_piece_historique(centre, journal, ligne)
        if deja_importee(cur, idp):
            resultats["deja_importees"] += 1
            continue
        if ligne["confiance"] not in CONFIANCES_VALIDES:
            resultats["confiance_inconnue"] += 1
            continue
        if not ligne["compte"]:
            # Une ligne rouge non corrigee (compte encore vide) ne doit pas
            # passer en "validee" sans compte : on la signale plutot que de
            # l'importer a moitie ou de deviner un compte a sa place.
            resultats["compte_manquant"].append(idp)
            continue

        note_source = f" - {ligne['note']}" if ligne["note"] else ""
        mention_couleur = {"VERT": "", "ORANGE": "", "ROUGE": " (ligne rouge corrigee manuellement)"}[ligne["confiance"]]
        observation = f"Import historique{mention_couleur}{note_source}"

        lignes_ecr = construire_lignes_piece(ligne, cc)
        resultats["montant"] += ligne["debit"] + ligne["credit"]
        resultats["a_valider"].append(idp)
        if not dry_run:
            inserer_piece(cur, idp, centre, journal, ligne["date_piece"], lignes_ecr, observation)


def importer(dry_run=False):
    resultats = {"a_valider": [], "compte_manquant": [], "deja_importees": 0,
                 "confiance_inconnue": 0, "montant": 0.0}
    journaux = dl._lire_df("SELECT journal, compte_contrepartie FROM journaux")
    cc_par_journal = dict(zip(journaux["journal"], journaux["compte_contrepartie"]))
    print(f"Comptes de contrepartie lus dans ta base : {cc_par_journal}")

    # En dry-run, inserer_piece() n'est jamais appelee (voir importer_fichier)
    # donc aucune ecriture SQL de modification n'a lieu dans ce bloc : la
    # transaction se termine sans rien avoir a annuler.
    with dl._connexion() as c, c.cursor() as cur:
        for fichier_conf in FICHIERS:
            importer_fichier(cur, cc_par_journal, fichier_conf, dry_run, resultats)

    if not dry_run and resultats["a_valider"]:
        dl.valider_pieces(resultats["a_valider"], UTILISATEUR_IMPORT)
    return resultats


def afficher_resume(resultats, dry_run):
    entete = "SIMULATION (rien n'a ete ecrit)" if dry_run else "IMPORT TERMINE"
    print(f"\n=== {entete} ===")
    print(f"Pieces validees : {len(resultats['a_valider'])}")
    print(f"Deja presentes en base (ignorees, script rejouable) : {resultats['deja_importees']}")
    if resultats["compte_manquant"]:
        print(f"ATTENTION - lignes ROUGE sans compte renseigne, ignorees : {len(resultats['compte_manquant'])}")
        print(f"  -> {', '.join(resultats['compte_manquant'][:10])}"
              + (" ..." if len(resultats["compte_manquant"]) > 10 else ""))
    if resultats["confiance_inconnue"]:
        print(f"ATTENTION - lignes ni VERT/ORANGE/ROUGE, ignorees : {resultats['confiance_inconnue']}")
    print(f"Montant total mouvemente : {dl.fcfa(resultats['montant'])} F")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="simule l'import sans rien ecrire en base")
    args = parser.parse_args()
    try:
        res = importer(dry_run=args.dry_run)
    except Exception as e:
        print(f"Import interrompu : {e}", file=sys.stderr)
        sys.exit(1)
    afficher_resume(res, args.dry_run)