# ---------------------------------------------------------------------------
# verifier_donnees.py
#
# Importe les brouillards historiques dans une base de VERIFICATION, puis
# controle que toute la chaine d'analyse et les graphiques de l'assistant IA
# donnent des resultats justes sur ces donnees reelles.
#
# NE TOUCHE JAMAIS Hakili_compta. Le nom de la base est force ici, exactement
# comme le fait deja verifier.py : l'hote, le port, l'utilisateur et le mot de
# passe sont repris de DATABASE_URL (.env), mais le nom de la base est
# remplace par celui demande, et le script refuse de demarrer si ce nom
# retombe sur la base de production.
#
# Ne touche pas non plus a hakili_test : cette base-la est effacee et recreee
# par verifier.py a chaque execution, un import y serait perdu au prochain
# lancement des tests.
#
# Usage (a la racine du projet, environnement virtuel active) :
#
#     python verifier_donnees.py
#         Recree hakili_verif a partir de sql/schema.sql + sql/seed.sql,
#         importe les quatre brouillards Excel, puis affiche le controle
#         complet et ecrit les graphiques dans "Claude outputs/".
#
#     python verifier_donnees.py --controle-seul
#         Ne touche a rien : relit la base de verification telle qu'elle est
#         et refait le controle. A utiliser apres avoir saisi a la main dans
#         l'application.
#
#     python verifier_donnees.py --base autre_base
#         Meme chose sur une autre base de verification.
#
# Prerequis, une seule fois : creer dans pgAdmin une base VIDE nommee
# "hakili_verif" (clic droit sur Databases -> Create -> Database, onglet
# Definition -> Encoding : UTF8).
#
# Pour ouvrir ENSUITE l'application sur ces donnees sans toucher au .env :
#
#     Windows (PowerShell) :
#         $env:DATABASE_URL="postgresql://.../hakili_verif"; shiny run app.py
#     Linux / macOS :
#         DATABASE_URL="postgresql://.../hakili_verif" shiny run app.py
#
#   Le script affiche l'URL exacte a coller, a la fin du controle.
# ---------------------------------------------------------------------------

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

RACINE = Path(__file__).resolve().parent
BASE_VERIFICATION_PAR_DEFAUT = "hakili_verif"

# Bases interdites comme cible. hakili_test est ecrasee par verifier.py a
# chaque execution ; tout le reste est considere comme de la production tant
# que le nom ne commence pas par "hakili_verif".
BASES_INTERDITES = {"hakili_test"}


def url_base_verification(nom_base):
    """Reprend l'hote/le port/l'utilisateur/le mot de passe de DATABASE_URL,
    mais force le nom de la base. Meme mecanique que verifier.py."""
    load_dotenv(RACINE / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL absent de .env - impossible de savoir a quel serveur Postgres "
                 "se connecter.")
    morceaux = urlsplit(url)
    base_production = (morceaux.path or "/").lstrip("/")

    if nom_base == base_production:
        sys.exit(
            f"Refus : '{nom_base}' est la base utilisee par l'application ({base_production}).\n"
            f"Ce script n'ecrit que dans une base de verification. Utilisez "
            f"--base {BASE_VERIFICATION_PAR_DEFAUT}.")
    if nom_base in BASES_INTERDITES:
        sys.exit(
            f"Refus : '{nom_base}' est effacee et recreee par verifier.py a chaque execution ; "
            f"un import y serait perdu au prochain lancement des tests.\n"
            f"Utilisez --base {BASE_VERIFICATION_PAR_DEFAUT}.")
    if not nom_base.startswith("hakili_verif"):
        reponse = input(
            f"'{nom_base}' ne ressemble pas a une base de verification (attendu : un nom "
            f"commencant par 'hakili_verif').\nTout son contenu va etre efface. Continuer ? "
            f"Tapez le nom de la base pour confirmer : ")
        if reponse.strip() != nom_base:
            sys.exit("Annule.")
    return urlunsplit(morceaux._replace(path=f"/{nom_base}")), base_production


def _contenu_existant(cur):
    """(nombre de pieces, dont saisies a la main). Sert a ne jamais effacer
    sans prevenir une base ou l'on travaille depuis des semaines."""
    cur.execute("SELECT to_regclass('public.ecritures')")
    if cur.fetchone()[0] is None:
        return 0, 0
    cur.execute("SELECT count(DISTINCT id_piece), "
                "count(DISTINCT id_piece) FILTER (WHERE saisi_par <> 'import_historique') "
                "FROM ecritures")
    return cur.fetchone()


def recreer_base(url, nom_base, sans_confirmation=False):
    """Vide la base de verification et la reconstruit a partir des fichiers
    reels du projet : schema.sql (deja a jour des migrations) puis seed.sql.

    Demande confirmation des que la base contient deja des pieces. Pendant la
    conception, cette base sert de base de travail pendant des semaines : la
    reecraser par reflexe en relancant le script ferait perdre toutes les
    saisies faites a la main depuis l'application."""
    import psycopg2
    print(f"1/4  Recreation de '{nom_base}' a partir de sql/schema.sql et sql/seed.sql...")
    try:
        conn = psycopg2.connect(url)
    except Exception as e:
        sys.exit(f"Connexion a '{nom_base}' impossible : {e}\n"
                 f"Verifiez que cette base existe (a creer une seule fois dans pgAdmin, "
                 f"encodage UTF8).")
    conn.set_client_encoding("UTF8")
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            pieces, a_la_main = _contenu_existant(cur)
            if pieces and not sans_confirmation:
                print()
                print(f"     ATTENTION : '{nom_base}' contient deja {pieces} piece(s),")
                print(f"     dont {a_la_main} saisie(s) depuis l'application (pas importee(s)).")
                print("     Tout va etre efface et reconstruit.")
                if input("     Taper OUI pour continuer, autre chose pour annuler : ").strip() != "OUI":
                    sys.exit("Annule - la base n'a pas ete touchee.\n"
                             "Pour recontroler sans rien effacer : "
                             "python verifier_donnees.py --controle-seul")
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            for fichier in ("schema.sql", "seed.sql"):
                cur.execute((RACINE / "sql" / fichier).read_text(encoding="utf-8"))
    finally:
        conn.close()
    print("     base recreee.")


def importer_brouillards():
    print("2/4  Import des brouillards Excel...")
    import import_historique
    res = import_historique.importer(dry_run=False)
    import_historique.afficher_resume(res, dry_run=False)


def _titre(texte):
    print()
    print(texte)
    print("-" * len(texte))


def controler():
    """Affiche, sur les donnees reellement en base, les chiffres que
    l'assistant IA repondra. C'est le controle qui compte : il ne teste pas le
    code contre lui-meme, mais contre les vraies ecritures."""
    import pandas as pd
    import logic.analyse as an
    import logic.donnees as dl

    print()
    print("3/4  Controle de la chaine d'analyse")
    ref = dl.lire_referentiel()
    d = dl.lire_ecritures()
    if len(d) == 0:
        print("     Aucune ecriture en base : rien a controler.")
        return None, None, []

    d = d.copy()
    d["mois"] = pd.to_datetime(d["date_piece"], errors="coerce").dt.strftime("%Y%m")
    mois_presents = sorted(m for m in d["mois"].dropna().unique() if m >= "202601")
    centres = [c for c in ref["centres"]["code_centre"]]

    _titre(f"Volume : {len(d)} lignes, {d['id_piece'].nunique()} pieces, "
           f"{len(mois_presents)} mois de 2026")

    _titre("Resultat consolide, mois par mois (transferts exclus)")
    total_r = total_d = 0.0
    for m in mois_presents:
        r = an.resultat_net_mois(m, ref)
        total_r += r["recettes"]
        total_d += r["depenses"]
        print(f"  {m}   recettes {r['recettes']:>12,.0f}   depenses {r['depenses']:>12,.0f}"
              f"   resultat {r['resultat_net']:>12,.0f}")
    print(f"  TOTAL  recettes {total_r:>12,.0f}   depenses {total_d:>12,.0f}"
          f"   resultat {total_r - total_d:>12,.0f}")

    dernier = mois_presents[-1] if mois_presents else None
    if dernier:
        _titre(f"Par centre sur {dernier}")
        for c in centres:
            rec = an.recettes_centre_mois(c, dernier, ref, d)
            dep = an.depenses_centre_mois(c, dernier, ref, d)
            marge = ((rec - dep) / rec * 100) if rec else None
            marge_txt = f"{marge:>6.1f} %" if marge is not None else "      -"
            print(f"  {dl.nom_centre(ref, c):<10} recettes {rec:>11,.0f}   "
                  f"depenses {dep:>11,.0f}   marge {marge_txt}")

        _titre(f"Depenses sur {dernier}")
        poste = an.poste_depense_principal(dernier, None, ref, d)
        masse = an.part_masse_salariale(dernier, None, ref, d)
        print(f"  Premier poste       : {poste['intitule']} ({poste['compte']}) "
              f"{poste['montant']:,.0f} F" if poste else "  Premier poste       : aucun")
        print(f"  Total des charges   : {masse['total_charges']:,.0f} F")
        print(f"  Masse salariale     : {masse['masse_salariale']:,.0f} F "
              f"({masse['part_pct']:.1f} %)")
        nv = an.charges_non_ventilees(dernier, None, ref, d)
        print(f"  Non ventilees       : {nv['montant_total']:,.0f} F "
              f"({nv['part_des_charges_pct']:.1f} %) sur {nv['nombre_lignes']} ligne(s)")

    _titre("Controles")
    doublons = sum(len(an.paiements_suspects(m, d, ref)) for m in mois_presents)
    dates = an.ecritures_date_douteuse(None, None, d)
    print(f"  Paiements a verifier        : {doublons} piece(s)")
    print(f"  Ecritures mal datees        : {dates['nombre_pieces']} piece(s), "
          f"{dates['montant_total']:,.0f} F (avant {dates['borne_basse']})")

    trf = an.transferts_internes(None, ref, d)
    print(f"  Transferts soldes           : {trf['resume']['soldes']}")
    print(f"  Transferts en transit       : {trf['resume']['en_transit']}")
    print(f"  Transferts en anomalie      : {trf['resume']['anomalies']}")
    print(f"  Transferts sans reference   : {trf['resume']['sans_reference']} "
          f"(historique, a regulariser)")
    print(f"  Solde du compte 585000      : {trf['solde_compte_585000']:,.0f} F "
          f"(doit valoir 0 quand tout est termine)")

    tres = an.tresorerie_disponible(None, ref, d)
    print(f"  Tresorerie disponible       : {tres['total']:,.0f} F")

    return ref, dernier, mois_presents


def produire_graphiques(ref, dernier):
    """Genere en PNG les onze graphiques que l'assistant IA peut afficher, en
    passant par le MEME chemin que l'application : la valeur est serialisee en
    JSON comme le fait le serveur MCP, puis decodee par logic.graphiques. Un
    graphique qui sort ici sortira dans le chat."""
    import json
    import base64
    import logic.analyse as an
    import logic.graphiques as gr

    print()
    print("4/4  Graphiques de l'assistant IA")
    print("     (chemin identique a celui de l'application : serialisation JSON")
    print("      comme le serveur MCP, puis decodage par logic.graphiques)")
    dossier = RACINE / "Claude outputs" / "graphiques_verification"
    dossier.mkdir(parents=True, exist_ok=True)

    # Un graphique qui ne sort pas doit signaler un VRAI probleme. On choisit
    # donc des parametres qui ont forcement des donnees : le centre le plus
    # actif du mois, et une date de reference a l'interieur de la periode
    # couverte. Sinon un "RIEN" ne voudrait dire que "pas de donnees ce
    # mois-la", et le controle ne servirait a rien.
    classement = an.classement_centres_recettes(dernier, ref)
    centre_actif = (classement["centre"].iloc[0] if len(classement)
                    else ref["centres"]["code_centre"].iloc[0])
    fin_periode = f"{dernier[:4]}-{dernier[4:]}-28"

    cas = {
        "evolution_six_mois": lambda: an.evolution_6mois(dernier, ref).to_dict("records"),
        "evolution_resultat_par_centre": lambda: an.evolution_resultat_par_centre(dernier, 6, ref).to_dict("records"),
        "classement_centres_par_recettes": lambda: an.classement_centres_recettes(dernier, ref).to_dict("records"),
        "classement_centres_par_recettes_trimestre": lambda: an.classement_centres_recettes_trimestre(dernier, ref).to_dict("records"),
        "classement_rentabilite": lambda: an.classement_rentabilite_centres(dernier, ref).to_dict("records"),
        "classement_structure_couts": lambda: an.classement_structure_couts(dernier, ref).to_dict("records"),
        "contribution_centres": lambda: an.contribution_centres_mois(dernier, ref).to_dict("records"),
        "repartition_recettes": lambda: an.repartition_recettes_mois(centre_actif, dernier, ref),
        "effectif_actif_evolution": lambda: an.effectif_actif_evolution(centre_actif, dernier, 6).to_dict("records"),
        "resultat_periode": lambda: an.resultat_periode(f"{dernier[:4]}-01-01", f"{dernier[:4]}-12-31", None, ref),
        "resultat_annee_academique": lambda: an.resultat_annee_academique_vs_precedente(fin_periode, None, ref),
    }

    produits = manquants = 0
    for nom, calcul in cas.items():
        try:
            valeur = calcul()
        except Exception as e:
            print(f"  [erreur de calcul] {nom} : {e}")
            manquants += 1
            continue
        # Serialisation identique a celle du serveur MCP : une liste devient
        # un fragment de texte par element, recolles par des sauts de ligne.
        if isinstance(valeur, list):
            flux = "\n".join(json.dumps(x, indent=2, default=str) for x in valeur)
        else:
            flux = json.dumps(valeur, indent=2, default=str)
        image = gr.graphique_pour_outil(nom, flux)
        if image:
            (dossier / f"{nom}.png").write_bytes(base64.b64decode(image))
            print(f"  OK   {nom}.png")
            produits += 1
        else:
            print(f"  RIEN {nom} - aucun graphique produit")
            manquants += 1

    print()
    print(f"  {produits} graphique(s) ecrit(s) dans : {dossier}")
    if manquants:
        print(f"  {manquants} graphique(s) non produit(s) - a regarder de pres.")
    return manquants


def main():
    parser = argparse.ArgumentParser(
        description="Importe les brouillards dans une base de verification et controle "
                    "toute la chaine d'analyse. Ne touche jamais la base de l'application.")
    parser.add_argument("--base", default=BASE_VERIFICATION_PAR_DEFAUT,
                        help=f"base de verification (defaut : {BASE_VERIFICATION_PAR_DEFAUT})")
    parser.add_argument("--controle-seul", action="store_true",
                        help="ne rien recreer ni importer, controler la base telle qu'elle est")
    parser.add_argument("--forcer", action="store_true",
                        help="effacer la base sans demander confirmation, meme si elle "
                             "contient deja des saisies")
    args = parser.parse_args()

    url, base_application = url_base_verification(args.base)
    print(f"Base de l'application (intacte) : {base_application}")
    print(f"Base de verification (cible)    : {args.base}")
    print()

    # Doit etre pose AVANT le premier import de logic.donnees : c'est a
    # l'import du module que le pool de connexions Postgres est cree.
    os.environ["DATABASE_URL"] = url

    if not args.controle_seul:
        recreer_base(url, args.base, sans_confirmation=args.forcer)
        importer_brouillards()
    else:
        print("Mode controle seul : la base n'est ni recreee ni alimentee.")

    ref, dernier, mois = controler()
    manquants = produire_graphiques(ref, dernier) if ref is not None and dernier else 0

    print()
    print("=" * 70)
    if manquants == 0:
        print("Controle termine. Tous les graphiques ont ete produits.")
    else:
        print(f"Controle termine, mais {manquants} graphique(s) n'ont pas ete produits.")
    print()
    print("POUR OUVRIR L'APPLICATION SUR CES DONNEES, SANS TOUCHER AU .env")
    print()
    print("  Pour un essai ponctuel :")
    print(f'      PowerShell : $env:DATABASE_URL="{url}"; shiny run app.py')
    print(f'      Linux/macOS : DATABASE_URL="{url}" shiny run app.py')
    print()
    print(f"  Votre fichier .env n'est pas touche : la base reelle ({base_application})")
    print("  reste celle utilisee des que vous relancez l'application normalement.")
    print("=" * 70)


if __name__ == "__main__":
    main()
