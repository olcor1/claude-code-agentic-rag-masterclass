from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import ConversationPIIRegistryEntry
from app.services.local_llm import get_local_llm_client, get_local_llm_model
from app.services.metadata import extract_json_object, get_completion_text

try:  # pragma: no cover - optional dependency path
    from faker import Faker
except Exception:  # pragma: no cover - optional dependency path
    Faker = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from gender_guesser import detector as gender_detector
except Exception:  # pragma: no cover - optional dependency path
    gender_detector = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from nameparser import HumanName
except Exception:  # pragma: no cover - optional dependency path
    HumanName = None  # type: ignore[assignment]

try:  # pragma: no cover - optional dependency path
    from presidio_analyzer import AnalyzerEngine
except Exception:  # pragma: no cover - optional dependency path
    AnalyzerEngine = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\w)(?:\+?1[-.\s]*)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}(?!\w)")
URL_PATTERN = re.compile(r"\bhttps?://[^\s<>()]+", re.IGNORECASE)
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
IBAN_PATTERN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b", re.IGNORECASE)
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, \d{4})\b",
    re.IGNORECASE,
)
PERSON_FALLBACK_PATTERN = re.compile(
    r"\b(?:Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2}\b"
)
TITLE_PREFIX_PATTERN = re.compile(r"^(mr|mrs|ms|miss|dr|prof)\.?\s+", re.IGNORECASE)
SUFFIX_PATTERN = re.compile(r"(?:,\s*|\s+)(jr|sr|ii|iii|iv)\.?$", re.IGNORECASE)

PERSON_TITLES = {
    "mr": "Mr.",
    "mrs": "Mrs.",
    "ms": "Ms.",
    "miss": "Miss",
    "dr": "Dr.",
    "prof": "Prof.",
}
NICKNAME_CANONICAL = {
    "abby": "abigail",
    "abe": "abraham",
    "alex": "alexander",
    "andy": "andrew",
    "ben": "benjamin",
    "beth": "elizabeth",
    "bill": "william",
    "bob": "robert",
    "charlie": "charles",
    "danny": "daniel",
    "dave": "david",
    "kate": "katherine",
    "katie": "katherine",
    "liz": "elizabeth",
    "maggie": "margaret",
    "mike": "michael",
    "pat": "patrick",
    "rick": "richard",
    "rob": "robert",
    "sam": "samuel",
    "steve": "steven",
    "sue": "susan",
    "tom": "thomas",
    "will": "william",
}
MASCULINE_HINTS = {"mr", "sir", "he", "him"}
FEMININE_HINTS = {"mrs", "ms", "miss", "madam", "she", "her"}

_REGISTRY_LOCKS: dict[str, threading.Lock] = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()


@dataclass(slots=True)
class DetectedPIIEntity:
    start: int
    end: int
    entity_type: str
    text: str
    score: float


@dataclass(slots=True)
class ParsedPersonName:
    raw: str
    normalized: str
    title: str | None
    first: str | None
    middle: str | None
    last: str | None
    suffix: str | None
    canonical_first: str | None
    form: str


@dataclass(slots=True)
class PersonFamily:
    cluster_key: str
    real_first: str | None
    real_last: str | None
    canonical_first: str | None
    surrogate_first: str | None
    surrogate_last: str | None
    gender: str | None


def _normalize_space(value: str) -> str:
    return " ".join(value.split()).strip()


def _normalized_lookup(value: str) -> str:
    return _normalize_space(value).lower()


def _registry_lock(conversation_id: uuid.UUID | str) -> threading.Lock:
    key = str(conversation_id)
    with _REGISTRY_LOCKS_GUARD:
        if key not in _REGISTRY_LOCKS:
            _REGISTRY_LOCKS[key] = threading.Lock()
        return _REGISTRY_LOCKS[key]


@lru_cache
def get_presidio_analyzer() -> Any | None:
    if AnalyzerEngine is None:
        logger.warning("PII redaction: Presidio is unavailable; falling back to regex-only detectors.")
        return None
    try:  # pragma: no cover - depends on runtime NLP assets
        return AnalyzerEngine()
    except Exception as exc:  # pragma: no cover - depends on runtime NLP assets
        logger.warning("PII redaction: Presidio initialization failed: %s", exc)
        return None


@lru_cache
def get_faker() -> Any | None:
    if Faker is None:
        return None
    fake = Faker("en_US")
    Faker.seed(42)
    return fake


@lru_cache
def get_gender_detector() -> Any | None:
    if gender_detector is None:
        return None
    try:  # pragma: no cover - depends on optional package
        return gender_detector.Detector(case_sensitive=False)
    except Exception:  # pragma: no cover - depends on optional package
        return None


def warm_redaction_resources() -> None:
    if not settings.pii_redaction_enabled:
        return
    get_presidio_analyzer()
    get_faker()
    get_gender_detector()


def normalize_entity_value(entity_type: str, value: str) -> str:
    cleaned = _normalize_space(value)
    if not cleaned:
        return ""

    entity_type = entity_type.upper()
    if entity_type == "PERSON":
        return _normalized_lookup(cleaned)
    if entity_type == "EMAIL_ADDRESS":
        return cleaned.lower()
    if entity_type == "PHONE_NUMBER":
        digits = re.sub(r"\D", "", cleaned)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        return digits
    if entity_type == "URL":
        value = cleaned.lower()
        value = re.sub(r"^https?://(www\.)?", "", value)
        return value.rstrip("/")
    if entity_type == "IP_ADDRESS":
        return cleaned.lower()
    if entity_type == "IBAN_CODE":
        return re.sub(r"\s+", "", cleaned).upper()
    return _normalized_lookup(cleaned)


def _parse_person_name(value: str) -> ParsedPersonName:
    cleaned = _normalize_space(value)
    normalized = _normalized_lookup(cleaned)
    title: str | None = None
    suffix: str | None = None
    first: str | None = None
    middle: str | None = None
    last: str | None = None

    if HumanName is not None:
        parsed = HumanName(cleaned)
        title = _normalize_space(str(parsed.title)) or None
        first = _normalize_space(str(parsed.first)) or None
        middle = _normalize_space(str(parsed.middle)) or None
        last = _normalize_space(str(parsed.last)) or None
        suffix = _normalize_space(str(parsed.suffix)) or None
    else:
        raw = cleaned
        title_match = TITLE_PREFIX_PATTERN.match(raw)
        if title_match:
            title = title_match.group(0).strip()
            raw = raw[title_match.end() :].strip()
        suffix_match = SUFFIX_PATTERN.search(raw)
        if suffix_match:
            suffix = suffix_match.group(1)
            raw = raw[: suffix_match.start()].strip()
        tokens = raw.split()
        if len(tokens) == 1:
            first = tokens[0]
        elif len(tokens) >= 2:
            first = tokens[0]
            last = tokens[-1]
            middle = " ".join(tokens[1:-1]) or None

    if first and re.fullmatch(r"[A-Za-z]\.?", first) and last:
        form = "initial_last"
    elif title and last and not first:
        form = "title_last"
    elif first and last:
        form = "full"
    elif first and not last:
        form = "first_only"
    elif last and not first:
        form = "last_only"
    else:
        form = "full"

    canonical_first = None
    if first:
        canonical_first = NICKNAME_CANONICAL.get(first.lower().rstrip("."), first.lower().rstrip("."))

    return ParsedPersonName(
        raw=cleaned,
        normalized=normalized,
        title=title,
        first=first,
        middle=middle,
        last=last,
        suffix=suffix,
        canonical_first=canonical_first,
        form=form,
    )


def _person_profile_to_dict(profile: ParsedPersonName, family: PersonFamily | None, gender: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "raw": profile.raw,
        "title": profile.title,
        "first": profile.first,
        "middle": profile.middle,
        "last": profile.last,
        "suffix": profile.suffix,
        "canonical_first": profile.canonical_first,
        "form": profile.form,
        "gender": gender,
    }
    if family is not None:
        payload["family"] = {
            "cluster_key": family.cluster_key,
            "real_first": family.real_first,
            "real_last": family.real_last,
            "canonical_first": family.canonical_first,
            "surrogate_first": family.surrogate_first,
            "surrogate_last": family.surrogate_last,
            "gender": family.gender,
        }
    return payload


def _family_from_profile(profile: dict[str, Any] | None, fallback_cluster_key: str | None) -> PersonFamily | None:
    family = (profile or {}).get("family")
    if not isinstance(family, dict):
        return None
    cluster_key = family.get("cluster_key") or fallback_cluster_key
    if not cluster_key:
        return None
    return PersonFamily(
        cluster_key=str(cluster_key),
        real_first=family.get("real_first"),
        real_last=family.get("real_last"),
        canonical_first=family.get("canonical_first"),
        surrogate_first=family.get("surrogate_first"),
        surrogate_last=family.get("surrogate_last"),
        gender=family.get("gender"),
    )


def _detect_gender(profile: ParsedPersonName) -> str | None:
    if profile.title:
        key = profile.title.lower().rstrip(".")
        if key in MASCULINE_HINTS:
            return "male"
        if key in FEMININE_HINTS:
            return "female"

    if not profile.first:
        return None
    detector = get_gender_detector()
    if detector is None:
        return None
    value = detector.get_gender(profile.first)
    if value in {"male", "mostly_male"}:
        return "male"
    if value in {"female", "mostly_female"}:
        return "female"
    return None


def _title_for_output(title: str | None) -> str | None:
    if not title:
        return None
    key = title.lower().rstrip(".")
    return PERSON_TITLES.get(key, title)


def _render_person_variant(profile: ParsedPersonName, family: PersonFamily, *, for_real_name: bool) -> str:
    first = family.real_first if for_real_name else family.surrogate_first
    last = family.real_last if for_real_name else family.surrogate_last
    title = _title_for_output(profile.title)
    suffix = profile.suffix

    if profile.form == "title_last" and title and last:
        return f"{title} {last}".strip()
    if profile.form == "initial_last" and last:
        initial_source = family.real_first if for_real_name else family.surrogate_first
        if initial_source:
            return f"{initial_source[0]}. {last}"
    if profile.form == "first_only" and first:
        return first
    if profile.form == "last_only" and last:
        return last

    parts = [part for part in (title, first, last, suffix) if part]
    return " ".join(parts).strip() or profile.raw


def _redaction_status_text(stage: str) -> str:
    if stage == "anonymizing":
        return "Anonymizing sensitive data before the model call"
    if stage == "deanonymizing":
        return "Restoring original values before delivery"
    return "Processing redaction state"


class ConversationRedactionSession:
    def __init__(self, db: Session, *, conversation_id: uuid.UUID | str, user_id: uuid.UUID | str) -> None:
        self.db = db
        self.conversation_id = str(conversation_id)
        self.user_id = str(user_id)
        self.enabled = settings.pii_redaction_enabled
        self._lock = _registry_lock(self.conversation_id)
        self._entries: dict[tuple[str, str], ConversationPIIRegistryEntry] = {}
        self._families: dict[str, PersonFamily] = {}
        self._real_values: set[str] = set()
        self._surrogate_values: set[str] = set()
        self._load_registry()

    def _load_registry(self) -> None:
        statement = (
            select(ConversationPIIRegistryEntry)
            .where(ConversationPIIRegistryEntry.conversation_id == self.conversation_id)
            .order_by(ConversationPIIRegistryEntry.created_at.asc())
        )
        rows = list(self.db.scalars(statement))
        for row in rows:
            self._entries[(row.entity_type.upper(), row.normalized_value)] = row
            self._real_values.add(_normalized_lookup(row.real_value))
            self._surrogate_values.add(_normalized_lookup(row.surrogate_value))
            family = _family_from_profile(row.profile, row.cluster_key)
            if family is not None and family.cluster_key not in self._families:
                self._families[family.cluster_key] = family

    def has_active_redaction(self) -> bool:
        return self.enabled

    def status_payload(self, stage: str) -> dict[str, str]:
        return {"stage": stage, "text": _redaction_status_text(stage)}

    def anonymize_jsonable(self, value: Any) -> Any:
        if not self.enabled:
            return value
        if isinstance(value, str):
            return self.anonymize_text(value)
        if isinstance(value, list):
            return [self.anonymize_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {key: self.anonymize_jsonable(item) for key, item in value.items()}
        return value

    def deanonymize_jsonable(self, value: Any) -> Any:
        if not self.enabled:
            return value
        if isinstance(value, str):
            return self.deanonymize_text(value)
        if isinstance(value, list):
            return [self.deanonymize_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {key: self.deanonymize_jsonable(item) for key, item in value.items()}
        return value

    def detect_entities(self, text: str) -> list[DetectedPIIEntity]:
        if not text.strip():
            return []

        candidates: list[DetectedPIIEntity] = []
        analyzer = get_presidio_analyzer()
        if analyzer is not None:
            try:  # pragma: no cover - depends on optional NLP runtime
                surrogate_results = analyzer.analyze(
                    text=text,
                    language="en",
                    entities=settings.resolved_pii_surrogate_entities,
                    score_threshold=settings.pii_surrogate_score_threshold,
                )
                redact_results = analyzer.analyze(
                    text=text,
                    language="en",
                    entities=settings.resolved_pii_redact_entities,
                    score_threshold=settings.pii_redact_score_threshold,
                )
                candidates.extend(
                    [
                        DetectedPIIEntity(
                            start=item.start,
                            end=item.end,
                            entity_type=item.entity_type,
                            text=text[item.start : item.end],
                            score=float(item.score or 0),
                        )
                        for item in [*surrogate_results, *redact_results]
                    ]
                )
            except Exception as exc:  # pragma: no cover - depends on optional NLP runtime
                logger.warning("PII detection: Presidio analyze failed, using regex fallback: %s", exc)

        candidates.extend(self._detect_regex_entities(text))
        return self._dedupe_entities(text, candidates)

    def _detect_regex_entities(self, text: str) -> list[DetectedPIIEntity]:
        candidates: list[DetectedPIIEntity] = []
        patterns = [
            ("EMAIL_ADDRESS", EMAIL_PATTERN, 0.95),
            ("PHONE_NUMBER", PHONE_PATTERN, 0.9),
            ("URL", URL_PATTERN, 0.9),
            ("IP_ADDRESS", IPV4_PATTERN, 0.9),
            ("US_SSN", SSN_PATTERN, 0.95),
            ("CREDIT_CARD", CREDIT_CARD_PATTERN, 0.85),
            ("IBAN_CODE", IBAN_PATTERN, 0.95),
            ("DATE_TIME", DATE_PATTERN, 0.8),
        ]
        for entity_type, pattern, score in patterns:
            for match in pattern.finditer(text):
                candidates.append(
                    DetectedPIIEntity(
                        start=match.start(),
                        end=match.end(),
                        entity_type=entity_type,
                        text=match.group(0),
                        score=score,
                    )
                )

        for match in PERSON_FALLBACK_PATTERN.finditer(text):
            raw = match.group(0)
            if len(raw.split()) < 2 and not TITLE_PREFIX_PATTERN.match(raw):
                continue
            candidates.append(
                DetectedPIIEntity(
                    start=match.start(),
                    end=match.end(),
                    entity_type="PERSON",
                    text=raw,
                    score=0.72,
                )
            )
        return candidates

    def _dedupe_entities(self, text: str, candidates: list[DetectedPIIEntity]) -> list[DetectedPIIEntity]:
        uuid_spans = [(match.start(), match.end()) for match in UUID_PATTERN.finditer(text)]
        filtered = [
            item
            for item in candidates
            if item.text.strip()
            and not any(item.start < end and item.end > start for start, end in uuid_spans)
            and item.entity_type.upper() in (*settings.resolved_pii_surrogate_entities, *settings.resolved_pii_redact_entities)
        ]
        filtered.sort(
            key=lambda item: (
                item.start,
                -self._priority_for_entity(item.entity_type),
                -(item.end - item.start),
                -item.score,
            )
        )

        accepted: list[DetectedPIIEntity] = []
        for candidate in filtered:
            if accepted and candidate.start < accepted[-1].end:
                previous = accepted[-1]
                if self._rank_entity(candidate) > self._rank_entity(previous):
                    accepted[-1] = candidate
                continue
            accepted.append(candidate)
        return accepted

    def _priority_for_entity(self, entity_type: str) -> int:
        if entity_type.upper() in settings.resolved_pii_redact_entities:
            return 2
        return 1

    def _rank_entity(self, item: DetectedPIIEntity) -> tuple[int, int, float]:
        return (self._priority_for_entity(item.entity_type), item.end - item.start, item.score)

    def anonymize_text(self, text: str) -> str:
        if not self.enabled or not text.strip():
            return text

        with self._lock:
            entities = self.detect_entities(text)
            if settings.pii_missed_scan_enabled:
                entities = self._apply_missed_pii_scan(text, entities)
            if not entities:
                return text

            parts: list[str] = []
            cursor = 0
            for entity in entities:
                parts.append(text[cursor : entity.start])
                parts.append(self._replacement_for_entity(entity))
                cursor = entity.end
            parts.append(text[cursor:])
            return "".join(parts)

    def _replacement_for_entity(self, entity: DetectedPIIEntity) -> str:
        entity_type = entity.entity_type.upper()
        if entity_type in settings.resolved_pii_redact_entities:
            return f"[{entity_type}]"
        if entity_type == "PERSON":
            return self._person_surrogate_for(entity.text)
        return self._exact_surrogate_for(entity_type, entity.text)

    def _entry_for(self, entity_type: str, normalized_value: str) -> ConversationPIIRegistryEntry | None:
        return self._entries.get((entity_type.upper(), normalized_value))

    def _save_entry(
        self,
        *,
        entity_type: str,
        normalized_value: str,
        real_value: str,
        surrogate_value: str,
        cluster_key: str | None,
        profile: dict[str, Any] | None,
    ) -> ConversationPIIRegistryEntry:
        entry = ConversationPIIRegistryEntry(
            conversation_id=self.conversation_id,
            user_id=self.user_id,
            entity_type=entity_type.upper(),
            normalized_value=normalized_value,
            real_value=real_value,
            surrogate_value=surrogate_value,
            cluster_key=cluster_key,
            profile=profile,
        )
        self.db.add(entry)
        self.db.flush()
        self._entries[(entry.entity_type, entry.normalized_value)] = entry
        self._real_values.add(_normalized_lookup(real_value))
        self._surrogate_values.add(_normalized_lookup(surrogate_value))
        family = _family_from_profile(profile, cluster_key)
        if family is not None:
            self._families[family.cluster_key] = family
        return entry

    def _exact_surrogate_for(self, entity_type: str, value: str) -> str:
        normalized = normalize_entity_value(entity_type, value)
        if not normalized:
            return value

        existing = self._entry_for(entity_type, normalized)
        if existing is not None:
            return existing.surrogate_value

        surrogate = self._generate_unique_surrogate(entity_type, value)
        self._save_entry(
            entity_type=entity_type,
            normalized_value=normalized,
            real_value=value,
            surrogate_value=surrogate,
            cluster_key=None,
            profile=None,
        )
        return surrogate

    def _person_surrogate_for(self, value: str) -> str:
        profile = _parse_person_name(value)
        existing = self._entry_for("PERSON", profile.normalized)
        if existing is not None:
            return existing.surrogate_value

        family = self._match_or_create_person_family(profile)
        surrogate = _render_person_variant(profile, family, for_real_name=False)
        self._save_entry(
            entity_type="PERSON",
            normalized_value=profile.normalized,
            real_value=profile.raw,
            surrogate_value=surrogate,
            cluster_key=family.cluster_key,
            profile=_person_profile_to_dict(profile, family, family.gender),
        )
        return surrogate

    def _match_or_create_person_family(self, profile: ParsedPersonName) -> PersonFamily:
        mode = settings.normalized_entity_resolution_mode
        if mode == "llm":
            family = self._resolve_person_family_with_local_llm(profile)
            if family is not None:
                return family
        if mode != "none":
            family = self._resolve_person_family_algorithmic(profile)
            if family is not None:
                return family

        gender = _detect_gender(profile)
        family = self._create_person_family(profile, gender)
        self._families[family.cluster_key] = family
        return family

    def _resolve_person_family_algorithmic(self, profile: ParsedPersonName) -> PersonFamily | None:
        if not self._families:
            return None

        if profile.canonical_first and profile.last:
            matches = [
                family
                for family in self._families.values()
                if family.canonical_first == profile.canonical_first
                and family.real_last
                and family.real_last.lower() == profile.last.lower()
            ]
            if len(matches) == 1:
                return matches[0]

        if profile.last and not profile.first:
            matches = [
                family
                for family in self._families.values()
                if family.real_last and family.real_last.lower() == profile.last.lower()
            ]
            if len(matches) == 1:
                return matches[0]

        if profile.canonical_first and not profile.last:
            matches = [
                family
                for family in self._families.values()
                if family.canonical_first == profile.canonical_first
            ]
            if len(matches) == 1:
                return matches[0]

        return None

    def _resolve_person_family_with_local_llm(self, profile: ParsedPersonName) -> PersonFamily | None:
        client = get_local_llm_client()
        model = get_local_llm_model()
        if client is None or model is None or not self._families:
            return None

        family_payload = [
            {
                "cluster_key": family.cluster_key,
                "real_first": family.real_first,
                "real_last": family.real_last,
                "canonical_first": family.canonical_first,
            }
            for family in self._families.values()
        ]
        system_prompt = (
            "You resolve whether a person-name mention belongs to an existing person cluster. "
            "Return JSON with keys cluster_key and confidence. "
            "Use cluster_key=null if there is no safe match."
        )
        user_prompt = f"Candidate name: {profile.raw}\nExisting clusters: {family_payload}"

        try:  # pragma: no cover - depends on optional local LLM runtime
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            raw_text = get_completion_text(response.choices[0].message.content)
            data = json.loads(extract_json_object(raw_text))
            cluster_key = data.get("cluster_key")
            if isinstance(cluster_key, str) and cluster_key in self._families:
                return self._families[cluster_key]
        except Exception:
            logger.info("PII redaction: local LLM entity resolution unavailable, falling back.")
        return None

    def _create_person_family(self, profile: ParsedPersonName, gender: str | None) -> PersonFamily:
        real_fragments = {
            token.lower()
            for entry in self._entries.values()
            if entry.entity_type == "PERSON"
            for token in re.findall(r"[A-Za-z][A-Za-z'-]+", entry.real_value)
        }
        fake = get_faker()
        surrogate_first = None
        surrogate_last = None

        for _ in range(40):
            if fake is None:
                candidate_first = f"Person{uuid.uuid4().hex[:6]}"
                candidate_last = f"Alias{uuid.uuid4().hex[:6]}"
            else:
                if gender == "female":
                    candidate_first = fake.first_name_female()
                elif gender == "male":
                    candidate_first = fake.first_name_male()
                else:
                    candidate_first = fake.first_name()
                candidate_last = fake.last_name()

            if candidate_first.lower() in real_fragments or candidate_last.lower() in real_fragments:
                continue
            full_candidate = f"{candidate_first} {candidate_last}"
            if _normalized_lookup(full_candidate) in self._real_values or _normalized_lookup(full_candidate) in self._surrogate_values:
                continue
            surrogate_first = candidate_first
            surrogate_last = candidate_last
            break

        if surrogate_first is None or surrogate_last is None:
            unique_key = uuid.uuid4().hex[:8]
            surrogate_first = f"Person{unique_key}"
            surrogate_last = f"Alias{unique_key}"

        return PersonFamily(
            cluster_key=f"person-{uuid.uuid4()}",
            real_first=profile.first,
            real_last=profile.last,
            canonical_first=profile.canonical_first,
            surrogate_first=surrogate_first,
            surrogate_last=surrogate_last,
            gender=gender,
        )

    def _generate_unique_surrogate(self, entity_type: str, value: str) -> str:
        fake = get_faker()
        entity_type = entity_type.upper()

        for _ in range(40):
            if entity_type == "EMAIL_ADDRESS":
                candidate = self._generate_fake_email(fake)
            elif entity_type == "PHONE_NUMBER":
                candidate = self._generate_fake_phone(value)
            elif entity_type == "LOCATION":
                candidate = self._generate_fake_location(fake)
            elif entity_type == "DATE_TIME":
                candidate = self._generate_fake_datetime(fake, value)
            elif entity_type == "URL":
                candidate = self._generate_fake_url(fake)
            elif entity_type == "IP_ADDRESS":
                candidate = self._generate_fake_ip(fake, value)
            else:
                candidate = f"{entity_type}_{uuid.uuid4().hex[:8]}"

            normalized_candidate = _normalized_lookup(candidate)
            if normalized_candidate in self._real_values or normalized_candidate in self._surrogate_values:
                continue
            return candidate

        return f"{entity_type}_{uuid.uuid4().hex[:10]}"

    def _generate_fake_email(self, fake: Any | None) -> str:
        if fake is None:
            return f"user-{uuid.uuid4().hex[:8]}@example.test"
        return f"{fake.user_name()}@example.test"

    def _generate_fake_phone(self, original: str) -> str:
        digits = "555" + uuid.uuid4().hex[:7]
        if "(" in original and ")" in original:
            return f"({digits[:3]}) {digits[3:6]}-{digits[6:10]}"
        if "-" in original:
            return f"{digits[:3]}-{digits[3:6]}-{digits[6:10]}"
        if "." in original:
            return f"{digits[:3]}.{digits[3:6]}.{digits[6:10]}"
        if " " in original:
            return f"{digits[:3]} {digits[3:6]} {digits[6:10]}"
        return digits[:10]

    def _generate_fake_location(self, fake: Any | None) -> str:
        if fake is None:
            return f"Harbor City {uuid.uuid4().hex[:4]}"
        return f"{fake.city()}, {fake.state_abbr()}"

    def _generate_fake_datetime(self, fake: Any | None, original: str) -> str:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", original):
            return "2030-01-15"
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", original):
            parts = original.split("/")
            year = parts[-1] if len(parts[-1]) in {2, 4} else "2030"
            return f"01/15/{year}"
        if fake is None:
            return "January 15, 2030"
        return fake.date(pattern="%B %d, %Y")

    def _generate_fake_url(self, fake: Any | None) -> str:
        slug = uuid.uuid4().hex[:8]
        if fake is not None:
            slug = fake.slug()
        return f"https://{slug}.example.test"

    def _generate_fake_ip(self, fake: Any | None, original: str) -> str:
        if ":" in original:
            return "2001:db8::1"
        if fake is None:
            return "203.0.113.10"
        return fake.ipv4_public()

    def _apply_missed_pii_scan(self, text: str, entities: list[DetectedPIIEntity]) -> list[DetectedPIIEntity]:
        if not settings.pii_missed_scan_enabled:
            return entities
        client = get_local_llm_client()
        model = get_local_llm_model()
        if client is None or model is None:
            return entities
        return entities

    def deanonymize_text(self, text: str) -> str:
        if not self.enabled or not text.strip() or not self._entries:
            return text

        placeholder_map: dict[str, str] = {}
        transformed = text
        exact_entries = sorted(self._entries.values(), key=lambda item: len(item.surrogate_value), reverse=True)

        for index, entry in enumerate(exact_entries, start=1):
            placeholder = f"<<PII_{index:04d}>>"
            pattern = re.compile(re.escape(entry.surrogate_value), re.IGNORECASE)
            transformed = pattern.sub(placeholder, transformed)
            placeholder_map[placeholder] = entry.real_value

        transformed = self._apply_person_fuzzy_deanonymization(transformed)
        for placeholder, real_value in placeholder_map.items():
            transformed = transformed.replace(placeholder, real_value)
        return transformed

    def _apply_person_fuzzy_deanonymization(self, text: str) -> str:
        transformed = text
        for family in self._families.values():
            if family.surrogate_last and family.real_last:
                title_pattern = re.compile(
                    rf"\b(Mr|Mrs|Ms|Miss|Dr|Prof)\.?\s+{re.escape(family.surrogate_last)}\b",
                    re.IGNORECASE,
                )

                def replace_title(match: re.Match[str]) -> str:
                    title = _title_for_output(match.group(1))
                    return f"{title} {family.real_last}".strip()

                transformed = title_pattern.sub(replace_title, transformed)

            if family.surrogate_first and family.surrogate_last and family.real_first and family.real_last:
                initial_pattern = re.compile(
                    rf"\b{re.escape(family.surrogate_first[0])}\.\s*{re.escape(family.surrogate_last)}\b",
                    re.IGNORECASE,
                )
                transformed = initial_pattern.sub(f"{family.real_first[0]}. {family.real_last}", transformed)
        return transformed


def build_redaction_session(db: Session, *, conversation_id: uuid.UUID | str, user_id: uuid.UUID | str) -> ConversationRedactionSession:
    return ConversationRedactionSession(db, conversation_id=conversation_id, user_id=user_id)


def build_redaction_status_sse_payload(stage: str) -> dict[str, str]:
    return {"stage": stage, "text": _redaction_status_text(stage)}


def chunk_deanonymized_output(text: str, *, max_chunk_length: int = 160) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    return [cleaned[index : index + max_chunk_length] for index in range(0, len(cleaned), max_chunk_length)]
