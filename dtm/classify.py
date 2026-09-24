"""Keyword-based classification of DTM Nigeria report records.

Every rule lives in config/taxonomy.json so the IM team can tune keywords
without touching code.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def load_taxonomy(path: Path | None = None) -> dict:
    path = path or ROOT / "config" / "taxonomy.json"
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _norm(text: str) -> str:
    """Lower-case, unify dashes/quotes, pad with spaces so ' ett ' style terms work."""
    text = (text or "").lower()
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    text = re.sub(r"[^\w&/\-\s]", " ", text)
    return " " + re.sub(r"\s+", " ", text).strip() + " "


class Classifier:
    def __init__(self, taxonomy: dict | None = None):
        self.tax = taxonomy or load_taxonomy()
        self.components = self.tax["components"]
        self.state_region = {}
        self.state_rx = {}
        overrides = self.tax.get("state_patterns", {})
        for region, spec in self.tax["regions"].items():
            for st in spec["states"]:
                self.state_region[st] = region
                pat = overrides.get(st, r"\b" + re.escape(st.lower()) + r"\b")
                self.state_rx[st] = re.compile(pat, re.I)
        self.region_rx = {
            region: [re.compile(r"(?<![a-z])" + re.escape(a.lower()) + r"(?![a-z])") for a in spec["aliases"]]
            for region, spec in self.tax["regions"].items()
        }

    # ---- component -------------------------------------------------------
    def component(self, title: str, summary: str = "") -> tuple[str, str, str]:
        """Return (key, label, matched_term). Title is decisive; summary is a fallback."""
        for text, where in ((_norm(title), "title"), (_norm(summary), "summary")):
            for rule in self.components:
                if any(_norm(x).strip() in text for x in rule.get("exclude", []) if x.strip()):
                    continue
                for term in rule["include"]:
                    t = term.lower()
                    if t.startswith(" ") or t.endswith(" "):
                        hit = t in text
                    else:
                        hit = _norm(t).strip() in text
                    if hit:
                        return rule["key"], rule["label"], f"{where}:{term.strip()}"
        return self.tax.get("unclassified_key", "other"), self.tax["unclassified_label"], ""

    # ---- geography -------------------------------------------------------
    def states(self, text: str) -> list[str]:
        return [st for st, rx in self.state_rx.items() if rx.search(text or "")]

    def regions(self, title: str, summary: str, states: list[str]) -> list[str]:
        found = {self.state_region[s] for s in states}
        t = _norm(title)
        for region, rxs in self.region_rx.items():
            if any(rx.search(t) for rx in rxs):
                found.add(region)
        if not found:  # fall back to summary only when the title is silent
            s = _norm(summary)
            for region, rxs in self.region_rx.items():
                if any(rx.search(s) for rx in rxs):
                    found.add(region)
        order = list(self.tax["regions"].keys())
        return sorted(found, key=order.index)

    # ---- dates -----------------------------------------------------------
    @staticmethod
    def parse_date(*candidates: str) -> str | None:
        """Return ISO date (YYYY-MM-DD) from the first parseable candidate.
        A candidate string may hold several dates joined by ' | '; they are tried
        left to right, so the report's citation date wins over site-wide timestamps."""
        parts = [p.strip() for c in candidates if c for p in c.split(" | ") if p.strip()]
        for c in parts:
            m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", c)
            if m and m.group(1).lower() in MONTHS:
                return f"{m.group(3)}-{MONTHS[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
            m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})\b", c)
            if m and m.group(2).lower() in MONTHS:
                return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", c)
            if m:
                return m.group(0)
        return None

    @staticmethod
    def year_from_title(title: str) -> int | None:
        years = [int(y) for y in re.findall(r"\b(20[1-3]\d)\b", title or "")]
        return years[-1] if years else None

    def in_scope(self, rec: dict) -> bool:
        rx = self.tax.get("scope_title_regex")
        return not rx or bool(re.search(rx, rec.get("title", ""), re.I))

    # ---- full record -----------------------------------------------------
    def classify(self, rec: dict) -> dict:
        title, summary = rec.get("title", ""), rec.get("summary", "")
        key, label, why = self.component(title, summary)
        states = self.states(title) or self.states(summary)
        date = self.parse_date(rec.get("date_raw", "")) or rec.get("date")
        year = int(date[:4]) if date else self.year_from_title(title)
        out = dict(rec)
        out.update({
            "component_key": key,
            "component": label,
            "matched_on": why,
            "states": states,
            "regions": self.regions(title, summary, states),
            "date": date,
            "year": year,
            "classified_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        return out


if __name__ == "__main__":  # quick manual check
    c = Classifier()
    for t in ["Nigeria — Emergency Tracking Tool Report 378 (29 April - 5 May 2024)",
              "Nigeria — North-central & North-west Flash Report 163 (22 - 28 April 2024)",
              "Nigeria — Bauchi - Intention Survey (April 2024)"]:
        r = c.classify({"title": t})
        print(r["component"], r["regions"], r["states"], r["year"])
