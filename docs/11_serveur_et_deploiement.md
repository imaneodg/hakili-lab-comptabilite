# 11. Le serveur : se connecter, déployer, sauvegarder

## 11.1 Ce qu'il y a sur le serveur

| Élément | Valeur |
|---|---|
| Adresse | `167.233.234.219` (Linux) |
| Compte | `imane` (pas de droits `sudo`) |
| Nom d'hôte | `guichet-entrepreneur` |
| Dossier du projet | `~/hakili_gestion_caisse` (un clone Git de la branche `main`) |
| Conteneur `app` | l'application Shiny, publiée sur `127.0.0.1:8022` |
| Conteneur `db` | PostgreSQL 16, publié sur `127.0.0.1:5432` (jamais sur Internet) |
| Volume des données | `hakili_gestion_caisse_pgdata` (volume Docker **externe**) |
| Base / utilisateur | `Hakili_compta` / `hakili_admin` |
| Configuration | `~/hakili_gestion_caisse/.env` (jamais dans Git) |
| Reverse proxy | nginx **de l'hôte**, partagé entre toutes les applications, géré par l'administrateur |

Le serveur héberge **une douzaine d'autres applications**. Le port 8000 appartient à « guichet-entrepreneur » : c'est pour ça que Hakili tourne sur **8022**. Ne touchez à rien qui n'est pas dans `~/hakili_gestion_caisse`.

Le compte `imane` n'a pas `sudo` : on ne peut ni installer de paquet, ni modifier nginx, ni poser un certificat. **Tout passe par Docker.** `psql` et `pg_dump` ne sont pas installés sur l'hôte : on les utilise à l'intérieur du conteneur `db`.

## 11.2 Se connecter

Depuis Windows (PowerShell) ou Linux/macOS :

```bash
ssh imane@167.233.234.219
cd ~/hakili_gestion_caisse
```

Le mot de passe est remis en main propre (chapitre 0). Recommandations, dans l'ordre :

1. demander à l'administrateur un **compte personnel** pour le repreneur, membre du groupe `docker`, plutôt que de partager `imane` ;
2. passer à une **clé SSH** (`ssh-keygen -t ed25519`, puis ajout de la clé publique dans `~/.ssh/authorized_keys`) ;
3. changer le mot de passe de `imane` après la passation (il est apparu en clair dans une session de travail le 18/09/2026).

Premiers gestes pour vérifier que tout va bien :

```bash
docker compose ps                      # app et db "running" / "healthy"
docker compose logs --tail=50 app      # pas d'erreur, "Application startup complete"
git log -1 --oneline                   # quel commit tourne
git status                             # doit être propre
```

## 11.3 Le fichier `.env` du serveur

Il contient au minimum :

```
POSTGRES_USER=hakili_admin
POSTGRES_PASSWORD=…            # mot de passe de la base
POSTGRES_DB=Hakili_compta
ANTHROPIC_API_KEY=…            # clé de l'assistant IA
```

`docker-compose.yml` construit lui-même `DATABASE_URL` pour l'application (hôte `db`, le nom du service dans le réseau Docker). Les autres variables possibles sont dans `.env.example` (`HAKILI_MODELE_IA`, `HAKILI_BACKUP_RCLONE_REMOTE`, etc.).

Ne copiez jamais ce fichier hors du serveur, ne l'affichez pas dans un terminal partagé.

## 11.4 Déployer une nouvelle version

Principe : **on déploie du code, jamais des données.** La base vit dans le volume ; Git ne contient aucune donnée.

**Sur le poste de développement :**

```bash
python verifier.py          # tous les tests sur une base jetable
git add -A
git status                  # uniquement du code, du SQL, des tests (aucun .xlsx, .env, .log)
git commit -m "Message clair en français"
git push origin main
```

**Sur le serveur :**

```bash
cd ~/hakili_gestion_caisse
git status                                    # propre, sinon s'arrêter et comprendre pourquoi
# 1. sauvegarde avant tout
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > ~/sauvegarde_avant_maj_$(date +%F).dump
ls -lh ~/sauvegarde_avant_maj_*.dump          # le fichier n'est pas vide
# 2. état de la base
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
SELECT count(*) AS lignes, count(DISTINCT id_piece) AS pieces FROM ecritures;
SELECT id_piece FROM ecritures GROUP BY id_piece HAVING round(sum(debit),2) <> round(sum(credit),2);
SQL
# 3. code
git pull origin main
docker compose build app
docker compose up -d app
# 4. vérification
docker compose logs --tail=80 app             # migrations appliquées, "Application startup complete"
```

Puis recompter les lignes et les pièces (identiques à avant), ouvrir l'application dans un navigateur et se connecter.

Les **migrations se jouent toutes seules** au démarrage du conteneur `app`. Si l'une échoue, le conteneur ne démarre pas et le journal nomme le fichier : corriger, recommiter, redéployer. Le conteneur `db` n'a pas besoin d'être recréé.

**Retour arrière :**

```bash
git log --oneline -5
git checkout <commit_precedent> -- .
docker compose build app && docker compose up -d app
```

Une migration ne se défait pas toute seule. Si elle a abîmé des données (ça ne devrait jamais arriver, elles sont faites pour ne rien supprimer), restaurer la sauvegarde faite juste avant (11.6).

## 11.5 Les sauvegardes

**État au 08/10/2026 : aucune sauvegarde automatique ne tourne en production.** L'ancien script (`cron_sauvegarde_host.sh`) exige `pg_dump` sur l'hôte, qui n'y est pas. Le nouveau script `backup/sauvegarde.sh` passe par le conteneur et ne demande aucun droit administrateur. Il est écrit et testé, mais pas encore déployé ni planifié. **C'est la première chose à faire.**

Une fois le code déployé :

```bash
cd ~/hakili_gestion_caisse
chmod +x backup/*.sh
./backup/sauvegarde.sh                          # premier essai à la main
ls -lh backup/sauvegardes/                      # un fichier hakili_AAAAMMJJ_HHMM.dump non vide
crontab -e                                      # le crontab personnel ne demande pas sudo
```

Ligne à ajouter dans le crontab :

```
30 22 * * * ~/hakili_gestion_caisse/backup/sauvegarde.sh >> ~/hakili_gestion_caisse/backup/sauvegardes/journal.log 2>&1
```

Le script garde 30 jours de sauvegardes (`HAKILI_BACKUP_RETENTION_JOURS`) et vérifie que chaque fichier n'est pas vide.

**Copie hors du serveur** : une sauvegarde sur le même disque que la base ne protège ni d'une panne de disque ni d'un piratage. Deux possibilités :
- `rclone` configuré vers un Drive, et `HAKILI_BACKUP_RCLONE_REMOTE` dans `.env` (le script copie alors chaque sauvegarde) ;
- à défaut, récupérer régulièrement les dumps sur un autre poste : `scp imane@167.233.234.219:~/hakili_gestion_caisse/backup/sauvegardes/hakili_*.dump .`

Les dumps contiennent toute la comptabilité et les noms des élèves : rangez-les comme des documents confidentiels.

## 11.6 Restaurer

**Essai de restauration** (à faire une fois tout de suite, puis chaque trimestre ; ne touche jamais la production) :

```bash
./backup/restauration_essai.sh                  # dernier dump
./backup/restauration_essai.sh backup/sauvegardes/hakili_20261008_2230.dump
```

Le script restaure dans une base temporaire, compare le nombre de pièces et de tiers avec la production, puis supprime la base temporaire.

**Restauration réelle** (sinistre seulement, après réflexion, application arrêtée) :

```bash
docker compose stop app
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' \
    < chemin/vers/le_dump.dump
docker compose start app
```

Tout ce qui a été saisi après la sauvegarde est perdu : prévenir les centres pour qu'ils ressaisissent.

## 11.7 Gestes d'administration courants

| Besoin | Commande (dans `~/hakili_gestion_caisse`) |
|---|---|
| Redémarrer l'application | `docker compose restart app` |
| Voir les journaux en direct | `docker compose logs -f app` |
| Ouvrir la base | `docker compose exec db psql -U hakili_admin -d Hakili_compta` |
| Plus personne ne connaît le code du comptable | `docker compose exec app python outils/definir_code.py comptable` |
| Lister les codes tiers trop longs | `docker compose exec -T db psql -U hakili_admin -d Hakili_compta -f - < outils/tiers_trop_longs.sql` |
| Copier un script SQL sur le serveur sans passer par Git | `scp fichier.sql imane@167.233.234.219:~/` puis l'effacer après usage |
| Espace disque | `df -h ~` et `du -sh backup/sauvegardes` |

**Changer le mot de passe de la base** demande trois gestes solidaires, dans cet ordre, sinon l'application tombe au prochain redémarrage :

1. `ALTER USER hakili_admin WITH PASSWORD '…';` (dans psql) ;
2. mettre le même mot de passe dans `POSTGRES_PASSWORD` du `.env` ;
3. `docker compose up -d --force-recreate app`.

Modifier `POSTGRES_PASSWORD` seul ne change rien : cette variable ne sert qu'à la création d'un volume vide.

## 11.8 Ce qui demande l'administrateur du serveur

Le compte `imane` ne peut pas le faire ; il faut passer par l'administrateur de la machine (contact à compléter au chapitre 0) :

- **HTTPS** : poser un certificat (Let's Encrypt) et configurer le nginx de l'hôte pour Hakili. Sans HTTPS, les codes d'accès et toutes les données circulent en clair. Au dernier contrôle, l'état n'a pas pu être vérifié : ouvrez l'adresse de l'application dans un navigateur et regardez s'il y a un cadenas. `nginx/hakili.conf` du dépôt est un bon modèle à lui transmettre (il pointe sur `127.0.0.1:8022` et contient les en-têtes websocket indispensables à Shiny : sans eux, la page se charge mais reste figée) ;
- les mises à jour du système et de Docker ;
- un compte SSH pour le repreneur ;
- si un jour on veut plusieurs processus Shiny : des sessions « collantes » dans nginx.

Afiya avait demandé qu'on lui rappelle ces trois points (certificat, nginx, mises à jour système) en fin de projet : ils sont donc toujours ouverts.

## 11.9 Ne jamais faire en production

- `docker compose down -v` (le `-v` supprime les volumes ; le volume externe protège en principe, mais ne tentez pas le diable) ;
- supprimer le volume `hakili_gestion_caisse_pgdata` ;
- jouer `schema.sql`, `seed.sql`, `production_reset.sql`, `purge_avant_mise_en_service.sql`, `nettoyer_operations.py` ou `import_historique.py` sur `Hakili_compta` ;
- modifier une migration déjà jouée ;
- publier PostgreSQL sur `0.0.0.0` ou l'application hors de `127.0.0.1` ;
- utiliser le port 8000 ;
- `git add -A` sans relire `git status` (classeurs Excel, `.env`, dumps) ;
- éditer du code directement sur le serveur : la modification serait écrasée au prochain `git pull`, ou bloquerait le `pull`.

## 11.10 Incidents passés, pour ne pas les revivre

| Date | Incident | Leçon |
|---|---|---|
| 15/09 | Une IA tierce avait réécrit le dépôt : port 8000, compose sans base. La production avait été corrigée à la main sans commit | le dépôt doit décrire exactement la production (`docker-compose.yml` est la référence) |
| 15/09 | Quatre migrations jamais jouées en production : « relation … does not exist » | les migrations sont maintenant jouées automatiquement au démarrage |
| 15/09 | PostgreSQL exposé sur Internet (`0.0.0.0:5432`) | publication limitée à `127.0.0.1` |
| 15/09 | Assistant en panne en conteneur : `chatlas` sans son extra `anthropic` | `chatlas[anthropic]` dans `requirements.txt` |
| 18/09 | « La liste déroulante des élèves n'apparaît pas » : la base de production n'avait que 4 tiers | avant de chercher dans le code, regarder ce que contient la base |
| 18/09 | Mot de passe de la base changé à moitié (`ALTER USER` sans `.env`) | les trois gestes du 11.7 |
| 23/09 | Dossier `backup/` appartenant à root (ancien montage Docker) | `docker run --rm -v ~/hakili_gestion_caisse/backup:/b alpine chown -R 1005:1005 /b` |
| 18/09 | Session qui se grise, saisie bloquée : connexion morte rendue au pool | `_est_cassee()`, sondage tolérant aux coupures |

## 11.11 Fins de ligne Windows

Git sous Windows convertit en CRLF : un fichier du PC fait un octet de plus par ligne que le même fichier sur le serveur, à contenu identique. Ce n'est pas une différence de code. Pour comparer le PC et le serveur, comparez après `dos2unix` ou avec `git diff --ignore-cr-at-eol`. Ajouter un fichier `.gitattributes` (`* text=auto eol=lf`) réglerait la question une fois pour toutes (voir chantiers).
