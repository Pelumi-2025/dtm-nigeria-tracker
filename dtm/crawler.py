"""Crawler and harvester for DTM Nigeria reports on dtm.iom.int.

Discovery runs three ways and merges the results:
  1. sitemap.xml (fast, complete when the site publishes it)
  2. seed listing pages, following their pagination
  3. site search, one query per keyword/terminology

Each discovered report page is then fetched once, parsed (title, publication
date, summary, PDF link, product series) and classified. Already-harvested
pages are cached in data/cache.json, so re-runs only fetch new reports.
"""
from __future__ import annotations

import csv
import json
import re
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote_plus, unquote, urljoin, urlparse, urlunparse, parse_qs
from urllib import robotparser

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .classify import Classifier, ROOT

DATA = ROOT / "data"
CITATION_RX = re.compile(
    r"International Organization for Migration \(IOM\),\s*([A-Z][a-z]{2,9}\.?\s+\d{1,2},?\s+\d{4})")

Log = Callable[[str], None]
CACHE_VERSION = 2  # v2 adds attached files and page text (needed to find Needs Monitoring reports)
FILE_RX = re.compile(r"""((?:https?:)?(?://[a-z0-9.-]+)?/sites/g/files/[^\s"'<>]*?\.(?:pdf|xlsx?|zip|docx?))""", re.I)
NM_FILE_RX = re.compile(r"needs?[\s_-]*monitoring|(?:^|[\s_(-])NM[\s_-]", re.I)
NM_TEXT_RX = re.compile(r"needs?\s+monitoring", re.I)
ATLAS_FILE_RX = re.compile(r"atlas", re.I)
PDF_MAX_BYTES = 60_000_000


def file_name(f: str) -> str:
    return unquote(f.rsplit("/", 1)[-1])


def pdf_text(data: bytes, pages: int = 6) -> str:
    """Text of the first pages of a PDF (cover, summary, methodology)."""
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    return " ".join((p.extract_text() or "") for p in reader.pages[:pages])


def classify_pdf_text(text: str) -> tuple[str, str]:
    t = re.sub(r"\s+", " ", text)
    m = re.search(r".{0,70}needs?\s+monitoring.{0,70}", t, re.I)
    if m:
        return "needs", m.group(0).strip()
    m = re.search(r".{0,70}(idp and returnee atlas|idp atlas|\batlas\b).{0,50}", t, re.I)
    if m:
        return "atlas", m.group(0).strip()
    m = re.search(r".{0,60}(baseline assessment|site assessment|mobility tracking).{0,60}", t, re.I)
    return ("atlas", m.group(0).strip()) if m else ("unknown", "")


def load_config(path: Path | None = None) -> dict:
    return json.loads((path or ROOT / "config" / "crawler.json").read_text(encoding="utf-8"))


class Crawler:
    def __init__(self, config: dict | None = None, classifier: Classifier | None = None,
                 log: Log = print, stop_event: threading.Event | None = None):
        self.cfg = config or load_config()
        self.clf = classifier or Classifier()
        self.log = log
        self.stop = stop_event or threading.Event()
        self.base = self.cfg["base_url"].rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.cfg["user_agent"],
                                     "Accept-Language": "en"})
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=[429, 500, 502, 503, 504])
        self.session.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=8))
        self._lock = threading.Lock()
        self._last = 0.0
        self.robots = robotparser.RobotFileParser(self.base + "/robots.txt")
        try:
            self.robots.read()
            if getattr(self.robots, "disallow_all", False):
                self.log("Warning: robots.txt could not be read (access denied). The site or your network "
                         "proxy may be blocking this computer. Check the connection, then run again.")
        except Exception:  # unreachable robots.txt -> allow, but stay polite
            self.robots = None
        self.listing_hints: dict[str, dict] = {}

    # ---- HTTP ------------------------------------------------------------
    def _allowed(self, url: str) -> bool:
        return self.robots is None or self.robots.can_fetch(self.cfg["user_agent"], url)

    def get(self, url: str) -> str | None:
        if self.stop.is_set():
            return None
        if not self._allowed(url):
            self.log(f"  skipped (robots.txt): {url}")
            return None
        with self._lock:  # global politeness delay across worker threads
            wait = self.cfg["delay_seconds"] - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        try:
            r = self.session.get(url, timeout=self.cfg["timeout_seconds"])
            if r.status_code == 200:
                return r.text
            self.log(f"  HTTP {r.status_code}: {url}")
        except requests.RequestException as e:
            self.log(f"  error: {url} ({e.__class__.__name__})")
        return None

    def get_bytes(self, url: str) -> bytes | None:
        if self.stop.is_set() or not self._allowed(url):
            return None
        with self._lock:
            wait = self.cfg["delay_seconds"] - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
        try:
            with self.session.get(url, timeout=self.cfg["timeout_seconds"] * 4, stream=True) as r:
                if r.status_code != 200:
                    self.log(f"  HTTP {r.status_code}: {url}")
                    return None
                buf = bytearray()
                for chunk in r.iter_content(1 << 16):
                    buf += chunk
                    if len(buf) > PDF_MAX_BYTES:
                        self.log(f"  file too large to check: {url}")
                        return None
                return bytes(buf)
        except requests.RequestException as e:
            self.log(f"  error: {url} ({e.__class__.__name__})")
        return None

    def check_round_pdfs(self, cache: dict) -> int:
        """Open the PDF of every Mobility Tracking round report whose file name does not already
        say whether it is a Needs Monitoring report or an Atlas, and read its first pages."""
        todo = []
        for key, e in cache.items():
            if not Classifier.is_mt_main(e.get("title", "")):
                continue
            pdfs = [f for f in e.get("files") or [] if f.lower().endswith(".pdf")]
            if not pdfs or any(NM_FILE_RX.search(" " + file_name(f)) or ATLAS_FILE_RX.search(file_name(f)) for f in pdfs):
                continue
            if (e.get("pdf_check") or {}).get("file") == pdfs[0]:
                continue
            todo.append((key, pdfs[0]))
        if not todo:
            return 0
        self.log(f"Reading inside {len(todo)} round-report PDFs to tell Needs Monitoring from Atlas…")
        for i, (key, f) in enumerate(todo, 1):
            data = self.get_bytes(f)
            kind, evidence = ("unknown", "")
            if data:
                try:
                    kind, evidence = classify_pdf_text(pdf_text(data))
                except Exception as ex:  # damaged or scanned PDF
                    kind, evidence = "unknown", f"could not read PDF ({ex.__class__.__name__})"
            cache[key]["pdf_check"] = {"file": f, "kind": kind, "evidence": evidence[:200]}
            self.log(f"  {i}/{len(todo)} {kind:7} {file_name(f)[:70]}")
            if self.stop.is_set():
                break
        return len(todo)

    # ---- URL helpers -----------------------------------------------------
    def canon(self, href: str, page_url: str) -> str:
        u = urlparse(urljoin(page_url, href))
        return urlunparse((u.scheme, u.netloc, u.path.rstrip("/"), "", u.query, ""))

    def is_report(self, url: str) -> bool:
        u = urlparse(url)
        if not u.netloc.endswith(urlparse(self.base).netloc):
            return False
        if self.cfg["report_path"] not in u.path:
            return False
        slug = u.path.split(self.cfg["report_path"], 1)[1]
        return bool(slug) and self.cfg["report_slug_must_contain"] in slug.lower()

    @staticmethod
    def report_key(url: str) -> str:
        return urlparse(url).path.rstrip("/")

    # ---- Discovery -------------------------------------------------------
    def from_sitemaps(self) -> set[str]:
        found, queue, seen = set(), list(self.cfg.get("sitemaps", [])), set()
        while queue and not self.stop.is_set():
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            xml = self.get(sm)
            if not xml:
                continue
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
            for loc in locs:
                if loc.endswith(".xml") or "sitemap" in loc and "page=" in loc:
                    queue.append(loc)
                elif self.is_report(loc):
                    found.add(self.canon(loc, loc).split("?")[0])
            self.log(f"  sitemap {sm}: {len(locs)} entries")
        return found

    def _harvest_listing(self, html: str, page_url: str) -> tuple[set[str], set[str]]:
        soup = BeautifulSoup(html, "html.parser")
        reports, pages = set(), set()
        seed_path = urlparse(page_url).path.rstrip("/")
        for a in soup.find_all("a", href=True):
            url = self.canon(a["href"], page_url)
            if self.is_report(url):
                url = url.split("?")[0]
                reports.add(url)
                text = a.get_text(" ", strip=True)
                if text and len(text) > 15 and not text.endswith("…"):
                    card = a.find_parent(["article", "li", "div"])
                    blob = card.get_text(" ", strip=True) if card else ""
                    self.listing_hints.setdefault(self.report_key(url), {
                        "title": text, "date_raw": blob[:400]})
                continue
            u = urlparse(url)
            is_pager = ("page=" in u.query and u.path.rstrip("/") == seed_path) or \
                       ("next" in (a.get("rel") or [])) or \
                       (a.find_parent(class_=re.compile("pager")) is not None and u.path.rstrip("/") == seed_path)
            if is_pager:
                pages.add(url)
        return reports, pages

    def from_listings(self, seeds: Iterable[str], label: str = "listing") -> set[str]:
        found, seen, queue = set(), set(), list(seeds)
        limit = self.cfg["max_listing_pages"]
        while queue and len(seen) < limit and not self.stop.is_set():
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            html = self.get(url)
            if not html:
                continue
            reports, pages = self._harvest_listing(html, url)
            new = reports - found
            found |= reports
            queue.extend(p for p in sorted(pages, key=_page_no) if p not in seen)
            self.log(f"  {label} page {len(seen)}: +{len(new)} reports ({len(found)} total) {url}")
        return found

    def from_keywords(self, keywords: Iterable[str]) -> set[str]:
        found = set()
        for kw in keywords:
            if self.stop.is_set():
                break
            seeds = [t.replace("{q}", quote_plus(kw)) for t in self.cfg.get("keyword_search_templates", [])]
            got = self.from_listings(seeds, label=f"search '{kw}'")
            found |= got
        return found

    # ---- Report page -----------------------------------------------------
    def parse_report(self, url: str, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        meta = lambda **kw: (soup.find("meta", attrs=kw) or {}).get("content", "")  # noqa: E731
        h1 = soup.find("h1")
        title = (h1.get_text(" ", strip=True) if h1 else "") or meta(property="og:title") or \
                (soup.title.get_text(strip=True).split("|")[0] if soup.title else "")
        text = soup.get_text(" ", strip=True)
        cite = CITATION_RX.search(text)
        time_tag = soup.find("time")
        date_raw = " | ".join(filter(None, [
            cite.group(1) if cite else "",
            (time_tag.get("datetime") or time_tag.get_text(strip=True)) if time_tag else "",
            meta(property="article:published_time"),
        ]))
        summary = meta(name="description") or meta(property="og:description")
        if not summary:
            main = soup.find("main") or soup
            ps = [p.get_text(" ", strip=True) for p in main.find_all("p")]
            summary = next((p for p in ps if len(p) > 80), "")
        series = sorted({a.get_text(" ", strip=True) for a in soup.find_all("a", href=True)
                         if "/product-series/" in a["href"] and a.get_text(strip=True)})
        # every file the page references, wherever it appears (links, download forms, scripts)
        files, seen = [], set()
        for m in FILE_RX.findall(html):
            f = urljoin(url, m.replace("&amp;", "&")).split("?")[0]
            if f not in seen:
                seen.add(f)
                files.append(f)
        pdf = next((f for f in files if f.lower().endswith(".pdf")), "")
        # page text from the title onwards (skips site navigation), kept short
        body = text[text.find(title.strip()):] if title.strip() and title.strip() in text else text
        return {"url": url, "title": title.strip(), "date_raw": date_raw,
                "date": Classifier.parse_date(date_raw), "summary": summary[:600],
                "series": series, "pdf": pdf, "files": files[:20], "body": body[:3000],
                "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "v": CACHE_VERSION}

    def fetch_report(self, url: str) -> dict | None:
        html = self.get(url)
        if html:
            return self.parse_report(url, html)
        hint = self.listing_hints.get(self.report_key(url))
        if hint:  # page failed but the listing gave us enough to count it
            return {"url": url, "title": hint["title"], "date_raw": hint["date_raw"],
                    "date": Classifier.parse_date(hint["date_raw"]), "summary": "",
                    "series": [], "pdf": "", "from_listing_only": True}
        return None

    # ---- Orchestration ---------------------------------------------------
    def run(self, keywords: list[str] | None = None, use_sitemap: bool = True,
            use_listings: bool = True, refresh: bool = False,
            max_reports: int | None = None, quick: bool = False) -> dict:
        """quick=True checks only the newest listing pages (for frequent runs).
        New reports always appear on page 1, so this catches them in seconds."""
        if quick:
            use_sitemap, keywords = False, []
            self.cfg = {**self.cfg, "max_listing_pages": 3 * len(self.cfg["seeds"])}
        t0 = time.time()
        cache_path = DATA / "cache.json"
        cache = {} if refresh or not cache_path.exists() else json.loads(cache_path.read_text("utf-8"))

        urls: set[str] = set()
        if use_sitemap:
            self.log("Discovering via sitemap…")
            urls |= self.from_sitemaps()
        if use_listings:
            self.log("Discovering via listing pages…")
            urls |= self.from_listings(self.cfg["seeds"])
        kws = keywords if keywords is not None else self.cfg.get("keywords", [])
        if kws:
            self.log(f"Discovering via {len(kws)} keyword searches…")
            urls |= self.from_keywords(kws)
        self.log(f"Discovered {len(urls)} report URLs.")
        if not urls and not self.stop.is_set():
            raise RuntimeError("No report pages could be reached on dtm.iom.int. Check the internet "
                               "connection or proxy settings; existing data was left unchanged.")

        todo = [u for u in sorted(urls) if self.report_key(u) not in cache]
        # pages saved by an older harvester version are read again once, to pick up new fields
        upgrade = [v["url"] for v in cache.values() if v.get("v", 1) < CACHE_VERSION and not v.get("from_listing_only")]
        if upgrade:
            self.log(f"Re-reading {len(upgrade)} saved pages once to collect attached files and page text…")
            todo = sorted(set(todo) | set(upgrade))
        if max_reports:
            todo = todo[:max_reports]
        self.log(f"Fetching {len(todo)} new report pages ({len(cache)} cached)…")
        done = 0
        with ThreadPoolExecutor(max_workers=self.cfg["workers"]) as ex:
            futs = {ex.submit(self.fetch_report, u): u for u in todo}
            for f in as_completed(futs):
                rec = f.result()
                done += 1
                if rec:
                    cache[self.report_key(rec["url"])] = rec
                if done % 25 == 0 or done == len(todo):
                    self.log(f"  {done}/{len(todo)} fetched")
                    _write_json(cache_path, cache)
                if self.stop.is_set():
                    break
        _write_json(cache_path, cache)
        try:
            import pypdf  # noqa: F401
        except ImportError:  # install on the fly so the GitHub workflow needs no change
            import subprocess, sys
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "pypdf"], check=False)
        try:
            if self.check_round_pdfs(cache):
                _write_json(cache_path, cache)
        except ImportError:
            self.log("pypdf could not be installed, so round-report PDFs were not opened.")

        result = export(cache.values(), self.clf, keywords=kws,
                        seconds=round(time.time() - t0, 1), log=self.log)
        return result


# ---- Export -------------------------------------------------------------
def _page_no(url: str) -> int:
    q = parse_qs(urlparse(url).query).get("page", ["0"])[0]
    nums = re.findall(r"\d+", q)
    return int(nums[-1]) if nums else 0


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def export(records: Iterable[dict], clf: Classifier, keywords=None, seconds=None, log: Log = print) -> dict:
    classified = []
    skipped, pages = 0, []
    for r in records:
        if not clf.in_scope(r):
            skipped += 1
            continue
        rr = dict(r)
        extra = " ".join(rr.get("series") or [])
        c = clf.classify({**rr, "summary": (extra + " " + rr.get("summary", "")).strip()})
        c["summary"] = rr.get("summary", "")
        classified.append(c)
        pages.append((rr, c))

    # The DTM site sometimes publishes the same report twice; count each title once (earliest date).
    norm = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()  # noqa: E731
    first: dict[str, tuple] = {}
    for rr, c in sorted(pages, key=lambda p: (p[1].get("date") or "9999", p[1]["url"])):
        first.setdefault(norm(c["title"]), (rr, c))
    dupes = len(pages) - len(first)
    pages = list(first.values())
    classified = [c for _, c in pages]
    if dupes:
        log(f"Counted {dupes} duplicate report pages once each (same title published twice).")

    # Mobility Tracking: decide Needs Monitoring vs Atlas for each round's main report, using (in order)
    # the attached file names, the text inside the PDF, the page text, and finally the title.
    needs_label = next(x["label"] for x in clf.components if x["key"] == "needs")
    atlas_label = next(x["label"] for x in clf.components if x["key"] == "atlas")
    extra = []
    for rr, c in pages:
        rnd = Classifier.mt_round(c["title"])
        if c["component_key"] in ("needs", "atlas") and rnd:
            c["round"], c["round_zone"] = rnd, Classifier.mt_zone(c["title"])
        if not Classifier.is_mt_main(c["title"]) or c["component_key"] not in ("needs", "atlas"):
            continue
        c["mt_main"] = True
        pdfs = [f for f in rr.get("files") or [] if f.lower().endswith(".pdf")]
        nm_f = [f for f in pdfs if NM_FILE_RX.search(" " + file_name(f))]
        at_f = [f for f in pdfs if ATLAS_FILE_RX.search(file_name(f))]
        chk = rr.get("pdf_check") or {}
        if nm_f and at_f:
            kind, why = "atlas", "file name: " + file_name(at_f[0])[:70]
            extra.append((rr, c, nm_f[0]))
        elif nm_f:
            kind, why = "needs", "file name: " + file_name(nm_f[0])[:70]
        elif at_f:
            kind, why = "atlas", "file name: " + file_name(at_f[0])[:70]
        elif chk.get("kind") in ("needs", "atlas"):
            kind, why = chk["kind"], "inside PDF: \u201c" + chk.get("evidence", "")[:120] + "\u201d"
        elif NM_TEXT_RX.search(rr.get("body") or ""):
            kind, why = "needs", "report page says it contains needs monitoring findings"
        else:
            kind = c["component_key"]
            why = c.get("matched_on", "") + " (title only; PDF not yet checked)"
        c["component_key"], c["component"], c["matched_on"] = kind, (needs_label if kind == "needs" else atlas_label), why
        if pdfs and not c.get("pdf"):
            c["pdf"] = (nm_f or at_f or pdfs)[0]
    # A round's main report published twice (different page titles) counts once, earliest date.
    seen_main, keep = set(), []
    for c in sorted(classified, key=lambda c: c.get("date") or "9999"):
        k = (c.get("round_zone"), c.get("round"), c["component_key"]) if c.get("mt_main") and c.get("round") else None
        if k and k in seen_main:
            log(f"Round report counted once: {c['title'][:90]}")
            continue
        if k:
            seen_main.add(k)
        keep.append(c)
    classified = keep

    # A page carrying both an Atlas and a Needs Monitoring PDF holds two reports.
    have = {(c.get("round_zone"), c.get("round")) for c in classified if c["component_key"] == "needs" and c.get("round")}
    for rr, c, f in extra:
        if (c.get("round_zone"), c.get("round")) in have:
            continue
        n = dict(c)
        n.update(url=c["url"] + "#needs-monitoring", component_key="needs", component=needs_label, pdf=f,
                 title=f"{c['title']} \u2014 Needs Monitoring report", matched_on="file name: " + file_name(f)[:70])
        classified.append(n)

    classified.sort(key=lambda r: (r.get("date") or "", r["title"]), reverse=True)
    for i, r in enumerate(classified):
        r["id"] = i + 1

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_path = DATA / "reports.json"
    prev = json.loads(prev_path.read_text("utf-8")) if prev_path.exists() else {}
    fp = lambda rs: sorted((r["url"], r["title"], r.get("date") or "", r["component_key"]) for r in rs)  # noqa: E731
    changed = not prev or fp(prev.get("reports", [])) != fp(classified)
    prev_urls = {r["url"] for r in prev.get("reports", [])}
    if changed:
        added = [{"title": r["title"], "url": r["url"], "date": r.get("date")}
                 for r in classified if r["url"] not in prev_urls][:50] if prev else []
    else:
        added = prev.get("latest_additions", [])

    payload = {
        # generated_at = when the report list last CHANGED, so the dashboard can tell new data apart
        "generated_at": now if changed else prev.get("generated_at", now),
        "source": "https://dtm.iom.int/nigeria",
        "keywords": keywords or [],
        "latest_additions": added,
        "components": [{"key": c["key"], "label": c["label"]} for c in clf.components] +
                      [{"key": clf.tax.get("unclassified_key", "other"), "label": clf.tax["unclassified_label"]}],
        "regions": {k: v["states"] for k, v in clf.tax["regions"].items()},
        "mt_rounds": {k: v for k, v in clf.tax.get("mobility_tracking_rounds", {}).items() if not k.startswith("_")},
        "count": len(classified),
        "reports": [{k: r.get(k) for k in ("id", "title", "date", "year", "component_key", "component",
                                            "regions", "states", "url", "pdf", "summary", "matched_on", "date_basis",
                                            "period_date", "round", "round_zone", "mt_main")}
                    for r in classified],
    }
    status = {"checked_at": now, "last_changed": payload["generated_at"], "count": len(classified),
              "changed_this_run": changed, "new_this_run": len(added) if changed else 0, "crawl_seconds": seconds}
    _write_json(DATA / "status.json", status)
    if not changed:
        log(f"No new or changed reports ({len(classified)} total). Data files left as they were.")
        return payload
    _write_json(DATA / "reports.json", payload)
    # JS wrapper so the dashboard can load data from file:// with no server
    (DATA / "reports.js").write_text("window.DTM_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
                                     encoding="utf-8")

    with open(DATA / "reports.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "year", "date", "component", "regions", "states", "title", "url", "pdf", "matched_on"])
        for r in classified:
            w.writerow([r["id"], r.get("year"), r.get("date"), r["component"], "; ".join(r["regions"]),
                        "; ".join(r["states"]), r["title"], r["url"], r.get("pdf", ""), r.get("matched_on", "")])

    pivot = defaultdict(Counter)
    years = sorted({r["year"] for r in classified if r.get("year")})
    for r in classified:
        if r.get("year"):
            pivot[r["component"]][r["year"]] += 1
    with open(DATA / "counts_component_by_year.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["component", *years, "total"])
        for comp, cnt in sorted(pivot.items()):
            w.writerow([comp, *[cnt.get(y, 0) for y in years], sum(cnt.values())])

    unclassified = sum(1 for r in classified if r["component_key"] == payload["components"][-1]["key"])
    if skipped:
        log(f"Left out {skipped} pages that are not DTM Nigeria reports (see scope_title_regex in taxonomy.json).")
    log(f"Exported {len(classified)} reports ({len(added)} new, {unclassified} unclassified) -> data/reports.json, .csv, .js")
    return payload
