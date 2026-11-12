"""Rebuild library/symptoms/icd10cm.symptoms.json: the ICD-10-CM symptom and sign codes.

ICD-10-CM is published by CDC's National Center for Health Statistics and is free to use. The
CDC download server can be unreachable from some networks, so this reads the tabular XML that
the `simple-icd-10-cm` package redistributes on PyPI (data unchanged; package MIT licensed).

Codes R00–R69 cover symptoms and signs; R70–R99 (abnormal test findings) are left out. A few
symptom codes that ICD-10-CM files under body systems instead (joint, limb, back, eye and ear
pain, visual disturbance, tinnitus) are added from those chapters; see EXTRA.

Usage:
    python medsim-eval/scripts/build_symptoms.py [--xml PATH]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "library" / "symptoms" / "icd10cm.symptoms.json"
PACKAGE = "simple-icd-10-cm==1.5.0"


def find_xml(folder: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "pip", "download", "--no-deps", "-q", "-d", str(folder), PACKAGE],
        check=True,
    )
    wheel = next(folder.glob("*.whl"))
    with zipfile.ZipFile(wheel) as z:
        name = next(n for n in z.namelist() if re.search(r"icd10c-tabular-.*\.xml$", n))
        z.extract(name, folder)
    return folder / name


# Symptom codes outside chapter 18, by code prefix.
EXTRA = ("M25.5", "M79.6", "M54.2", "M54.5", "M54.6", "H57.1", "H92.0", "H53.1", "H53.2", "H93.1")


def in_range(code: str) -> bool:
    m = re.match(r"^R(\d\d)", code)
    return bool(m) and int(m.group(1)) <= 69


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", type=Path, help="ICD-10-CM tabular XML, if already downloaded")
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        xml = args.xml or find_xml(Path(tmp))
        root = ET.parse(xml).getroot()
        release = (root.findtext("version") or "").strip()
        symptoms = []
        for top in root.iter("diag"):
            code = top.findtext("name") or ""
            if not (len(code) == 3 and in_range(code)):
                continue
            group = f"{code} {top.findtext('desc')}"
            for d in top.iter("diag"):
                symptoms.append(
                    {"code": d.findtext("name"), "name": d.findtext("desc"), "group": group}
                )
        for d in root.iter("diag"):
            code = d.findtext("name") or ""
            if code.startswith(EXTRA) and len(code) > 5:
                cat = next(x for x in root.iter("diag") if x.findtext("name") == code[:3])
                symptoms.append(
                    {
                        "code": code,
                        "name": d.findtext("desc"),
                        "group": f"{code[:3]} {cat.findtext('desc')}",
                    }
                )
    doc = {
        "schema_version": "0.2",
        "source": {
            "doc": f"ICD-10-CM {release} Tabular List (CDC/NCHS), codes R00–R69 plus joint, limb, back, eye and ear symptom codes, via simple-icd-10-cm on PyPI",
            "url": "https://www.cdc.gov/nchs/icd/icd-10-cm/",
            "locator": f"retrieved {date.today().isoformat()}",
        },
        "symptoms": symptoms,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(symptoms)} codes")


if __name__ == "__main__":
    main()
