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
import logging
import os
import re
from datetime import date
from pathlib import Path



import pandas as pd
from dotenv import load_dotenv
from shiny import App, reactive, render, req, ui

load_dotenv()  # avant l'import de logic.donnees : c'est la que le pool de
                # connexions Postgres est cree, il a besoin de DATABASE_URL.

# Journalisation applicative : un seul appel a basicConfig par processus,
# ici (le point d'entree), jamais dans logic/donnees.py qui ne fait
# qu'ecrire sur le logger deja configure - sinon un import de logic.donnees
# depuis un autre script (import_historique.py, un shell interactif...)
# reconfigurerait les handlers a chaque fois.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(os.environ.get("HAKILI_LOG_FILE", "hakili.log"), encoding="utf-8"),
              logging.StreamHandler()],
)

import logic.donnees as dl
import logic.modeles as md


STATUTS = {"saisie": "En attente de validation", "validee": "Validee",
           "a_corriger": "A corriger", "exportee": "Exportee vers Sage"}

# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

/* ---------------------------------------------------------------------
   Design tokens. Palette derivee du logo Hakili Lab (bleu/vert), echelle
   d'espacement et d'ombres coherente reprise par tous les composants
   ci-dessous - rien n'est defini "en dur" ailleurs que dans une classe
   partagee, pour que ce fichier reste le seul endroit a changer.
   ------------------------------------------------------------------ */
:root {
  --encre: #0F1B2A; --gris: #4A5B70; --gris-clair: #93A5BC;
  --bord: #E1E6ED; --bord-fort: #C7CFDA; --fond: #F4F6F9; --surface: #FFFFFF;
  --bleu: #0F65B8; --bleu-sombre: #0B4E90; --bleu-teinte: #EAF2FB;
  --vert: #4C8C2B; --vert-teinte: #E9F4E1;
  --rouge: #B23A2E; --rouge-teinte: #FBEAE8;
  --ambre: #9A6B12; --ambre-teinte: #FBF1DD;
  --rayon-s: 6px; --rayon: 10px; --rayon-l: 14px;
  --ombre-s: 0 1px 2px rgba(15,27,42,.06);
  --ombre: 0 2px 10px rgba(15,27,42,.07), 0 1px 2px rgba(15,27,42,.05);
  --ombre-l: 0 16px 40px rgba(15,27,42,.14);
}

* { box-sizing:border-box; }
body { background:var(--fond); color:var(--encre);
  font-family:'Inter',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-size:14.5px; line-height:1.5; -webkit-font-smoothing:antialiased; }
h1, h2, h3, h4, h5 { font-family:inherit; color:var(--encre); }
::selection { background:var(--bleu-teinte); color:var(--encre); }

/* Ascenseur discret, coherent sur les grilles et le corps de page - une
   appli professionnelle ne laisse jamais l'ascenseur natif du systeme
   dominer une interface par ailleurs entierement dessinee. */
::-webkit-scrollbar { width:10px; height:10px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background:var(--bord-fort); border-radius:99px; border:2px solid var(--fond); }
::-webkit-scrollbar-thumb:hover { background:var(--gris-clair); }

/* ---------------------------------------------------------------------
   Bandeau superieur
   ------------------------------------------------------------------ */
.bandeau { background:var(--encre); color:#fff; padding:16px 26px;
  display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  border-bottom:3px solid var(--vert); }
.logo-bandeau { height:32px; width:auto; display:block; }
.logo-connexion { height:118px; width:auto; display:block; margin:0 auto 14px; }
.bandeau .soc { display:flex; align-items:center; }
.bandeau .soc span { font-weight:400; letter-spacing:.02em; text-transform:none;
  color:var(--gris-clair); font-size:12.5px; padding-left:18px; margin-left:18px;
  border-left:1px solid rgba(255,255,255,.16); }
.bandeau .qui { margin-left:auto; text-align:right; font-size:12px; color:var(--gris-clair);
  line-height:1.45; }
.bandeau .qui b { color:#fff; display:block; font-size:13.5px; font-weight:600; }
.bandeau .qui a { color:var(--gris-clair) !important; }
.bandeau .qui a:hover { color:#fff !important; }

/* Barre d'onglets : un bandeau de navigation propre, pas une liste de
   liens soulignes - registre visuel d'une appli de gestion (Sage, Odoo),
   pas d'un blog. */
.nav-tabs { background:var(--fond); border-bottom-color:var(--bord);
  padding:10px 26px 0; margin:-24px -26px 22px; }
.nav-tabs > li > a { color:var(--gris); font-size:14.5px; font-weight:700; padding:10px 16px; }
.nav-tabs > li.active > a { border-bottom:2px solid var(--vert) !important; color:var(--encre) !important; }

/* Corps de page : la navigation vit dans sa propre bande blanche, le
   contenu dans le fond gris - separation nette entre structure et donnees. */
.corps-page { padding:24px 26px 40px; max-width:1400px; margin:0 auto; }

/* ---------------------------------------------------------------------
   Cartes : unite visuelle de base de toute l'appli
   ------------------------------------------------------------------ */
.carte { background:var(--surface); border:1px solid var(--bord); border-radius:var(--rayon);
  padding:20px 22px; margin-bottom:20px; box-shadow:var(--ombre-s); }
.carte-entete { display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }
.carte-entete h4 { margin:0; }
.carte h4 { margin:0 0 16px 0; font-size:11px; text-transform:uppercase;
  letter-spacing:.08em; color:var(--gris); font-weight:700; }

/* Variante compacte : formulaire de saisie, ou l'essentiel doit tenir sans
   defiler - memes codes visuels, juste moins d'air entre les champs. Ne
   change rien ailleurs dans l'appli (classe ajoutee, .carte inchangee). */
.carte-compacte { padding:16px 20px; }
.carte-compacte h4 { margin-bottom:12px; }
.carte-compacte .form-group { margin-bottom:10px; }
.carte-compacte > .row { margin-bottom:0; }

/* Bouton discret "+" qui ouvre un mini-formulaire : jamais un gros bloc
   affiche par defaut, un geste de plus pour agir. */
.btn-icone { width:27px; height:27px; border-radius:50%; border:1px solid var(--bord);
  background:var(--surface); color:var(--gris); font-size:16px; line-height:1; cursor:pointer;
  display:flex; align-items:center; justify-content:center; padding:0; transition:.12s;
  /* Ce bouton n'est pas une variante Bootstrap (btn-primary, btn-secondary...) :
     sans ces variables, l'etat "presse" retombe sur la regle Bootstrap
     ".btn-outline-default, .btn-default:not(.btn-primary, ...)" (bootstrap.min.css)
     qui met --bs-btn-active-bg a #404040 (gris tres fonce). Cette regle a une
     specificite plus elevee (0,2,0, a cause du :not()) que ".btn-icone" seul
     (0,1,0) : sans !important elle gagne quand meme et le bouton flashe en
     sombre a chaque clic au lieu de rester dans ses propres tons discrets. */
  --bs-btn-active-bg:var(--bleu-teinte) !important; --bs-btn-active-color:var(--bleu) !important;
  --bs-btn-active-border-color:var(--bleu) !important; }
.btn-icone:hover { background:var(--bleu-teinte); border-color:var(--bleu); color:var(--bleu); }
.btn-texte { border:none; background:none; color:var(--bleu); font-size:12.5px;
  font-weight:600; padding:0; cursor:pointer;
  --bs-btn-active-bg:transparent !important; --bs-btn-active-color:var(--bleu) !important;
  --bs-btn-active-border-color:transparent !important; }
.btn-texte:hover { text-decoration:underline; }
.popover-form { min-width:230px; }
.popover-form .form-group:last-child { margin-bottom:0; }
.param-item { padding:4px 0; }

/* Panneau flottant : positionne au-dessus du contenu, ne pousse jamais le
   tableau vers le bas. Rendu par le serveur (jamais duplique), seul son
   positionnement vient du CSS. */
.flottant-conteneur { position:relative; display:inline-block; }
.panneau-flottant { position:absolute; top:100%; z-index:40; margin-top:8px;
  background:var(--surface); border:1px solid var(--bord); border-radius:var(--rayon);
  box-shadow:var(--ombre-l); padding:16px 18px; }
.flottant-conteneur.a-droite .panneau-flottant { right:0; }
.flottant-conteneur.a-gauche .panneau-flottant { left:0; }
.param-aide { font-size:11.5px; color:var(--gris); margin:6px 0 0 0; }

/* ---------------------------------------------------------------------
   Champs de formulaire : coherents partout, jamais l'apparence par
   defaut du navigateur. Aucun texte d'exemple dans les champs vides -
   un libelle clair au-dessus suffit, le champ reste vide tant que
   personne n'a rien saisi.
   ------------------------------------------------------------------ */
.form-group label, label.control-label { font-size:12.5px; font-weight:600;
  color:var(--gris); margin-bottom:5px; text-transform:uppercase; letter-spacing:.03em; }
.form-control, .selectize-input, select.form-select { border-radius:var(--rayon-s);
  border-color:var(--bord); font-size:14px; color:var(--encre); }
.form-control::placeholder { color:transparent; }
.form-control:focus, .selectize-input.focus, .selectize-control.focus > .selectize-input {
  border-color:var(--bleu) !important; box-shadow:0 0 0 3px var(--bleu-teinte) !important; }
.selectize-dropdown { border-color:var(--bord); box-shadow:var(--ombre); border-radius:var(--rayon-s); }
.selectize-dropdown .active { background:var(--bleu-teinte); color:var(--encre); }

.num { font-family:ui-monospace,Menlo,Consolas,monospace; font-variant-numeric:tabular-nums; }

/* ---------------------------------------------------------------------
   Badges de statut : pastilles pleines, memes teintes que les rubans,
   pour une lecture immediate du circuit de validation.
   ------------------------------------------------------------------ */
.cell-statut-saisie, .cell-statut-validee, .cell-statut-a_corriger, .cell-statut-exportee {
  font-weight:600; font-size:12.5px; }
.cell-statut-saisie { background:var(--fond); color:var(--gris); }
.cell-statut-validee { background:var(--vert-teinte); color:#2E6B1A; }
.cell-statut-a_corriger { background:var(--rouge-teinte); color:var(--rouge); }
.cell-statut-exportee { background:var(--bleu-teinte); color:var(--bleu-sombre); }

/* Rubans de message : bordure gauche coloree plutot qu'un simple fond
   teinte, registre "notification" d'une appli metier plutot qu'une
   bulle de chat. */
.ruban { padding:11px 16px; border-radius:var(--rayon-s); margin:14px 0; font-size:13px;
  border-left:3px solid transparent; }
.ruban.ok { background:var(--vert-teinte); color:#2E6B1A; border-left-color:var(--vert); }
.ruban.ko { background:var(--rouge-teinte); color:var(--rouge); border-left-color:var(--rouge); }
.ruban.att { background:var(--fond); color:var(--gris); border-left-color:var(--bord-fort); }

table.apercu { width:100%; border-collapse:collapse; }
table.apercu th { text-align:left; font-size:11px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--gris); border-bottom:1px solid var(--bord); padding:9px 8px; font-weight:700; }
table.apercu td { padding:9px 8px; border-bottom:1px solid #EEF1F5; font-size:13.5px; }
table.apercu td.m { text-align:right; font-family:ui-monospace,Menlo,Consolas,monospace; }
table.apercu tr.tresorerie td { background:#FAFBFD; font-style:italic; color:var(--gris); }
table.apercu tfoot td { font-weight:700; border-top:2px solid var(--encre); }

/* Grilles natives Shiny (Brouillard, Validation, Referentiel, Controles) :
   memes codes visuels que le reste de l'appli - bordure, radius, entetes
   discrets, ligne survolee/selectionnee marquee en bleu de marque. */
.shiny-data-grid { border:1px solid var(--bord) !important; border-radius:var(--rayon) !important;
  overflow:hidden; font-size:13.5px; }
.shiny-data-grid table { width:100%; }
.shiny-data-grid thead th { background:#FAFBFD !important; color:var(--gris) !important;
  font-size:11px !important; text-transform:uppercase; letter-spacing:.05em; font-weight:700 !important;
  border-bottom:1px solid var(--bord) !important; }
.shiny-data-grid tbody td { border-bottom:1px solid #EEF1F5 !important; }
.shiny-data-grid tbody tr:hover td { background:#FAFBFD !important; }
.shiny-data-grid tbody tr[aria-selected="true"] td { background:var(--bleu-teinte) !important; }
.shiny-data-grid input { border-radius:var(--rayon-s) !important; border-color:var(--bord) !important;
  font-size:12.5px !important; }

/* ---------------------------------------------------------------------
   Indicateurs cles (KPI) : label discret, valeur en avant, alignement
   strict quel que soit le nombre de cartes affichees.
   ------------------------------------------------------------------ */
/* Bandeau d'indicateurs : une seule bordure d'ensemble, chaque chiffre
   dans une cellule fine separee par un simple filet - un en-tete
   d'information, jamais une rangee de cartes qui reclament chacune de
   l'attention. */
/* Bandeau d'indicateurs : une grille fixe a 3 colonnes (jamais un
   flex-wrap dont les rangees varient avec la largeur d'ecran), une seule
   bordure d'ensemble et un simple filet entre cellules - un en-tete
   d'information compact, jamais une rangee de cartes qui reclament
   chacune de l'attention. */
.bandeau-indicateurs { display:grid; grid-template-columns:repeat(3, 1fr); border:1px solid var(--bord);
  border-radius:var(--rayon); background:var(--surface); overflow:hidden; margin-bottom:16px; }
@media (max-width: 720px) { .bandeau-indicateurs { grid-template-columns:repeat(2, 1fr); } }
.stat { padding:9px 16px; display:flex; align-items:baseline; gap:8px; white-space:nowrap;
  border-top:1px solid var(--bord); border-right:1px solid var(--bord); margin-top:-1px; }
.stat:nth-child(-n+3) { border-top:none; margin-top:0; }
.stat:nth-child(3n) { border-right:none; }
.stat .l { font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--gris);
  font-weight:700; }
.stat .v { font-family:ui-monospace,Menlo,Consolas,monospace; font-size:15px; font-weight:600;
  color:var(--encre); margin-left:auto; }

/* ---------------------------------------------------------------------
   Boutons : hierarchie nette entre action principale, secondaire et
   destructive - jamais une rangee de boutons uniformes.
   ------------------------------------------------------------------ */
.btn { border-radius:var(--rayon-s); font-weight:600; font-size:13.5px; padding:8px 16px;
  transition:background .12s, border-color .12s, box-shadow .12s; box-shadow:none; }
.btn:focus, .btn:focus-visible { box-shadow:0 0 0 3px var(--bleu-teinte) !important; }
.btn-primary { background:var(--bleu); border-color:var(--bleu); }
.btn-primary:hover { background:var(--bleu-sombre); border-color:var(--bleu-sombre); }
.btn-sm { padding:5px 13px; font-size:12.5px; }
.btn-discret { background:var(--surface); border:1px solid var(--bord); color:var(--gris);
  --bs-btn-active-bg:var(--fond) !important; --bs-btn-active-color:var(--encre) !important;
  --bs-btn-active-border-color:var(--bord-fort) !important; }
.btn-discret:hover { background:var(--fond); border-color:var(--bord-fort); color:var(--encre); }
.btn-danger-discret { background:var(--surface); border:1px solid var(--bord); color:var(--rouge);
  --bs-btn-active-bg:var(--rouge-teinte) !important; --bs-btn-active-color:var(--rouge) !important;
  --bs-btn-active-border-color:var(--rouge) !important; }
.btn-danger-discret:hover { background:var(--rouge-teinte); border-color:var(--rouge); }

/* Barre d'actions compacte au-dessus d'un tableau : action principale
   pleine, action secondaire discrete, aide alignee a droite. */
.barre-actions { display:flex; align-items:center; gap:8px; margin:-4px 0 16px 0; flex-wrap:wrap; }
.barre-actions .aide { margin-left:auto; font-size:12px; color:var(--gris-clair); font-style:italic; }

/* Disclosure progressif sur les listes longues du Referentiel : le lien
   "Afficher tout" ne fait rien d'autre que basculer une valeur reactive,
   c'est le rendu Python qui decide combien de lignes partent au navigateur. */
.lien-etendre { display:block; margin-top:8px; font-size:12.5px; }

/* Tableau de repartition (mois/nature/montant) du modele "Encaissement" :
   largeurs de colonnes fixes pour qu'il ne deborde jamais de sa carte,
   quel que soit le texte choisi (ex. "Solde / Retard") ou le nombre de
   lignes ajoutees via "+ Ajouter un mois". Classe dediee : ne touche pas
   au tableau "apercu" de l'ecriture generee (colonnes differentes). */
table.apercu-repartition { table-layout:fixed; }
table.apercu-repartition th:nth-child(1), table.apercu-repartition td:nth-child(1) { width:29%; }
table.apercu-repartition th:nth-child(2), table.apercu-repartition td:nth-child(2) { width:31%; }
table.apercu-repartition th:nth-child(3), table.apercu-repartition td:nth-child(3) { width:26%; }
table.apercu-repartition th:nth-child(4), table.apercu-repartition td:nth-child(4) { width:14%; }
table.apercu-repartition select, table.apercu-repartition input.form-control { min-width:0; }

/* ---------------------------------------------------------------------
   Page de connexion
   ------------------------------------------------------------------ */
.connexion { max-width:400px; margin:9vh auto; }
.connexion .carte { box-shadow:var(--ombre-l); border-top:3px solid var(--bleu); }

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
                 ui.tags.link(rel="icon", type="image/x-icon", href="favicon.ico"),
                 ui.tags.link(rel="apple-touch-icon", href="apple-touch-icon.png"),
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
            if m.get("retire"):
                continue
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
                    {"class": "carte carte-compacte"},
                    ui.h4("Operation"),
                    ui.row(
                        ui.column(8, ui.input_select("m_modele", "Modele d'operation",
                                                       choices=_modeles_groupes(r))),
                        ui.column(4, ui.input_date("m_date", "Date de l'operation",
                                                    value=date.today(), format="dd/mm/yyyy")),
                    ),
                    # Le journal est impose par le modele dans presque tous
                    # les cas (cf. _modele_journal/_garde_journal plus bas,
                    # qui le remettent en place et avertissent si on le
                    # force) : un selecteur en permanence a l'ecran
                    # inviterait a le changer pour rien. panel_conditional
                    # ne fait que le masquer cote client, jamais cote
                    # serveur - la valeur reste lue normalement par
                    # input.m_journal(), aucun autre code n'a besoin de
                    # changer. Seule "Ecriture libre" a vraiment besoin du
                    # choix.
                    ui.panel_conditional(
                        "input.m_modele == 'libre'",
                        ui.row(ui.column(6, ui.input_select(
                            "m_journal", "Journal",
                            choices={j: f"{j} - {i}" for j, i in
                                     zip(r["journaux"]["journal"], r["journaux"]["intitule"])}))),
                    ),
                    ui.panel_conditional(
                        "input.m_modele != 'libre'",
                        ui.output_ui("m_journal_texte"),
                    ),
                    ui.output_ui("m_champs"),
                    ui.output_ui("m_note_wrap"),
                )),
                ui.column(6, ui.div(
                    {"class": "carte carte-compacte"},
                    ui.h4("Ecriture generee"),
                    ui.output_ui("m_apercu"),
                    ui.output_ui("m_ruban"),
                    ui.input_action_button("m_enregistrer", "Enregistrer la piece", class_="btn-primary"),
                    ui.input_action_button("m_vider", "Vider", class_="btn-discret btn-sm"),
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
                # Ligne 1 : les filtres, qui decident ce qui s'affiche.
                ui.div(
                    {"style": "display:flex; gap:16px; flex-wrap:wrap; margin-bottom:16px"},
                    ui.div({"style": "flex:1 1 200px"}, ui.input_select(
                        "b_statut", "Statut", choices=["Tous"] + list(STATUTS.values()))),
                    ui.div({"style": "flex:1 1 200px"}, ui.input_select(
                        "b_journal", "Journal", choices=["Tous"] + list(r["journaux"]["journal"]))),
                    ui.div({"style": "flex:2 1 320px"}, ui.input_date_range(
                        "b_periode", "Periode", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                ),
                # Ligne 2 : un bandeau d'indicateurs compact - une seule
                # bordure d'ensemble avec des separateurs fins entre chaque
                # chiffre, jamais six cartes independantes qui gaspillent de
                # la hauteur pour un seul nombre chacune.
                ui.div({"class": "bandeau-indicateurs"}, ui.output_ui("b_stats")),
                # Ligne 3 : les actions sur la piece selectionnee, juste
                # au-dessus du tableau qu'elles concernent.
                ui.div(
                    {"class": "barre-actions"},
                    ui.input_action_button("b_corriger", "Corriger la piece", class_="btn-sm btn-primary"),
                    ui.input_action_button("b_supprimer", "Supprimer", class_="btn-sm btn-danger-discret"),
                    ui.span({"class": "aide"}, "Selectionnez une ligne dans le tableau ci-dessous."),
                ),
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
                # Les deux actions et leur motif partagent une seule ligne :
                # le motif ne sert qu'au renvoi, mais il occupe l'espace
                # libre plutot que de s'empiler seul en dessous.
                ui.div(
                    {"style": "display:flex; align-items:flex-end; gap:12px; flex-wrap:wrap"},
                    ui.input_action_button("v_valider", "Valider les pieces choisies",
                                            class_="btn-primary"),
                    ui.input_action_button("v_rejeter", "Renvoyer pour correction",
                                            class_="btn-discret"),
                    ui.div({"style": "flex:1 1 240px; margin-bottom:0"},
                           ui.input_text("v_motif", "Motif du renvoi")),
                ),
            ),
            value="validation",
        )

    def onglet_export(r):
        return ui.nav_panel(
            "Export Sage", ui.br(),
            ui.div(
                {"class": "carte"},
                ui.h4("Fichier d'import Sage"),
                ui.div(
                    {"style": "display:flex; align-items:flex-end; gap:24px; flex-wrap:wrap"},
                    ui.div({"style": "flex:1 1 260px"}, ui.input_date_range(
                        "e_periode", "Periode", start=date.today().replace(day=1), end=date.today(),
                        format="dd/mm/yyyy", separator=" au ")),
                    ui.div({"style": "flex:0 1 220px"}, ui.input_select(
                        "e_journal", "Journal", choices=["Tous"] + list(r["journaux"]["journal"]))),
                    ui.div({"style": "padding-bottom:9px"},
                           ui.input_checkbox("e_deja", "Inclure les pieces deja exportees", False)),
                ),
                ui.output_ui("e_resume"),
                ui.div(
                    {"class": "barre-actions"},
                    ui.download_button("e_txt", "Telecharger le fichier Sage (.txt)", class_="btn-primary"),
                    ui.download_button("e_xlsx", "Telecharger en Excel", class_="btn-discret"),
                    ui.input_action_button("e_marquer", "Marquer comme exportees", class_="btn-discret"),
                ),
                ui.output_data_frame("e_table"),
            ),
            value="export",
        )

    def onglet_controles():
        return ui.nav_panel(
            "Controles", ui.br(),
            ui.div({"class": "carte"}, ui.h4("Anomalies detectees"),
                   ui.output_ui("c_reparation"),
                   ui.output_data_frame("c_table"),
                   ui.output_ui("c_reclassement")),
            value="controles",
        )


    # Shiny n'accepte que lettres, chiffres et souligne dans un identifiant de
    # champ. Un code journal peut contenir autre chose - "CBI" vient tel quel
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

    # Disclosure progressif des listes longues du Referentiel : repliees par
    # defaut (LIGNES_APERCU lignes), un lien les deplie/replie entierement.
    # Ne change rien aux donnees ni au filtrage, seulement le nombre de
    # lignes envoyees au navigateur.
    LIGNES_APERCU = 8
    etendu_comptes = reactive.value(False)
    etendu_tiers = reactive.value(False)
    etendu_utilisateurs = reactive.value(False)

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
                ui.output_data_frame("r_comptes"),
                ui.output_ui("lien_comptes"))),
            ui.column(6, ui.div(
                {"class": "carte"},
                entete("Comptes de tiers", "tiers" if comptable else None, "panneau_tiers"),
                ui.output_data_frame("r_tiers"),
                ui.output_ui("lien_tiers"))),
        )]

        if comptable:
            blocs.append(ui.div(
                {"class": "carte"},
                entete("Utilisateurs", "utilisateur", "panneau_utilisateur"),
                ui.p({"class": "param-aide"},
                     "Un identifiant par personne, pas par centre : c'est ce qui permet de savoir "
                     "qui a fait quoi. Desactiver ne supprime rien, l'historique reste intact."),
                ui.output_data_frame("r_utilisateurs"),
                ui.output_ui("lien_utilisateurs"),
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
            ui.input_text("r_num_compte", "Numero"),
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
            ui.input_text("r_code", "Code tiers"),
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
            ui.input_text("r_id_utilisateur", "Identifiant"),
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
        tabs.append(onglet_controles())
        tabs.append(onglet_referentiel(u, r))
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
                    ui.tags.img({"class": "logo-bandeau", "src": "hakili_logo_header.png", "alt": "Hakili Lab"}),
                    ui.div({"class": "soc"}, ui.tags.span("Gestion de caisse")),
                    ui.div(
                        {"class": "qui"}, ui.tags.b(u.get("nom")),
                        f"Centre {u.get('centre')} - {role_txt}",
                        ui.input_action_link("deconnexion", "Fermer la session",
                                              style="display:block")),
                ),
                ui.div({"class": "corps-page"}, ui.output_ui("corps")),
            )

        entete = ui.div({"style": "text-align:center;margin-bottom:18px"},
                         ui.tags.img({"class": "logo-connexion", "src": "hakili_logo_full.png",
                                      "alt": "Hakili Lab"}),
                         ui.tags.div({"style": "font-size:12.5px;color:var(--gris);margin-top:2px"},
                                     "Gestion de caisse"))

        r = ref()
        centres_actifs = r["centres"][r["centres"]["actif"] == "oui"]
        choix = dict(zip(centres_actifs["code_centre"], centres_actifs["intitule"]))
        return ui.div(
            {"class": "connexion"}, entete,
            ui.div(
                {"class": "carte"},
                ui.h4("Connexion"),
                ui.input_select("l_centre", "Centre", choices=choix),
                ui.input_text("l_id", "Nom d'utilisateur"),
                ui.input_password("l_code", "Code personnel"),
                ui.input_action_button("l_ok", "Se connecter", class_="btn-primary"),
                ui.output_ui("l_msg"),
            ),
        )

    # Corrige le 10/09/2026 : page() appelait onglets(u) directement, qui lit
    # ref() -> _disque() (sondage 0,5 s sur les ecritures des 5 centres,
    # cf. plus haut). Consequence : chaque piece enregistree n'importe ou
    # invalidait page() entierement - tous les onglets recrees, m_modele et
    # m_journal remis a leur valeur par defaut, formulaire de Saisie en
    # cours efface (c'est ce qui donnait l'impression que l'ecran
    # "tremblait" et rendait la saisie difficile). La structure des onglets
    # ne depend en realite que du role, fixe pour toute la session : on la
    # construit donc une seule fois par connexion, dans une sortie separee
    # (corps), avec reactive.isolate() pour que la lecture de ref() a
    # l'interieur d'onglets(u) ne cree pas de dependance a _disque(). page()
    # ne depend plus que de util() (connexion/deconnexion). Les donnees
    # affichees a l'interieur des onglets (tableaux, soldes...) restent
    # dans leurs propres sorties (b_table, v_table, m_apercu...), deja
    # correctement isolees plus bas dans ce fichier, et continuent de se
    # rafraichir normalement.
    @render.ui
    def corps():
        u = req(util())
        with reactive.isolate():
            tabs = onglets(u)
        return ui.navset_tab(*tabs, id="onglets")

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
        # Le nom d'utilisateur n'est pas sensible a la casse : AFIYA, Afiya et
        # afiya designent la meme personne. La comparaison se fait toujours
        # dans le centre choisi dans le formulaire - un identifiant valide
        # mais d'un autre centre est refuse ici, pas seulement absent d'une
        # liste qui n'existe plus.
        #
        # Verifie directement en base (dl.tenter_connexion), jamais via le
        # referentiel mis en cache cote session : la verification du code,
        # le verrouillage anti brute-force et la mise a niveau bcrypt d'un
        # code encore en clair doivent toujours porter sur l'etat le plus
        # recent, pas sur une copie potentiellement vieille de 0.5s.
        saisi = str(input.l_id() or "").strip().lower()
        statut, u, minutes = dl.tenter_connexion(saisi, input.l_centre(), input.l_code())
        if statut == "ok":
            util.set(u)
            login_msg.set(None)
        elif statut == "inactif":
            login_msg.set("Ce compte a ete desactive.")
        elif statut == "verrouille":
            login_msg.set(f"Trop de tentatives incorrectes. Reessayer dans {minutes} min.")
        else:
            login_msg.set("Centre, nom d'utilisateur ou code incorrect.")

    @reactive.effect
    @reactive.event(input.deconnexion)
    def _deconnexion():
        util.set(None)

    # ---------------- formulaire "encaissement" : lignes de repartition ------
    #
    # Un reglement peut couvrir plusieurs mois (frais du mois, avance, ou
    # rattrapage d'un mois passe) : le champ "repartition" du modele
    # "encaissement" (cf. logic.modeles) n'est pas un widget simple mais un
    # petit tableau dont le nombre de lignes varie. Chaque ligne a un
    # identifiant stable qui ne change jamais tant qu'elle existe
    # (m_rep_mois_<id>, m_rep_nature_<id>, m_rep_montant_<id>) : la premiere
    # ligne porte toujours l'identifiant 1 et ne peut pas etre retiree, les
    # suivantes sont ajoutees par "+ Ajouter un mois" (max 6, spec 2026).
    MAX_LIGNES_REPARTITION = 6
    rep_ids = reactive.value([1])
    rep_prochain_id = reactive.value(2)
    etendu_historique_tiers = reactive.value(False)
    # Un identifiant de ligne peut etre reutilise apres un "Vider" (le
    # compteur reprend a 2) : cet ensemble evite de re-enregistrer un effet
    # deja cree pour ce meme identifiant. Jamais purge - sans consequence,
    # l'effet ne fait rien de plus la seconde fois qu'il s'applique.
    rep_effets_crees = set()

    # Suggestion de mois selon la nature choisie (spec §4) : "Frais" propose
    # le mois calendaire en cours, "Avance" le mois suivant le dernier
    # mouvement connu du tiers sur son compte 411 (ou le mois en cours si
    # aucun historique), "Solde" ne propose rien - deviner un mauvais mois
    # de rattrapage serait pire que ne rien suggerer. Toujours modifiable
    # ensuite a la main : une suggestion de confort, jamais une validation
    # automatique.
    def _mois_suggere(nature, code_tiers):
        if nature == "avance" and code_tiers:
            hist = dl.dernieres_lignes_tiers(code_tiers, limite=1)
            if len(hist):
                dernier = md.mois_depuis_libelle(hist.iloc[0]["libelle"])
                if dernier:
                    return md.mois_suivant(dernier)
        if nature == "solde":
            return ""
        return md.MOIS_FR[date.today().month - 1]

    def _code_tiers_saisi():
        brut = get_input("ch_tiers")
        if not brut:
            return ""
        return dl.code_tiers_candidat(brut, "411", ref())

    # Lit les lignes actuellement affichees (une par mois reparti) pour en
    # faire la valeur du champ "repartition" - le rendu generique de
    # m_champs ignore ce type de champ, valeurs() vient les lire ici.
    def _lire_repartition():
        return [
            {"mois": get_input(f"m_rep_mois_{rid}", ""),
             "nature": get_input(f"m_rep_nature_{rid}", "frais"),
             "montant": get_input(f"m_rep_montant_{rid}", 0)}
            for rid in rep_ids()
        ]

    # Enregistre, pour une ligne donnee, l'effet qui rafraichit sa
    # suggestion de mois quand sa nature change, et (sauf pour la premiere
    # ligne, jamais retirable) le lien qui la supprime. Appelee une seule
    # fois a la creation de chaque ligne, cf. rep_effets_crees.
    def _fabrique_effets_repartition(rid):
        if rid in rep_effets_crees:
            return
        rep_effets_crees.add(rid)

        @reactive.effect
        @reactive.event(input[f"m_rep_nature_{rid}"])
        def _maj_mois_suggere():
            if req(input.m_modele()) != "encaissement":
                return
            nature = get_input(f"m_rep_nature_{rid}", "frais")
            ui.update_select(f"m_rep_mois_{rid}", selected=_mois_suggere(nature, _code_tiers_saisi()))

        if rid != 1:
            @reactive.effect
            @reactive.event(input[f"m_rep_suppr_{rid}"])
            def _retirer_ligne():
                rep_ids.set([x for x in rep_ids() if x != rid])

    _fabrique_effets_repartition(1)

    @reactive.effect
    @reactive.event(input.m_rep_ajouter)
    def _ajouter_ligne_repartition():
        if req(input.m_modele()) != "encaissement":
            return
        ids = rep_ids()
        if len(ids) >= MAX_LIGNES_REPARTITION:
            return
        nouveau = rep_prochain_id()
        rep_prochain_id.set(nouveau + 1)
        _fabrique_effets_repartition(nouveau)
        rep_ids.set(ids + [nouveau])

    def _ligne_repartition_ui(rid, premiere):
        # Corrige le 10/09/2026 (quater) : ces trois get_input() (donc
        # input[id]()) etaient lus sans isolate(), alors que cette fonction
        # est appelee depuis m_bloc_repartition() - un @render.ui qui DEFINIT
        # ces memes widgets. Consequence : m_bloc_repartition() dependait
        # reactivement de m_rep_mois_*/m_rep_nature_*/m_rep_montant_* de
        # TOUTES les lignes, donc modifier une seule ligne (meme apres
        # update_on="blur" ci-dessous) reconstruisait tout le tableau,
        # detruisant et recreant les <input> des AUTRES lignes non touchees.
        # Isoler ces lectures les rend "lecture de la valeur actuelle a la
        # construction" plutot que "dependance reactive" : m_bloc_repartition()
        # ne se reconstruit plus que pour une vraie raison structurelle
        # (ajout/suppression de ligne, changement de modele), jamais parce
        # qu'une valeur a change dans une ligne existante.
        with reactive.isolate():
            nature_val = get_input(f"m_rep_nature_{rid}", "frais")
            mois_defaut = get_input(f"m_rep_mois_{rid}", None)
            montant_val = get_input(f"m_rep_montant_{rid}", 0)
            if mois_defaut is None:
                mois_defaut = _mois_suggere(nature_val, _code_tiers_saisi())
        suppr = ui.tags.td() if premiere else ui.tags.td(
            ui.input_action_link(f"m_rep_suppr_{rid}", "Retirer", class_="lien-etendre"))
        return ui.tags.tr(
            ui.tags.td(ui.input_select(f"m_rep_mois_{rid}", None, choices=[""] + md.MOIS_FR,
                                        selected=mois_defaut)),
            ui.tags.td(ui.input_select(f"m_rep_nature_{rid}", None,
                                        choices={"frais": "Frais", "avance": "Avance",
                                                 "solde": "Solde / Retard"},
                                        selected=nature_val)),
            # update_on="blur" (10/09/2026, ter) : par defaut Shiny renvoie la
            # valeur au serveur a chaque frappe, ce qui reconstruisait tout le
            # panneau "Ecriture generee" (m_apercu/m_ruban, cf. plus bas) a
            # chaque chiffre tape - signale par Afiya comme "ca bouge" pendant
            # la saisie du montant. Avec "blur", la valeur n'est envoyee que
            # lorsqu'on quitte le champ (tabulation ou clic ailleurs) : aucune
            # perte fonctionnelle, juste un apercu qui se met a jour une fois
            # le montant termine plutot qu'a chaque caractere.
            ui.tags.td(ui.input_numeric(f"m_rep_montant_{rid}", None, value=float(montant_val or 0),
                                         min=0, step=500, update_on="blur")),
            suppr,
        )

    @render.ui
    def m_bloc_repartition():
        if req(input.m_modele()) != "encaissement":
            return None
        ids = rep_ids()
        table = ui.tags.table(
            {"class": "apercu apercu-repartition"},
            ui.tags.thead(ui.tags.tr(ui.tags.th("Mois"), ui.tags.th("Nature"),
                                      ui.tags.th("Montant"), ui.tags.th())),
            ui.tags.tbody(*[_ligne_repartition_ui(rid, rid == ids[0]) for rid in ids]),
        )
        if len(ids) < MAX_LIGNES_REPARTITION:
            pied = ui.input_action_link("m_rep_ajouter", "+ Ajouter un mois", class_="lien-etendre")
        else:
            pied = ui.div({"class": "ruban att", "style": "font-size:12px"},
                           "Six mois par piece au maximum : au-dela, traiter la creance ancienne "
                           "separement plutot que de tout regrouper ici.")
        return ui.div(table, pied)

    @reactive.effect
    @reactive.event(input.m_lien_historique)
    def _toggle_historique_tiers():
        etendu_historique_tiers.set(not etendu_historique_tiers())

    # Bloc historique (spec §3.2) : un resume compact toujours visible des
    # qu'un tiers est choisi, jamais calcule a partir d'un tarif ou d'un
    # statut - seulement ce que la base sait deja des dernieres lignes 411
    # de ce tiers.
    #
    # NOTE (7 sept., Claude) : le corps original de cette fonction a ete
    # perdu lors d'une erreur de manipulation de fichier et n'a pas pu etre
    # recupere avec certitude. Desactivee sans risque en attendant (elle ne
    # casse rien : cette seule vignette ne s'affiche pas) plutot que
    # reecrite au hasard - a refaire quand vous aurez confirme le
    # comportement voulu.
    @render.ui
    def m_bloc_historique():
        return None

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
    @reactive.event(input.m_journal, ignore_init=True)
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
    def m_journal_texte():
        m = md.modele_par_id(input.m_modele()) if input.m_modele() else None
        if m is None or not m.get("journal"):
            return None
        r = ref()
        lig = r["journaux"].loc[r["journaux"]["journal"] == m["journal"], "intitule"]
        intitule = lig.iloc[0] if len(lig) else m["journal"]
        return ui.p({"class": "param-aide", "style": "margin:-2px 0 12px"},
                    f"Journal : {m['journal']} - {intitule}")

    @render.ui
    def m_champs():
        m = md.modele_par_id(req(input.m_modele()))
        # Corrige le 10/09/2026 : ref() etait lu directement ici, donc ce
        # bloc (les champs Eleve/Compte/Montant... du formulaire de Saisie)
        # se reconstruisait a chaque ecriture comptable ailleurs (meme
        # cause que le correctif de page()/corps() plus haut) et effacait ce
        # que l'utilisateur etait en train de taper ou de choisir - c'etait
        # notamment le cas visible sur le champ "Eleve" en plein milieu
        # d'une recherche. Isoler cette lecture est sans perte
        # fonctionnelle : un tiers tape librement mais absent de la liste
        # reste gere normalement a l'enregistrement (resoudre_tiers,
        # cf. create=True plus bas) ; seule la fraicheur immediate de la
        # liste proposee change, pas la possibilite de saisir.
        with reactive.isolate():
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
                # Les tiers deja presents dans le plan de tiers sont
                # disponibles meme s'ils ne sont pas encore actifs pour
                # l'annee courante. Lorsqu'un ancien tiers est utilise,
                # resoudre_tiers() le reactive automatiquement.
                #
                # Le champ reste searchable : on peut choisir un tiers
                # existant par son nom ou son code.
                #
                # create=True permet egalement de saisir directement le
                # nom d'une nouvelle personne absente du plan de tiers.
                # La creation reelle du tiers est faite uniquement au moment
                # de l'enregistrement par _enregistrer(), via resoudre_tiers().
                sous = r["tiers"][
                    r["tiers"]["code_tiers"].str.startswith(ch["pref"])
                ]

                choix = {"": ""}

                for _, row in sous.iterrows():
                    code = str(row["code_tiers"])
                    nom = str(row["intitule"])
                    choix[code] = f"{nom}  ({code})"

                if defaut and defaut not in choix:
                    choix[defaut] = defaut

                widgets.append(
                    ui.input_selectize(
                        id_,
                        ch["l"],
                        choices=choix,
                        selected=defaut or "",
                        options={
                            "create": True,
                            "persist": False,
                            "placeholder": "Rechercher un nom ou saisir un nouveau nom..."
                        }
                    )
                )

                if ch.get("historique"):
                    widgets.append(ui.output_ui("m_bloc_historique"))
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
                    options={"placeholder": "Rechercher..."}))
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
                    options={"create": False, "placeholder": "Rechercher un nom..."}))
            elif t == "mois":
                widgets.append(ui.input_select(id_, ch["l"], choices=md.MOIS_FR,
                                                selected=defaut or md.MOIS_FR[date.today().month - 1]))
            elif t == "montant":
                valeur = defaut if defaut not in (None, "") else ch.get("defaut") or 0
                # update_on="blur" (10/09/2026, ter) : par defaut Shiny renvoie
                # la valeur au serveur a chaque frappe, ce qui reconstruisait
                # tout le panneau "Ecriture generee" (m_apercu/m_ruban, cf.
                # plus bas) a chaque chiffre tape - signale par Afiya comme
                # "ca bouge" pendant la saisie du montant. Avec "blur", la
                # valeur n'est envoyee que lorsqu'on quitte le champ
                # (tabulation ou clic ailleurs) : aucune perte fonctionnelle,
                # juste un apercu qui se met a jour une fois le montant
                # termine plutot qu'a chaque caractere.
                widgets.append(ui.input_numeric(id_, ch["l"], value=float(valeur), min=0, step=500,
                                                 update_on="blur"))
            elif t == "oui_non":
                widgets.append(ui.input_select(id_, ch["l"], choices={"oui": "Oui", "non": "Non"},
                                                selected=defaut or "non"))
            elif t == "choix":
                widgets.append(ui.input_select(id_, ch["l"], choices=ch["options"],
                                                selected=defaut or next(iter(ch["options"]))))
            elif t == "repartition":
                widgets.append(ui.output_ui("m_bloc_repartition"))
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
            "m_note", "Note pour le comptable (facultatif)", rows=2)

    @reactive.calc
    def valeurs():
        m = md.modele_par_id(req(input.m_modele()))
        # Corrige le 10/09/2026 (ter) : ref() etait lu directement ici. Comme
        # operation()/m_apercu()/m_ruban() dependent tous de valeurs(), toute
        # ecriture enregistree ailleurs (sondage _disque(), 0,5 s) reconstruisait
        # l'apercu "Ecriture generee" en entier meme sans rien y toucher - Afiya
        # l'a signale comme "ca bouge" a l'ouverture et pendant la saisie du
        # montant. Meme traitement que pour m_champs() : la lecture du
        # referentiel est isolee, valeurs() reste reactif aux vrais
        # changements (modele, journal, champs tapes).
        with reactive.isolate():
            r = ref()
        champs, _ = md.resoudre_variante(m, req(input.m_journal()), r)
        v = {}
        for ch in champs:
            v[ch["n"]] = get_input(f"ch_{ch['n']}")
        for ch in champs:
            if ch["t"] == "repartition":
                v[ch["n"]] = _lire_repartition()
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
            with reactive.isolate():
                journaux = ref()["journaux"]
            return md.construire_operation(input.m_modele(), valeurs(), input.m_journal(), journaux)
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
        # Meme correctif que valeurs() ci-dessus : ne pas rendre m_apercu()
        # dependant de _disque() (0,5 s), sinon tout l'apercu "Ecriture
        # generee" se reconstruit en boucle pendant que la piece se remplit.
        with reactive.isolate():
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
        # Meme correctif que m_apercu()/valeurs() : r et donnees() ne doivent
        # pas rendre ce ruban dependant de _disque() (0,5 s) ni du sondage
        # d'ecritures - seul un vrai changement de la piece en cours (modele,
        # journal, champs) doit le reconstruire.
        with reactive.isolate():
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
                dl.supprimer_piece(cor["id_piece"], u["identifiant"])
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
            elif ch["t"] == "repartition":
                # "Vider" ne remettait jamais a zero le tableau de
                # repartition (mois/nature/montant du modele Encaissement) :
                # ni les lignes ajoutees via "+ Ajouter un mois" (rep_ids)
                # ni les widgets m_rep_mois_1/m_rep_nature_1/m_rep_montant_1
                # de la premiere ligne (jamais retiree) n'etaient touches -
                # Frais/Avance/Solde et leurs montants restaient affiches
                # tels quels apres Vider, et le restaient tant que la
                # session restait ouverte. On revient explicitement a
                # l'etat d'une ligne 1 neuve : seule ligne, nature "frais",
                # mois suggere pour "frais" (mois en cours), montant 0.
                rep_ids.set([1])
                rep_prochain_id.set(2)
                ui.update_select("m_rep_nature_1", selected="frais")
                ui.update_select("m_rep_mois_1", selected=_mois_suggere("frais", ""))
                ui.update_numeric("m_rep_montant_1", value=0)

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

    def table_pieces(d, centres):
        if len(d) == 0:
            return pd.DataFrame({"Message": ["Aucune piece pour ce filtre."]})
        # File d'attente, pas registre comptable : la piece la plus recemment
        # saisie remonte en tete, quelle que soit sa date d'operation. Une
        # depense datee du 17 mais saisie aujourd'hui doit apparaitre avant
        # les pieces du 20 saisies hier - c'est l'ordre de saisie (saisi_le)
        # qui classe, jamais la date comptable (date_piece), qui elle ne
        # bouge pas et reste la seule utilisee pour l'export Sage.
        d = d.sort_values("saisi_le", ascending=False, kind="mergesort")
        # Nom complet du centre plutot que son abreviation (SAA -> Saaba) :
        # la comptable et les caissieres lisent ce tableau, pas Sage - Sage,
        # lui, garde sa section analytique abregee (cf. format_sage), qui
        # n'est pas ce tableau-ci.
        noms_centres = dict(zip(centres["code_centre"], centres["intitule"]))
        lignes = []
        ids = []
        for idp in d["id_piece"].unique():
            p = d[d["id_piece"] == idp]
            code_centre = p["centre"].iloc[0]
            lignes.append({
                "Date": pd.to_datetime(p["date_piece"].iloc[0]).strftime("%d/%m/%Y"),
                "Piece": dl.ou(p["num_definitif"].iloc[0], p["num_provisoire"].iloc[0]),
                "Journal": p["journal"].iloc[0],
                "Centre": noms_centres.get(code_centre, code_centre),
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

    # filters=True (rangee de filtres sous les en-tetes, native a
    # render.DataGrid) plutot qu'une dependance externe : quelques centaines
    # de pieces par an, une poignee d'utilisateurs simultanes, aucun besoin
    # de tri/filtre serveur cote base. Le filtrage entierement cote
    # navigateur suffit tant que ces volumes restent d'un ordre de grandeur
    # "annee scolaire", et evite d'ajouter une librairie pour ce que Shiny
    # fait deja nativement.
    # Classe CSS par valeur affichee dans la colonne "Statut" (cf. CSS
    # .cell-statut-*) : un code technique ("a_corriger") devient une classe
    # CSS valide en remplacant les underscores, le texte humain reste ce que
    # STATUTS affiche deja dans la colonne.
    _CLASSE_PAR_STATUT = {texte: f"cell-statut-{code}" for code, texte in STATUTS.items()}

    def styles_statut(d):
        if "Statut" not in d.columns:
            return []
        styles = []
        for texte, classe in _CLASSE_PAR_STATUT.items():
            lignes = [i for i, v in enumerate(d["Statut"]) if v == texte]
            if lignes:
                styles.append({"rows": lignes, "cols": ["Statut"], "class": classe})
        return styles

    def grille_pieces(d, selection_mode):
        if "Message" in d.columns:
            return render.DataGrid(d, selection_mode="none", width="100%")
        return render.DataGrid(d, selection_mode=selection_mode, width="100%", filters=True,
                                styles=styles_statut(d))

    # Le Referentiel et les Controles affichent le resultat brut d'un
    # SELECT * : des colonnes avec des None/NaN non uniformises, contrairement
    # aux tableaux ci-dessus qui passent par une fonction de mise en forme.
    # C'est ce qui empechait filters=True de fonctionner (l'inference de type
    # cote navigateur se perd sur une colonne au contenu heterogene). On
    # nettoie donc avant d'envoyer au navigateur : index par defaut, valeurs
    # manquantes remplacees par une chaine vide, colonnes textuelles casees en
    # str pur.
    def _pour_grille(d):
        d = d.reset_index(drop=True).copy()
        for col in d.columns:
            if d[col].dtype == "object":
                d[col] = d[col].fillna("").astype(str)
        return d

    # Les trois premiers indicateurs suivent le filtre affiche ; les soldes de
    # caisse portent toujours sur la totalite des ecritures (sinon ce ne
    # seraient pas des soldes), et couvrent tous les journaux de tresorerie
    # du referentiel - CP et CMD hier, CBI aujourd'hui, un quatrieme
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
            *cartes,
            ui.div({"style": "font-size:11px;color:var(--gris);grid-column:1/-1;margin-top:2px"},
                   "Soldes toujours calcules sur l'ensemble des pieces, filtre ou non."),
        )

    @render.data_frame
    def b_table():
        return grille_pieces(table_pieces(pieces_vue(), ref()["centres"]), "row")

    @reactive.effect
    @reactive.event(input.b_supprimer)
    def _supprimer():
        sel = b_table.data_view(selected=True)
        if len(sel) == 0 or "Message" in sel.columns:
            ui.notification_show("Choisir d'abord une piece.", type="warning")
            return
        try:
            dl.supprimer_piece(list(sel.index), util()["identifiant"])
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
        return grille_pieces(table_pieces(attente(), ref()["centres"]), "rows")

    @reactive.effect
    @reactive.event(input.v_valider)
    def _valider():
        # Filet de securite cote serveur : v_valider n'est boutonne qu'a
        # l'ecran pour le comptable, mais un input Shiny reste positionnable
        # par n'importe quel client de la session (masquer un widget n'est
        # pas un controle d'acces) - la verification du role doit donc etre
        # refaite ici, jamais seulement dans onglets()/onglet_validation().
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        # Meme filet de securite que _valider (voir son commentaire) :
        # v_rejeter est aussi un bouton reserve au comptable a l'ecran.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        return render.DataGrid(x, selection_mode="none", width="100%", filters=True)

    @render.download_button(filename=lambda: f"sage_{date.today().strftime('%Y%m%d')}.txt", encoding="cp1252")
    def e_txt():
        x = dl.format_sage(a_exporter(), ref())
        if x is None:
            yield ""
            return
        texte = x.to_csv(sep=";", index=False, header=False, lineterminator="\n", na_rep="")
        # Corrige le 10/09/2026 : cp1252 (au lieu de latin1) couvre en plus
        # "oe", les guillemets typographiques et le tiret cadratin ; et on
        # encode nous-memes avec errors="replace" plutot que de laisser
        # @render.download_button faire chunk.encode(encoding) sans filet -
        # Shiny transmet un chunk deja en bytes tel quel, sans le reencoder,
        # donc un caractere malgre tout hors cp1252 devient "?" au lieu de
        # faire planter (UnicodeEncodeError) le telechargement de tout le lot
        # de pieces selectionne.
        yield texte.encode("cp1252", errors="replace")

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
        # Meme filet de securite que _valider : l'export vers Sage est
        # reserve au comptable a l'ecran (onglet_export), a reverifier ici.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
            {"class": "ruban", "style": "background:var(--ambre-teinte);border-left-color:var(--ambre);"
                      "padding:14px 16px;margin-bottom:16px"},
            ui.tags.b(f"{len(manquants)} tiers cite par des pieces mais absent du referentiel."),
            ui.p({"style": "margin:8px 0"},
                 "Ces codes ont ete crees a la saisie puis perdus, en general parce que le "
                 "referentiel a ete remplace par une copie plus ancienne. Les recreer debloque "
                 "l'export ; l'intitule sera reconstruit depuis le code et reste modifiable "
                 "dans l'onglet Referentiel."),
            ui.p({"style": "margin:8px 0;font-size:12px;color:var(--gris)"}, ", ".join(manquants[:12])
                 + (" ..." if len(manquants) > 12 else "")),
            ui.input_action_button("c_reparer", "Recreer ces tiers", class_="btn-primary"),
        )

    @reactive.effect
    @reactive.event(input.c_reparer)
    def _reparer():
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
        crees = dl.reparer_tiers_manquants(donnees(), ref())
        ui.notification_show(
            f"{len(crees)} tiers recree(s)" if crees else "Aucun tiers a recreer",
            type="message")
        rafraichir()

    # Retrouve l'id_piece reel derriere le numero affiche dans la colonne
    # "piece" des anomalies (num_definitif si la piece en a un, sinon son
    # numero provisoire) - c'est ce qui permet de selectionner une ligne
    # d'anomalie et d'agir sur la piece qu'elle designe.
    def _num_vers_id_piece(d):
        m = {}
        for _, row in d.drop_duplicates("id_piece").iterrows():
            for num in (row.get("num_definitif"), row.get("num_provisoire")):
                if num and num not in m:
                    m[num] = row["id_piece"]
        return m

    @render.data_frame
    def c_table():
        a = anomalies_vue()
        if len(a) == 0:
            a = pd.DataFrame([{"gravite": "", "piece": "",
                                "anomalie": "Aucune anomalie sur les pieces enregistrees."}])
            return render.DataGrid(_pour_grille(a), selection_mode="none", width="100%", filters=True)
        mapping = _num_vers_id_piece(donnees())
        grille = _pour_grille(a)
        grille.index = [mapping.get(p) for p in a["piece"]]
        return render.DataGrid(grille, selection_mode="row", width="100%", filters=True)

    # Reclassement direct depuis Controles : la comptable choisit une ligne
    # d'anomalie, voit la piece concernee (date, libelle, montant), et peut
    # lui attribuer le bon compte et le bon tiers sans repasser par une
    # nouvelle saisie complete. Se replie tout seul (rien affiche) tant
    # qu'aucune piece corrigeable n'est selectionnee - disclosure progressif,
    # pas un formulaire permanent qui alourdirait l'onglet.
    @render.ui
    def c_reclassement():
        sel = c_table.data_view(selected=True)
        if len(sel) == 0 or sel.index[0] is None:
            return None
        idp = sel.index[0]
        d = donnees()
        p = d[d["id_piece"] == idp]
        if len(p) == 0:
            return None
        statut = p["statut"].iloc[0]
        if statut not in ("saisie", "a_corriger"):
            return ui.div({"class": "ruban att"},
                           f"Piece {dl.ou(p['num_definitif'].iloc[0], p['num_provisoire'].iloc[0])} : "
                           "deja validee ou exportee, non modifiable ici.")
        r = ref()
        ligne_attente = p[p["compte"] == md.COMPTE_ATTENTE]
        montant = p["debit"].sum()
        comptes = r["comptes"][r["comptes"]["compte"] != md.COMPTE_ATTENTE]
        choix_comptes = {"": ""}
        for _, row in comptes.iterrows():
            choix_comptes[row["compte"]] = f"{row['compte']} - {row['intitule']}"
        return ui.div(
            {"class": "carte", "style": "margin-top:14px;background:var(--fond)"},
            ui.h4("Attribuer le compte et le tiers"),
            ui.p({"style": "font-size:13px;color:var(--gris);margin:-6px 0 12px 0"},
                 f"{pd.to_datetime(p['date_piece'].iloc[0]).strftime('%d/%m/%Y')} - "
                 f"{p['journal'].iloc[0]} - {p['libelle'].iloc[0]} - {dl.fcfa(montant)} F"
                 + ("" if len(ligne_attente) else " (compte d'attente deja reclasse sur cette piece)")),
            ui.row(
                ui.column(6, ui.input_selectize(
                    "c_compte", "Compte comptable", choices=choix_comptes,
                    options={"placeholder": "Rechercher..."})),
                ui.column(6, ui.output_ui("c_tiers_wrap")),
            ),
            ui.input_action_button("c_attribuer", "Attribuer et remettre en file d'attente",
                                    class_="btn-primary btn-sm"),
        )

    # Le champ tiers ne s'affiche que si le compte choisi l'exige (meme
    # logique que le formulaire de Saisie) - jamais impose pour un compte de
    # charge qui n'en a pas besoin.
    @render.ui
    def c_tiers_wrap():
        compte = get_input("c_compte")
        if not compte:
            return None
        r = ref()
        ligne_compte = r["comptes"][r["comptes"]["compte"] == compte]
        if not len(ligne_compte) or ligne_compte.iloc[0]["tiers_obligatoire"] != "oui":
            return None
        pref = str(compte)[:3]

        # Tous les tiers existants du collectif sont proposés, même si
        # actif_annee = "non". Un ancien élève/personnel/fournisseur peut
        # ainsi être retrouvé et utilisé à nouveau.
        sous = r["tiers"][
            r["tiers"]["code_tiers"].str.startswith(pref)
        ]

        choix = {"": ""}

        for _, row in sous.iterrows():
            code = str(row["code_tiers"])
            nom = str(row["intitule"])
            choix[code] = f"{nom}  ({code})"

        # On peut choisir un tiers existant OU saisir directement le nom
        # d'une nouvelle personne absente du plan de tiers.
        # La création réelle se fait uniquement dans _attribuer().
        return ui.input_selectize(
            "c_tiers",
            "Tiers",
            choices=choix,
            options={
                "create": True,
                "persist": False,
                "placeholder": "Rechercher un nom ou saisir un nouveau nom..."
            }
        )
    @reactive.effect
    @reactive.event(input.c_attribuer)
    def _attribuer():
        sel = c_table.data_view(selected=True)
        if len(sel) == 0 or sel.index[0] is None:
            return
        idp = sel.index[0]
        compte = get_input("c_compte")
        if not compte:
            ui.notification_show("Choisir un compte.", type="warning")
            return
        r = ref()
        tiers_brut = get_input("c_tiers", "")
        ligne_compte = r["comptes"][r["comptes"]["compte"] == compte]
        code_tiers = ""
        if len(ligne_compte) and ligne_compte.iloc[0]["tiers_obligatoire"] == "oui":
            if not tiers_brut:
                ui.notification_show("Ce compte exige un tiers.", type="warning")
                return
            try:
                code_tiers = dl.resoudre_tiers(tiers_brut, str(compte)[:3], compte)
            except Exception as e:
                ui.notification_show(f"Impossible de resoudre le tiers : {e}", type="error")
                return
        try:
            dl.reclasser_piece(idp, md.COMPTE_ATTENTE, compte, code_tiers, util()["identifiant"])
        except Exception as e:
            ui.notification_show(str(e), type="error")
            return
        ui.notification_show(
            "Compte attribue - la piece repasse en file d'attente normale (onglet Validation).",
            type="message")
        ui.update_selectize("c_compte", selected="")
        rafraichir()

    # Lien "Afficher tout (N) / Reduire" : n'existe que si la liste depasse
    # LIGNES_APERCU lignes, pour ne jamais surcharger un referentiel qui
    # tient deja sur un seul ecran.
    def _lien_toggle(id_bouton, etendu, total):
        if total <= LIGNES_APERCU:
            return None
        libelle = "Reduire" if etendu else f"Afficher tout ({total})"
        return ui.input_action_link(id_bouton, libelle, class_="lien-etendre")

    def _tronquer(d, etendu):
        return d if etendu else d.head(LIGNES_APERCU)

    @render.data_frame
    def r_comptes():
        d = _pour_grille(ref()["comptes"])
        return render.DataGrid(_tronquer(d, etendu_comptes()), selection_mode="none",
                                width="100%", filters=True)

    @render.ui
    def lien_comptes():
        return _lien_toggle("toggle_etendu_comptes", etendu_comptes(), len(ref()["comptes"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_comptes)
    def _toggle_etendu_comptes():
        etendu_comptes.set(not etendu_comptes())

    @render.data_frame
    def r_tiers():
        d = _pour_grille(ref()["tiers"])
        return render.DataGrid(_tronquer(d, etendu_tiers()), selection_mode="none",
                                width="100%", filters=True)

    @render.ui
    def lien_tiers():
        return _lien_toggle("toggle_etendu_tiers", etendu_tiers(), len(ref()["tiers"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_tiers)
    def _toggle_etendu_tiers():
        etendu_tiers.set(not etendu_tiers())

    @render.data_frame
    def r_utilisateurs():
        u_aff = ref()["utilisateurs"][["identifiant", "nom", "role", "centre", "actif"]]
        return render.DataGrid(_tronquer(_pour_grille(u_aff), etendu_utilisateurs()),
                                selection_mode="row", width="100%", filters=True)

    @render.ui
    def lien_utilisateurs():
        return _lien_toggle("toggle_etendu_utilisateurs", etendu_utilisateurs(),
                             len(ref()["utilisateurs"]))

    @reactive.effect
    @reactive.event(input.toggle_etendu_utilisateurs)
    def _toggle_etendu_utilisateurs():
        etendu_utilisateurs.set(not etendu_utilisateurs())

    @reactive.effect
    @reactive.event(input.r_ajouter_utilisateur)
    def _ajouter_utilisateur():
        # Le panneau de creation d'utilisateur n'est rendu qu'au comptable
        # (onglet_referentiel) ; meme filet de securite cote serveur que
        # _valider - sans lui, n'importe quel compte "saisie" pourrait se
        # creer un acces "validation" sur n'importe quel centre.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        # Meme filet de securite que _ajouter_utilisateur.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        # Le panneau "Comptes de tiers" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        # Le panneau "Plan de comptes" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
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
        # Le panneau "Soldes d'ouverture" n'est rendu qu'au comptable ; meme
        # filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
        echecs = []
        for j in ref()["journaux"]["journal"]:
            v = get_input(_id_journal(j))
            if v is not None:
                try:
                    dl.maj_solde_ouverture(j, v)
                except Exception as e:
                    dl.logger.error("Echec de mise a jour du solde d'ouverture (journal %s) : %s", j, e)
                    echecs.append(j)
        # Corrige le 10/09/2026 : l'echec etait avale (`except Exception:
        # pass`) et "Soldes d'ouverture enregistres" s'affichait quand meme,
        # meme si aucun solde n'avait ete ecrit - le comptable croyait avoir
        # corrige un solde reste faux, avec un effet direct sur les controles
        # de solde de caisse (controler_soldes) qui en dependent. Desormais
        # un echec est nomme et ne peut plus etre confondu avec un succes.
        if echecs:
            ui.notification_show(
                "Echec sur : " + ", ".join(echecs) + ". Les autres soldes ont ete "
                "enregistres ; corrigez et reessayez pour ceux en echec.", type="error")
        else:
            ui.notification_show("Soldes d'ouverture enregistres", type="message")
        panneau_ouvert.set(None)
        rafraichir()

    @reactive.effect
    @reactive.event(input.r_nouvelle_annee)
    def _nouvelle_annee():
        # Le panneau "Nouvelle annee academique" n'est rendu qu'au
        # comptable ; meme filet de securite cote serveur que _valider.
        if not est_comptable():
            ui.notification_show("Action reservee au comptable.", type="error")
            return
        n = dl.nouvelle_annee_academique()
        panneau_ouvert.set(None)
        ui.notification_show(
            f"Nouvelle annee academique demarree : {n} tiers retires des listes de saisie "
            "(rien n'est supprime, l'historique reste intact).", type="message")


# "www" contient le logo/favicon ; static_assets exige un chemin absolu,
# jamais mis en correspondance automatiquement par Shiny.
app = App(app_ui, server, static_assets={"/": Path(__file__).resolve().parent / "www"})