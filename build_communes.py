#!/usr/bin/env python3
"""Rebuild data/communes.csv from the official ARE Wohnungsinventar.

The ARE workbook has a metadata sheet and a data sheet whose columns are coded:
Name (commune), Kt_Kz (canton), ZWG_3120 (second home ratio), Status (0 white /
1 blue, blue meaning subject to the building restrictions), Verfahren (3 and 4
mean the share just crossed the line and is under review). Status is the
operative legal flag and handles the review edge cases better than the raw
percentage.

    python build_communes.py                         # expects data/ZWG_2026_Q1.xlsx
    python build_communes.py path/to/ZWG_2026_Q1.xlsx

The file is republished every end of March at
https://www.are.admin.ch/de/wohnungsinventar (Daten section). Refresh yearly.
"""

from __future__ import annotations

import csv
import os
import sys

import openpyxl

# The seventeen cantons that permit non-resident holiday-home acquisition.
# Set to [] to keep every canton.
TARGET_CANTONS = ["VS", "GR", "TI", "VD", "BE", "LU", "SG", "FR", "NE", "SZ",
                  "AR", "UR", "NW", "OW", "GL", "JU", "SH"]

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = os.path.join(HERE, "data", "ZWG_2026_Q1.xlsx")
OUT = os.path.join(HERE, "data", "communes.csv")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    src = argv[0] if argv else DEFAULT_SRC
    if not os.path.exists(src):
        raise SystemExit(f"ARE file not found: {src}")

    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    sheet = [s for s in wb.sheetnames
             if "metadat" not in s.lower() and "tadonn" not in s.lower()][-1]
    ws = wb[sheet]
    rows = ws.iter_rows(values_only=True)
    hdr = list(next(rows))
    ix = {name: i for i, name in enumerate(hdr)}
    need = ["Name", "Kt_Kz", "ZWG_3120", "Status", "Verfahren"]
    missing = [c for c in need if c not in ix]
    if missing:
        raise SystemExit(f"Columns not found: {missing}. Header was: {hdr}")

    out = []
    for r in rows:
        name = r[ix["Name"]]
        if name is None:
            continue
        canton = r[ix["Kt_Kz"]]
        if TARGET_CANTONS and canton not in TARGET_CANTONS:
            continue
        pct = r[ix["ZWG_3120"]]
        status = r[ix["Status"]]
        verf = r[ix["Verfahren"]]
        out.append({
            "municipality": str(name).strip(),
            "pct": round(float(pct), 1) if pct is not None else "",
            "canton": canton,
            "restricted": int(status) if status is not None else "",
            "in_review": (int(verf) in (3, 4)) if verf is not None else "",
        })

    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["municipality", "pct", "canton",
                                           "restricted", "in_review"])
        w.writeheader()
        w.writerows(out)

    frozen = sum(1 for o in out if o["restricted"] == 1)
    openn = sum(1 for o in out if o["restricted"] == 0)
    scope = f" (cantons {', '.join(TARGET_CANTONS)})" if TARGET_CANTONS else ""
    print(f"Wrote {OUT}: {len(out)} communes{scope}")
    print(f"  open (<20%): {openn}")
    print(f"  frozen (>20%): {frozen}")


if __name__ == "__main__":
    main()
