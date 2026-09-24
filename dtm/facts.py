"""Pull the numbers out of each report's text so the dashboard assistant can answer
"how many households / individuals / camps ..." questions with evidence.

Sources, in order of trust: the report page's description, its summary, then the
text of the first pages of its PDF. Every figure keeps the sentence it came from.
"""
from __future__ import annotations

import re

NUM = r"(\d{1,3}(?:[ ,]\d{3})+|\d+(?:\.\d+)?)"
# (label, noun pattern that follows the number). Order matters: specific before general.
METRICS = [
    ("households", r"households?|hhs?\b|families"),
    ("new arrivals", r"new arrivals?|arrivals?"),
    ("departures", r"departures?"),
    ("returnees", r"returnees|returned individuals|returnee individuals"),
    ("IDPs", r"internally displaced persons|internally displaced people|idps"),
    ("individuals", r"individuals|persons|people|inhabitants"),
    ("camps", r"camps?(?: and camp-like settings?)?|camp-like settings?"),
    ("host communities", r"host communit(?:y|ies)(?: locations)?"),
    ("locations", r"locations|sites|communities|settlements"),
    ("wards", r"wards"),
    ("LGAs", r"local government areas|lgas"),
    ("shelters", r"shelters?|makeshift shelters?"),
    ("herders", r"herders"),
    ("animals", r"animals|livestock|cattle|heads? of cattle"),
    ("alerts", r"alerts"),
    ("fatalities", r"fatalities|deaths|dead|killed"),
    ("injuries", r"injur(?:y|ies)|injured"),
    ("children", r"children"),
    ("women", r"women"),
    ("men", r"men"),
    ("migrants", r"migrants|travell?ers|movements"),
    ("key informants", r"key informants"),
]
_METRIC_RX = [(lab, re.compile(NUM + r"\s+(?:\w+\s+){0,2}?(?:" + pat + r")\b", re.I)) for lab, pat in METRICS]
_PERCENT = re.compile(r"\d\s*%|per ?cent", re.I)
_SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9(])")
_KEEP = re.compile(r"\d", re.I)


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    out = []
    for sent in _SENT_SPLIT.split(text):
        sent = sent.strip()
        if 25 <= len(sent) <= 450 and _KEEP.search(sent):
            out.append(sent)
    return out


def subject(sent: str) -> str:
    """Who a figure is about: IDPs, returnees, displaced (flash/ETT), or general."""
    t = sent.lower()
    if "returnee" in t or "returned" in t:
        return "returnees"
    if "idp" in t or "internally displaced" in t:
        return "IDPs"
    if "displaced" in t or "fled" in t:
        return "displaced"
    if "arriv" in t:
        return "arrivals"
    return ""


def local_subject(s: str, start: int, end: int, label: str) -> str:
    """What THIS number describes, judged from the words right around it
    ("affected 16,921 individuals ... displaced 3,894 individuals")."""
    if label in ("IDPs", "returnees", "new arrivals", "departures"):
        return {"IDPs": "IDPs", "returnees": "returnees", "new arrivals": "arrivals", "departures": "departures"}[label]
    before = s[max(0, start - 45):start].lower()
    after = re.split(r"\d", s[end:end + 30].lower())[0]      # stop at the next number
    verbs = (("displac", "displaced"), ("affect", "affected"), ("regist", "registered"), ("returnee", "returnees"),
             ("idp", "IDPs"), ("arriv", "arrivals"), ("fled", "displaced"), ("identified", ""), ("recorded", ""))
    best, pos = "", -1
    for word, subj in verbs:              # the verb closest BEFORE the number decides
        i = before.rfind(word)
        if i > pos:
            best, pos = subj, i
    if pos >= 0:
        return best
    for word, subj in verbs:              # else a verb right after it ("individuals displaced")
        if word in after:
            return subj
    return ""


def extract(page_text: str, summary: str, pdf_text: str, limit_sentences: int = 45) -> dict:
    """Return {"s": [sentences], "f": [[label, value, sentence_index, subject, source]]}."""
    sents, src, seen = [], [], set()
    for source, text in (("page", page_text), ("summary", summary), ("pdf", pdf_text)):
        for s in sentences(text):
            k = re.sub(r"\W+", "", s.lower())[:160]
            if k in seen:
                continue
            seen.add(k)
            sents.append(s)
            src.append(source)
            if len(sents) >= limit_sentences:
                break
    figs, got = [], set()
    for i, s in enumerate(sents):
        for lab, rx in _METRIC_RX:
            for m in rx.finditer(s):
                val = _num(m.group(1))
                if val is None or (1900 <= val <= 2035 and "," not in m.group(1)):
                    continue  # a year, not a count
                tail = s[m.end():m.end() + 12]
                if _PERCENT.search(s[m.start():m.end() + 3]):
                    continue
                pre = s[max(0, m.start() - 22):m.start()].lower()
                if val != int(val) or re.search(r"average|size of|\bper\b|ratio|rate of", pre):
                    continue  # averages and rates are not counts
                subj = local_subject(s, m.start(), m.end(), lab) or subject(s)
                key = (lab, val, subj)
                if key in got:
                    continue
                got.add(key)
                figs.append([lab, int(val) if val == int(val) else val, i, subj, src[i]])
                del tail
    return {"s": sents, "f": figs}
