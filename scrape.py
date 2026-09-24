"""Command-line harvester.

Examples
  python scrape.py                         # full crawl (sitemap + listings + default keywords)
  python scrape.py --keywords "flash report, intention survey"
  python scrape.py --quick                 # fast check of the newest pages only (hourly)
  python scrape.py --refresh               # ignore cache, re-fetch every report page
  python scrape.py --reclassify            # re-apply taxonomy.json to cached pages, no network
"""
import argparse
import json

from dtm.classify import Classifier
from dtm.crawler import Crawler, DATA, export


def main():
    p = argparse.ArgumentParser(description="Harvest DTM Nigeria reports and classify them.")
    p.add_argument("--keywords", help="comma-separated keywords/terminologies to search the site for")
    p.add_argument("--no-sitemap", action="store_true")
    p.add_argument("--no-listings", action="store_true")
    p.add_argument("--refresh", action="store_true", help="ignore the cache and re-fetch all pages")
    p.add_argument("--max-reports", type=int, help="cap new report pages fetched (testing)")
    p.add_argument("--quick", action="store_true", help="only check the newest listing pages (fast, for hourly runs)")
    p.add_argument("--reclassify", action="store_true", help="re-run classification on cached data only")
    a = p.parse_args()

    if a.reclassify:
        cache = json.loads((DATA / "cache.json").read_text("utf-8"))
        export(cache.values(), Classifier())
        return
    kws = [k.strip() for k in a.keywords.split(",")] if a.keywords else None
    try:
        Crawler().run(keywords=kws, use_sitemap=not a.no_sitemap, use_listings=not a.no_listings,
                      refresh=a.refresh, max_reports=a.max_reports, quick=a.quick)
    except RuntimeError as e:
        raise SystemExit(f"\nHarvest stopped: {e}")


if __name__ == "__main__":
    main()
