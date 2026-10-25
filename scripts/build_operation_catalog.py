"""Construit le catalogue d'opérations proposé dans l'éditeur de gamme.

Entrée  : data/catalogue/*.csv (relevés bruts, un temps publié par ligne, avec sa source)
          colonnes : vetement;section;operation_source;operation_fr;machine;sam_min;source_url
Sortie  : web/public/catalogue/operations.json

Les relevés de même désignation française (sans accents ni casse) sont regroupés :
fourchette min / médiane / max, nombre de relevés, vêtements concernés, sources.
Les temps sont des valeurs publiées (articles en accès libre, fiches de praticiens) :
indicatifs, à confirmer par chronométrage dans l'atelier.

Usage : python scripts/build_operation_catalog.py
"""
from __future__ import annotations

import csv
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "catalogue"
OUT = ROOT / "web" / "public" / "catalogue" / "operations.json"

# Codes machine des relevés → types machine de l'éditeur (web/src/lib/gamme.ts, MACHINES)
MACHINES = {
    "PIQ": "piqueuse_plate", "SURJ": "surjeteuse_4_fils", "RECOUV": "recouvreuse",
    "DBL": "piqueuse_2_aiguilles", "CHAIN": "chainette", "BOUT": "piqueuse_boutonniere",
    "BOUTON": "piqueuse_bouton", "BRID": "bride", "THERMO": "presse_thermocollage",
    "FER": "fer_repassage", "MAN": "manuel", "ZZ": "zigzag", "AUTRE": "",
}

# Pages dont certaines valeurs sont mal imprimées : on écarte les temps douteux (>= 1 min).
SUSPECT_HIGH = {"textileengineering.net"}
MAX_SAM = 6.0  # au-delà, très probablement une erreur de saisie de la source

TITLES = {
    "onlinelibrary.wiley.com": "Bongomin et al. 2020, Engineering Reports (Wiley, accès libre)",
    "eujournal.org": "Rahman et al. 2014, European Scientific Journal",
    "doi.org/10.15406/jteft.2024": "Koç & Eryürük 2024, J. Textile Eng. & Fashion Tech. (MedCrave)",
    "doi.org/10.15406/jteft.2019": "J. Textile Eng. & Fashion Tech. 2019 (MedCrave)",
    "scindeks-clanci.ceon.rs": "Tekstilna industrija 2020 (CC BY 4.0)",
    "onlineclothingstudy.com": "Online Clothing Study",
    "ordnur.com": "ORDNUR",
    "textileindustry.net": "Textile Industry",
    "textileblog.com": "Textile Blog",
    "scanerp.pro": "Scan ERP",
    "shorabhossain.blogspot.com": "Shorab Hossain (blog)",
    "textileengineering.net": "Textile Engineering",
    "ojstexere.stttekstil.ac.id": "Texere vol. 23 n° 1, 2025 : blouse de laboratoire (accès libre)",
    "ajer.org": "American Journal of Engineering Research 2018",
    "researchgate.net/publication/380023224": "Ferdous, Manik & Rahman 2023, Bangladesh J. Fashion Tech. : blazer",
    "garmentmanufacturerguru.blogspot.com": "Garment Manufacturer Guru (blog)",
    "tantutextile.com": "H&H Asia / UNIK : bulletin technique combinaison EPI",
    "jurnal.usbypkp.ac.id": "Safaati & Azwar, Jurnal ReTiMs : tablier médical",
    "dergipark.org.tr": "Karabay 2014, Tekstil ve Konfeksiyon : chemisier",
    "revistaindustriatextila.ro": "Shao et al. 2022, Industria Textila : robe en lin",
    "ijiset.com": "IJISET 2025 vol. 12 n° 4 : débardeur",
    "hilarispublisher.com": "Murugesan 2018, J. Textile Sci. Eng. : débardeur",
    "tekstilec.si": "Kirin & Hursa Šajatović 2020, Tekstilec : col de chemisier",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("œ", "oe")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def title_for(url: str) -> str:
    for key, t in TITLES.items():
        if key in url:
            slug = urlparse(url).path.rstrip("/").split("/")[-1]
            if any(k in url for k in ("doi.org", "wiley", "eujournal", "ceon", "ojstexere", "ajer.org", "researchgate", "tantutextile", "usbypkp", "dergipark", "industriatextila", "ijiset", "hilarispublisher", "tekstilec")):
                return t
            words = re.sub(r"[-_]+", " ", slug).replace(".html", "").strip()
            return f"{t} : {words}" if words else t
    return urlparse(url).netloc


def main() -> None:
    rows = []
    for f in sorted(SRC.glob("*.csv")):
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                try:
                    sam = float(str(r["sam_min"]).replace(",", "."))
                except (TypeError, ValueError):
                    continue
                url = (r.get("source_url") or "").strip()
                name = re.sub(r"^Appairer\b", "Apparier", (r.get("operation_fr") or "").strip())
                if not name or not url or not (0 < sam <= MAX_SAM):
                    continue
                if sam >= 1 and any(d in url for d in SUSPECT_HIGH):
                    continue
                rows.append({**r, "sam": sam, "url": url, "name": name})

    urls = sorted({r["url"] for r in rows})
    src_id = {u: i + 1 for i, u in enumerate(urls)}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[norm(r["name"])].append(r)

    ops = []
    for key, g in groups.items():
        times = sorted(r["sam"] for r in g)
        name = Counter(r["name"] for r in g).most_common(1)[0][0]
        machine = Counter(MACHINES.get((r.get("machine") or "").strip().upper(), "") for r in g).most_common(1)[0][0]
        section = Counter((r.get("section") or "").strip() for r in g).most_common(1)[0][0]
        ops.append({
            "id": re.sub(r"\s+", "-", key)[:60],
            "nom": name,
            "vetements": sorted({(r.get("vetement") or "").strip() for r in g if r.get("vetement")}),
            "section": section,
            "machine": machine,
            "sam": {"min": round(times[0], 3), "med": round(statistics.median(times), 3),
                    "max": round(times[-1], 3), "n": len(times)},
            "sources": sorted({src_id[r["url"]] for r in g}),
        })
    ops.sort(key=lambda o: norm(o["nom"]))

    out = {
        "version": date.today().isoformat(),
        "avertissement": "Temps publiés (minutes standard, SAM/SMV) relevés dans des sources en accès libre. "
                         "Valeurs indicatives : elles varient avec le tissu, la longueur de couture, la machine "
                         "et l'opératrice. À confirmer par chronométrage.",
        "sources": [{"id": src_id[u], "titre": title_for(u), "url": u} for u in urls],
        "operations": ops,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(rows)} relevés, {len(ops)} opérations, {len(urls)} sources → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
