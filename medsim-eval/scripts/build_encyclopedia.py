"""Rebuild library/encyclopedia/reference.encyclopedia.json for the authoring form.

Two kinds of entry, both free to redistribute:
  * drugs in the IMM kit lists: short excerpts of a US FDA label from DailyMed (public domain),
    plus which kits carry the drug;
  * space-medicine terms from the SpaceDoc glossary (docs/glossary.md).

Conditions are in the CLiFF index (their CLiFF summaries) and normal values in the physiology
library, so they are not repeated here.

Needs network access to dailymed.nlm.nih.gov. Usage:
    python medsim-eval/scripts/build_encyclopedia.py
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "library" / "encyclopedia" / "reference.encyclopedia.json"
KITS = ROOT / "library" / "sources" / "imm-medkits.json"
GLOSSARY = ROOT.parent / "docs" / "glossary.md"
API = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
UA = {"User-Agent": "Mozilla/5.0"}
EXCERPT = 600

# Kit resource name -> generic name to look up. Kept by hand: brand and generic names are mixed
# in the IMM list, so a rule would guess wrong.
GENERIC = {
    "ABILIFY (ARIPIPRAZOLE) 5 MG": "aripiprazole",
    "ABILIFY (ARIPIPRAZOLE) 7.5 MG/ML, 1.3 ML": "aripiprazole",
    "ADRENALINE (EPINEPHRINE 1:10000) 10ML": "epinephrine",
    "EPIPEN 1:1000": "epinephrine",
    "AFRIN (OXYMETAZOLINE) 0.05% 15ML BOTTLE": "oxymetazoline",
    "ALBUTEROL INHALER (PROVENTIL) 90 MCG, 6.7 GM": "albuterol",
    "AMBIEN 10MG TABLET": "zolpidem",
    "AMOXICILLIN 500 MG CAPSULE": "amoxicillin",
    "ANTIVERT (MECLIZINE) 25 MG": "meclizine",
    "ASPIRIN 325MG TAB.": "aspirin",
    "ATIVAN (LORAZEPAM) 1 MG TABLET": "lorazepam",
    "ATROPINE 1 MG, 10ML SYRINGE.": "atropine",
    "BACITRACIN 500 UNITS/GM. 28 GM TUBE": "bacitracin",
    "BACTRIM DS (SULFAMETHOXAZOLE/TRIMETHOPRIM) 800 MG/160 MG TABLET": "sulfamethoxazole and trimethoprim",
    "BENADRYL 25 MG CAPSULE": "diphenhydramine",
    "BENADRYL 50 MG/ML, 1ML INJECTABLE": "diphenhydramine",
    "BENZOCAINE SWAB STICK ORAL 20%, 0.15 ML SWAB": "benzocaine",
    "CIPROFLOXACIN AND DEXAMETHASONE (CIPRODEX) 3%,7%, 7.5 ML BOTTLE": "ciprofloxacin and dexamethasone",
    "CLARITIN (LORATADINE)10MG TABLET": "loratadine",
    "CLEOCIN (CLINDAMYCIN) 300MG": "clindamycin",
    "CYCLOPENTOLATE 2% 15ML BOTTLE.": "cyclopentolate",
    "DEBROX FOR EARWAX (CARBAMIDE PEROXIDE) 6.5% 15ML BOTTLE": "carbamide peroxide",
    "DENTAL EUGENOL ANESTHETIC 1ML ORAL SYRINGE": "eugenol",
    "DEXAMETHASONE (DECADRON) 10MG INJECTABLE": "dexamethasone",
    "DIAMOX (ACETAZOLAMIDE) 250 MG TABLETS": "acetazolamide",
    "DIFLUCAN (FLUCONAZOLE) 150 MG": "fluconazole",
    "DILANTIN (PHENYTOIN) 300MG CAPSULES": "phenytoin",
    "DILAUDID (HYDROMORPHONE) 2MG/ML, 1ML SYRINGE": "hydromorphone",
    "DULCOLAX (BISACODYL) TABLET 5MG": "bisacodyl",
    "EFFEXOR XR (VENLAFAXINE XR) 75 MG CAPSULES": "venlafaxine",
    "ERTAPENEM 1GM": "ertapenem",
    "ERYTHROMYCIN OINTMENT 0.5%, 3.5 GM TUBE": "erythromycin",
    "ESTROGEN 1.25 MG TABLETS": "conjugated estrogens",
    "ETHINYL ESTRADIOL / NORGESTREL 0.05 MG/ 0.5 MG": "norgestrel and ethinyl estradiol",
    "FLAGYL (METRONIDAZOLE) 500MG": "metronidazole",
    "FLUOCINONIDE 0.05%, 30GM TUBE": "fluocinonide",
    "FLUORESCEIN 1MG STRIPS": "fluorescein",
    "FLUTICASONE 220MCG, 12GM INHALER": "fluticasone propionate",
    "IMODIUM (LOPERAMIDE HCL) 2 MG TABLET": "loperamide",
    "KETAMINE 50 MG/ML, 10 ML MULTI DOSE VIAL": "ketamine",
    "LEVAQUIN (LEVOFLOXACIN) 500MG": "levofloxacin",
    "LIDOCAINE (XYLOCAINE) CARDIAC 2% (20MG/ML) 5ML SYRINGE": "lidocaine",
    "LIDOCAINE (XYLOCAINE) PLAIN 1%, 10ML MULTI DOSE VIAL": "lidocaine",
    "LIDOCAINE JELLY 2% 30ML TUBE": "lidocaine",
    "LIDOCAINE W/ EPINEPHRINE (XYLOCAINE) 2 %, 2-ML UNITS 1:100,000 EPI, 20 ML. MULTI DOSE VIALS.": "lidocaine and epinephrine",
    "LOPRESSOR (METOPROLOL) 50 MG": "metoprolol tartrate",
    "LOTRIMIN AF CREAM (CLOTRIMAZOLE) 1%, 30GM TUBE": "clotrimazole",
    "MELATONIN 3 MG": None,  # a dietary supplement: no FDA drug label
    "MOTRIN (IBUPROFEN) 400MG": "ibuprofen",
    "MOXIFLOXACIN (AVELOX) 0.5%, 3ML BOTTLE": "moxifloxacin",
    "MUPIROCIN (BACTROBAN) 2%, 22 GM TUBE": "mupirocin",
    "NITROGLYCERIN TABLET 0.4MG": "nitroglycerin",
    "PEPTO-BISMOL 262MG CHEWABLE TABS": "bismuth subsalicylate",
    "PHENERGAN (PROMETHAZINE TABLET) 25 MG": "promethazine",
    "PROMETHAZINE INJECTABLE (PHENERGAN) 50MG/ML SINGLE DOSE VIAL": "promethazine",
    "PREDNISONE 20 MG": "prednisone",
    "PRILOSEC 20MG": "omeprazole",
    "PROPARACAINE EYE DROPS 0.5%, 15ML BOTTLE": "proparacaine",
    "PROVIGIL (MODAFINIL) 200 MG TABLETS": "modafinil",
    "REFRESH ARTIFICIAL TEARS (CARBOXYMETHYLCELLULOSE) 0.5%, 0.4ML BOTTLE": "carboxymethylcellulose",
    "REFRESH EYE OINTMENT (PETROLATUM WHITE AND MINERAL OIL) 42.5%; 57.3%, 3.5GM": "mineral oil and white petrolatum",
    "ROBINUL (GLYCOPYRROLATE) 0.2MG/ML": "glycopyrrolate",
    "ROCEPHIN (CEFTRIAXONE) 1 GM": "ceftriaxone",
    "SALINE NOSE SPRAY 22ML BOTTLE": "sodium chloride",
    "SILVER NITRATE STICK 75%/25%": "silver nitrate",
    "SUDAFED (PSEUDOEPHEDRINE) 30MG": "pseudoephedrine",
    "SUDAFED 12 HOUR (PSEUDOEPHEDRINE) 120 MG": "pseudoephedrine",
    "TAMSULOSIN 0.4 MG TABLET": "tamsulosin",
    "TOBRAMYCIN AND DEXAMETHASONE 0.3%; 0.1%, 10ML BOTTLE": "tobramycin and dexamethasone",
    "TORADOL (KETOROLAC) 30MG/ML, 2ML SINGLE DOSE VIAL": "ketorolac",
    "TROPICAMIDE 1%": "tropicamide",
    "TYLENOL (ACETAMINOPHEN) 325 MG": "acetaminophen",
    "VALACYCLOVIR 1 GM TABLET": "valacyclovir",
    "VALIUM (DIAZEPAM) 5 MG/ML, 2 ML SYRINGE": "diazepam",
    "VICODIN HP (HYDROCODONE/ ACETAMINOPHEN HP) 10 MG/660 MG": "hydrocodone bitartrate and acetaminophen",
    "ZANTAC (RANITIDINE) 150 MG": "famotidine",  # ranitidine was withdrawn from the US market in 2020
    "ZIPRASIDONE (GEODON 20MG/ML)": "ziprasidone",
    "ZITHROMAX (AZITHROMYCIN) 250 MG": "azithromycin",
    "ZOFRAN (ONDANSETRON) 8 MG TABLET": "ondansetron",
    "ZOLOFT (SERTRALINE) 50 MG": "sertraline",
    "ZYRTEC (CETIRIZINE) 10 MG TABLET": "cetirizine",
}
NOTES = {
    "famotidine": "The IMM kit lists ranitidine (Zantac), which was withdrawn from the US market in 2020; "
    "the label shown is famotidine, a drug of the same class.",
}
# LOINC section codes in FDA labels.
SECTIONS = {"34067-9": "Uses", "34068-7": "Dosage", "34070-3": "Contraindications"}
NS = {"v3": "urn:hl7-org:v3"}


def get(url: str) -> bytes:
    for attempt in range(4):
        try:
            return urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=60
            ).read()
        except OSError:
            time.sleep(2**attempt)
    raise RuntimeError(f"could not fetch {url}")


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")


FORMS = [
    (r"TABLET|\bTAB\b|TABS", r"TABLET"),
    (r"CAPSULE", r"CAPSULE"),
    (r"INJECTABLE|SYRINGE|VIAL|MG/ML|ERTAPENEM|ROCEPHIN|EPIPEN|ADRENALINE", r"INJECTION"),
    (r"OINTMENT", r"OINTMENT"),
    (r"CREAM", r"CREAM"),
    (r"EYE|DROPS|CYCLOPENTOLATE|TROPICAMIDE|MOXIFLOXACIN|CIPRODEX|TOBRAMYCIN", r"DROPS|OPHTHALMIC"),
    (r"INHALER", r"AEROSOL|INHAL"),
    (r"SPRAY|AFRIN", r"SPRAY"),
    (r"STICK", r"STICK|APPLICATOR"),
]
ORAL = r"TABLET|CAPSULE"  # kit items named only by strength ("MOTRIN 400MG") are oral solids
# Veterinary labelers also publish on DailyMed; their labels are not wanted here.
VETERINARY = ("ZOETIS", "VEDCO", "ELANCO", "DECHRA", "BIMEDA", "NORBROOK", "VETERINARY", "ANIMAL")


def form_of(names: list[str]) -> str:
    for pattern, form in FORMS:
        if any(re.search(pattern, n) for n in names):
            return form
    return ORAL


def score(title: str, generic: str, form: str) -> int:
    t = title.upper()
    product = t.split("[")[0]
    words = generic.upper().split()
    s = 0
    if product.startswith(words[0]) or f"({words[0]}" in product:
        s += 3
    single = " AND " not in generic.upper()
    # The ingredient list: from the first "(" to the last ")" (it can hold nested brackets).
    if "(" in product:
        listed = product[product.find("(") + 1 : product.rfind(")")]
    else:
        listed = product.split(",")[0]  # no ingredient list: commas belong to the dosage form
    if single and ("," in listed or " AND " in listed or "/" in listed or "NEOMYCIN" in listed):
        s -= 5  # a combination product, when the kit item is a single drug
    if re.search(form, product):
        s += 2
    if product.count(" - ") >= 2 or "HOMEOPATHIC" in t or "HP " in product:
        s -= 6  # homeopathic multi-ingredient products
    if any(v in t for v in VETERINARY):
        s -= 10
    if "KIT" in product:
        s -= 2
    return s


def label(generic: str, names: list[str]) -> tuple[str, str, dict[str, str]] | None:
    """(title, setid, {section: excerpt}) for the best-matching US label."""
    q = urllib.parse.quote(generic)
    found = json.loads(get(f"{API}/spls.json?drug_name={q}&pagesize=50"))["data"]
    form = form_of(names)
    found.sort(key=lambda d: -score(d["title"], generic, form))
    for spl in found[:6]:
        if score(spl["title"], generic, form) < 0:
            break
        root = ET.fromstring(get(f"{API}/spls/{spl['setid']}.xml"))
        out = {}
        for sec in root.iter("{urn:hl7-org:v3}section"):
            code = sec.find("v3:code", NS)
            name = SECTIONS.get(code.get("code")) if code is not None else None
            if name and name not in out:
                text = " ".join(t.strip() for t in sec.itertext() if t.strip())
                text = re.sub(r"\s+", " ", text)
                text = re.sub(
                    r"^\d*\.?\s*(INDICATIONS? (AND|&) USAGE|DOSAGE (AND|&) ADMINISTRATION|CONTRAINDICATIONS|USES?|DIRECTIONS)\s*",
                    "",
                    text,
                    flags=re.I,
                )
                out[name] = text[:EXCERPT].rsplit(" ", 1)[0] + ("…" if len(text) > EXCERPT else "")
        if "Uses" in out:
            return spl["title"], spl["setid"], out
    return None


def kits_of(resources: list[dict], names: list[str]) -> str:
    parts = []
    for r in resources:
        if r["name"] not in names:
            continue
        held = [
            f"{k} {r[k]['qty']}"
            for k in ("iss", "orion_mass_volume", "lunar_7_5d")
            if r.get(k) and r[k]["qty"] > 0
        ]
        parts.append(
            f"{r['name'].title()}: "
            + (
                ", ".join(held)
                .replace("orion_mass_volume", "Orion")
                .replace("iss", "ISS")
                .replace("lunar_7_5d", "lunar lander")
                or "not in any kit"
            )
        )
    return "; ".join(parts)


def glossary_terms() -> list[dict]:
    text = GLOSSARY.read_text(encoding="utf-8")
    section = text[
        text.index("## Aerospace medicine & clinical") : text.index("## Engineering & regulatory")
    ]
    out = []
    for term, meaning in re.findall(r"^\|\s*\*\*(.+?)\*\*\s*\|\s*(.+?)\s*\|\s*$", section, re.M):
        meaning = re.sub(
            r"\[\[?(R\d+)\]?\]\([^)]*\)", r"[\1]", meaning
        )  # keep reference numbers, drop links
        out.append(
            {
                "id": f"term-{slug(term)}",
                "kind": "term",
                "title": term,
                "text": meaning,
                "source": {"doc": "SpaceDoc glossary (docs/glossary.md)", "url": None},
            }
        )
    return out


def main() -> None:
    resources = json.loads(KITS.read_text(encoding="utf-8"))["resources"]
    by_generic: dict[str, list[str]] = {}
    for r in resources:
        if r["category"] == "drug":
            g = GENERIC.get(r["name"], "?")
            if g == "?":
                raise SystemExit(f"add {r['name']!r} to GENERIC")
            if g:
                by_generic.setdefault(g, []).append(r["name"])
    entries, missing = [], []
    for generic, names in sorted(by_generic.items()):
        found = label(generic, names)
        if not found:
            missing.append(generic)
            continue
        title, setid, sections = found
        body = " ".join(f"{k}: {v}" for k, v in sections.items())
        note = NOTES.get(generic, "")
        entries.append(
            {
                "id": f"drug-{slug(generic)}",
                "kind": "drug",
                "title": generic,
                "text": " ".join(
                    x for x in (note, f"In the IMM kits: {kits_of(resources, names)}.", body) if x
                ),
                "source": {
                    "doc": f"FDA label via DailyMed: {title}",
                    "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
                },
            }
        )
    entries += glossary_terms()
    doc = {
        "schema_version": "0.2",
        "note": "Reference only, for writing scenarios. Drug text is from one US product label and may "
        "differ from the product in a flight kit; it is not dosing advice.",
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(entries)} entries; no label found for {missing}")


if __name__ == "__main__":
    main()
