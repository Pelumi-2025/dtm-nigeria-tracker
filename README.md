# DTM Nigeria publications tracker

Harvests every report IOM DTM Nigeria publishes on https://dtm.iom.int/nigeria, classifies each one by report type, region, state and year using keywords, and shows the counts in an interactive dashboard that works online and offline, with an AI assistant built in.

## Quick start (Windows)

1. Install Python 3.10 or newer from python.org (tick "Add Python to PATH").
2. Double-click `run_dashboard.bat`. The dashboard opens at http://localhost:8050.
3. Click **Harvest now**. The first harvest reads every Nigeria report page and takes a while (roughly 1 second per report, on purpose, to be polite to the IOM server). Later harvests only fetch new reports.

On Mac or Linux, run `./run_dashboard.sh` instead.

## What is in the folder

| Path | What it does |
|---|---|
| `scrape.py` | Command-line harvester |
| `server.py` | Serves the dashboard, runs harvests in the background, powers the AI assistant |
| `build_site.py` | Builds the web site and the single-file offline dashboard |
| `config/taxonomy.json` | Keywords that decide report type, region and state. Edit freely |
| `config/crawler.json` | Pages to crawl, search keywords, speed and politeness settings |
| `dashboard/` | The dashboard (HTML, offline service worker, app manifest) |
| `data/` | Harvest output: `reports.json`, `reports.csv`, `counts_component_by_year.csv`, `cache.json` |
| `.github/workflows/harvest.yml` | Optional daily automatic harvest and web publishing |

## How the harvester finds reports

It discovers report pages three ways and merges the results: the site's sitemap, the Nigeria listing pages (following every "next page" link), and a site search for each keyword in `config/crawler.json`. Each report page is read once for its title, publication date (from the citation line "International Organization for Migration (IOM), May 25 2023"), summary, PDF link and product series. Pages already harvested are kept in `data/cache.json`.

```
python scrape.py                                     # full harvest
python scrape.py --keywords "flood, biometric"       # add your own keywords/terminologies
python scrape.py --reclassify                        # re-apply taxonomy.json, no internet needed
python scrape.py --refresh                           # re-read every page from scratch
```

## Tuning the classification

Open `config/taxonomy.json`. Each report type has `include` keywords and optional `exclude` keywords. Rules run top to bottom and the first match wins, checked against the title first, then the summary. That order matters: Early Warning comes before Transhumance so "Transhumance Tracking Tool — Early Warning Dashboard" lands in Early Warning. After editing, run `python scrape.py --reclassify` and reload the dashboard. Anything that matches no rule shows as "Other / Unclassified"; look at those titles to find keywords worth adding.

States are matched as whole words, so "Niger" never matches "Nigeria". Region comes from the states found, or from phrases like "North-east" and "North-central & North-west" in the title.

## Using the dashboard

Report types, regions and states are multi-select checklists. Years run 2019 to 2030: drag the slider for a range, or click individual year buttons to pick any combination (for example 2019, 2022 and 2025 only). Click any cell in the matrix to list those exact reports. **Download counts** saves the type-by-year matrix; **Export CSV** saves the filtered report list.

## The AI assistant

Click **Ask the data**. It answers questions and can change the dashboard for you, for example "flash reports per year in Borno since 2021", "compare ETT reports in 2023 and 2024", "show transhumance reports for Katsina", or "fetch latest reports on flood".

It runs in one of three modes, shown under its title:

- **Claude, via your server**: set an Anthropic API key before starting the server (`set ANTHROPIC_API_KEY=sk-ant-...` on Windows, `export ...` on Mac/Linux). This mode can also start a new harvest of the website when you ask it to fetch.
- **Claude, in claude.ai**: the published claude.ai version uses the viewer's Claude account. It answers from the loaded data but cannot crawl the site.
- **Offline command assistant**: always available, no internet or key needed. Understands report types, states, regions, years, "per year", "by state", "show", "list", "reset", and "fetch".

## Online and offline

**Offline, single file.** Run `python build_site.py`, then use `site/DTM_Nigeria_Dashboard_OFFLINE.html`. The data is inside the file, so it opens with no internet, can be emailed, or copied to a USB stick. Rebuild it after each harvest.

**Offline, installed.** When served from `server.py` or GitHub Pages, the browser caches the dashboard and the last data, so it keeps working if the connection drops. In Chrome or Edge you can also install it as an app from the address bar.

**Live on the web, updating itself.** Follow `GITHUB_SETUP.md`. GitHub checks dtm.iom.int every hour (full crawl nightly) and republishes the site; open dashboards pick up new reports within 5 minutes without losing their filters.

**Any other host.** Upload the contents of `site/` to SharePoint, an intranet server or any static web host.

## Good practice

The crawler identifies itself, respects robots.txt, waits between requests and retries gently on errors. Keep `delay_seconds` at 0.5 or more. If the site's layout or search address changes, update `seeds` or `keyword_search_templates` in `config/crawler.json`; if a harvest finds nothing, it stops with a message and leaves your existing data untouched.
