"""Pure deterministic routing classifier. It does not diagnose or import DB/web code."""
from dataclasses import dataclass, asdict
import re
import unicodedata
from typing import Protocol

from app.engine.lexicons import FALL_WORDS, INTENSITY, NEGATIONS, PERSISTENCE, RULES

CLASSIFIER_VERSION = "rules-1"
ROMANISED_HINDI = {"seene mein dard", "saans nahi aa rahi", "behosh", "khoon bahut", "daura", "paani chahiye"}

class UrgencyAdvisor(Protocol):
    def advise(self, text: str, context: dict) -> int | None: ...

class NullAdvisor:
    def advise(self, text: str, context: dict) -> int | None:
        return None

@dataclass(frozen=True)
class MatchedRule:
    id: str
    label: str
    lang: str
    span: tuple[int, int]

@dataclass(frozen=True)
class Classification:
    level: int
    category: str
    severity: str
    matched_rules: tuple[MatchedRule, ...]
    modifiers: tuple[str, ...]
    negation_detected: bool
    reasons: tuple[str, ...]
    classifier_version: str
    advisor: dict | None = None

    def as_dict(self):
        return asdict(self)


def _normalise(value: str) -> str:
    value = unicodedata.normalize("NFC", value).lower()
    value = "".join(ch if unicodedata.category(ch)[0] in "LMN" or ch.isspace() or ch == "'" else " " for ch in value)
    return re.sub(r"\s+", " ", value).strip()


def _pattern_language(phrase: str) -> str:
    for ch in phrase:
        code = ord(ch)
        if 0x0900 <= code <= 0x097F: return "hi"
        if 0x0C80 <= code <= 0x0CFF: return "kn"
        if 0x0C00 <= code <= 0x0C7F: return "te"
    return "hi" if _normalise(phrase) in ROMANISED_HINDI else "en"


def classify_message(text: str, *, language_hint: str | None = None, context: dict | None = None,
                     advisor: UrgencyAdvisor | None = None, sos: bool = False) -> Classification:
    """Classify routing urgency; unknown or ambiguous text defaults to L2."""
    context = context or {}
    clean = _normalise(text)
    found: list[MatchedRule] = []
    candidates = []
    for rule in RULES:  # Deliberately scan every language, regardless of hint.
        for phrase in rule["patterns"]:
            term = _normalise(phrase)
            match = re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", clean)
            if match:
                found.append(MatchedRule(rule["id"], phrase, _pattern_language(phrase), match.span()))
                candidates.append((rule["level"], rule["category"], rule))
                break
    level, category = (2, "UNCLASSIFIED")
    if candidates:
        level, category, _ = max(candidates, key=lambda item: item[0])
    reasons = []
    if found:
        reasons.extend(f"Matched '{m.label}' ({m.lang.upper()}) → L{next(x[0] for x in candidates if x[2]['id'] == m.id)} {next(x[1].lower().replace('_',' ') for x in candidates if x[2]['id'] == m.id)}" for m in found)
    else:
        reasons.append("Text was not recognised by a specific rule; routed to L2 for review")
    modifiers = []
    severity = "HIGH" if level >= 5 else "MEDIUM"
    if any(_normalise(word) in clean for word in INTENSITY):
        level = min(5, level + 1); severity = "HIGH"; modifiers.append("intensity")
        reasons.append("Intensity wording raised routing level")
    if any(_normalise(word) in clean for word in PERSISTENCE):
        severity = "HIGH" if severity != "HIGH" else severity; modifiers.append("persistence")
        reasons.append("Persistence wording raised severity")
    if context.get("repeat_category") and context["repeat_category"] == category:
        level = min(5, level + 1); modifiers.append("repeat_24h"); reasons.append("Repeated category within 24 hours raised routing level")
    negation = False
    if level >= 5 and category == "EMERGENCY":
        for m in found:
            if not m.id.startswith("emergency_"): continue
            words_before = clean[:m.span[0]].split()[-3:]
            phrase_words = _normalise(m.label).split()
            meaningful_negations = [n for n in NEGATIONS if n not in phrase_words]
            if any(n in words_before for n in meaningful_negations):
                negation = True; level = 3; category = "HEALTH_CONCERN"
                reasons.append("Negation near emergency wording lowered routing to L3 for human review")
                modifiers.append("negated_red_flag")
                break
    if context.get("mobility_level") in {"WHEELCHAIR", "BEDBOUND"} and any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", clean) for w in FALL_WORDS):
        level = 5; category = "EMERGENCY"; severity = "HIGH"; modifiers.append("mobility_fall"); reasons.append("Fall with limited mobility routed to L5")
    if context.get("critical_activity_within_3h") and category == "LOGISTICS":
        severity = "HIGH"; modifiers.append("critical_activity_within_3h"); reasons.append("Critical activity within 3 hours raised severity")
    if sos:
        level = 5; category = "EMERGENCY"; severity = "HIGH"; modifiers.append("sos_override"); reasons.append("SOS request always routes to L5")
    advisor_result = None
    if advisor:
        try:
            suggested = advisor.advise(text[:1000], {k: v for k, v in context.items() if k in {"mobility_level", "critical_activity_within_3h"}})
            if suggested is not None and not 0 <= int(suggested) <= 5:
                raise ValueError("advisor level is outside 0..5")
            applied = None
            if suggested is not None and 0 <= int(suggested) <= 5 and int(suggested) > level:
                level = int(suggested); applied = level; modifiers.append("advisor_raise"); reasons.append(f"Urgency advisor raised routing to L{level}")
            advisor_result = {"suggested_level": suggested, "applied_level": applied}
        except Exception:
            advisor_result = {"error": "advisor_unavailable"}
    if level == 0 and (any(_normalise(n) in clean for n in NEGATIONS) or any(_normalise(w) in clean for w in ("pain", "dizzy", "fever", "vomiting", "worse"))):
        level, category = 2, "UNCLASSIFIED"; reasons.append("Negative or symptom wording prevented informational routing")
    return Classification(level, category, severity, tuple(found), tuple(modifiers), negation, tuple(reasons), CLASSIFIER_VERSION, advisor_result)
