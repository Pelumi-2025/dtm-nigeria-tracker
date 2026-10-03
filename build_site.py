"""Build the deployable web site and the single-file offline dashboard.

  python build_site.py
    site/                                   -> upload anywhere (GitHub Pages, SharePoint, a web server)
    site/DTM_Nigeria_Dashboard_OFFLINE.html -> one file with data inside; open it with no internet,
                                               email it, or put it on a USB stick
"""
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE, DATA, DASH = ROOT / "site", ROOT / "data", ROOT / "dashboard"


def main():
    if SITE.exists():
        shutil.rmtree(SITE)
    (SITE / "data").mkdir(parents=True)
    for f in ("index.html", "sw.js", "manifest.webmanifest"):
        shutil.copy(DASH / f, SITE / f)
    for f in ("reports.json", "reports.js", "reports.csv", "counts_component_by_year.csv", "status.json", "facts.json"):
        if (DATA / f).exists():
            shutil.copy(DATA / f, SITE / "data" / f)

    html = (DASH / "index.html").read_text("utf-8")
    payload = json.loads((DATA / "reports.json").read_text("utf-8")) if (DATA / "reports.json").exists() else None
    inline = ("<script>window.DTM_DATA = " + json.dumps(payload, ensure_ascii=False).replace("</", "<\\/") + ";</script>"
              if payload else "")
    for src, dst, var in (("ncnw_mobility_rounds.json", "reference_ncnw.json", "DTM_REF2"), ("nigeria_states_svg.json", "states.json", "DTM_GEO")):
        f = ROOT / "config" / "reference" / src
        if f.exists():
            shutil.copy(f, SITE / "data" / dst)
            inline += f"<script>window.{var} = " + f.read_text("utf-8").replace("</", "<\\/") + ";</script>"
    ref = ROOT / "config" / "reference" / "ne_mobility_rounds.json"
    if ref.exists():
        shutil.copy(ref, SITE / "data" / "reference.json")
        inline += "<script>window.DTM_REF = " + ref.read_text("utf-8").replace("</", "<\\/") + ";</script>"
    fx = DATA / "facts.json"
    if fx.exists():
        inline += "<script>window.DTM_FACTS = " + fx.read_text("utf-8").replace("</", "<\\/") + ";</script>"
    offline = re.sub(r"<!--DTM_DATA-->.*?<!--/DTM_DATA-->", lambda m: inline, html, flags=re.S)
    offline = offline.replace('<link rel="manifest" href="manifest.webmanifest">', "")
    (SITE / "DTM_Nigeria_Dashboard_OFFLINE.html").write_text(offline, "utf-8")
    n = payload["count"] if payload else 0
    print(f"Built site/ and the offline dashboard with {n} reports.")


if __name__ == "__main__":
    main()
