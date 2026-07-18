#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Met a jour data/uas_supaip.json a partir des bulletins SUP-AIP officiels du SIA
(Service de l'Information Aeronautique, DGAC France).

Source unique et officielle : https://www.sia.aviation-civile.gouv.fr
Aucune dependance a AirOps ou tout autre agregateur tiers.

Logique :
  1. Recupere la liste des SUP-AIP Metropole actuellement valides.
  2. Filtre les bulletins de creation/renouvellement de zones (ZRT/ZIT/ZDT),
     exclut les procedures d'aerodrome, travaux, annulations, zones expirees.
  3. Pour chaque bulletin candidat, telecharge le PDF et extrait le texte.
  4. Parse les coordonnees (cercle ou polygone), limites verticales, dates.
  5. Ne garde que les zones dont le plancher est SFC (sol) -- pertinent pour
     un drone ; les zones en altitude (FL/AMSL eleve) sont ignorees.
  6. FUSIONNE le resultat avec data/uas_supaip.json existant (par numero de
     bulletin) au lieu de tout ecraser : un echec de parsing ponctuel sur un
     bulletin deja connu ne fait pas disparaitre la zone. Seuls les bulletins
     confirmes annules ou expires sont retires.
  7. Garde-fou : si la fusion ferait chuter le nombre de zones de plus de 50%
     par rapport au fichier existant, l'ecriture est annulee (le fichier
     existant est conserve tel quel) et le job se termine en erreur.

Concu pour tourner en CI (GitHub Actions) via .github/workflows/update-supaip.yml,
mais fonctionne aussi en local (python3 scripts/update_supaip.py).
"""
import re
import io
import sys
import json
import time
from datetime import datetime, timezone

import requests

try:
    import pdfplumber
except ImportError:
    print("pdfplumber manquant : pip install pdfplumber requests beautifulsoup4", file=sys.stderr)
    raise

from bs4 import BeautifulSoup

LIST_URL = "https://www.sia.aviation-civile.gouv.fr/documents/supaip/aip/id/6"
OUT_PATH = "data/uas_supaip.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; drone-checker-bot/1.0; +https://github.com/guillaume-drone/drone-checker)"}

CREATION_RE = re.compile(r"(cr[ée]ation|renouvellement|prolongation|exp[ée]rimentation)", re.I)
ZONEWORD_RE = re.compile(r"\b(ZRT|ZIT|ZDT)\b", re.I)
EXCLUDE_RE = re.compile(
    r"(travaux|taxiway|r[ée]habilitation|poste[s]? de stationnement|proc[ée]dure[s]?|"
    r"itin[ée]raire|trou[ée]e[s]?|h[ée]listation.*(gru|trou)|RNAV|RNP|SID|IAF|PinS|"
    r"restriction d.utilisation|[ée]valuation|compte.rendu|seuil d[ée]cal[ée]|"
    r"points? de report|FATO|zone de stationnement)",
    re.I,
)

# ---------------------------------------------------------------------------
# Geometrie / DMS
# ---------------------------------------------------------------------------

def dms_to_dd(deg, mn, sec, hemi):
    dd = float(deg) + float(mn) / 60 + float(sec) / 3600
    if hemi in ("S", "W"):
        dd = -dd
    return round(dd, 6)


COORD_RE = re.compile(
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*[\"'″′]{0,2}\s*(N|S)\s*[,-]?\s*"
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*[\"'″′]{0,2}\s*(E|W)"
)

CIRCLE_RE = re.compile(
    r"(?:cercle|arc(?:\s+(?:horaire|anti-horaire))?)\s+de\s+([\d.]+)\s*nm\s+de\s+rayon\s+centr[ée]\s+sur[^0-9]{0,20}"
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*[\"'″′]{0,2}\s*(N|S)\s*[,-]?\s*"
    r"(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*[\"'″′]{0,2}\s*(E|W)",
    re.IGNORECASE,
)


def parse_coords(text):
    pts = []
    for m in COORD_RE.finditer(text):
        lat = dms_to_dd(m.group(1), m.group(2), m.group(3), m.group(4))
        lon = dms_to_dd(m.group(5), m.group(6), m.group(7), m.group(8))
        pts.append([lat, lon])
    return pts


def parse_geometry(block):
    cm = CIRCLE_RE.search(block)
    if cm:
        radius_nm = float(cm.group(1))
        lat = dms_to_dd(cm.group(2), cm.group(3), cm.group(4), cm.group(5))
        lon = dms_to_dd(cm.group(6), cm.group(7), cm.group(8), cm.group(9))
        return {"t": "circ", "c": [lat, lon], "r": round(radius_nm * 1852)}
    pts = parse_coords(block)
    if len(pts) >= 3:
        return {"t": "poly", "c": pts}
    return None


def parse_vertical(block):
    block = re.sub(r"^LIMITES VERTICALES\s*", "", block.strip())
    m = re.search(r"^([A-Za-z0-9°'\s]+?)\s*/\s*([A-Za-z0-9°'\s]+?)(?:\n|$)", block)
    floor = ceiling = None
    if m:
        floor = re.sub(r"\s+", " ", m.group(1)).strip()
        ceiling = re.sub(r"\s+", " ", m.group(2)).strip()
    is_sfc = bool(floor and floor.upper().startswith("SFC"))
    return floor, ceiling, is_sfc


NAME_LINE_RE = re.compile(r"^(?:ZRT|ZIT|ZDT)\b[^\n]{0,80}$")
GROUP_HEADER_RE = re.compile(r"^(?:(?:ZRT|ZIT|ZDT)\b[^\n]*){2,}$")


def split_names(line):
    parts = re.split(r"(?=(?:ZRT|ZIT|ZDT)\s)", line)
    return [p.strip() for p in parts if p.strip()]


def parse_sup(text, sup_num, pdf_url):
    result = {"sup": sup_num, "pdf": pdf_url, "zones": [], "parseable": False}
    m = re.search(r"Objet\s*:\s*(.+?)\n", text)
    result["title"] = m.group(1).strip() if m else None
    result["cancelled"] = bool(re.search(r"Annul[ée]\s+le", text[:600], re.IGNORECASE))
    m = re.search(r"En vigueur\s*:\s*(.+?)\n", text)
    result["validity_raw"] = m.group(1).strip() if m else None

    idx = text.find("LIMITES LATERALES ET VERTICALES")
    if idx == -1:
        idx = text.find("LIMITES LATÉRALES ET VERTICALES")
    if idx == -1:
        return result
    section = text[idx:]

    lat_positions = [mm.start() for mm in re.finditer(r"LIMITES LAT[ÉE]RALES(?!\s+ET\s+VERTICALES)", section)]
    vert_positions = [mm.start() for mm in re.finditer(r"LIMITES VERTICALES", section)]
    n = len(lat_positions)
    if n == 0 or len(vert_positions) != n:
        return result

    lat_blocks, vert_blocks = [], []
    for i in range(n):
        start = lat_positions[i]
        next_lat = lat_positions[i + 1] if i + 1 < n else float("inf")
        later_verts = [v for v in vert_positions if v > start]
        next_vert = min(later_verts) if later_verts else float("inf")
        end = min(next_lat, next_vert)
        lat_blocks.append(section[start: (end if end != float("inf") else len(section))])
    for i in range(n):
        start = vert_positions[i]
        next_vert = vert_positions[i + 1] if i + 1 < n else float("inf")
        later_lats = [l for l in lat_positions if l > start]
        next_lat = min(later_lats) if later_lats else float("inf")
        end = min(next_vert, next_lat)
        vert_blocks.append(section[start: (end if end != float("inf") else len(section))])

    # Pattern B : un nom de zone isole juste avant chaque bloc LIMITES LATERALES
    names_b, ok_b = [], True
    search_start = 0
    for i in range(n):
        preceding = section[search_start:lat_positions[i]]
        lines = [l.strip() for l in preceding.split("\n") if l.strip()]
        cand = lines[-1] if lines else ""
        if NAME_LINE_RE.match(cand):
            names_b.append(cand)
        else:
            ok_b = False
        search_start = vert_positions[i] + len("LIMITES VERTICALES")

    zone_names = None
    if ok_b and len(set(names_b)) == n:
        zone_names = names_b
    else:
        group_lines = [l.strip() for l in section.split("\n") if GROUP_HEADER_RE.match(l.strip())]
        names = []
        for gl in group_lines:
            names.extend(split_names(gl))
        if len(names) == n:
            zone_names = names
        else:
            zone_names = [f"Zone {i+1}" for i in range(n)]

    for i in range(n):
        geom = parse_geometry(lat_blocks[i])
        floor, ceiling, is_sfc = parse_vertical(vert_blocks[i])
        result["zones"].append({"name": zone_names[i], "geom": geom, "floor": floor, "ceiling": ceiling, "sfc": is_sfc})
    result["parseable"] = True
    return result


# ---------------------------------------------------------------------------
# Scraping de la liste SIA
# ---------------------------------------------------------------------------

def fetch_list_entries():
    r = requests.get(LIST_URL, headers=UA, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    entries = []
    seen = set()
    for a in soup.find_all("a", href=re.compile(r"/documents/download/f/d/\d+/?")):
        href = a["href"]
        if not href.startswith("http"):
            href = "https://www.sia.aviation-civile.gouv.fr" + href
        title_text = a.get_text(" ", strip=True)
        # Le site formate le numero de bulletin tantot en annee sur 2 chiffres
        # (ex "035/26"), tantot sur 4 (ex "137/2026") -- on accepte les deux.
        m = re.match(r"(\d+/\d{2,4})\s*(.*)", title_text)
        if not m:
            continue
        num, title = m.group(1), m.group(2)
        if href in seen:
            continue
        seen.add(href)
        row = a.find_parent("tr")
        row_text = row.get_text(" ", strip=True) if row else title_text
        dm = re.search(r"Valide du\s*(\d{4}-\d{2}-\d{2})\s*au\s*(\d{4}-\d{2}-\d{2})", row_text)
        if not dm:
            continue
        start, end = dm.groups()
        entries.append({
            "num": num,
            "title": title,
            "pdf": href,
            "start": start,
            "end": end,
            "cancelled": bool(re.search(r"annul[ée]", row_text, re.I)),
        })
    return entries


def filter_candidates(entries):
    today = datetime.now(timezone.utc).date()
    out = []
    for e in entries:
        if e["cancelled"]:
            continue
        try:
            end_date = datetime.strptime(e["end"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if end_date < today:
            continue
        if EXCLUDE_RE.search(e["title"]):
            continue
        if not ZONEWORD_RE.search(e["title"]):
            continue
        if not CREATION_RE.search(e["title"]):
            continue
        out.append(e)
    return out


def fetch_pdf_text(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=UA, timeout=30)
            r.raise_for_status()
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                return "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception as e:
            if attempt == retries:
                print(f"  ! echec telechargement/extraction {url}: {e}", file=sys.stderr)
                return None
            time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Assemblage GeoJSON-like
# ---------------------------------------------------------------------------

def to_feature(fid, name, geom, restriction, msg, link, reason):
    if geom["t"] == "circ":
        lat, lon = geom["c"]
        g = {"t": "circ", "c": [lon, lat], "r": geom["r"]}
    else:
        ring = [[lon, lat] for lat, lon in geom["c"]]
        g = {"t": "poly", "c": [ring]}
    return {
        "id": f"supaip-{fid}",
        "name": name,
        "restriction": restriction,
        "reason": reason,
        "msg": msg,
        "link": link,
        "geom": [g],
    }


def bulletin_num_from_reason(reason):
    return (reason or "").replace("SUP-AIP", "").strip()


def load_existing():
    try:
        with open(OUT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def main():
    print("Recuperation de la liste SUP-AIP SIA...")
    entries = fetch_list_entries()
    print(f"  {len(entries)} bulletins trouves sur la liste.")
    candidates = filter_candidates(entries)
    print(f"  {len(candidates)} bulletins candidats (creation ZRT/ZIT/ZDT, valides, non annules).")

    existing = load_existing()
    print(f"  {len(existing)} zones existantes dans {OUT_PATH} avant mise a jour.")

    # Bulletins desormais annules ou expires (pour purge), meme s'ils ne sont
    # plus dans la liste de candidats.
    today = datetime.now(timezone.utc).date()
    dead_nums = set()
    for e in entries:
        dead = e["cancelled"]
        if not dead:
            try:
                dead = datetime.strptime(e["end"], "%Y-%m-%d").date() < today
            except ValueError:
                dead = False
        if dead:
            dead_nums.add(e["num"])

    new_by_bulletin = {}
    fid = 1
    ok, fail, no_sfc = 0, 0, 0
    fail_details = []
    for e in candidates:
        text = fetch_pdf_text(e["pdf"])
        if not text:
            fail += 1
            fail_details.append(f"{e['num']} : echec telechargement/extraction PDF")
            continue
        r = parse_sup(text, e["num"], e["pdf"])
        if not r.get("parseable") or r.get("cancelled"):
            fail += 1
            fail_details.append(f"{e['num']} : echec parsing (structure non reconnue)")
            continue
        title = r.get("title") or e["title"]
        is_zit = "INTERDIT" in title.upper() or bool(re.search(r"\bZIT\b", title))
        restriction = "PROHIBITED" if is_zit else "REQ_AUTHORISATION"
        feats = []
        for z in r["zones"]:
            if not z["sfc"] or not z["geom"]:
                continue
            msg = f"{title} — SUP AIP {e['num']}. Valide {r.get('validity_raw') or ''}. Plafond {z['ceiling'] or '?'}."
            feats.append(to_feature(fid, z["name"], z["geom"], restriction, msg, e["pdf"], reason=f"SUP-AIP {e['num']}"))
            fid += 1
        if feats:
            new_by_bulletin[e["num"]] = feats
            ok += 1
        else:
            no_sfc += 1

        time.sleep(0.5)

    if fail_details:
        print("  Details des echecs :")
        for d in fail_details:
            print(f"    - {d}")

    # Fusion : on garde les zones existantes dont le bulletin n'a pas ete
    # re-traite avec succes cette fois-ci (echec de parsing ponctuel ou
    # bulletin plus dans la liste de candidats), sauf si le bulletin est
    # desormais confirme annule/expire. Les bulletins re-parses avec succes
    # remplacent leur ancienne version.
    merged = []
    for feat in existing:
        num = bulletin_num_from_reason(feat.get("reason"))
        if num in dead_nums:
            continue
        if num in new_by_bulletin:
            continue
        merged.append(feat)
    for feats in new_by_bulletin.values():
        merged.extend(feats)

    for i, feat in enumerate(merged, start=1):
        feat["id"] = f"supaip-{i}"

    print(f"  Bulletins traites avec succes : {ok} | echecs : {fail} | sans zone SFC exploitable : {no_sfc}")
    print(f"  Total zones apres fusion : {len(merged)} (etait {len(existing)} avant).")

    if len(existing) >= 10 and len(merged) < len(existing) * 0.5:
        print(
            f"  ALERTE : la fusion ferait chuter le nombre de zones de {len(existing)} a {len(merged)} "
            "(plus de 50% de perte). Ecriture annulee par securite, fichier existant conserve.",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
     json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Ecrit {OUT_PATH} ({len(merged)} zones).")


if __name__ == "__main__":
    main()
