# 1. Le projet : pourquoi cette application existe

## Hakili Lab

Hakili Lab est une entreprise de soutien scolaire installée à Ouagadougou (Burkina Faso). Elle propose surtout des **cours d'appui** (maths, physique-chimie, anglais) aux élèves, payés au mois par les parents, et organise en été un **camp de vacances**. Elle vend aussi quelques documents (attestations, bulletins) et des t-shirts.

L'activité est répartie sur **cinq centres**, chacun avec ses élèves, ses enseignants, ses dépenses et **sa propre caisse** :

| Centre | Code dans l'application | Section analytique Sage | Ordre de numérotation |
|---|---|---|---|
| SIAO | `SIA` | `SIAO` | 1 |
| Tampouy | `TAM` | `TAMP` | 2 |
| Saaba | `SAA` | `SAAB` | 3 |
| Pissy | `PIS` | `PSSY` | 4 |
| Nagrin | `NAG` | `NAGR` | 5 |
| Siège | `SIE` | `SIEG` | 6 |

**Le Siège n'est pas un centre.** Il n'a ni caisse ni élèves. Il existe seulement pour que le comptable puisse se connecter (l'écran de connexion demande un centre). Depuis le 08/10/2026, quand le comptable saisit une opération, il doit choisir le centre réel concerné.

**Le SIAO a un rôle particulier.** C'est le plus grand centre, celui qui a le plus de dépenses. Sur décision du propriétaire, chacun des quatre autres centres lui envoie chaque mois une somme (50 000 F au moment de la rédaction), appelée **contribution au SIAO** (ou « contribution au siège »). Cette somme n'est jamais remboursée. Il arrive aussi qu'un centre **prête** de l'argent au SIAO, ou que le SIAO paie des impôts pour le compte d'un centre. Ces mouvements entre centres ont leur propre formulaire (« Transfert entre centres ») et un motif obligatoire.

Chaque centre a **deux caisses physiques** :

- la **caisse principale (CP)**, où arrivent les paiements des élèves ;
- la **caisse menues dépenses (CMD)**, alimentée par la caisse principale, d'où sortent les petites dépenses (carburant, impressions, eau, vacations…).

Il y a aussi **une seule banque**, commune à tous les centres (CBI, Coris Bank International). L'ancienne banque, BDU-BF, a été fermée en septembre 2026 ; son journal est conservé en lecture seule pour l'historique.

## Ce qui se passait avant

Chaque caissière tenait un **brouillard de caisse** dans Excel : une feuille par mois, une ligne par opération, avec un libellé écrit à sa façon. En fin de période, le comptable reprenait ces fichiers, devinait les comptes, corrigeait les erreurs et ressaisissait tout dans **Sage 100**, le logiciel comptable officiel.

Les brouillards 2026 de Tampouy et Saaba (encore dans le dossier du projet) montrent ce que ça donnait : dates fausses (2006 au lieu de 2026), pages manquantes, soldes reportés qui ne collent pas, un même élève écrit de trois façons, le camp confondu avec les cours, un prêt au SIAO compté comme une charge. Le comptable passait son temps à rattraper, et la direction n'avait aucun chiffre fiable en cours d'année.

## Ce que fait l'application

```
  Caissière d'un centre           Comptable (Siège)                      Sage 100
  ─────────────────────           ─────────────────                      ────────
  Saisie d'une opération  ──►  Contrôles, validation  ──►  Fichier Sage  ──►  Import
  (formulaire simple)          (numéro définitif)          (fichier .txt)     (livre officiel)
                                         │
                                         ▼
                           Tableau de bord, assistant IA
                           (pilotage pour la direction)
```

1. **Saisie** : la caissière choisit un modèle d'opération (« Encaissement de frais de scolarité », « Dépense courante »…), remplit trois ou quatre champs, et voit l'écriture comptable se construire en direct. Elle n'a jamais à taper « débit » ou « crédit ».
2. **Contrôle** : l'application vérifie l'équilibre, les comptes, les tiers, les soldes de caisse, et signale les anomalies.
3. **Validation** : le comptable (ou un validateur local pour son centre) valide les pièces. Chaque pièce reçoit alors un **numéro définitif** sans trou, ou est renvoyée au centre avec un motif.
4. **Export** : le comptable télécharge le fichier que Sage sait importer, l'importe, puis marque les pièces « exportées ». Une pièce déjà exportée ne repart dans un fichier qu'avec une double confirmation.
5. **Pilotage** : le comptable dispose d'un **tableau de bord** par centre (résultat, élèves payants, caisse, fiabilité) et d'un **assistant IA** à qui l'on pose des questions comme « combien avons-nous reçu ce mois-ci ? ».

**Sage reste le livre officiel.** L'application prépare et contrôle les écritures ; elle ne produit ni bilan ni liasse fiscale.

## Les personnes

| Qui | Rôle dans l'application | Ce qu'il fait |
|---|---|---|
| Caissière ou caissier d'un centre | `saisie`, rattaché à son centre | Saisit les opérations de son centre, corrige les pièces renvoyées |
| Validateur local (rare) | `validation`, rattaché à un centre réel | Valide les pièces de son seul centre |
| Comptable | `validation`, rattaché au Siège (`SIE`) | Voit tout, valide, exporte vers Sage, gère le référentiel et les utilisateurs, consulte tableau de bord et assistant |
| Directeur | Pas encore de rôle propre | Lit le tableau de bord avec le comptable ; un accès direct est prévu plus tard |

Décision prise : le rôle `validation` ne doit pas être donné aux centres. En pratique, seul le comptable valide.

## Ce que le projet n'est pas

- Ce n'est pas un logiciel comptable complet : pas de bilan, pas de lettrage, pas de déclaration fiscale. Tout cela se fait dans Sage.
- Ce n'est pas un outil générique : les modèles de saisie, les comptes, les libellés et les règles du tableau de bord sont taillés pour Hakili Lab. Avant d'ajouter une fonction « standard », vérifiez qu'elle correspond à la façon dont les centres travaillent vraiment.
- Les brouillards Excel historiques **ne sont pas importés en production** (décision du 16/09/2026). La base de production démarre au 01/04/2026 avec la saisie réelle. Les brouillards 2026 ont seulement servi à construire une base de démonstration locale pour tester le tableau de bord.

## Les exigences de départ

Elles viennent des instructions du projet et restent valables :

- un outil **réel et durable**, pensé pour les centres, les journaux, le plan comptable et le circuit de validation de Hakili Lab ;
- un code de niveau professionnel, fiable, découpé par domaine (saisie, validation, export, référentiel, assistant) ;
- une interface **sobre** : beaucoup de fonctions, mais le détail se déplie (onglets, accordéons, « afficher plus ») au lieu d'encombrer l'écran ;
- une cohérence visuelle et fonctionnelle entre tous les modules.

Afiya a aussi fixé deux règles de travail qu'il est sage de garder : un changement de présentation ne touche jamais la logique métier, les identifiants des champs ni les appels serveur ; et le code reste simple et lisible plutôt qu'astucieux.
