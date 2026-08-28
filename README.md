# Saisie des operations de caisse - HAKILI LAB (version PostgreSQL)

Les centres saisissent des operations, le comptable les valide, l'application
produit le fichier a importer dans Sage 100. **Sage reste le livre
officiel** : rien n'est comptabilise ici, l'application ne fait que preparer
des ecritures propres.

Cette version est concue directement pour PostgreSQL : ce n'est pas la
version Excel a laquelle on aurait branche une base, la couche donnees
(`logic/donnees.py`) est ecrite comme si l'application avait demarre sur
Postgres depuis le premier jour. Aucun fichier `.xlsx` n'est lu ni ecrit par
l'application elle-meme.

## Etat de cette livraison

Nettoyee avant remise : aucune ecriture de test, aucun tiers (eleve,
professeur, fournisseur) preexistant, un seul compte utilisateur au demarrage
(le siege). Le plan de comptes, les journaux, les centres et les libelles
normalises sont conserves tels quels : c'est de la structure comptable, pas
des donnees personnelles.

## Ce qui change pour la caisse d'un centre

La caissiere ne saisit pas une ecriture mais une operation : « Kone Mira a
paye 30 000 F pour janvier ». L'application choisit les comptes, ajoute la
contrepartie de caisse, normalise le libelle et refuse d'enregistrer une
piece desequilibree. Treize modeles couvrent l'essentiel des operations
courantes (caisse, banque, ventes, achats).

## Technologie

- `shiny` (Shiny for Python) — interface et serveur, memes concepts que R
  Shiny (valeurs reactives, `reactive.calc`, `reactive.effect`, `render.*`)
- `psycopg2` — connexion PostgreSQL
- `pandas` — manipulation des donnees en memoire (les requetes SQL
  alimentent des DataFrame, le reste de la logique ne change pas)
- `python-dotenv` — lecture de `.env` pour la configuration de connexion

## Installation

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\Activate.ps1 sous Windows
pip install -r requirements.txt
```

### Base de donnees

1. Creer la base et l'utilisateur applicatif (adapter le mot de passe) :

   ```sql
   CREATE USER hakili WITH PASSWORD 'choisir_un_mot_de_passe_fort';
   CREATE DATABASE hakilisso OWNER hakili;
   ```

2. Charger le schema puis les donnees de depart :

   ```bash
   psql -h <hote> -U hakili -d hakilisso -f sql/schema.sql
   psql -h <hote> -U hakili -d hakilisso -f sql/seed.sql
   ```

3. Copier `.env.example` en `.env` et renseigner `DATABASE_URL` (ou les
   variables `PGHOST`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`).

## Lancement

```bash
shiny run --reload app.py
```

Puis ouvrir l'adresse affichee dans le terminal (par defaut
`http://127.0.0.1:8000`).

Pour un usage en reseau (plusieurs postes), deployer avec un serveur ASGI
standard (uvicorn/gunicorn) pointant sur l'objet `app` de `app.py`, tous les
postes visant la meme base Postgres.

## Avant la mise en service — a faire dans l'ordre

1. **Se connecter avec le seul compte livre** : identifiant `comptable`,
   centre **Siege**, code d'acces `9999`. **Changer ce code avant toute
   utilisation reelle.** L'interface ne propose pas encore de modifier un
   code d'acces existant (ni la version Excel ne le proposait) : le plus
   simple pour l'instant est une requete directe en base,
   `UPDATE utilisateurs SET code_acces = 'nouveau_code' WHERE identifiant =
   'comptable';`. Un ecran "changer mon code" est un ajout naturel a
   prevoir avant d'ouvrir l'acces a davantage de monde.
2. **Creer un compte de saisie par centre** (Pissy, Tampouy, Saaba, SIAO,
   Nagrin), depuis l'onglet Referentiel, avec un code propre a chaque poste.
   Aucun compte de centre n'est pre-cree : c'est volontaire, pour ne pas
   livrer de codes d'acces devines a l'avance.
3. **Renseigner le solde de caisse d'ouverture** de CP et CMD (l'encaisse
   reelle constatee le jour de la mise en service), onglet Referentiel >
   Parametres. Tant qu'il vaut zero, le controle de solde de caisse n'a pas
   de sens.
4. **Verifier le plan de comptes et les codes de section analytique** des
   centres (onglet `centres` en base) : ils servent de section analytique
   dans Sage.

## Le circuit d'une piece

| Statut | Qui | Ce qui se passe |
|---|---|---|
| `saisie` | le centre | numero provisoire `PIS-2608-001`, propre au centre |
| `a_corriger` | le comptable | renvoyee avec un motif, le centre la corrige |
| `validee` | le comptable | numero definitif `CP2608001`, continu par journal et par mois, tous centres confondus |
| `exportee` | le comptable | figee, plus modifiable |

La numerotation definitive est attribuee a la validation, jamais a la
saisie. Elle repose sur une table `compteurs` incrementee de facon atomique
(`INSERT ... ON CONFLICT DO UPDATE ... RETURNING`) : deux centres qui
valident au meme instant ne peuvent jamais recevoir le meme numero, sans
qu'aucun verrou applicatif ne soit necessaire — Postgres s'en charge.

## Les deux caisses sont solidaires

Un transfert de la caisse principale vers les menues depenses n'est pas une
ecriture mais une operation a deux pieces, generees ensemble, validees
ensemble, exportees ensemble, supprimees ensemble. Voir le commentaire du
modele `approvisionnement` dans `logic/modeles.py` pour le detail.

## Import dans Sage 100

Le fichier produit est un texte delimite par des points-virgules, encode en
latin1, sans ligne d'entete :

```
Journal ; Date (JJMMAAAA) ; Piece ; Compte ; Tiers ; Libelle ; Debit ; Credit ; Section analytique
```

Dans Sage 100 i7 : **Fichier > Format import/export parametrable**, type
**Delimite**, separateur `;`, declarer les champs dans cet ordre. Le bouton
« Marquer comme exportees » se presse apres un import reussi, pas avant :
c'est lui qui empeche un double import.

## Controles avant transfert

Deux familles : les **controles de piece** (desequilibre, compte hors plan,
compte 401/411 sans tiers, tiers inconnu, absence de ligne de tresorerie,
transfert sans contrepartie) bloquent la validation. Les **controles de
coherence** (solde de caisse) portent toujours sur la totalite des
ecritures et ne bloquent jamais — ils signalent.

## Restauration

Depuis un fichier `.dump` du dossier `backup/sauvegardes/` :

```bash
# Restaurer dans une base neuve (recommande pour verifier une sauvegarde
# sans toucher a la base de production)
createdb -h <hote> -U hakili hakilisso_test
pg_restore -h <hote> -U hakili -d hakilisso_test backup/sauvegardes/hakilisso_AAAAMMJJ_HHMMSS.dump

# Restaurer par-dessus la base de production existante (ecrase son contenu -
# a n'utiliser qu'en cas de sinistre reel)
pg_restore -h <hote> -U hakili -d hakilisso --clean --if-exists \
  backup/sauvegardes/hakilisso_AAAAMMJJ_HHMMSS.dump
```

Cette procedure a ete testee reellement lors de la mise en place de la
sauvegarde : dump pris sur une base contenant des ecritures liees (un
approvisionnement, donc deux pieces partageant un id_lien), restaure dans
une base neuve, contenu verifie identique ligne par ligne.

## Sauvegarde automatique

`backup/pg_backup.py` produit un dump compresse (`pg_dump -Fc`, restaurable
avec `pg_restore`) dans `backup/sauvegardes/`, horodate, et supprime les
sauvegardes de plus de 30 jours (reglable, voir plus bas) — sans jamais
descendre sous 3 fichiers conserves, meme si toutes sont vieilles : une
purge qui tournerait le jour ou `pg_dump` echouerait en amont ne doit
jamais pouvoir effacer la derniere sauvegarde valable. Chaque execution
(reussie ou non) est journalisee dans `backup/sauvegardes/journal.log`.

Test manuel :

```bash
python backup/pg_backup.py
```

Reglages optionnels (variables d'environnement, ou dans `.env`) :

```
HAKILI_BACKUP_DIR=/chemin/vers/sauvegardes      # par defaut : backup/sauvegardes
HAKILI_BACKUP_RETENTION_JOURS=30                # par defaut : 30
```

### Planifier — Windows (Task Scheduler)

```powershell
$action = New-ScheduledTaskAction -Execute "C:\chemin\vers\.venv\Scripts\python.exe" `
  -Argument "backup\pg_backup.py" -WorkingDirectory "C:\chemin\vers\hakilisso"
$trigger = New-ScheduledTaskTrigger -Daily -At 21:00
Register-ScheduledTask -TaskName "HakiliLab-Sauvegarde" -Action $action -Trigger $trigger `
  -Description "Sauvegarde quotidienne de la base HAKILI LAB"
```

Ou via l'interface graphique (Planificateur de taches > Creer une tache de
base) en pointant sur le meme executable Python et le meme script, tous les
jours a une heure creuse (21h par exemple, apres la derniere validation du
comptable).

### Planifier — Linux (cron)

```bash
crontab -e
```

Ajouter (sauvegarde tous les jours a 21h) :

```
0 21 * * * cd /chemin/vers/hakilisso && /chemin/vers/.venv/bin/python backup/pg_backup.py >> backup/sauvegardes/cron.log 2>&1
```

### A ne pas oublier

- **Le dossier `backup/sauvegardes/` doit vivre en dehors du disque qui
  contient la base** (sur un disque externe, un partage reseau, ou
  synchronise vers un stockage cloud) — une sauvegarde sur le meme disque
  que la base ne protege de rien en cas de panne materielle.
- **Verifier la sauvegarde de temps en temps**, pas seulement se fier au
  journal : le test de restauration ci-dessus, une fois par trimestre par
  exemple, dans une base `hakilisso_test` jetable.
- Le script echoue proprement et le journalise (voir `journal.log`) si
  `pg_dump` n'arrive pas a se connecter — mais rien n'envoie encore
  d'alerte active (e-mail, SMS) en cas d'echec. A ajouter si la
  planification tourne sans supervision humaine reguliere.


## Structure du projet

```
app.py                     interface et logique de session (Shiny for Python)
logic/donnees.py           acces PostgreSQL, numerotation, controles, export
logic/modeles.py           les treize modeles d'operation (inchange)
sql/schema.sql             schema complet (tables, contraintes, triggers)
sql/seed.sql                donnees de depart : plan de comptes, journaux,
                             centres, libelles normalises, compte "siege"
backup/pg_backup.py         sauvegarde automatique (voir section dediee)
backup/sauvegardes/         dumps produits par pg_backup.py (a exclure d'un
                             depot git, a synchroniser vers un stockage externe)
.env.example                modele de configuration de connexion
requirements.txt            dependances Python
```

## Limites connues

- **Pas de piece jointe.** Les justificatifs restent papier.
- **Codes d'acces en clair en base**, comme dans la version precedente.
  Acceptable pour un premier usage interne avec un acces base restreint,
  pas au-dela : prevoir un hachage (`bcrypt`/`argon2`) avant toute
  exposition plus large.
- **Pas de reprise de l'historique.** L'application demarre a la date de
  mise en service ; les pieces des annees precedentes restent dans Sage
  uniquement.
- **Un seul schema, une seule base.** Les cinq centres et le siege
  partagent la meme base Postgres (c'est le but : plus de synchronisation
  differee entre classeurs).

## Verification effectuee lors de cette livraison

- Schema charge et seed applique sur une instance PostgreSQL 16 reelle.
- Cycle complet execute reellement en base : creation d'un utilisateur de
  centre, resolution d'un nouveau tiers, construction et enregistrement
  d'une operation d'encaissement, controle (aucune anomalie), validation
  avec numerotation definitive, export au format Sage, marquage exporte.
- Application lancee reellement (`shiny run`) et verifiee servir la page de
  connexion (HTTP 200) avec uniquement le compte Siege visible.
