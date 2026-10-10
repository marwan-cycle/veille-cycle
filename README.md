# Veille Cycle – nouveautés decathlon.fr

Chaque matin vers 6 h 35, un petit programme compare le catalogue de decathlon.fr
avec celui de la veille, repère les produits apparus dans le rayon cycle, les
classe par famille / sous-famille et :

- met à jour l'appli sur ton téléphone (liste « depuis ma dernière visite ») ;
- t'envoie une notification (si tu l'as activée) pour les familles que tu as cochées.

Tout tourne gratuitement chez GitHub. **Aucune utilisation de Claude** après l'installation.

---

## Installation (≈ 20 minutes, sur un ordinateur)

### 1. Créer un compte GitHub
Va sur <https://github.com/signup> et crée un compte gratuit. Retiens ton
**nom d'utilisateur** (ex. `marwan-cycle`) : il fera partie de l'adresse de l'appli.

### 2. Créer le dépôt
1. En haut à droite : **+** → **New repository**.
2. Nom : `veille-cycle`.
3. Coche **Public** (obligatoire pour l'hébergement gratuit de l'appli).
4. Clique **Create repository**.

### 3. Envoyer les fichiers
1. Décompresse le fichier `veille-cycle.zip` sur ton ordinateur.
2. Sur la page du dépôt, clique **uploading an existing file** (ou **Add file → Upload files**).
3. Ouvre le dossier décompressé, sélectionne **tout son contenu** (pas le dossier lui-même)
   et glisse-le dans la page. Clique **Commit changes**.
4. Vérifie qu'un dossier **`.github`** apparaît dans la liste. S'il manque (les
   dossiers commençant par un point sont parfois cachés) :
   **Add file → Create new file**, tape comme nom
   `.github/workflows/veille.yml`, colle le contenu du fichier
   `.github/workflows/veille.yml` du zip, puis **Commit changes**.

### 4. Publier l'appli
1. Onglet **Settings** → menu de gauche **Pages**.
2. *Source* : **Deploy from a branch**. *Branch* : **main**, dossier **/docs** → **Save**.
3. Après 1 à 2 minutes, l'adresse s'affiche :
   `https://TON-NOM.github.io/veille-cycle/`

### 5. Lancer le premier relevé
1. Onglet **Actions**. Si GitHub le demande, clique **I understand my workflows, go ahead and enable them**.
2. À gauche : **Veille nouveautés cycle** → bouton **Run workflow** → **Run workflow**.
3. Attends que la pastille devienne verte (2 à 5 minutes).

Ce premier passage mémorise tout le catalogue actuel comme **base de départ** :
la liste reste vide ce jour-là, c'est normal. Les nouveautés apparaissent à
partir du passage du lendemain matin.

> Si l'étape « Enregistrer les résultats » échoue avec *Permission denied* :
> **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**, puis relance.

---

## Sur le téléphone (Android)

### 6. Installer l'appli
1. Ouvre `https://TON-NOM.github.io/veille-cycle/` dans **Chrome**.
2. Menu **⋮** → **Ajouter à l'écran d'accueil** (ou **Installer l'application**).

L'icône s'utilise comme une appli : la liste s'ouvre sur les nouveautés
**depuis ta dernière visite**, le reste (90 jours) est dans l'onglet *Tout*.
Le bouton réglages (curseurs en haut à droite) permet de cocher / décocher
familles et sous-familles, séparément pour l'**affichage** et pour les **notifications**.

### 7. Recevoir les notifications
1. Installe **ntfy** depuis le Play Store (gratuit, sans compte).
2. Dans ntfy : **+** → sujet `veille-cycle-uu2m2atfzj` → **S'abonner**.

Tu recevras une seule notification le matin, uniquement s'il y a des nouveautés
dans les familles cochées. Toucher la notification ouvre l'appli.
Pour couper : réglages de l'appli → *Notifications* → premier interrupteur.

### 8. Relier tes choix de notifications au programme (recommandé)
Le programme du matin tourne chez GitHub ; pour qu'il connaisse les familles que
tu as cochées dans l'onglet *Notifications*, l'appli a besoin d'une clé d'accès
limitée à ce seul dépôt :

1. Sur GitHub : photo de profil → **Settings** → tout en bas **Developer settings**
   → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. *Name* : `appli veille`. *Expiration* : 1 an.
3. *Repository access* : **Only select repositories** → `veille-cycle`.
4. *Permissions* → *Repository permissions* → **Contents : Read and write**.
5. **Generate token**, copie le code (`github_pat_…`).
6. Dans l'appli : réglages → *Synchronisation* → colle le code → **Enregistrer**.
   Le message « Synchronisé ✓ » confirme.

Sans cette étape, l'appli fonctionne quand même, mais les notifications couvrent tout le rayon cycle.

---

## Bon à savoir

- **Données mobiles** : quelques dizaines de Ko par ouverture (+ les vignettes des produits).
- **Coût** : 0 €. GitHub Actions est gratuit et illimité pour un dépôt public.
- **Nouveau coloris** : un produit déjà vendu qui sort dans une nouvelle couleur.
  Affiché par défaut, exclu des notifications par défaut (modifiable).
- **Source** : le plan du site produits que Decathlon publie pour les moteurs de
  recherche, puis une lecture par fiche nouvelle (1,5 s d'écart entre deux lectures).
- **Produits marketplace** (vendeurs partenaires) : désactivés. Pour les inclure,
  mets `"inclure_marketplace": true` dans `config.json` (beaucoup plus de lectures).
- **En cas de souci**, un message orange s'affiche en haut de l'appli
  (ex. site momentanément indisponible) ; le programme réessaie le lendemain.
- **Diagnostic** : si des fiches n'ont pas pu être classées, les pages concernées
  sont téléchargeables 7 jours dans l'onglet *Actions* → dernier passage → *Artifacts → diagnostic*.

## Contenu du dépôt

| Élément | Rôle |
|---|---|
| `scripts/veille.py` | Le programme du matin |
| `.github/workflows/veille.yml` | Lance le programme chaque jour à 4 h 35 UTC |
| `config.json` | Réglages (sujet ntfy, familles de départ, rythme de lecture) |
| `docs/` | L'appli téléphone (page web installable) |
| `docs/data/` | Nouveautés, familles, préférences, état du dernier passage |
| `etat/` | Mémoire du catalogue (ne pas modifier) |
