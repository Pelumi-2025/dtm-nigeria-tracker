"""Build the North-East Mobility Tracking reference figures (round and state totals only)
from the DTM master workbook, for the dashboard and its assistant.

  python tools/build_reference.py path/to/ne_mobility_r1_r52.xlsx

Writes config/reference/ne_mobility_rounds.json. Ward-level rows are NOT copied: the
website is public, so only round- and state-level totals are published.
Needs: pip install pandas openpyxl
"""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "reference" / "ne_mobility_rounds.json"


# What the cross-check against dtm.iom.int found (see the workbook's "Corrections log" sheet)
KNOWN_NOTES = {
    36: ["DTM published two versions: the report gives 2,184,254 IDPs in 447,628 households; its ward list gives 2,181,707 in 447,238"],
    38: ["Round 38 published 2,182,613 IDPs in 444,781 households, while the ward rows hold 16,760 more people, all in Borno camp rows (published: 879,400 IDPs in camps, 1,303,213 in host communities)"],
    43: ["the Round 43 report gives 2,375,846 IDPs (483,507 households) on one page and 2,375,661 (483,467) on another"],
    45: ["published 2,295,534 IDPs in 471,346 households; the ward rows are 3,086 people short in Borno. Returnees corrected to the published 2,075,257"],
    6: ["this is the figure in Round 6's own report (2,233,506 IDPs, 318,937 households); later reports list Round 6 as 2,239,749, a revision by DTM"],
    42: ["returns were not reassessed in Round 42: DTM published the Round 41 figure of 1,983,130 'as of March 2022'"],
    39: ["returnee households: DTM published 313,834 (report) and 314,732 (dashboard); the ward rows give 314,834"],
    51: ["IDP households: the report states 478,229; the ward rows give 478,233"],
}


# Household totals as published by DTM where the ward rows differ (individual totals come from the summary sheet)
PUBLISHED_HH = {36: 447628, 38: 444781, 43: 483507, 45: 471346, 51: 478229}
PUBLISHED_RET_HH = {39: 313834, 42: 323277}


def main(path: str):
    xl = pd.read_excel(path, sheet_name=None)
    cmp_, idp, ret = xl["ALL ROUNDS COMPARISM"], xl["IDPs"], xl["Returns"]
    for df in (idp, ret):  # some rounds spell states "Borno"/"borno"; treat them as one state
        df["state_name"] = df["state_name"].astype(str).str.strip().str.upper()
    cmp_["n"] = cmp_["Rounds"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    idp["n"] = idp["Rounds"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    ret["n"] = ret["Round"].astype(str).str.extract(r"(\d+)")[0].astype(int)
    rounds = {}
    for _, row in cmp_.sort_values("n").iterrows():
        n = int(row["n"])
        i, r = idp[idp["n"] == n], ret[ret["n"] == n]
        loc = i.groupby("location_type").agg(ind=("estimate_Ind_Ward", "sum"), hh=("estimate_hh_Ward", "sum"))
        st_i = i.groupby("state_name").agg(ind=("estimate_Ind_Ward", "sum"), hh=("estimate_hh_Ward", "sum"))
        st_r = r.groupby("state_name").agg(ind=("estimate_ind", "sum"), hh=("estimate_hh", "sum"))
        idp_sum, ret_sum = int(i["estimate_Ind_Ward"].sum()), int(r["estimate_ind"].sum()) if len(r) else None
        notes = []
        if abs(int(row["IDP FIGURES"]) - idp_sum) > 1:
            notes.append(f"summary IDP total {int(row['IDP FIGURES']):,} differs from the sum of ward rows {idp_sum:,}")
        rf = int(row["RETURN FIGURES"]) if pd.notna(row["RETURN FIGURES"]) else None
        if rf and ret_sum is not None and abs(rf - ret_sum) > 1:
            notes.append(f"summary returnee total {rf:,} differs from the sum of ward rows {ret_sum:,}")
        if rf and not len(r):
            notes.append("no ward-level returnee rows for this round; the summary figure may be carried over from the previous round")
        notes = KNOWN_NOTES.get(n, notes)
        idp_hh = PUBLISHED_HH.get(n, int(i["estimate_hh_Ward"].sum()))
        ret_hh = PUBLISHED_RET_HH.get(n, int(r["estimate_hh"].sum()) if len(r) else None)
        rounds[str(n)] = {
            "round": n,
            "date": pd.to_datetime(row["Date"]).strftime("%Y-%m-%d"),
            "idp_ind": int(row["IDP FIGURES"]),
            "idp_hh": idp_hh,
            "ret_ind": rf if rf else None,
            "ret_hh": ret_hh,
            "wards": int(i.groupby(["state_name", "lga_name", "ward_name"]).ngroups),
            "lgas": int(i.groupby(["state_name", "lga_name"]).ngroups),
            "by_location": {k: {"ind": int(v["ind"]), "hh": int(v["hh"])} for k, v in loc.iterrows()},
            "by_state": {k.title(): {"idp_ind": int(v["ind"]), "idp_hh": int(v["hh"]),
                                     "ret_ind": int(st_r.loc[k, "ind"]) if k in st_r.index else None,
                                     "ret_hh": int(st_r.loc[k, "hh"]) if k in st_r.index else None}
                         for k, v in st_i.iterrows()},
            "notes": notes,
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "DTM Nigeria North-East Mobility Tracking dataset, Rounds 1-52 (ne_mobility_r1_r52.xlsx)",
                               "rounds": rounds}, indent=1), encoding="utf-8")
    print(f"Wrote {OUT} with {len(rounds)} rounds")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ne_mobility_r1_r52.xlsx")
