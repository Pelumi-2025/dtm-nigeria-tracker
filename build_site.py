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
