"""Two-tier foreign-eligibility detection.

Tier 1 (regex) matches the standard phrases Swiss agents use, in German,
French, Italian, and English, over normalized text. Tier 2 asks Sonnet through
OpenRouter to read the full listing text and return strict JSON, and the model
must quote a verbatim snippet that actually appears in the text, which is the
hallucination guard.

Both tiers run on every listing. The eligible result is the superset (either
method flags it), and an alignment Boolean records whether they agreed.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
import urllib.request

from .config import LEX_WEBER_YEAR


def normalize(text: str) -> str:
    s = (text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch))


_ELIGIBLE = [
    r"verkauf\s+an\s+auslaender", r"an\s+personen\s+im\s+ausland",
    r"auslaender\s+(?:erlaubt|moeglich|zulaessig)",
    r"(?:erwerb|kauf)\s+durch\s+auslaender", r"auch\s+an\s+auslaender",
    r"auslaendererwerb\s+moeglich", r"fuer\s+auslaender\s+erwerbbar",
    r"vente\s+aux\s+etrangers", r"acquisition\s+par\s+des\s+etrangers",
    r"domicili\w*\s+a\s+l.{0,3}etranger", r"(?:ouvert|accessible)\s+aux\s+etrangers",
    r"vendita\s+a\s+stranieri", r"acquisto\s+da\s+parte\s+di\s+stranieri",
    r"aperto\s+agli\s+stranieri",
    r"(?:available|sale|open)\s+to\s+(?:foreign(?:ers)?|international\s+buyers)",
    r"foreigners?\s+permitted",
]
_NEGATION = [
    r"nicht\s+an\s+auslaender", r"kein(?:e)?\s+verkauf\s+an\s+auslaender",
    r"nur\s+an\s+schweizer", r"nicht\s+fuer\s+auslaender",
    r"pas\s+de\s+vente\s+aux\s+etrangers", r"reserve\s+aux\s+residents\s+suisses",
    r"non\s+ouvert\s+aux\s+etrangers", r"riservato\s+a\s+residenti\s+svizzeri",
    r"non\s+a\s+stranieri", r"swiss\s+residents\s+only", r"not\s+available\s+to\s+foreign",
]
_NEW_BUILD = [r"neubau", r"erstbezug", r"nouvelle\s+construction", r"\bneuf\b",
              r"nuova\s+costruzione", r"new\s+build", r"newly\s+built"]
_PRIMARY = [r"erstwohnung(?:spflicht)?", r"hauptwohnsitz(?:pflicht)?",
            r"residence\s+principale", r"residenza\s+primaria", r"primary\s+residence\s+only"]
_MANAGED = [r"bewirtschaftet", r"warme[sn]?\s+bett", r"vermietungspflicht",
            r"residence\s+geree", r"logement\s+gere", r"gestione\s+alberghiera",
            r"rental\s+obligation", r"managed\s+rental"]
_EXISTING = [r"altbau", r"altrechtlich", r"bestehende\s+wohnung", r"\bbestand\b",
             r"zweitwohnung", r"residence\s+secondaire", r"residenza\s+secondaria",
             r"resale", r"wiederverkauf"]


def _compile(patterns):
    return re.compile("|".join(patterns), re.IGNORECASE)


ELIGIBLE_RX = _compile(_ELIGIBLE)
NEGATION_RX = _compile(_NEGATION)
NEW_RX = _compile(_NEW_BUILD)
PRIMARY_RX = _compile(_PRIMARY)
MANAGED_RX = _compile(_MANAGED)
EXISTING_RX = _compile(_EXISTING)

BUILD_EXISTING = "existing"
BUILD_NEW_PRIMARY = "new_primary"
BUILD_NEW_MANAGED = "new_managed"
BUILD_NEW_OTHER = "new_unspecified"
BUILD_UNKNOWN = "unknown"


def _first(rx, text):
    m = rx.search(text)
    return m.group(0) if m else ""


def detect_build(text: str, year_built=None) -> str:
    is_new = bool(NEW_RX.search(text))
    if is_new and PRIMARY_RX.search(text):
        return BUILD_NEW_PRIMARY
    if is_new and MANAGED_RX.search(text):
        return BUILD_NEW_MANAGED
    if is_new:
        return BUILD_NEW_OTHER
    if EXISTING_RX.search(text):
        return BUILD_EXISTING
    if year_built is not None and year_built < LEX_WEBER_YEAR:
        return BUILD_EXISTING
    return BUILD_UNKNOWN


def classify_rules(title, description, year_built=None) -> dict:
    text = normalize(f"{title}\n{description}")
    build = detect_build(text, year_built)
    neg = _first(NEGATION_RX, text)
    if neg:
        return {"eligible": False, "snippet": neg, "build": build, "confidence": 0.95}
    pos = _first(ELIGIBLE_RX, text)
    if pos:
        return {"eligible": True, "snippet": pos, "build": build, "confidence": 0.95}
    return {"eligible": None, "snippet": "", "build": build, "confidence": 0.0}


# ---------------------------------------------------------------------------
# Tier 2: Sonnet via OpenRouter (reads the full listing text)
# ---------------------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
LLM_SYSTEM = (
    "You classify Swiss real estate listings for one question: does the text "
    "assert the property may be sold to a foreigner resident abroad (a Lex Koller "
    "holiday-home eligibility statement)? Reply with ONLY a JSON object, no prose, "
    "no code fences, with keys: eligible (true, false, or null if the text does "
    "not say), confidence (0 to 1), snippet (a verbatim substring supporting the "
    "call, or empty string), and build_type (one of existing, new_primary, "
    "new_managed, new_unspecified, unknown). Do not infer eligibility from the "
    "town alone. If the text is silent, return null."
)


DEFAULT_LLM_MODEL = "anthropic/claude-sonnet-5.5"
LLM_FAILURES = []


def classify_llm(title, description, canton, municipality):
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    # `or`, not a get() default: Actions passes an unset repo variable as "".
    model = os.environ.get("OPENROUTER_MODEL") or DEFAULT_LLM_MODEL
    user = (
        f"Canton: {canton}. Municipality: {municipality}.\n"
        f"Title: {title}\n\nDescription:\n{description}"
    )
    payload = json.dumps({
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        OPENROUTER_URL, data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        raw = data["choices"][0]["message"]["content"]
        raw = re.sub(r"```json|```", "", raw).strip()
        parsed = json.loads(raw)
    except Exception as exc:
        LLM_FAILURES.append(f"{municipality}: {exc}")
        if len(LLM_FAILURES) <= 3:
            detail = exc.read().decode("utf-8", "replace")[:300] if hasattr(exc, "read") else ""
            print(f"LLM call failed ({model}): {exc} {detail}", file=sys.stderr)
        return None

    eligible = parsed.get("eligible", None)
    snippet = (parsed.get("snippet") or "").strip()
    conf = float(parsed.get("confidence", 0) or 0)
    build = parsed.get("build_type") or BUILD_UNKNOWN
    # Verbatim guard: a positive must quote text that appears in the listing.
    if eligible is True and snippet and normalize(snippet) not in normalize(description):
        return {"eligible": None, "snippet": "", "build": build, "confidence": 0.3}
    return {"eligible": eligible, "snippet": snippet, "build": build, "confidence": conf}


def combine(rules, llm) -> dict:
    """Superset of the two verdicts, with an alignment Boolean."""
    re_ = rules["eligible"]
    le = None if llm is None else llm["eligible"]
    if re_ is True or le is True:
        final = True
    elif re_ is False or le is False:
        final = False
    else:
        final = None
    align = None if (re_ is None or le is None) else (re_ == le)
    if re_ is not None and le is not None:
        method = "both"
    elif re_ is not None:
        method = "rule"
    elif le is not None:
        method = "llm"
    else:
        method = "none"
    snippet = rules["snippet"] or (llm["snippet"] if llm else "")
    build = rules["build"]
    if build == BUILD_UNKNOWN and llm and llm.get("build"):
        build = llm["build"]
    conf = max(rules["confidence"], (llm["confidence"] if llm else 0.0))
    return {
        "eligible": final, "rules_eligible": re_, "llm_eligible": le, "align": align,
        "method": method, "snippet": snippet, "build": build, "confidence": conf,
    }


def classify(listing: dict, use_llm: bool = True) -> dict:
    rules = classify_rules(listing.get("title", ""), listing.get("description", ""),
                           listing.get("year_built"))
    llm = None
    if use_llm and (listing.get("description") or "").strip():
        llm = classify_llm(listing.get("title", ""), listing.get("description", ""),
                           listing.get("canton", ""), listing.get("municipality", ""))
    det = combine(rules, llm)
    # Records whether the model actually answered, so a failed or skipped call
    # is retried on the next run instead of being cached as "text is silent".
    det["llm_ok"] = llm is not None
    return det
