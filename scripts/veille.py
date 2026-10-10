#!/usr/bin/env python3
"""
Veille des nouveautés du rayon cycle sur decathlon.fr.

Tourne chaque matin (GitHub Actions) :
 1. télécharge le plan du site produits officiel de Decathlon (sitemap) ;
 2. compare avec la liste de la veille pour trouver les produits apparus ;
 3. lit la fiche de chaque nouveau produit pour connaître son rayon
    (fil d'Ariane) et ne garde que le cycle, classé famille / sous-famille ;
 4. met à jour les fichiers lus par l'appli (docs/data/) ;
 5. envoie une notification ntfy selon les préférences choisies dans l'appli.

Aucun appel à Claude : le programme est 100 % autonome.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

RACINE = Path(__file__).resolve().parent.parent
ETAT = RACINE / "etat"
DATA = RACINE / "docs" / "data"
DEBUG = RACINE / "debug"

FICHIER_ARTICLES = ETAT / "articles_connus.txt"   # texte trié : git ne stocke que les différences
FICHIER_MODELES = ETAT / "modeles_connus.txt"
FICHIER_FILE = ETAT / "a_verifier.json"
FICHIER_NOUV = DATA / "nouveautes.json"
FICHIER_ARBRE = DATA / "arbre.json"
FICHIER_STATUT = DATA / "statut.json"
FICHIER_WIDGET = DATA / "widget.json"
FICHIER_PREFS = DATA / "preferences.json"

PARIS = dt.timezone(dt.timedelta(hours=2))  # suffisant pour dater la journée

ENTETES = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
}
NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
}
# /p/<slug>/<modele>/<prefixes couleur>m<article>
RE_PRODUIT = re.compile(r"/p/([^/]+)/(\d+)/([a-z0-9]*?)m(\d+)/?$")
RE_PRIX = re.compile(r"(\d{1,3}(?:[   ]?\d{3})*,\d{2})\s*€")


# ---------------------------------------------------------------- outils
def lire_json(chemin: Path, defaut):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return defaut


def ecrire_json(chemin: Path, donnees, compact=False):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    texte = json.dumps(donnees, ensure_ascii=False,
                       indent=None if compact else 1,
                       separators=(",", ":") if compact else None)
    chemin.write_text(texte, encoding="utf-8")


def log(*a):
    print(*a, flush=True)


SESSION = requests.Session()
SESSION.headers.update(ENTETES)


def telecharger(url: str, tentatives: int = 3) -> requests.Response | None:
    """GET avec quelques reprises. Renvoie la réponse (même 404/403) ou None."""
    for essai in range(tentatives):
        try:
            r = SESSION.get(url, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504) and essai < tentatives - 1:
                time.sleep(10 * (essai + 1))
                continue
            return r
        except requests.RequestException as e:
            log(f"  ! erreur réseau ({e.__class__.__name__}) sur {url}")
            time.sleep(5 * (essai + 1))
    return None


def cle_famille(fam: str, sous: str | None = None) -> str:
    return f"{fam}|{sous}" if sous else fam


# ---------------------------------------------------------------- sitemap
def lister_sitemaps(index_url: str) -> list[str]:
    r = telecharger(index_url)
    if r is None or r.status_code != 200:
        raise RuntimeError(f"Index sitemap inaccessible ({index_url}) : "
                           f"{None if r is None else r.status_code}")
    racine = ET.fromstring(r.content)
    if racine.tag.endswith("urlset"):
        return [index_url]
    return [e.text.strip() for e in racine.findall("sm:sitemap/sm:loc", NS) if e.text]


def lire_sitemap(url: str) -> dict[str, dict]:
    """Renvoie {cle_article: {url, modele, image}}."""
    r = telecharger(url)
    if r is None or r.status_code != 200:
        raise RuntimeError(f"Sitemap inaccessible ({url}) : "
                           f"{None if r is None else r.status_code}")
    contenu = r.content
    if url.endswith(".gz") or contenu[:2] == b"\x1f\x8b":
        contenu = gzip.decompress(contenu)
    produits = {}
    for bloc in ET.fromstring(contenu).findall("sm:url", NS):
        loc = bloc.findtext("sm:loc", default="", namespaces=NS).strip()
        m = RE_PRODUIT.search(urlparse(loc).path)
        if not m:
            continue  # assurances, seconde vie (-N), formats inconnus
        slug, modele, _, article = m.groups()
        if slug.startswith("seconde-vie"):
            continue
        img = bloc.findtext("image:image/image:loc", default="", namespaces=NS)
        produits[f"{modele}-{article}"] = {"url": loc, "modele": modele, "image": img.strip()}
    return produits


def catalogue_complet(config) -> dict[str, dict]:
    index = list(config["sitemaps"])
    if config.get("inclure_marketplace"):
        index.append(config["sitemap_marketplace"])
    tous = {}
    for idx in index:
        for sm in lister_sitemaps(idx):
            log(f"Lecture du plan du site : {sm}")
            tous.update(lire_sitemap(sm))
    return tous


# ---------------------------------------------------------------- fiche produit
def _chemin(href: str) -> str:
    p = urlparse(href).path.rstrip("/")
    return p or "/"


def fil_ariane(soup: BeautifulSoup, html: str) -> list[tuple[str, str]]:
    """Liste [(nom, chemin)] du fil d'Ariane, du plus général au plus précis."""
    # 1. Données structurées JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        pile = data if isinstance(data, list) else [data]
        while pile:
            o = pile.pop()
            if isinstance(o, dict):
                if o.get("@type") == "BreadcrumbList":
                    elts = sorted(o.get("itemListElement", []),
                                  key=lambda e: e.get("position", 0))
                    fil = []
                    for e in elts:
                        item = e.get("item")
                        href = item.get("@id", "") if isinstance(item, dict) else (item or "")
                        nom = e.get("name") or (item.get("name") if isinstance(item, dict) else "")
                        if nom:
                            fil.append((nom.strip(), _chemin(href)))
                    if len(fil) >= 2:
                        return fil
                pile.extend(o.values())
            elif isinstance(o, list):
                pile.extend(o)

    # 2. Bloc HTML explicitement marqué comme fil d'Ariane
    for bloc in soup.find_all(["nav", "ol", "ul", "div"]):
        etiquette = " ".join([bloc.get("aria-label", "")] + bloc.get("class", []))
        if re.search(r"breadcrumb|ariane", etiquette, re.I):
            fil = [(a.get_text(" ", strip=True), _chemin(a["href"]))
                   for a in bloc.find_all("a", href=True) if a.get_text(strip=True)]
            if len(fil) >= 2:
                return fil

    # 3. Heuristique : liens entre le dernier « Tous les sports » et le titre h1
    avant_titre = html.split("<h1", 1)[0]
    liens = BeautifulSoup(avant_titre, "html.parser").find_all("a", href=True)
    depart = None
    for i, a in enumerate(liens):
        if a.get_text(strip=True).lower() == "tous les sports":
            depart = i
    if depart is not None:
        fil = []
        for a in liens[depart:]:
            ch = _chemin(a["href"])
            if ch.startswith("/tous-les-sports") or ch.startswith("/electronique"):
                fil.append((a.get_text(" ", strip=True), ch))
        if len(fil) >= 2:
            return fil
    return []


def classer(fil: list[tuple[str, str]], config) -> tuple[str, str | None, str | None] | None:
    """(famille, sous-famille, détail) si le produit est du rayon cycle, sinon None."""
    for i, (nom, chemin) in enumerate(fil):
        if re.match(r"^/tous-les-sports/velo", chemin):
            reste = [n for n, _ in fil[i + 1:]]
            if not reste:
                return ("Autres", None, None)
            famille = reste[0]
            sous = reste[1] if len(reste) > 1 else None
            detail = reste[-1] if len(reste) > 2 else None
            return (famille, sous, detail)
    for prefixe, (fam, sous) in config.get("rubriques_supplementaires", {}).items():
        if any(ch.startswith(prefixe) for _, ch in fil):
            return (fam, sous, fil[-1][0] if fil else None)
    return None


def objets_json(data):
    """Parcourt tous les objets (dict) imbriqués d'un bloc JSON-LD."""
    pile = [data]
    while pile:
        o = pile.pop()
        if isinstance(o, dict):
            yield o
            pile.extend(o.values())
        elif isinstance(o, list):
            pile.extend(o)


def lire_fiche(html: str, config) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    fil = fil_ariane(soup, html)
    classement = classer(fil, config)
    if classement is None:
        return {"cycle": False, "fil": fil}

    nom = marque = prix = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for o in objets_json(data):
            if o.get("@type") in ("Product", "ProductGroup"):
                nom = nom or o.get("name")
                b = o.get("brand")
                marque = marque or (b.get("name") if isinstance(b, dict) else b)
                offres = o.get("offers")
                offres = offres[0] if isinstance(offres, list) and offres else offres
                if isinstance(offres, dict):
                    p = offres.get("price") or offres.get("lowPrice")
                    if p and not prix:
                        try:
                            prix = f"{float(str(p).replace(',', '.')):.2f}".replace(".", ",") + " €"
                        except ValueError:
                            pass
    h1 = soup.find("h1")
    if not nom and h1:
        nom = h1.get_text(" ", strip=True)
    if not marque:
        a = soup.find("a", href=re.compile(r"/brands/"))
        if a:
            marque = a.get_text(" ", strip=True)
    if not prix:
        texte = html.split("<h1", 1)[-1]
        m = RE_PRIX.search(BeautifulSoup(texte, "html.parser").get_text(" "))
        if m:
            prix = m.group(1).replace(" ", " ").replace(" ", " ") + " €"
    if not nom:
        og = soup.find("meta", property="og:title")
        nom = og["content"].split("|")[0].strip() if og and og.get("content") else None

    famille, sous, detail = classement
    return {"cycle": True, "nom": nom, "marque": marque, "prix": prix,
            "famille": famille, "sous_famille": sous, "detail": detail, "fil": fil}


# ---------------------------------------------------------------- notifications
def exclu(item: dict, exclus: set[str]) -> bool:
    return (item["famille"] in exclus
            or cle_famille(item["famille"], item.get("sous_famille")) in exclus)


def notifier(config, prefs, items, url_appli):
    sujet = config.get("ntfy_sujet")
    if not sujet or not prefs.get("notif_actives", True):
        log("Notifications désactivées.")
        return
    exclus = set(prefs.get("notif_exclus", []))
    retenus = [i for i in items
               if not exclu(i, exclus)
               and (prefs.get("notif_coloris", False) or i["type"] == "produit")]
    if not retenus:
        log("Aucune nouveauté à notifier selon les préférences.")
        return
    lignes = [f"• {i['nom'] or 'Produit'} ({i.get('sous_famille') or i['famille']})"
              + (f" – {i['prix']}" if i.get("prix") else "") for i in retenus[:8]]
    if len(retenus) > 8:
        lignes.append(f"… et {len(retenus) - 8} autre(s)")
    n = len(retenus)
    corps = {
        "topic": sujet,
        "title": f"{n} nouveauté{'s' if n > 1 else ''} cycle sur decathlon.fr",
        "message": "\n".join(lignes),
        "tags": ["bike"],
        "click": url_appli,
    }
    try:
        r = requests.post(config.get("ntfy_serveur", "https://ntfy.sh").rstrip("/"),
                          json=corps, timeout=30)
        log(f"Notification envoyée ({r.status_code}).")
    except requests.RequestException as e:
        log(f"! Notification impossible : {e}")


# ---------------------------------------------------------------- programme
def main():
    config = lire_json(RACINE / "config.json", {})
    prefs = lire_json(FICHIER_PREFS, {})
    maintenant = dt.datetime.now(PARIS)
    aujourd_hui = maintenant.date().isoformat()
    depot = os.environ.get("GITHUB_REPOSITORY", "")
    url_appli = (f"https://{depot.split('/')[0]}.github.io/{depot.split('/')[1]}/"
                 if "/" in depot else "")

    statut = {"maj": maintenant.isoformat(timespec="minutes"), "ok": True, "message": ""}

    # 1. Catalogue du jour
    try:
        catalogue = catalogue_complet(config)
    except Exception as e:  # site indisponible : on garde l'état, on signale
        statut.update(ok=False, message=f"Plan du site illisible : {e}")
        ecrire_json(FICHIER_STATUT, statut)
        log(statut["message"])
        return 0
    log(f"{len(catalogue)} articles au catalogue.")

    premiere_fois = not FICHIER_ARTICLES.exists()
    lire_liste = lambda f: set(f.read_text().split()) if f.exists() else set()
    articles_connus = lire_liste(FICHIER_ARTICLES)
    modeles_connus = lire_liste(FICHIER_MODELES)

    if not premiere_fois and len(catalogue) < 0.5 * len(articles_connus):
        statut.update(ok=False, message="Plan du site anormalement court, veille suspendue aujourd'hui.")
        ecrire_json(FICHIER_STATUT, statut)
        log(statut["message"])
        return 0

    # 2. Nouveaux articles -> file d'attente des fiches à lire
    file_attente = lire_json(FICHIER_FILE, [])
    deja_en_file = {f["cle"] for f in file_attente}
    nouveaux = 0
    for cle, p in catalogue.items():
        if cle in articles_connus:
            continue
        nouveaux += 1
        if not premiere_fois and cle not in deja_en_file:
            file_attente.append({
                "cle": cle, "url": p["url"], "image": p["image"],
                "type": "coloris" if p["modele"] in modeles_connus else "produit",
                "vu_le": aujourd_hui,
            })
    articles_connus.update(catalogue.keys())
    modeles_connus.update(p["modele"] for p in catalogue.values())
    ETAT.mkdir(parents=True, exist_ok=True)
    FICHIER_ARTICLES.write_text("\n".join(sorted(articles_connus)) + "\n")
    FICHIER_MODELES.write_text("\n".join(sorted(modeles_connus)) + "\n")

    if premiere_fois:
        log(f"Premier passage : {len(articles_connus)} articles mémorisés comme base de départ.")
        statut["message"] = ("Base de départ enregistrée. Les nouveautés apparaîtront "
                             "à partir du prochain passage.")

    log(f"{nouveaux} nouveaux articles, {len(file_attente)} fiches à lire.")

    # 3. Lecture des fiches
    nouveautes = lire_json(FICHIER_NOUV, [])
    ids_presents = {n["id"] for n in nouveautes}
    ajouts, restants = [], []
    lues = echecs_suite = 0
    for f in file_attente:
        if lues >= config.get("fiches_max_par_jour", 500) or echecs_suite >= 8:
            restants.append(f)
            continue
        r = telecharger(f["url"], tentatives=2)
        lues += 1
        time.sleep(config.get("pause_entre_fiches_secondes", 1.5))
        if r is None or r.status_code in (403, 429) or r.status_code >= 500:
            echecs_suite += 1
            restants.append(f)
            continue
        echecs_suite = 0
        if r.status_code != 200:
            continue  # produit retiré entre-temps
        fiche = lire_fiche(r.text, config)
        if not fiche["fil"]:
            DEBUG.mkdir(exist_ok=True)
            (DEBUG / f"sans_fil_{f['cle']}.html").write_text(r.text, encoding="utf-8")
        if not fiche["cycle"] or f["cle"] in ids_presents:
            continue
        item = {
            "id": f["cle"], "nom": fiche["nom"], "marque": fiche["marque"],
            "prix": fiche["prix"], "famille": fiche["famille"],
            "sous_famille": fiche["sous_famille"], "detail": fiche["detail"],
            "type": f["type"], "url": f["url"],
            "image": (f["image"] + "?format=auto&f=300x300") if f["image"] else "",
            "date": aujourd_hui, "ts": maintenant.isoformat(timespec="seconds"),
        }
        ajouts.append(item)
        ids_presents.add(item["id"])
        log(f"  + {item['famille']} › {item['sous_famille']} : {item['nom']}")
    ecrire_json(FICHIER_FILE, restants, compact=True)

    if echecs_suite >= 8:
        statut.update(ok=False, message=("Le site a refusé plusieurs lectures de fiches ; "
                                         "elles seront retentées demain."))

    # 4. Fichiers pour l'appli
    limite = (maintenant.date() - dt.timedelta(days=config.get("retention_jours", 90))).isoformat()
    nouveautes = sorted([n for n in nouveautes + ajouts if n["date"] >= limite],
                        key=lambda n: n["ts"], reverse=True)
    ecrire_json(FICHIER_NOUV, nouveautes)

    arbre = {k: list(v) for k, v in config.get("arbre_de_depart", {}).items()}
    for n in nouveautes:
        sous_liste = arbre.setdefault(n["famille"], [])
        if n.get("sous_famille") and n["sous_famille"] not in sous_liste:
            sous_liste.append(n["sous_famille"])
    ecrire_json(FICHIER_ARBRE, arbre)

    excl_aff = set(prefs.get("affichage_exclus", []))
    visibles = [n for n in nouveautes if not exclu(n, excl_aff)
                and (prefs.get("affichage_coloris", True) or n["type"] == "produit")]
    ecrire_json(FICHIER_WIDGET, {
        "maj": statut["maj"],
        "aujourd_hui": sum(1 for n in visibles if n["date"] == aujourd_hui),
        "sept_jours": sum(1 for n in visibles
                          if n["date"] >= (maintenant.date() - dt.timedelta(days=7)).isoformat()),
        "derniers": [{"nom": n["nom"], "prix": n["prix"],
                      "rayon": n.get("sous_famille") or n["famille"], "url": n["url"]}
                     for n in visibles[:5]],
    })

    statut.update(articles_suivis=len(articles_connus), nouveautes_jour=len(ajouts),
                  fiches_en_attente=len(restants))
    ecrire_json(FICHIER_STATUT, statut)

    # 5. Notification
    if ajouts:
        notifier(config, prefs, ajouts, url_appli)
    log("Terminé.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
