"""Build the North Central & North West Mobility Tracking reference (Rounds 1-19+):
round totals and state totals, from the DTM Nigeria Data Hub's curated baseline
(https://github.com/Pelumi-2025/dtm-nigeria-data-hub, data/baseline.json).

  python tools/build_ncnw_reference.py path/to/baseline.json

Checked when built (October 2026): R1-R3 and R10-R19 IDP totals and households match the
published NC/NW round reports on dtm.iom.int; R4-R9 match DTM's own NC/NW trend-analysis
graphic and the Round 14 IDP Atlas; state/LGA rows add up exactly to every round total.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "reference" / "ncnw_mobility_rounds.json"


def main(path):
    b = json.loads(Path(path).read_text("utf-8"))["nc_nw"]
    cols = b["lga_rounds"]["cols"]; ix = {c: i for i, c in enumerate(cols)}
    st = defaultdict(lambda: defaultdict(lambda: {"idp_ind": 0, "idp_hh": 0, "ret_ind": 0, "ret_hh": 0}))
    for row in b["lga_rounds"]["rows"]:
        d = st[row[0]][row[ix["state"]]]
        for k in ("idp_ind", "idp_hh", "ret_ind", "ret_hh"):
            d[k] += row[ix[k]] or 0
    rounds = {}
    for r in b["rounds"]:
        n = r["round"]
        by_state = {s: {k: (v or None) for k, v in d.items()} for s, d in sorted(st[n].items())}
        for k in ("idp_ind", "idp_hh"):
            assert sum(v[k] or 0 for v in by_state.values()) == r[k], (n, k)
        rounds[str(n)] = {"round": n, "date": r["date"], "idp_ind": r["idp_ind"], "idp_hh": r["idp_hh"],
                          "ret_ind": r.get("ret_ind"), "ret_hh": r.get("ret_hh"), "by_state": by_state, "notes": []}
    OUT.write_text(json.dumps({"source": "DTM Nigeria North Central & North West Mobility Tracking, Rounds 1-%d (DTM Nigeria Data Hub baseline)" % len(rounds),
                               "rounds": rounds}, indent=1), encoding="utf-8")
    print(f"Wrote {OUT} with {len(rounds)} rounds")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "baseline.json")
