#!/usr/bin/env python3
"""Rebuild data/postcodes.csv from the official swisstopo postcode directory.

Flatfox listings often omit the canton, but always carry a postcode and a
locality. The swisstopo Amtliches Ortschaftenverzeichnis maps every postcode
and locality to its political commune and canton, which is what the regulatory
gates key on. Rows sharing a postcode and locality keep the commune with the
largest address share.

    python build_postcodes.py                        # downloads the current file
    python build_postcodes.py path/to/AMTOVZ_CSV_LV95.csv

Source (open data, refreshed by swisstopo several times a year):
https://data.geo.admin.ch/ch.swisstopo-vd.ortschaftenverzeichnis_plz/
"""

from __future__ import annotations

import csv
import io
import os
import sys
import urllib.request
import zipfile

URL = ("https://data.geo.admin.ch/ch.swisstopo-vd.ortschaftenverzeichnis_plz/"
       "ortschaftenverzeichnis_plz/ortschaftenverzeichnis_plz_2056.csv.zip")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "postcodes.csv")


def _read_source(path):
    if path:
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read()
    with urllib.request.urlopen(URL, timeout=120) as resp:
        zf = zipfile.ZipFile(io.BytesIO(resp.read()))
    name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    return zf.read(name).decode("utf-8-sig")


def main(argv):
    text = _read_source(argv[1] if len(argv) > 1 else "")
    best = {}
    for row in csv.DictReader(io.StringIO(text), delimiter=";"):
        share = float((row.get("Adressenanteil") or "0").rstrip(" %") or 0)
        key = (row["PLZ4"], row["Ortschaftsname"])
        if key not in best or share > best[key][0]:
            best[key] = (share, row["Gemeindename"], row["Kantonskürzel"])
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["postcode", "locality", "commune", "canton", "share"])
        for (plz, loc), (share, commune, canton) in sorted(best.items()):
            w.writerow([plz, loc, commune, canton, f"{share:g}"])
    print(f"wrote {len(best)} rows to {OUT}")


if __name__ == "__main__":
    main(sys.argv)
