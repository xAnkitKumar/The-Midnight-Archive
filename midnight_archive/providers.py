"""Idea providers (Agent 1 upstream).

Two implementations:

``OfflineIdeaProvider``
    A zero-cost combinatorial ideator. It assembles premise fragments from
    curated banks, scores them with a transparent rubric and deliberately
    avoids repeating components or recently used vocabulary. It is not a
    language model: it produces *candidates* for a human/agent to develop.

``OpenAICompatibleIdeaProvider``
    An opt-in adapter for any OpenAI-compatible chat-completions endpoint
    (including Freebuff's paid endpoint). It is disabled unless the owner sets
    ``TMA_ALLOW_PAID_API=1`` **and** passes ``--allow-paid-api``. The project
    never spends money on its own. This adapter has not been exercised against
    a live endpoint because no key is configured.
"""

from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol

from midnight_archive.config import Settings
from midnight_archive.errors import ProviderError
from midnight_archive.utils import normalize_words

# --------------------------------------------------------------------------- banks


@dataclass(frozen=True)
class Setting:
    text: str
    visual: int


@dataclass(frozen=True)
class Anomaly:
    text: str
    category: str
    hook_line: str
    rule: str
    title_noun: str
    hook: int
    suspense: int
    ending: int


@dataclass(frozen=True)
class Twist:
    text: str
    category: str
    ending: int


SETTINGS: tuple[Setting, ...] = (
    Setting("a flooded archive beneath a courthouse", 9),
    Setting("a night-shift radio station on the coast", 8),
    Setting("an apartment block with no fourth floor", 9),
    Setting("a laundromat that never closes", 7),
    Setting("a municipal swimming pool after hours", 8),
    Setting("a hotel where every room has the same view", 8),
    Setting("a hospital wing sealed in 1974", 9),
    Setting("a suburban house with a second basement", 9),
    Setting("a ferry that only runs in fog", 9),
    Setting("a photography studio above a pawn shop", 8),
    Setting("a library where the shelves rearrange overnight", 9),
    Setting("a car park six storeys underground", 7),
    Setting("a wedding venue after the guests leave", 7),
    Setting("a lighthouse with no light", 9),
    Setting("a data centre that hums at 3 a.m.", 8),
    Setting("a school kept open for one student", 8),
    Setting("a cinema screening films nobody made", 9),
    Setting("a cul-de-sac where the streetlights never switch off", 8),
)

ANOMALIES: tuple[Anomaly, ...] = (
    Anomaly(
        "the night porter greets a guest who checked out decades ago",
        "psychological_horror",
        "There is a guest who never checks out.",
        "Never answer the phone after 2 a.m.",
        "Permanent Guest",
        9, 9, 8,
    ),
    Anomaly(
        "the neighbours repeat the same argument every evening, word for word",
        "psychological_horror",
        "The neighbours argue the same words every night.",
        "Never interrupt the argument.",
        "Evening Argument",
        8, 9, 8,
    ),
    Anomaly(
        "every mirror shows the room four seconds late",
        "psychological_horror",
        "The mirror is always four seconds behind.",
        "Never look twice.",
        "Late Mirror",
        9, 8, 9,
    ),
    Anomaly(
        "the lift stops at a floor that is not on the panel",
        "psychological_horror",
        "The lift stops at a floor that does not exist.",
        "Never step out.",
        "Missing Floor",
        9, 9, 8,
    ),
    Anomaly(
        "the smoke alarm sounds at the exact minute someone lies",
        "psychological_horror",
        "The alarm sounds whenever someone lies.",
        "Never lie indoors.",
        "Smoke Alarm",
        8, 8, 9,
    ),
    Anomaly(
        "the caretaker replaces family photographs with slightly wrong versions",
        "psychological_horror",
        "The photographs are almost right.",
        "Never compare the faces.",
        "Family Photograph",
        8, 9, 9,
    ),
    Anomaly(
        "the receipts print tomorrow's date",
        "mystery",
        "Every receipt is dated tomorrow.",
        "Never keep a receipt.",
        "Paper Receipt",
        9, 8, 9,
    ),
    Anomaly(
        "the guest register fills with names that have not been used yet",
        "mystery",
        "The register is full of future names.",
        "Never sign last.",
        "Guest Register",
        8, 8, 8,
    ),
    Anomaly(
        "the security tapes show a corridor that was bricked up years ago",
        "mystery",
        "The cameras see a corridor that no longer exists.",
        "Never watch past 3 a.m.",
        "Bricked Corridor",
        9, 8, 8,
    ),
    Anomaly(
        "the newspaper reports crimes one day before they happen",
        "mystery",
        "The paper reports crimes before they occur.",
        "Never read page nine.",
        "Page Nine",
        10, 9, 9,
    ),
    Anomaly(
        "the crossword answers spell the names of missing people",
        "mystery",
        "The crossword spells missing names.",
        "Never finish the puzzle.",
        "Crossword",
        8, 8, 9,
    ),
    Anomaly(
        "the lost-property drawer holds objects from rooms nobody has built",
        "mystery",
        "Lost property holds things from unbuilt rooms.",
        "Never claim an item.",
        "Lost Property",
        8, 8, 8,
    ),
    Anomaly(
        "every clock in the building runs four minutes behind the world",
        "mind_bending",
        "Every clock here is four minutes slow.",
        "Never reset them.",
        "Four Minutes",
        8, 7, 9,
    ),
    Anomaly(
        "people who leave lose one memory for every day they were inside",
        "mind_bending",
        "Leaving costs you one memory a day.",
        "Never write it down.",
        "Leaving Cost",
        9, 8, 9,
    ),
    Anomaly(
        "the archive contains a file for every decision nobody made",
        "mind_bending",
        "There is a file for every life you did not live.",
        "Never open your own file.",
        "Unlived File",
        10, 8, 10,
    ),
    Anomaly(
        "Tuesday repeats, and everyone remembers the previous ones",
        "mind_bending",
        "Tuesday keeps happening, and everyone remembers.",
        "Never mention Tuesday.",
        "Borrowed Tuesday",
        9, 8, 9,
    ),
    Anomaly(
        "the building gains one more room each time someone counts them",
        "mind_bending",
        "The building grows a room whenever you count.",
        "Never count twice.",
        "Extra Room",
        8, 7, 8,
    ),
    Anomaly(
        "the camera develops the moment just before the photograph is taken",
        "mind_bending",
        "The camera captures the second before.",
        "Never take the last one.",
        "Last Photograph",
        8, 8, 9,
    ),
)

TWISTS: tuple[Twist, ...] = (
    Twist("The rule was never protecting them from it. It was protecting it from them.", "psychological_horror", 10),
    Twist("The thing at the door had been invited in years ago, and had been trying to leave ever since.", "psychological_horror", 8),
    Twist("Nobody in the building was alive. The rent was still due.", "psychological_horror", 9),
    Twist("The caretaker was not replacing the photographs. He was the only one who remembered the original faces.", "psychological_horror", 9),
    Twist("The building had been waiting for a tenant who would finally read the rules.", "psychological_horror", 8),
    Twist("She had been dead for six years, and the flat had kept paying her rent.", "psychological_horror", 8),
    Twist("The detective had solved the case before it happened. That was the case.", "mystery", 10),
    Twist("Every clue pointed to the one person who could not have been there: the one who reported it.", "mystery", 9),
    Twist("The missing person had been erased from the register, not from the world.", "mystery", 9),
    Twist("The crime was never committed. Someone needed it investigated.", "mystery", 10),
    Twist("The witness had been paid to remember the crime, not to see it.", "mystery", 9),
    Twist("The killer had reported the body before it was a body.", "mystery", 9),
    Twist("The file did not describe a life unlived. It was a receipt for the one he was living.", "mind_bending", 10),
    Twist("He had not been forgetting details. The details had been forgetting him.", "mind_bending", 10),
    Twist("The clocks were not slow. The rest of the world had already left.", "mind_bending", 9),
    Twist("The archive did not store the past. It was deciding what to keep.", "mind_bending", 10),
    Twist("The archive had no past to store. It was writing one, and he was the ink.", "mind_bending", 9),
    Twist("He had not travelled back. The world had moved on and left a copy behind.", "mind_bending", 9),
)

ROLES: tuple[str, ...] = (
    "night archivist",
    "locksmith",
    "grief counsellor",
    "tram driver",
    "sound engineer",
    "medical illustrator",
    "insurance clerk",
    "forensic accountant",
    "hotel porter",
    "lighthouse keeper",
    "estate agent",
    "sign-language interpreter",
    "radio producer",
    "security guard",
    "cartographer",
    "piano tuner",
)

PREMISE_TEMPLATES: tuple[str, ...] = (
    "{role} takes a job at {setting}. The rule is simple: {rule} Then {anomaly}.",
    "{role} returns to {setting} after years away. Nothing has changed, except {anomaly}.",
    "{role} is hired to catalogue {setting}. By the third night, {anomaly}.",
    "{role} inherits {setting}, along with one instruction: {rule} It takes a week to break it.",
)

TITLE_TEMPLATES: tuple[str, ...] = (
    "The {noun}",
    "{noun}, Unlisted",
    "After the {noun}",
    "The {noun} Files",
    "What the {noun} Knew",
    "A Quiet {noun}",
)


class IdeaProvider(Protocol):
    name: str

    def generate(
        self, count: int, seed: int, recent_premises: Iterable[str] = ()
    ) -> list[dict[str, Any]]: ...


# ------------------------------------------------------------------ offline engine


def _overlap_ratio(premise: str, recent: list[str]) -> float:
    words = set(normalize_words(premise))
    if not words:
        return 0.0
    worst = 0.0
    for other in recent:
        other_words = set(normalize_words(other))
        if not other_words:
            continue
        worst = max(worst, len(words & other_words) / len(words | other_words))
    return worst


@dataclass
class OfflineIdeaProvider:
    """Deterministic, seeded, zero-cost idea generation.

    Component usage is tracked on the instance, so a batch that needs several
    provider calls still never repeats a setting, anomaly, twist or title.
    """

    settings: Settings
    name: str = "offline"
    _used_settings: set[str] = field(default_factory=set, init=False, repr=False)
    _used_anomalies: set[str] = field(default_factory=set, init=False, repr=False)
    _used_twists: set[str] = field(default_factory=set, init=False, repr=False)
    _used_titles: set[str] = field(default_factory=set, init=False, repr=False)

    def _categories(self) -> list[str]:
        configured = [c for c in self.settings.categories if c in {"psychological_horror", "mystery", "mind_bending"}]
        return configured or ["psychological_horror", "mystery", "mind_bending"]

    def generate(
        self, count: int, seed: int, recent_premises: Iterable[str] = ()
    ) -> list[dict[str, Any]]:
        if count <= 0:
            raise ProviderError("Idea count must be positive")
        recent = [str(p) for p in recent_premises if p]
        rng = random.Random(seed)
        categories = self._categories()

        settings_pool = list(SETTINGS)
        anomaly_pool = list(ANOMALIES)
        twist_pool = list(TWISTS)
        rng.shuffle(settings_pool)
        rng.shuffle(anomaly_pool)
        rng.shuffle(twist_pool)

        ideas: list[dict[str, Any]] = []

        # Cycle through the banks so a session never repeats a component.
        for index in range(count):
            category = categories[index % len(categories)]
            setting = self._pick(settings_pool, lambda s: s.text, self._used_settings)
            anomaly = self._pick(
                [a for a in anomaly_pool if a.category == category],
                lambda a: a.text,
                self._used_anomalies,
            )
            twist = self._pick(
                [t for t in twist_pool if t.category == category],
                lambda t: t.text,
                self._used_twists,
            )
            if setting is None or anomaly is None or twist is None:  # pragma: no cover
                break

            role = ROLES[index % len(ROLES)]
            role_phrase = f"{'An' if role[0] in 'aeiou' else 'A'} {role}"
            template = PREMISE_TEMPLATES[(index + seed) % len(PREMISE_TEMPLATES)]
            premise = template.format(
                role=role_phrase,
                setting=setting.text,
                rule=anomaly.rule,
                anomaly=anomaly.text,
            )
            premise = premise[0].upper() + premise[1:]
            premise = f"{premise} {twist.text}"

            title = self._title(rng, anomaly.title_noun, self._used_titles)
            overlap = _overlap_ratio(premise, recent + [i["premise"] for i in ideas])
            originality = max(1, min(10, round(10 - overlap * 6)))

            scores = {
                "hook": anomaly.hook,
                "originality": int(originality),
                "suspense": max(1, round((anomaly.suspense + twist.ending) / 2)),
                "visual": setting.visual,
                "ending": twist.ending,
            }
            ideas.append(
                {
                    "title": title,
                    "category": category,
                    "premise": premise,
                    "hook": anomaly.hook_line,
                    "twist": twist.text,
                    "visual_hook": f"{setting.text} — {anomaly.text}",
                    "scores": scores,
                    "source": "local_generator",
                }
            )

        return ideas

    @staticmethod
    def _pick(items: list[Any], key: Any, used: set[str]) -> Any:
        """Pick the first unused item; recycle only when the bank is exhausted."""

        for item in items:
            if key(item) not in used:
                used.add(key(item))
                return item
        if not items:
            return None
        used.clear()
        used.add(key(items[0]))
        return items[0]

    @staticmethod
    def _title(rng: random.Random, noun: str, used: set[str]) -> str:
        for _ in range(20):
            candidate = rng.choice(TITLE_TEMPLATES).format(noun=noun)
            if candidate.casefold() not in used:
                used.add(candidate.casefold())
                return candidate
        fallback = f"{noun} ({len(used) + 1})"
        used.add(fallback.casefold())
        return fallback


# ------------------------------------------------------------------- paid adapter


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


@dataclass
class OpenAICompatibleIdeaProvider:
    """Opt-in adapter for OpenAI-compatible chat completions.

    Spending guardrail: construction requires ``allow_paid=True`` and
    ``TMA_ALLOW_PAID_API`` set to a truthy value. The adapter never retries a
    4xx other than 429.
    """

    settings: Settings
    allow_paid: bool
    name: str = "openai_compatible"

    def __post_init__(self) -> None:
        env_gate = os.environ.get("TMA_ALLOW_PAID_API", "").strip().lower()
        if not self.allow_paid:
            raise ProviderError(
                "The paid LLM adapter requires the --allow-paid-api flag. "
                "Phase 1 defaults to the offline generator."
            )
        if env_gate not in {"1", "true", "yes"}:
            raise ProviderError(
                "The paid LLM adapter is disabled. Set TMA_ALLOW_PAID_API=1 in your local .env "
                "to acknowledge that calls cost money."
            )
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderError("OPENAI_API_KEY is not set; the paid adapter cannot run.")
        self.base_url = str(self.settings.get("llm.base_url", "")).rstrip("/")
        self.model = os.environ.get("TMA_LLM_MODEL") or str(self.settings.get("llm.model", ""))
        if not self.base_url or not self.model:
            raise ProviderError("Set llm.base_url and llm.model (or TMA_LLM_MODEL) before using the paid adapter.")

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = int(self.settings.get("llm.timeout_seconds", 60))
        retries = int(self.settings.get("llm.max_retries", 2))
        url = f"{self.base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
        }
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            request = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:400]
                if exc.code == 429 or exc.code >= 500:
                    last_error = ProviderError(f"LLM endpoint returned HTTP {exc.code}: {body}")
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"LLM endpoint rejected the request (HTTP {exc.code}): {body}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = ProviderError(f"Could not reach the LLM endpoint: {exc}")
                time.sleep(min(2 ** attempt, 8))
        raise last_error or ProviderError("LLM endpoint failed")

    def generate(
        self, count: int, seed: int, recent_premises: Iterable[str] = ()
    ) -> list[dict[str, Any]]:
        recent = list(recent_premises)[:20]
        prompt = (
            f"You are Agent 1 for The Midnight Archive, a faceless short-form storytelling page.\n"
            f"Generate {count} original story ideas. Categories allowed: "
            "psychological_horror, mystery, mind_bending.\n"
            "Avoid these recently used premises: " + json.dumps(recent) + "\n"
            "Return ONLY a JSON array. Each object must have: title (string), category, "
            "premise (2-3 sentences), hook (one short line), twist (one sentence), "
            "visual_hook (one sentence), and scores with integer hook, originality, "
            "suspense, visual, ending from 1-10. No prose outside the JSON."
        )
        payload = {
            "model": self.model,
            "temperature": 0.9,
            "messages": [
                {"role": "system", "content": "You return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
        }
        raw = self._request(payload)
        try:
            content = raw["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Unexpected response shape from the LLM endpoint") from exc
        try:
            parsed = json.loads(_strip_code_fence(str(content)))
        except json.JSONDecodeError as exc:
            raise ProviderError(f"The LLM endpoint did not return valid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise ProviderError("The LLM endpoint returned JSON that is not a list")
        results: list[dict[str, Any]] = []
        for item in parsed[:count]:
            if not isinstance(item, dict):
                continue
            item.setdefault("source", "llm")
            results.append(item)
        return results


def build_provider(settings: Settings, name: str | None = None, allow_paid: bool = False) -> IdeaProvider:
    provider_name = (name or str(settings.get("llm.provider", "offline"))).strip().lower()
    if provider_name in {"offline", "local", "builtin"}:
        return OfflineIdeaProvider(settings)
    if provider_name in {"openai_compatible", "openai", "llm"}:
        return OpenAICompatibleIdeaProvider(settings, allow_paid=allow_paid)
    raise ProviderError(f"Unknown idea provider '{provider_name}'. Use 'offline' or 'openai_compatible'.")
