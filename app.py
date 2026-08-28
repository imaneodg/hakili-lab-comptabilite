# ---------------------------------------------------------------------------
# HAKILI LAB - Saisie des operations de caisse
#
# Les centres saisissent, le comptable valide, l'application produit le
# fichier a importer dans Sage 100. Sage reste le livre officiel.
#
# Stockage : PostgreSQL (voir sql/schema.sql), connexion via DATABASE_URL ou
# les variables PG* (voir .env.example). Aucun fichier Excel n'est lu ni
# ecrit par l'application.
#
# Lancement :  shiny run --reload app.py   (depuis un venv avec les
#              dependances de requirements.txt installees, et .env rempli)
# ---------------------------------------------------------------------------

import io
import json
import re
from datetime import date

import pandas as pd
from dotenv import load_dotenv
from shiny import App, reactive, render, req, ui

load_dotenv()  # avant l'import de logic.donnees : c'est la que le pool de
                # connexions Postgres est cree, il a besoin de DATABASE_URL.

import logic.donnees as dl
import logic.modeles as md

STATUTS = {"saisie": "En attente de validation", "validee": "Validee",
           "a_corriger": "A corriger", "exportee": "Exportee vers Sage"}

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {
  --encre: #0F1B2A; --gris: #4A5B70; --gris-clair: #93A5BC;
  --bord: #DEE3EA; --fond: #F3F5F8; --bleu: #005CB9; --vert: #2E9E5B;
  --rouge: #C0362C; --rayon: 10px;
}
body { background:var(--fond); color:var(--encre);
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-size:15px; -webkit-font-smoothing:antialiased; }

/* Bandeau superieur */
.bandeau { background:var(--encre); color:#fff; padding:14px 22px;
  display:flex; align-items:center; gap:24px; flex-wrap:wrap; }
.bandeau .soc { font-weight:700; letter-spacing:.04em; font-size:15px; }
.bandeau .soc span { display:block; font-weight:400; letter-spacing:0; text-transform:none;
  color:var(--gris-clair); font-size:11px; margin-top:2px; }
.bandeau .qui { margin-left:auto; text-align:right; font-size:12px; color:var(--gris-clair); }
.bandeau .qui b { color:#fff; display:block; font-size:13.5px; font-weight:600; }

/* Cartes : unite visuelle de base de toute l'appli */
.carte { background:#fff; border:1px solid var(--bord); border-radius:var(--rayon);
  padding:18px 20px; margin-bottom:18px; box-shadow:0 1px 2px rgba(15,27,42,.04); }
.carte-entete { display:flex; align-items:center; justify-content:space-between; margin-bottom:14px; }
.carte-entete h4 { margin:0; }
.carte h4 { margin:0 0 14px 0; font-size:11px; text-transform:uppercase;
  letter-spacing:.07em; color:var(--gris); font-weight:600; }

/* Bouton discret "+" qui ouvre un mini-formulaire, style Notion/Claude :
   jamais un gros bloc affiche par defaut, un geste de plus pour agir. */
.btn-icone { width:26px; height:26px; border-radius:50%; border:1px solid var(--bord);
  background:#fff; color:var(--gris); font-size:16px; line-height:1; cursor:pointer;
  display:flex; align-items:center; justify-content:center; padding:0; transition:.15s; }
.btn-icone:hover { background:var(--fond); border-color:var(--bleu); color:var(--bleu); }
.btn-texte { border:none; background:none; color:var(--bleu); font-size:12.5px;
  font-weight:600; padding:0; cursor:pointer; }
.btn-texte:hover { text-decoration:underline; }
.popover-form { min-width:230px; }
.popover-form .form-group:last-child { margin-bottom:0; }
.param-item { padding:4px 0; }

/* Panneau flottant : positionne au-dessus du contenu, ne pousse jamais le
   tableau vers le bas. Rendu par le serveur (jamais duplique), seul son
   positionnement vient du CSS. */
.flottant-conteneur { position:relative; display:inline-block; }
.panneau-flottant { position:absolute; top:100%; z-index:40; margin-top:8px;
  background:#fff; border:1px solid var(--bord); border-radius:10px;
  box-shadow:0 10px 30px rgba(15,27,42,.15); padding:14px 16px; }
.flottant-conteneur.a-droite .panneau-flottant { right:0; }
.flottant-conteneur.a-gauche .panneau-flottant { left:0; }
.param-aide { font-size:11.5px; color:var(--gris); margin:6px 0 0 0; }

/* Champs de formulaire : coherents partout, jamais l'apparence par defaut du navigateur */
.form-group label, label.control-label { font-size:13px; font-weight:500;
  color:var(--gris); margin-bottom:4px; }
.form-control, .selectize-input, select.form-select { border-radius:6px;
  border-color:var(--bord); font-size:14.5px; }
.form-control:focus, .selectize-input.focus { border-color:var(--bleu);
  box-shadow:0 0 0 3px rgba(0,92,185,.1); }

.num { font-family:ui-monospace,Menlo,Consolas,monospace; font-variant-numeric:tabular-nums; }
.ruban { padding:10px 14px; border-radius:8px; margin:12px 0; font-size:13px; }
.ruban.ok { background:#E7F5EC; color:#1E7A46; }
.ruban.ko { background:#FBEAE8; color:var(--rouge); }
.ruban.att { background:var(--fond); color:var(--gris); }

table.apercu { width:100%; border-collapse:collapse; }
table.apercu th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--gris); border-bottom:1px solid var(--bord); padding:8px; }
table.apercu td { padding:8px; border-bottom:1px solid #EEF1F5; font-size:14px; }
table.apercu td.m { text-align:right; font-family:ui-monospace,Menlo,Consolas,monospace; }
table.apercu tr.tresorerie td { background:#FAFBFD; font-style:italic; color:var(--gris); }
table.apercu tfoot td { font-weight:700; border-top:2px solid var(--encre); }

.stat { background:#fff; border:1px solid var(--bord); border-radius:var(--rayon); padding:12px 14px; }
.stat .l { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--gris); }
.stat .v { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:20px; font-weight:600; }

.btn-primary { background:var(--bleu); border-color:var(--bleu); }
.btn-sm { padding:4px 12px; font-size:12.5px; }
.connexion { max-width:380px; margin:8vh auto; }
.nav-tabs { border-bottom-color:var(--bord); }
.nav-tabs > li > a { color:var(--gris); font-size:14.5px; font-weight:700; padding:10px 16px; }
.nav-tabs > li.active > a { border-bottom:2px solid var(--vert) !important; color:var(--encre) !important; }
"""

# Memorise le dernier centre choisi sur ce poste (localStorage, cote
# navigateur - jamais transmis au serveur ni au referentiel). Le formulaire
# de connexion ("page") est re-rendu par le serveur a chaque fois - "l_centre"
# n'existe donc pas encore au chargement de la page elle-meme : on ecoute
# l'evenement shiny:value sur la sortie "page" plutot qu'un DOMContentLoaded,
# pour retrouver le menu a chaque fois qu'il reapparait. Repose sur le
# comportement natif de l'input select de Shiny (ecoute des evenements
# "change") plutot que sur Shiny.setInputValue, pour ne rien court-circuiter
# du cote reactif normal.
JS_DERNIER_CENTRE = """
document.addEventListener("change", function (e) {
  if (e.target && e.target.id === "l_centre") {
    try { localStorage.setItem("hakili_dernier_centre", e.target.value); } catch (err) {}
  }
});

document.addEventListener("shiny:value", function (e) {
  if (!e.target || e.target.id !== "page") return;
  var sel = document.getElementById("l_centre");
  if (!sel) return;
  var dernier;
  try { dernier = localStorage.getItem("hakili_dernier_centre"); } catch (err) { return; }
  if (!dernier || sel.value === dernier) return;
  var option_existe = sel.querySelector('option[value="' + dernier.replace(/"/g, '\\\\"') + '"]');
  if (!option_existe) return;
  sel.value = dernier;
  sel.dispatchEvent(new Event("change", { bubbles: true }));
});
"""

app_ui = ui.page_fluid(
    ui.tags.head(ui.tags.style(ui.HTML(CSS)), ui.tags.title("HAKILI LAB"),
                 ui.tags.script(ui.HTML(JS_DERNIER_CENTRE))),
    ui.output_ui("page"),
)


# ---------------------------------------------------------------------------
# Serveur
# ---------------------------------------------------------------------------

def server(input, output, session):

    maj = reactive.value(0)              # declencheur de relecture des donnees

    # Plusieurs postes travaillent en meme temps sur la meme base. Un objet
    # reactif ne peut pas deviner qu'un autre poste vient d'ecrire en base :
    # on interroge donc, deux fois par seconde, le watermark tenu par
    # Postgres (table revision, incrementee par trigger a chaque ecriture
    # metier) ; tant qu'il ne bouge pas, rien n'est relu.
    #
    # Sans cela, le comptable garde la copie du referentiel chargee a sa
    # connexion : un eleve cree a l'instant par la caisse de Pissy lui reste
    # invisible, et son onglet Controles annonce "Tiers inconnu" pour un tiers
    # qui existe bel et bien en base.
    @reactive.poll(dl.revision_bd, 0.5)
    def _disque():
        return dl.revision_bd()

    @reactive.calc
    def ref():
        _disque()
        return dl.lire_referentiel()

    util = reactive.value(None)          # utilisateur connecte
    login_msg = reactive.value(None)
    dernier_msg = reactive.value(None)
    # Piece en cours de correction : None, ou {"id_piece","modele","journal",
    # "valeurs"}. Rempli quand on clique "Corriger" dans le Brouillard,
    # consomme et efface a l'enregistrement de la piece corrigee.
    correction = reactive.value(None)

    def rafraichir():
        maj.set(maj() + 1)

    @reactive.calc
    def donnees():
        maj()       # nos propres actions, effet immediat
        _disque()   # les ecritures d'un autre poste
        return dl.lire_ecritures()

    @reactive.calc
    def est_comptable():
        u = util()
        return u is not None and u.get("role") == "validation"

    # Lecture tolerante d'un input dynamique (ch_*, sold_*) : peut ne pas
    # encore exister cote client, comme un input$xxx NULL en R.
    def get_input(id_, default=None):
        try:
            val = input[id_]()
        except Exception:
            return default
        return default if val is None else val

    # ---------------- construction des onglets --------------------------------

    # Le comptable travaille par lots, journal par journal, comme Sage l'impose.
    # Avec onze modeles, une liste plate devient illisible : on les regroupe donc
    # sous le journal auquel ils appartiennent. Les operations qui touchent deux
    # journaux (approvisionnement, versement en banque) apparaissent sous celui
    # ou elles commencent. Les modeles sans journal fixe ferment la liste.
    def _modeles_groupes(r):
        intitules = dict(zip(r["journaux"]["journal"], r["journaux"]["intitule"]))
        groupes, libres = {}, {}
        for m in md.MODELES:
            j = m.get("journal")
            if not j:
                libres[m["id"]] = m["titre"]
                continue
            titre = f"{j} - {intitules.get(j, j)}"
            groupes.setdefault(titre, {})[m["id"]] = m["titre"]
        if libres:
            groupes["Autres"] = libres
        return groupes

    def onglet_saisie(r):
        return ui.nav_panel(
            "Saisie", ui.br(),
            ui.output_ui("m_correction_bandeau"),
            ui.row(
                ui.column(6, ui.div(
                    {"class": "carte"},
                    ui.h4("Operation"),
                    ui.row(
                        ui.column(8, ui.input_select("m_modele", "Modele d'operation",
                                                       choices=_modeles_groupes(r))),
                        ui.column(4, ui.input_date("m_date", "Date de l'operation",
                                                    value=date.today(), format="dd/mm/yyyy")),
                    ),
                    ui.row(
                        ui.column(6, ui.input_select(
                            "m_journal", "Journal",
                            choices={j: f"{j} - {i}" for j, i in
                                     zip(r["journaux"]["journal"], r["journaux"]["intitule"])})),
                    ),
                    ui.output_ui("m_champs"),
                    ui.output_ui("m_note_wrap"),
                )),
                ui.column(6, ui.div(
                    {"class": "carte"},
                    ui.h4("Ecriture generee"),
                    ui.output_ui("m_apercu"),
                    ui.output_ui("m_ruban"),
                    ui.input_action_button("m_enregistrer", "Enregistrer la piece", class_="btn-primary"),
                    ui.input_action_button("m_vider", "Vider"),
                    ui.output_ui("m_dernier"),
                )),
            ),
            value="saisie",
        )

    def onglet_brouillard(r):
        return ui.nav_panel(
            "Brouillard", ui.br(),
            ui.div(
                {"class": "carte"},
                ui.h4("Pieces saisies"),
                ui.row(
                    ui.column(3, ui.input_select("b_statut", "Statut", choices=["Tous"] + list(STATUTS.values()))),
                    ui.column(3, ui.input_select("b_journal", "Journal",
                                                  choices=["Tous"] + list(r["journaux"]["journal"]))),
                    ui.column(6, ui.input_date_range(
                        "b_periode", "Periode", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                ),
                ui.div(
                    {"style": "display:flex;gap:10px;margin:-4px 0 4px 0"},
                    ui.input_action_button("b_corriger", "Corriger la piece choisie"),
                    ui.input_action_button("b_supprimer", "Supprimer la piece choisie"),
                ),
                ui.output_ui("b_stats"), ui.br(),
                ui.output_data_frame("b_table"),
            ),
            value="brouillard",
        )

    def onglet_validation():
        return ui.nav_panel(
            "Validation", ui.br(),
            ui.div(
                {"class": "carte"},
                ui.h4("Pieces en attente"),
                ui.output_data_frame("v_table"), ui.br(),
                ui.input_action_button("v_valider", "Valider les pieces choisies", class_="btn-primary"),
                ui.input_action_button("v_rejeter", "Renvoyer pour correction"),
                ui.input_text("v_motif", None, placeholder="Motif du renvoi"),
            ),
            value="validation",
        )

    def onglet_export(r):
        return ui.nav_panel(
            "Export Sage", ui.br(),
            ui.div(
                {"class": "carte"},
                ui.h4("Fichier d'import Sage"),
                ui.row(
                    ui.column(4, ui.input_date_range(
                        "e_periode", "Periode", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                    ui.column(4, ui.input_select("e_journal", "Journal",
                                                  choices=["Tous"] + list(r["journaux"]["journal"]))),
                    ui.column(4, ui.br(), ui.input_checkbox("e_deja", "Inclure les pieces deja exportees", False)),
                ),
                ui.output_ui("e_resume"),
                ui.download_button("e_txt", "Telecharger le fichier Sage (.txt)", class_="btn-primary"),
                ui.download_button("e_xlsx", "Telecharger en Excel"),
                ui.input_action_button("e_marquer", "Marquer comme exportees"), ui.br(), ui.br(),
                ui.output_data_frame("e_table"),
            ),
            value="export",
        )

    def onglet_controles():
        return ui.nav_panel(
            "Controles", ui.br(),
            ui.div({"class": "carte"}, ui.h4("Anomalies detectees"),
                   ui.output_ui("c_reparation"),
                   ui.output_data_frame("c_table")),
            value="controles",
        )

    # Shiny n'accepte que lettres, chiffres et souligne dans un identifiant de
    # champ. Un code journal peut contenir autre chose - "BDU-BF" vient tel quel
    # du plan Sage et son tiret faisait planter la page. On le transpose donc,
    # toujours par la meme fonction des deux cotes (creation et lecture).
    def _id_journal(j):
        return "sold_" + re.sub(r"[^A-Za-z0-9_]", "_", str(j))

    # Quel formulaire de creation est ouvert dans Referentiel : None ou une
    # cle ("compte", "tiers", "utilisateur", "soldes", "annee"). Un seul a la
    # fois, rendu par le serveur - jamais par une bibliotheque cote
    # navigateur qui peut cloner son contenu sans le retirer. C'est ce qui
    # garantit, structurellement, qu'un champ ne peut jamais apparaitre deux
    # fois dans la page.
    panneau_ouvert = reactive.value(None)

    def _bouton_toggle(cle, libelle="+", classe="btn-icone"):
        return ui.input_action_button(f"toggle_{cle}", libelle, class_=classe)

    def _declencheur_flottant(cle, id_panneau, libelle="+", classe="btn-icone", cote="a-droite"):
        # Bouton + panneau dans le meme conteneur positionne : c'est ce qui
        # fait flotter le panneau juste sous le bouton au lieu de pousser le
        # reste de la carte vers le bas.
        return ui.div(
            {"class": f"flottant-conteneur {cote}"},
            _bouton_toggle(cle, libelle, classe),
            ui.output_ui(id_panneau),
        )

    def onglet_referentiel(u, r):
        comptable = u.get("role") == "validation"

        def entete(titre, cle=None, id_panneau=None):
            enfants = [ui.h4(titre)]
            if cle is not None:
                enfants.append(_declencheur_flottant(cle, id_panneau))
            return ui.div({"class": "carte-entete"}, *enfants)

        blocs = [ui.row(
            ui.column(6, ui.div(
                {"class": "carte"},
                entete("Plan de comptes", "compte" if comptable else None, "panneau_compte"),
                ui.output_data_frame("r_comptes"))),
            ui.column(6, ui.div(
                {"class": "carte"},
                entete("Comptes de tiers", "tiers" if comptable else None, "panneau_tiers"),
                ui.output_data_frame("r_tiers"))),
        )]

        if comptable:
            blocs.append(ui.div(
                {"class": "carte"},
                entete("Utilisateurs", "utilisateur", "panneau_utilisateur"),
                ui.p({"class": "param-aide"},
                     "Un identifiant par personne, pas par centre : c'est ce qui permet de savoir "
                     "qui a fait quoi. Desactiver ne supprime rien, l'historique reste intact."),
                ui.output_data_frame("r_utilisateurs"),
                ui.input_action_button("r_desactiver_utilisateur", "Desactiver l'utilisateur choisi",
                                        class_="btn-sm"),
            ))
            blocs.append(ui.div(
                {"class": "carte"},
                ui.h4("Parametres"),
                ui.row(
                    ui.column(6, ui.div(
                        {"class": "param-item"},
                        _declencheur_flottant("soldes", "panneau_soldes",
                                               "Soldes d'ouverture des caisses", "btn-texte", "a-gauche"),
                        ui.p({"class": "param-aide"}, "Encaisse reelle a la mise en service."))),
                    ui.column(6, ui.div(
                        {"class": "param-item"},
                        _declencheur_flottant("annee", "panneau_annee",
                                               "Nouvelle annee academique", "btn-texte", "a-gauche"),
                        ui.p({"class": "param-aide"}, "Une fois par an, a la rentree."))),
                ),
            ))

        return ui.nav_panel("Referentiel", ui.br(), *blocs, value="referentiel")

    for _cle in ("compte", "tiers", "utilisateur", "soldes", "annee"):
        def _fabrique_toggle(cle):
            @reactive.effect
            @reactive.event(input[f"toggle_{cle}"])
            def _toggle():
                panneau_ouvert.set(None if panneau_ouvert() == cle else cle)
            return _toggle
        _fabrique_toggle(_cle)

    @render.ui
    def panneau_compte():
        if panneau_ouvert() != "compte":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_num_compte", "Numero", placeholder="6xxxxx"),
            ui.input_text("r_intitule_compte", "Intitule"),
            ui.input_select("r_nature_compte", "Nature",
                             choices={"charge": "Charge", "produit": "Produit",
                                      "bilan": "Bilan", "tresorerie": "Tresorerie",
                                      "tiers": "Tiers"}),
            ui.input_checkbox("r_compte_courante", "Proposer dans \"Depense courante\"", value=False),
            ui.input_checkbox("r_tiers_obligatoire", "Code tiers obligatoire sur ce compte", value=False),
            ui.input_action_button("r_ajouter_compte", "Creer", class_="btn-primary btn-sm"),
        )

    @render.ui
    def panneau_tiers():
        if panneau_ouvert() != "tiers":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_code", "Code tiers", placeholder="411NOMPRENOM"),
            ui.input_text("r_nom", "Intitule"),
            ui.input_select("r_collectif", "Collectif",
                             choices={"411000": "411000 - Eleve", "401000": "401000 - Fournisseur",
                                      "422000": "422000 - Personnel"}),
            ui.input_action_button("r_ajouter", "Creer", class_="btn-primary btn-sm"),
        )

    @render.ui
    def panneau_utilisateur():
        if panneau_ouvert() != "utilisateur":
            return None
        r = ref()
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_text("r_id_utilisateur", "Identifiant", placeholder="prenom.nom"),
            ui.input_text("r_nom_utilisateur", "Nom complet"),
            ui.input_select("r_role_utilisateur", "Role",
                             choices={"saisie": "Saisie", "validation": "Validation"}),
            ui.input_select("r_centre_utilisateur", "Centre",
                             choices=dict(zip(r["centres"]["code_centre"], r["centres"]["intitule"]))),
            ui.input_password("r_code_utilisateur", "Code d'acces"),
            ui.input_action_button("r_ajouter_utilisateur", "Creer", class_="btn-primary btn-sm"),
        )

    @render.ui
    def panneau_soldes():
        if panneau_ouvert() != "soldes":
            return None
        r = ref()
        jx = r["journaux"]
        if "type" in jx.columns:
            jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
        cols = []
        for j in jx["journal"]:
            brut = r["journaux"].loc[r["journaux"]["journal"] == j, "solde_ouverture"]
            val = float(brut.iloc[0]) if len(brut) and pd.notna(brut.iloc[0]) else 0.0
            cols.append(ui.input_numeric(_id_journal(j), j, value=val, min=0, step=1000))
        return ui.div({"class": "popover-form panneau-flottant"}, *cols,
                       ui.input_action_button("r_soldes", "Enregistrer", class_="btn-primary btn-sm"))

    @render.ui
    def panneau_annee():
        if panneau_ouvert() != "annee":
            return None
        return ui.div(
            {"class": "popover-form panneau-flottant"},
            ui.input_action_button("r_nouvelle_annee", "Demarrer", class_="btn-sm"),
        )

    def onglets(u):
        r = ref()
        tabs = [onglet_saisie(r), onglet_brouillard(r)]
        if u.get("role") == "validation":
            tabs += [onglet_validation(), onglet_export(r)]
        tabs += [onglet_controles(), onglet_referentiel(u, r)]
        return tabs

    # ---------------- connexion ----------------------------------------------
    #
    # Un seul formulaire : centre + identifiant + code personnel, tous
    # renseignes ensemble. Pas de mot de passe de centre distinct : le code
    # personnel de chacun est la seule barriere, exactement comme le code
    # d'un badge individuel. La tracabilite nominative (saisi_par/valide_par)
    # vient de ce meme code, qui reste propre a chaque personne.

    @render.ui
    def page():
        u = util()
        if u is not None:
            role_txt = "validation et export" if u.get("role") == "validation" else "saisie"
            return ui.TagList(
                ui.div(
                    {"class": "bandeau"},
                    ui.div({"class": "soc"}, "HAKILI LAB", ui.tags.span("Gestion de caisse")),
                    ui.div(
                        {"class": "qui"}, ui.tags.b(u.get("nom")),
                        f"Centre {u.get('centre')} - {role_txt}",
                        ui.input_action_link("deconnexion", "Fermer la session",
                                              style="color:#93A5BC;display:block")),
                ),
                ui.div({"style": "padding:20px 22px"}, ui.navset_tab(*onglets(u), id="onglets")),
            )

        entete = ui.div({"style": "text-align:center;margin-bottom:18px"},
                         ui.tags.div({"style": "font-weight:700;font-size:17px;letter-spacing:.04em"},
                                     "HAKILI LAB"),
                         ui.tags.div({"style": "font-size:12px;color:var(--gris)"}, "Gestion de caisse"))

        r = ref()
        centres_actifs = r["centres"][r["centres"]["actif"] == "oui"]
        choix = dict(zip(centres_actifs["code_centre"], centres_actifs["intitule"]))
        return ui.div(
            {"class": "connexion"}, entete,
            ui.div(
                {"class": "carte"},
                ui.h4("Connexion"),
                ui.input_select("l_centre", "Centre", choices=choix),
                ui.input_text("l_id", "Nom d'utilisateur", placeholder="prenom.nom"),
                ui.input_password("l_code", "Code personnel"),
                ui.input_action_button("l_ok", "Se connecter", class_="btn-primary"),
                ui.output_ui("l_msg"),
            ),
        )

    @render.ui
    def l_msg():
        if login_msg() is None:
            return None
        return ui.div({"class": "ruban ko"}, login_msg())

    @reactive.effect
    @reactive.event(input.l_ok)
    def _connexion():
        r = ref()
        cs = r["centres"]
        idx_c = cs.index[cs["code_centre"] == input.l_centre()]
        if len(idx_c) and str(cs.loc[idx_c[0], "actif"]) != "oui":
            login_msg.set("Ce centre a ete desactive.")
            return
        us = r["utilisateurs"]
        # Le nom d'utilisateur n'est pas sensible a la casse : AFIYA, Afiya et
        # afiya designent la meme personne. La comparaison se fait toujours
        # dans le centre choisi dans le formulaire - un identifiant valide
        # mais d'un autre centre est refuse ici, pas seulement absent d'une
        # liste qui n'existe plus.
        saisi = str(input.l_id() or "").strip().lower()
        idx = us.index[(us["identifiant"].str.lower() == saisi) & (us["centre"] == input.l_centre())]
        if len(idx) and str(input.l_code() or "").strip() == str(us.loc[idx[0], "code_acces"]).strip():
            if str(us.loc[idx[0], "actif"]) != "oui":
                login_msg.set("Ce compte a ete desactive.")
                return
            util.set(us.loc[idx[0]].to_dict())
            login_msg.set(None)
        else:
            login_msg.set("Centre, nom d'utilisateur ou code incorrect.")

    @reactive.effect
    @reactive.event(input.deconnexion)
    def _deconnexion():
        util.set(None)

    # ---------------- saisie --------------------------------------------------

    # Le modele impose son journal quand il n'en accepte qu'un ; aucun des
    # modeles actuels n'a besoin de restreindre la liste des journaux -
    # "Ecriture libre" fonctionne sur tous, ses champs s'adaptent tout seuls
    # (cf. m_champs) au journal deja choisi.
    @reactive.effect
    @reactive.event(input.m_modele)
    def _modele_journal():
        m = md.modele_par_id(input.m_modele())
        if m is not None and m.get("journal"):
            ui.update_select("m_journal", selected=m["journal"])

    # Le selecteur de journal reste modifiable a la main (utile pour
    # "Ecriture libre"), mais rien n'empeche alors de choisir une combinaison
    # impossible pour un modele a journal fixe (ex. "Encaissement" + VTE) -
    # l'apercu restait vide sans dire pourquoi. On remet le journal correct
    # et on explique, plutot que de laisser deviner.
    @reactive.effect
    @reactive.event(input.m_journal)
    def _garde_journal():
        m = md.modele_par_id(input.m_modele())
        if m is not None and m.get("journal") and input.m_journal() != m["journal"]:
            ui.update_select("m_journal", selected=m["journal"])
            ui.notification_show(
                f"Le modele \u00ab {m['titre']} \u00bb n'existe que sur le journal {m['journal']}.",
                type="warning")

    # Determine, pour le modele en cours, quels libelles proposer.
    # "Reglement fournisseur" propose les libelles rattaches au compte 401000,
    # les memes pour tous les fournisseurs : pas de dependance au fournisseur
    # choisi, volontairement, pour que le formulaire reste simple et
    # previsible. "Depense courante" propose ceux du compte de charge deja
    # choisi. "Ecriture libre" n'est pas filtre.
    #
    # La lecture d'un champ deja affiche par ce meme formulaire est isolee :
    # m_champs ne doit jamais reagir a un changement de ces champs, sinon le
    # formulaire entier se redessine et efface la selection qu'on vient de
    # faire.
    def _libelles_pour_champ(m, r):
        base = r["libelles"]
        if m["id"] == "fournisseur":
            return base[base["compte"] == "401000"]
        if m["id"] == "depense":
            with reactive.isolate():
                compte_choisi = get_input("ch_compte")
            if compte_choisi:
                return base[base["compte"] == compte_choisi]
            return base[base["compte"].isin(
                r["comptes"].loc[r["comptes"]["depense_courante"] == "oui", "compte"])]
        return base

    @render.ui
    def m_champs():
        m = md.modele_par_id(req(input.m_modele()))
        r = ref()
        # "Ecriture libre" a deux jeux de champs possibles ; les autres
        # modeles n'en ont qu'un. resoudre_variante() choisit le bon selon le
        # journal deja affiche dans le selecteur au-dessus - lire
        # input.m_journal() ici rend ce bloc reactif au journal, pas
        # seulement au modele : changer de journal met a jour les champs
        # sans que la caissiere ait rien d'autre a faire.
        champs, _ = md.resoudre_variante(m, req(input.m_journal()), r)
        # Une correction en cours pre-remplit chaque champ avec sa valeur
        # d'origine, mais seulement tant que le modele et le journal affiches
        # correspondent encore a la piece qu'on corrige : si l'utilisateur
        # change d'avis et choisit un autre modele, les valeurs de l'ancienne
        # piece n'ont plus de raison de s'imposer.
        cor = correction()
        pre = {}
        if cor and cor["modele"] == input.m_modele() and cor["journal"] == input.m_journal():
            pre = cor["valeurs"]
        widgets = []
        for ch in champs:
            id_ = f"ch_{ch['n']}"
            t = ch["t"]
            defaut = pre.get(ch["n"])
            if t == "tiers":
                # Seuls les tiers actifs pour l'annee academique en cours sont
                # proposes, pour ne pas polluer la liste avec des annees
                # revolues. "create=True" laisse taper un nom absent de la
                # liste (nouvel eleve, nouveau professeur, ancien tiers
                # revenu) : le code definitif n'est genere/reactive qu'au
                # moment de l'enregistrement (resoudre_tiers), jamais pendant
                # la frappe.
                sous = r["tiers"][
                    r["tiers"]["code_tiers"].str.startswith(ch["pref"])
                    & (r["tiers"]["actif_annee"] == "oui")
                ]
                choix = {"": ""}
                for _, row in sous.iterrows():
                    choix[row["code_tiers"]] = f"{row['intitule']}  ({row['code_tiers']})"
                if defaut and defaut not in choix:
                    choix[defaut] = defaut
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"create": True,
                             "placeholder": "Taper les premieres lettres, ou un nom nouveau"}))
            elif t == "compte":
                # "filtre" restreint la liste a une colonne oui/non du
                # referentiel (ex. depense_courante) : "Depense courante" ne
                # propose ainsi que des comptes de charge reellement
                # recurrents, jamais un compte a tiers obligatoire. Sans
                # filtre (ex. "Ecriture libre"), la liste complete reste
                # disponible pour les cas rares.
                comptes = r["comptes"]
                if ch.get("filtre"):
                    comptes = comptes[comptes[ch["filtre"]] == "oui"]
                # "exclut" retire au contraire les comptes marques "oui" dans
                # la colonne citee.
                if ch.get("exclut") and ch["exclut"] in comptes.columns:
                    comptes = comptes[comptes[ch["exclut"]] != "oui"]
                # "choix" fige une liste courte ecrite dans le modele lui-meme,
                # quand les comptes possibles se comptent sur les doigts d'une
                # main et ne meritent pas une colonne du referentiel.
                if ch.get("choix"):
                    comptes = comptes[comptes["compte"].isin(ch["choix"])]
                choix = {"": ""}
                for _, row in comptes.iterrows():
                    choix[row["compte"]] = f"{row['compte']} - {row['intitule']}"
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"placeholder": "Numero ou intitule"}))
            elif t == "libelle":
                # Si le filtrage ne laisse aucune suggestion, on retombe sur
                # la liste complete plutot que de laisser un champ vide et
                # bloque : create=True permet de toute facon de taper
                # n'importe quoi, la liste n'est qu'une aide, jamais une
                # obligation.
                base = _libelles_pour_champ(m, r)
                if len(base) == 0:
                    base = r["libelles"]
                choix = {"": ""}
                for lib in base["libelle"].dropna().unique():
                    choix[lib] = lib
                if defaut and defaut not in choix:
                    choix[defaut] = defaut
                widgets.append(ui.input_selectize(
                    id_, ch["l"], choices=choix, selected=defaut or "",
                    options={"create": True, "placeholder": "Libelle normalise, ou en creer un"}))
            elif t == "mois":
                widgets.append(ui.input_select(id_, ch["l"], choices=md.MOIS_FR,
                                                selected=defaut or md.MOIS_FR[date.today().month - 1]))
            elif t == "montant":
                valeur = defaut if defaut not in (None, "") else ch.get("defaut") or 0
                widgets.append(ui.input_numeric(id_, ch["l"], value=float(valeur), min=0, step=500))
            elif t == "oui_non":
                widgets.append(ui.input_select(id_, ch["l"], choices={"oui": "Oui", "non": "Non"},
                                                selected=defaut or "non"))
            elif t == "choix":
                widgets.append(ui.input_select(id_, ch["l"], choices=ch["options"],
                                                selected=defaut or next(iter(ch["options"]))))
            else:
                widgets.append(ui.input_text(id_, ch["l"], value=defaut or ""))
        return ui.TagList(*widgets)

    # La note n'a de sens que pour "Ecriture libre" : c'est le seul modele ou
    # une operation peut vraiment avoir besoin d'un mot d'explication pour le
    # comptable (compte a creer, contexte du 471000). Sur les 12 autres
    # modeles, l'operation est deja entierement decrite par ses champs -
    # ajouter une note partout serait juste du remplissage visuel.
    @render.ui
    def m_note_wrap():
        if req(input.m_modele()) != "libre":
            return None
        return ui.input_text_area(
            "m_note", "Note pour le comptable (facultatif)",
            placeholder="De quoi s'agit-il ? Quel compte faudrait-il creer ?", rows=2)

    @reactive.calc
    def valeurs():
        m = md.modele_par_id(req(input.m_modele()))
        r = ref()
        champs, _ = md.resoudre_variante(m, req(input.m_journal()), r)
        v = {}
        for ch in champs:
            v[ch["n"]] = get_input(f"ch_{ch['n']}")
        # Pour chaque champ tiers (eleve, fournisseur, personnel...), calcule
        # seulement le nom a afficher dans le libelle - jamais le code, qui
        # ne doit etre fige qu'a l'enregistrement (_enregistrer). La valeur
        # brute (code existant choisi, ou nom tape librement) reste dans
        # v[ch["n"]] telle quelle : c'est elle que resoudre_tiers() traitera.
        for ch in champs:
            if ch["t"] == "tiers" and v.get(ch["n"]):
                brut = v[ch["n"]]
                code = dl.code_tiers_candidat(brut, ch["pref"], r)
                tiers = r["tiers"]
                m_existant = tiers[tiers["code_tiers"] == code]
                v[f"{ch['n']}_nom"] = m_existant.iloc[0]["intitule"] if len(m_existant) else str(brut).upper()
        # La date de la piece est mise a disposition des libelles. Elle evite un
        # champ : dans l'historique, le mois ecrit dans un libelle de facture est
        # celui de la piece dans 966 cas sur 966. Le demander serait faire retaper
        # une information deja saisie juste au-dessus.
        try:
            d = input.m_date()
            v["_mois"] = md.MOIS_FR[d.month - 1]
            v["_annee"] = f"{d.year % 100:02d}"
        except Exception:
            v["_mois"] = ""
            v["_annee"] = ""
        return v

    # Une saisie en cours est presque toujours incomplete : operation() renvoie
    # None tant que l'ecriture n'est pas constructible, jamais une erreur.
    # Une operation contient une piece, ou deux quand les deux caisses bougent
    # ensemble (transfert de la caisse principale vers les menues depenses).
    @reactive.calc
    def operation():
        req(input.m_modele(), input.m_journal())
        try:
            return md.construire_operation(input.m_modele(), valeurs(), input.m_journal(), ref()["journaux"])
        except Exception:
            return None

    def table_ecriture(L, r):
        tr = set(r["journaux"]["compte_contrepartie"])
        lignes_html = []
        for _, x in L.iterrows():
            cls = "tresorerie" if x["compte"] in tr else ""
            lignes_html.append(
                f"<tr class='{cls}'>"
                f"<td class='num'>{x['compte']}<br><span style='font-size:10px;color:#4A5B70'>"
                f"{dl.intitule_compte(r, x['compte'])}</span></td>"
                f"<td class='num' style='font-size:11px'>{x['code_tiers']}</td>"
                f"<td>{x['libelle']}</td>"
                f"<td class='m'>{dl.fcfa(x['debit']) if float(x['debit']) > 0 else ''}</td>"
                f"<td class='m'>{dl.fcfa(x['credit']) if float(x['credit']) > 0 else ''}</td></tr>"
            )
        return (
            "<table class='apercu'><thead><tr><th>Compte</th><th>Tiers</th><th>Libelle</th>"
            "<th class='m'>Debit</th><th class='m'>Credit</th></tr></thead><tbody>"
            + "".join(lignes_html) +
            f"</tbody><tfoot><tr><td colspan='3'>Totaux</td><td class='m'>{dl.fcfa(L['debit'].sum())}"
            f"</td><td class='m'>{dl.fcfa(L['credit'].sum())}</td></tr></tfoot></table>"
        )

    @render.ui
    def m_apercu():
        op = operation()
        if op is None:
            return ui.div({"class": "ruban att"}, "Renseignez l'operation : l'ecriture se construit ici.")
        r = ref()
        morceaux = []
        for i, p in enumerate(op):
            ligne_j = r["journaux"].loc[r["journaux"]["journal"] == p["journal"], "intitule"]
            intitule = ligne_j.iloc[0] if len(ligne_j) else p["journal"]
            if len(op) > 1:
                marge = "0" if i == 0 else "18px"
                morceaux.append(
                    f"<div style='font-size:11px;text-transform:uppercase;letter-spacing:.06em;"
                    f"color:#4A5B70;font-weight:600;margin:{marge} 0 6px'>Piece {i + 1} sur {len(op)} - "
                    f"journal {p['journal']}, {intitule}</div>")
            morceaux.append(table_ecriture(p["lignes"], r))
        return ui.HTML("".join(morceaux))

    @reactive.calc
    def equilibree():
        return md.operation_equilibree(operation())

    # Effet de l'operation sur chaque caisse, avant enregistrement.
    def effet_caisses(op, r):
        res = {}
        for j in r["journaux"]["journal"]:
            cc_s = r["journaux"].loc[r["journaux"]["journal"] == j, "compte_contrepartie"]
            cc = cc_s.iloc[0] if len(cc_s) else None
            d = 0.0
            for p in op:
                L = p["lignes"]
                d += L.loc[L["compte"] == cc, "debit"].sum() - L.loc[L["compte"] == cc, "credit"].sum()
            if round(d) != 0:
                res[j] = d
        return res

    @render.ui
    def m_ruban():
        op = operation()
        if op is None:
            return None
        r = ref()
        if not equilibree():
            return ui.div({"class": "ruban ko"},
                           "L'operation n'est pas equilibree : elle ne peut pas etre enregistree.")
        doubles = md.comptes_annules(op)
        if doubles:
            return ui.div({"class": "ruban ko"},
                           f"Le compte {', '.join(doubles)} est debite et credite pour le meme tiers : "
                           "l'ecriture s'annule d'elle-meme. Choisissez deux comptes differents.")
        eff = effet_caisses(op, r)
        morceaux = []
        for j, val in eff.items():
            apres = dl.solde_caisse(j, r, donnees()) + val
            sens = "diminue" if val < 0 else "augmente"
            morceaux.append(f"caisse {j} {sens} de <span class='num'>{dl.fcfa(abs(val))}</span> F, "
                             f"solde <span class='num'>{dl.fcfa(apres)}</span> F")
        prefixe = (f"Operation liee, {len(op)} pieces enregistrees ensemble. "
                   if len(op) > 1 else "Piece equilibree. ")
        return ui.div({"class": "ruban ok"}, ui.HTML(prefixe + " ; ".join(morceaux) + "."))

    @reactive.effect
    @reactive.event(input.m_enregistrer)
    def _enregistrer():
        if not equilibree():
            ui.notification_show("Operation desequilibree ou incomplete.", type="error")
            return
        u = util()
        m = md.modele_par_id(input.m_modele())

        # Resolution definitive des champs tiers : un nom nouveau devient un
        # tiers reellement cree dans le referentiel a cet instant precis, un
        # ancien tiers retape est reactive avec son code d'origine. C'est le
        # seul moment ou le referentiel est modifie par la saisie - jamais
        # pendant la frappe (valeurs()/operation() ne font qu'un apercu).
        v_resolues = dict(valeurs())
        try:
            champs, _ = md.resoudre_variante(m, input.m_journal(), ref())
            for ch in champs:
                if ch["t"] == "tiers" and v_resolues.get(ch["n"]):
                    v_resolues[ch["n"]] = dl.resoudre_tiers(
                        v_resolues[ch["n"]], ch["pref"], ch["collectif"])
        except Exception as e:
            ui.notification_show(f"Impossible de resoudre le tiers : {e}", type="error")
            return

        op = md.construire_operation(input.m_modele(), v_resolues, input.m_journal(), ref()["journaux"])
        if op is None or not md.operation_equilibree(op):
            ui.notification_show("Operation desequilibree ou incomplete.", type="error")
            return
        doubles = md.comptes_annules(op)
        if doubles:
            ui.notification_show(f"Compte {', '.join(doubles)} debite et credite pour le meme tiers : "
                                 "l'ecriture n'aurait aucun effet.", type="error")
            return

        try:
            note = get_input("m_note", "") if input.m_modele() == "libre" else ""
            res = dl.enregistrer_operation(op, u["centre"], input.m_date(), input.m_modele(),
                                            u["identifiant"], note=note, valeurs=v_resolues)
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return

        # Si on venait de "Corriger" : la nouvelle piece est enregistree,
        # l'ancienne (a_corriger) n'a plus de raison d'exister. Une erreur ici
        # (piece deja supprimee entre-temps par le comptable, par exemple)
        # n'annule pas l'enregistrement qui vient de reussir - elle est juste
        # signalee a part.
        cor = correction()
        if cor is not None:
            try:
                dl.supprimer_piece(cor["id_piece"])
            except Exception as e:
                ui.notification_show(f"Piece corrigee, mais l'ancienne n'a pas pu etre retiree : {e}",
                                      type="warning")
            correction.set(None)
            ui.notification_show(f"Correction enregistree : {', '.join(res)} remplace {cor['id_piece']}",
                                  type="message")
        elif len(res) > 1:
            ui.notification_show(f"Operation enregistree : pieces {' et '.join(res)}, une par caisse",
                                  type="message")
        else:
            ui.notification_show(f"Piece {res[0]} enregistree", type="message")
        dernier_msg.set("Derniere operation : " + ", ".join(res))
        ui.update_text_area("m_note", value="")
        reinitialiser()
        rafraichir()

    @render.ui
    def m_dernier():
        if dernier_msg() is None:
            return None
        return ui.tags.span({"style": "margin-left:12px;color:#4A5B70"}, dernier_msg())

    @render.ui
    def m_correction_bandeau():
        cor = correction()
        if cor is None:
            return None
        if cor.get("restaure", True):
            texte = (f"Correction de la piece {cor['id_piece']} : les informations d'origine sont "
                     "reprises ci-dessous. Modifiez puis enregistrez. ")
        else:
            texte = (f"Correction de la piece {cor['id_piece']} : piece anterieure a la sauvegarde "
                      "des valeurs, les champs sont vides. Ressaisissez puis enregistrez. ")
        return ui.div(
            {"class": "ruban att"}, texte,
            ui.input_action_link("m_annuler_correction", "Annuler la correction"),
        )

    @reactive.effect
    @reactive.event(input.m_annuler_correction)
    def _annuler_correction():
        correction.set(None)
        ui.notification_show("Correction annulee, rien n'a ete modifie.", type="message")

    def reinitialiser():
        m = md.modele_par_id(input.m_modele())
        if m is None:
            return
        champs, _ = md.resoudre_variante(m, input.m_journal(), ref())
        for ch in champs:
            id_ = f"ch_{ch['n']}"
            if ch["t"] == "montant":
                ui.update_numeric(id_, value=float(ch.get("defaut") or 0))
            elif ch["t"] in ("tiers", "compte", "libelle"):
                ui.update_selectize(id_, selected="")
            elif ch["t"] == "texte":
                ui.update_text(id_, value="")
            elif ch["t"] == "choix" and ch.get("options"):
                ui.update_select(id_, selected=next(iter(ch["options"])))

    @reactive.effect
    @reactive.event(input.m_vider)
    def _vider():
        reinitialiser()

    # ---------------- brouillard ---------------------------------------------

    @reactive.calc
    def pieces_vue():
        d = donnees()
        u = req(util())  # tab inatteignable avant connexion, garde defensive quand meme
        if len(d) == 0:
            return d
        if not est_comptable():
            d = d[d["centre"] == u["centre"]]
        if input.b_journal() and input.b_journal() != "Tous":
            d = d[d["journal"] == input.b_journal()]
        if input.b_statut() and input.b_statut() != "Tous":
            code = [k for k, v in STATUTS.items() if v == input.b_statut()]
            if code:
                d = d[d["statut"] == code[0]]
        periode = input.b_periode()
        if periode and periode[0] and periode[1]:
            dts = pd.to_datetime(d["date_piece"])
            d = d[(dts >= pd.Timestamp(periode[0])) & (dts <= pd.Timestamp(periode[1]))]
        return d

    def table_pieces(d):
        if len(d) == 0:
            return pd.DataFrame({"Message": ["Aucune piece pour ce filtre."]})
        # File d'attente, pas registre comptable : la piece la plus recemment
        # saisie remonte en tete, quelle que soit sa date d'operation. Une
        # depense datee du 17 mais saisie aujourd'hui doit apparaitre avant
        # les pieces du 20 saisies hier - c'est l'ordre de saisie (saisi_le)
        # qui classe, jamais la date comptable (date_piece), qui elle ne
        # bouge pas et reste la seule utilisee pour l'export Sage.
        d = d.sort_values("saisi_le", ascending=False, kind="mergesort")
        lignes = []
        ids = []
        for idp in d["id_piece"].unique():
            p = d[d["id_piece"] == idp]
            lignes.append({
                "Date": pd.to_datetime(p["date_piece"].iloc[0]).strftime("%d/%m/%Y"),
                "Piece": dl.ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0]),
                "Journal": p["journal"].iloc[0],
                "Centre": p["centre"].iloc[0],
                "Libelle": p["libelle"].iloc[0],
                "Montant": dl.fcfa(p["debit"].sum()),
                "Statut": STATUTS.get(p["statut"].iloc[0], p["statut"].iloc[0]),
                "Saisi_par": p["saisi_par"].iloc[0],
                "Observation": p["observation"].iloc[0],
            })
            ids.append(idp)
        out = pd.DataFrame(lignes)
        out.index = ids
        return out

    def grille_pieces(d, selection_mode):
        if "Message" in d.columns:
            return render.DataGrid(d, selection_mode="none", width="100%")
        return render.DataGrid(d, selection_mode=selection_mode, width="100%")

    # Les trois premiers indicateurs suivent le filtre affiche ; les soldes de
    # caisse portent toujours sur la totalite des ecritures (sinon ce ne
    # seraient pas des soldes), et couvrent tous les journaux de tresorerie
    # du referentiel - CP et CMD hier, BDU-BF aujourd'hui, un quatrieme
    # demain sans qu'il faille toucher ce code.
    @render.ui
    def b_stats():
        d = pieces_vue()
        r = ref()
        cc = set(r["journaux"]["compte_contrepartie"])
        entrees = d.loc[d["compte"].isin(cc), "debit"].sum() if len(d) else 0
        sorties = d.loc[d["compte"].isin(cc), "credit"].sum() if len(d) else 0
        jx = r["journaux"]
        if "type" in jx.columns:
            jx = jx[jx["type"].fillna("tresorerie") == "tresorerie"]
        cartes = [
            ui.div({"class": "stat"}, ui.div({"class": "l"}, "Pieces affichees"),
                   ui.div({"class": "v"}, str(d["id_piece"].nunique()) if len(d) else "0")),
            ui.div({"class": "stat"}, ui.div({"class": "l"}, "Entrees en caisse"),
                   ui.div({"class": "v"}, dl.fcfa(entrees))),
            ui.div({"class": "stat"}, ui.div({"class": "l"}, "Sorties de caisse"),
                   ui.div({"class": "v"}, dl.fcfa(sorties))),
        ]
        for j in jx["journal"]:
            cartes.append(ui.div({"class": "stat"}, ui.div({"class": "l"}, f"Solde {j}"),
                                  ui.div({"class": "v"}, dl.fcfa(dl.solde_caisse(j, r, donnees())))))
        return ui.TagList(
            ui.div({"style": "display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));"
                              "gap:12px;margin-top:12px"}, *cartes),
            ui.div({"style": "font-size:11px;color:var(--gris);margin-top:8px"},
                   "Soldes toujours calcules sur l'ensemble des pieces, filtre ou non."),
        )

    @render.data_frame
    def b_table():
        return grille_pieces(table_pieces(pieces_vue()), "row")

    @reactive.effect
    @reactive.event(input.b_supprimer)
    def _supprimer():
        sel = b_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Choisir d'abord une piece.", type="warning")
            return
        try:
            dl.supprimer_piece(list(sel.index))
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Piece supprimee", type="message")
        rafraichir()

    # "Corriger" ne construit aucun ecran : elle recharge Saisie avec le
    # modele, le journal, la date et les valeurs d'origine de la piece
    # (conservees dans valeurs_json a l'enregistrement), pret a etre modifie
    # et renvoye. L'ancienne piece n'est retiree qu'a l'enregistrement de la
    # nouvelle (_enregistrer), jamais avant : abandonner une correction en
    # cours de route ne doit rien casser.
    @reactive.effect
    @reactive.event(input.b_corriger)
    def _corriger():
        sel = b_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Choisir d'abord une piece.", type="warning")
            return
        if len(sel) > 1:
            ui.notification_show("Choisir une seule piece a corriger.", type="warning")
            return
        idp = sel.index[0]
        d = donnees()
        p = d[d["id_piece"] == idp]
        if len(p) == 0:
            ui.notification_show("Piece introuvable.", type="error")
            return
        if p["statut"].iloc[0] != "a_corriger":
            ui.notification_show("Seule une piece renvoyee pour correction peut etre corrigee ainsi.",
                                  type="warning")
            return
        modele = p["modele"].iloc[0]
        journal = p["journal"].iloc[0]
        if md.modele_par_id(modele) is None:
            ui.notification_show("Modele d'origine introuvable, correction impossible ici.", type="error")
            return
        brut = p["valeurs_json"].iloc[0]
        try:
            vals = json.loads(brut) if brut else {}
        except (TypeError, ValueError):
            vals = {}
        restaure = bool(vals)
        try:
            date_piece = pd.to_datetime(p["date_piece"].iloc[0]).date()
        except Exception:
            date_piece = date.today()
        correction.set({"id_piece": idp, "modele": modele, "journal": journal,
                         "valeurs": vals, "restaure": restaure})
        ui.update_select("m_modele", selected=modele)
        ui.update_select("m_journal", selected=journal)
        ui.update_date("m_date", value=date_piece)
        ui.update_navs("onglets", selected="saisie")
        if not restaure:
            ui.notification_show(
                "Piece anterieure a la sauvegarde des valeurs de saisie : modele, journal et date "
                "sont repris, mais les champs du formulaire sont a ressaisir.", type="warning")

    # ---------------- validation ---------------------------------------------

    @reactive.calc
    def attente():
        d = donnees()
        return d[d["statut"].isin(["saisie", "a_corriger"])]

    @render.data_frame
    def v_table():
        return grille_pieces(table_pieces(attente()), "rows")

    @reactive.effect
    @reactive.event(input.v_valider)
    def _valider():
        sel = v_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Aucune piece choisie.", type="warning")
            return
        d = donnees()
        # Une piece liee entraine sa jumelle : on controle et on valide la paire.
        ids = dl.avec_liees(list(sel.index), d)
        ano = dl.controler(d[d["id_piece"].isin(ids)], ref(), d)
        bloquantes = ano[ano["gravite"] == "bloquante"]
        if len(bloquantes) > 0:
            items = [ui.tags.li(f"{row['piece']} : {row['anomalie']}") for _, row in bloquantes.iterrows()]
            ui.modal_show(ui.modal(
                ui.p("Ces pieces comportent des anomalies bloquantes :"),
                ui.tags.ul(*items),
                title="Validation impossible", easy_close=True))
            return
        try:
            res = dl.valider_pieces(ids, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show(f"{res} piece(s) validee(s) et numerotee(s)", type="message")
        rafraichir()

    @reactive.effect
    @reactive.event(input.v_rejeter)
    def _rejeter():
        sel = v_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Aucune piece choisie.", type="warning")
            return
        motif = input.v_motif()
        if not motif or not str(motif).strip():
            ui.notification_show("Indiquer le motif du renvoi.", type="warning")
            return
        try:
            dl.rejeter_pieces(list(sel.index), motif, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        ui.notification_show("Pieces renvoyees au centre", type="message")
        rafraichir()

    # ---------------- export --------------------------------------------------

    @reactive.calc
    def a_exporter():
        d = donnees()
        if len(d) == 0:
            return d
        statuts = ["validee", "exportee"] if input.e_deja() else ["validee"]
        d = d[d["statut"].isin(statuts)]
        if input.e_journal() and input.e_journal() != "Tous":
            d = d[d["journal"] == input.e_journal()]
        periode = input.e_periode()
        if periode and periode[0] and periode[1]:
            dts = pd.to_datetime(d["date_piece"])
            d = d[(dts >= pd.Timestamp(periode[0])) & (dts <= pd.Timestamp(periode[1]))]
        return d

    @render.ui
    def e_resume():
        d = a_exporter()
        if len(d) == 0:
            return ui.div({"class": "ruban att"}, "Aucune piece validee sur cette periode.")
        return ui.div({"class": "ruban ok"},
                       f"{d['id_piece'].nunique()} piece(s), {len(d)} ligne(s), "
                       f"{dl.fcfa(d['debit'].sum())} F au debit. Le fichier suit l'ordre de colonnes "
                       "declare dans Sage.")

    @render.data_frame
    def e_table():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            return render.DataGrid(pd.DataFrame({"Message": ["Rien a exporter."]}), selection_mode="none")
        return render.DataGrid(x, selection_mode="none", width="100%")

    @render.download_button(filename=lambda: f"sage_{date.today().strftime('%Y%m%d')}.txt", encoding="latin1")
    def e_txt():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            yield ""
            return
        yield x.to_csv(sep=";", index=False, header=False, lineterminator="\n", na_rep="")

    @render.download_button(
        filename=lambda: f"sage_{date.today().strftime('%Y%m%d')}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    def e_xlsx():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            x = pd.DataFrame()
        buf = io.BytesIO()
        x.to_excel(buf, index=False, engine="openpyxl")
        yield buf.getvalue()

    @reactive.effect
    @reactive.event(input.e_marquer)
    def _marquer():
        d = a_exporter()
        if len(d) == 0:
            return
        try:
            dl.marquer_exporte(list(d["id_piece"].unique()))
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        ui.notification_show("Pieces marquees comme exportees", type="message")
        rafraichir()

    # ---------------- controles et referentiel --------------------------------

    # Les anomalies suivent le meme perimetre que le brouillard : une caisse ne
    # voit que ses propres pieces. Montrer a Pissy un tiers manquant sur une
    # piece de Tampouy n'a aucun sens - elle ne peut rien y faire, et le bruit
    # finit par rendre l'onglet illisible, donc inutilise. Seul le comptable,
    # qui valide et exporte pour toute la maison, voit l'ensemble.
    #
    # Les soldes de caisse suivent la meme logique : un journal n'est affiche
    # que si le poste a des ecritures dedans.
    @reactive.calc
    def anomalies_vue():
        u = req(util())
        return dl.anomalies(donnees(), ref(),
                            centre=None if est_comptable() else u["centre"])

    # Quand des pieces citent un tiers absent du referentiel, il n'y a rien a
    # ressaisir : le code est deja dans les ecritures, il suffit de recreer la
    # fiche. On le propose au comptable plutot que de le faire en douce, parce
    # que l'intitule reconstruit depuis le code merite d'etre relu.
    @render.ui
    def c_reparation():
        if not est_comptable():
            return None
        manquants = dl.tiers_manquants(donnees(), ref())
        if not manquants:
            return None
        return ui.div(
            {"style": "background:#FFF6E5;border-left:4px solid #E0A030;"
                      "padding:10px 14px;margin-bottom:12px"},
            ui.tags.b(f"{len(manquants)} tiers cite par des pieces mais absent du referentiel."),
            ui.p({"style": "margin:6px 0"},
                 "Ces codes ont ete crees a la saisie puis perdus, en general parce que le "
                 "referentiel a ete remplace par une copie plus ancienne. Les recreer debloque "
                 "l'export ; l'intitule sera reconstruit depuis le code et reste modifiable "
                 "dans l'onglet Referentiel."),
            ui.p({"style": "margin:6px 0;font-size:12px;color:#4A5B70"}, ", ".join(manquants[:12])
                 + (" ..." if len(manquants) > 12 else "")),
            ui.input_action_button("c_reparer", "Recreer ces tiers", class_="btn-primary"),
        )

    @reactive.effect
    @reactive.event(input.c_reparer)
    def _reparer():
        crees = dl.reparer_tiers_manquants(donnees(), ref())
        ui.notification_show(
            f"{len(crees)} tiers recree(s)" if crees else "Aucun tiers a recreer",
            type="message")
        rafraichir()

    @render.data_frame
    def c_table():
        a = anomalies_vue()
        if len(a) == 0:
            a = pd.DataFrame([{"gravite": "", "piece": "",
                                "anomalie": "Aucune anomalie sur les pieces enregistrees."}])
        return render.DataGrid(a, selection_mode="none", width="100%")

    @render.data_frame
    def r_comptes():
        return render.DataGrid(ref()["comptes"], selection_mode="none", width="100%")

    @render.data_frame
    def r_tiers():
        return render.DataGrid(ref()["tiers"], selection_mode="none", width="100%")

    @render.data_frame
    def r_utilisateurs():
        u_aff = ref()["utilisateurs"][["identifiant", "nom", "role", "centre", "actif"]]
        return render.DataGrid(u_aff, selection_mode="row", width="100%")

    @reactive.effect
    @reactive.event(input.r_ajouter_utilisateur)
    def _ajouter_utilisateur():
        # Un clic sur un formulaire deja vide (par exemple un deuxieme clic
        # apres une creation reussie, le formulaire n'ayant pas encore ete
        # retape) ne doit produire aucun message : ce n'est pas une erreur de
        # l'utilisateur, juste un clic qui n'a plus rien a faire.
        if not str(input.r_id_utilisateur() or "").strip():
            return
        # Desactive le bouton des le premier clic : un double-clic (souris ou
        # geste involontaire) ne doit jamais declencher une deuxieme tentative
        # de creation avant que la premiere ait fini d'ecrire le fichier.
        ui.update_action_button("r_ajouter_utilisateur", disabled=True)
        try:
            dl.ajouter_utilisateur(
                input.r_id_utilisateur(), input.r_nom_utilisateur(), input.r_role_utilisateur(),
                input.r_centre_utilisateur(), input.r_code_utilisateur())
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Utilisateur cree", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter_utilisateur", disabled=False)

    @reactive.effect
    @reactive.event(input.r_desactiver_utilisateur)
    def _desactiver_utilisateur():
        sel = r_utilisateurs.data_view(selected=True)
        if len(sel) == 0:
            ui.notification_show("Choisir d'abord un utilisateur.", type="warning")
            return
        if util() is not None and sel["identifiant"].iloc[0] == util().get("identifiant"):
            ui.notification_show("Impossible de desactiver le compte actuellement connecte.", type="error")
            return
        try:
            dl.desactiver_utilisateur(sel["identifiant"].iloc[0])
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Utilisateur desactive", type="message")
            rafraichir()

    @reactive.effect
    @reactive.event(input.r_ajouter)
    def _ajouter_tiers():
        if not str(input.r_code() or "").strip():
            return
        ui.update_action_button("r_ajouter", disabled=True)
        try:
            dl.ajouter_tiers(str(input.r_code() or "").strip().upper(),
                              str(input.r_nom() or "").strip().upper(),
                              input.r_collectif())
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Tiers cree", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter", disabled=False)

    @reactive.effect
    @reactive.event(input.r_ajouter_compte)
    def _ajouter_compte():
        if not str(input.r_num_compte() or "").strip():
            return
        ui.update_action_button("r_ajouter_compte", disabled=True)
        try:
            dl.ajouter_compte(str(input.r_num_compte() or "").strip(),
                               str(input.r_intitule_compte() or "").strip(),
                               input.r_nature_compte(),
                               tiers_obligatoire="oui" if input.r_tiers_obligatoire() else "non",
                               depense_courante="oui" if input.r_compte_courante() else "non")
        except Exception as e:
            ui.notification_show(str(e), type="error")
        else:
            ui.notification_show("Compte cree", type="message")
            panneau_ouvert.set(None)
            rafraichir()
        finally:
            ui.update_action_button("r_ajouter_compte", disabled=False)

    @reactive.effect
    @reactive.event(input.r_soldes)
    def _soldes():
        for j in ref()["journaux"]["journal"]:
            v = get_input(_id_journal(j))
            if v is not None:
                try:
                    dl.maj_solde_ouverture(j, v)
                except Exception:
                    pass
        ui.notification_show("Soldes d'ouverture enregistres", type="message")
        panneau_ouvert.set(None)
        rafraichir()

    @reactive.effect
    @reactive.event(input.r_nouvelle_annee)
    def _nouvelle_annee():
        n = dl.nouvelle_annee_academique()
        panneau_ouvert.set(None)
        ui.notification_show(
            f"Nouvelle annee academique demarree : {n} tiers retires des listes de saisie "
            "(rien n'est supprime, l'historique reste intact).", type="message")


app = App(app_ui, server)