"""Turn Nigeria's state boundaries (Natural Earth, public domain) into light SVG paths
for the dashboard map. Writes config/reference/nigeria_states_svg.json.

  python tools/build_states_map.py path/to/nigeria_states.geojson
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "reference" / "nigeria_states_svg.json"


def main(path):
    g = json.loads(Path(path).read_text("utf-8"))
    lons, lats = [], []
    for f in g["features"]:
        geom = f["geometry"]; polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            for ring in poly:
                for x, y in ring:
                    lons.append(x); lats.append(y)
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    W = 800; sx = W / ((max(lons) - min(lons)) * k); H = (max(lats) - min(lats)) * sx
    P = lambda x, y: ((x - min(lons)) * k * sx, (max(lats) - y) * sx)
    states = {}
    for f in g["features"]:
        name = f["properties"]["name"]; geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        d, best = [], (0, None)
        for poly in polys:
            for ri, ring in enumerate(poly):
                pts, last = [], None
                for x, y in ring:
                    px, py = P(x, y); q = (round(px, 1), round(py, 1))
                    if q != last: pts.append(q); last = q
                if len(pts) < 3: continue
                d.append("M" + "L".join(f"{a:g},{b:g}" for a, b in pts) + "Z")
                if ri == 0:
                    a = abs(sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))) / 2
                    if a > best[0]:
                        cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts); best = (a, (round(cx, 1), round(cy, 1)))
        states[name] = {"d": "".join(d), "c": best[1]}
    OUT.write_text(json.dumps({"source": "Natural Earth admin-1 boundaries (public domain)", "w": W, "h": round(H, 1), "states": states},
                              separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT}: {len(states)} states, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main(sys.argv[1])
