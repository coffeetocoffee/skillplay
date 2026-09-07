"""Section E - Generative challenges: synthesize fresh, self-validating
challenges at runtime so practice never repeats.

Two modalities are supported:

- ``test_cases`` (Python **and** JavaScript): function puzzles graded by running
  user code against generated test cases. Difficulty scales input complexity and
  XP, and hints/explanations are drawn from per-family pools so two runs of the
  same family still feel different.
- ``regex`` (regex_tester): a reference regex plus positive/negative sample
  strings the player must reproduce.

Everything is offline and local-first (no network, no accounts). Every generated
challenge is validated by running its own reference solution through the same
validator the player is graded against, so it is always gradeable. Generation is
seeded for reproducibility.
"""

from __future__ import annotations

import random
from typing import Any

from .loader import Challenge, Pack
from .validators import test_cases_runtime_available, validate


def _lang_for_skill(skill: str) -> str:
    s = (skill or "python").lower()
    if s in ("javascript", "js", "fix-bug-js", "node"):
        return "javascript"
    return "python"


# ---------------------------------------------------------------------------
# Difficulty-aware input helpers (G6: generation depth, not hardcoded 1-3)
# ---------------------------------------------------------------------------


def _size(r: random.Random, d: int) -> int:
    return r.randint(2 + d, 3 + 2 * d)


def _ints(r: random.Random, d: int, lo: int | None = None, hi: int | None = None) -> list[int]:
    lo = lo if lo is not None else (-9 if d < 3 else -25)
    hi = hi if hi is not None else (9 if d < 3 else 25)
    return [r.randint(lo, hi) for _ in range(_size(r, d))]


_WORDS = [
    "the",
    "cat",
    "sat",
    "on",
    "mat",
    "dog",
    "ran",
    "red",
    "blue",
    "sky",
    "code",
    "learn",
    "play",
    "open",
    "fast",
    "quiet",
    "bright",
    "small",
]


def _words(r: random.Random, d: int, n: int | None = None) -> str:
    n = n or _size(r, d)
    return " ".join(r.choice(_WORDS) for _ in range(n))


def _lname(r: random.Random, d: int) -> str:
    return "".join(r.choice("abcdefghij") for _ in range(r.randint(3, 3 + d)))


def _pick_difficulty(r: random.Random) -> int:
    """Varied difficulty (1-5), weighted toward the middle."""
    return r.choices([1, 2, 3, 4, 5], weights=[1, 2, 3, 2, 1])[0]


# ---------------------------------------------------------------------------
# test_cases problem templates
# ---------------------------------------------------------------------------

_PROBLEMS: list[dict[str, Any]] = [
    {
        "family": "sum",
        "function": "total",
        "topic": "lists",
        "prompt": "Return the sum of all numbers in the list `nums`.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(4)],
        "ref": lambda nums: sum(nums),
        "hints": ["Loop and accumulate, or use sum(nums).", "sum(nums) adds every element."],
        "explanations": [
            "`sum(nums)` adds every element together.",
            "A running total over the list equals sum(nums).",
        ],
        "py": "def total(nums):\n    return sum(nums)\n",
        "js": "function total(nums) {\n  return nums.reduce((a, b) => a + b, 0);\n}\n",
    },
    {
        "family": "largest",
        "function": "largest",
        "topic": "lists",
        "prompt": "Return the largest number in the list `nums`.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(4)],
        "ref": lambda nums: max(nums),
        "hints": ["Use max(nums) or scan for the biggest.", "Track the maximum as you iterate."],
        "explanations": [
            "`max(nums)` returns the greatest element.",
            "Comparing each element to a running max finds the largest.",
        ],
        "py": "def largest(nums):\n    return max(nums)\n",
        "js": "function largest(nums) {\n  return Math.max.apply(null, nums);\n}\n",
    },
    {
        "family": "count_evens",
        "function": "count_evens",
        "topic": "lists",
        "prompt": "Return how many numbers in `nums` are even.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(4)],
        "ref": lambda nums: sum(1 for x in nums if x % 2 == 0),
        "hints": ["A number is even when n % 2 == 0.", "Count elements where x % 2 == 0."],
        "explanations": [
            "Count the elements where x % 2 == 0.",
            "Filtering to evens then taking the length counts them.",
        ],
        "py": "def count_evens(nums):\n    return sum(1 for x in nums if x % 2 == 0)\n",
        "js": "function count_evens(nums) {\n  return nums.filter(x => x % 2 === 0).length;\n}\n",
    },
    {
        "family": "reverse",
        "function": "reverse_text",
        "topic": "strings",
        "prompt": "Return `text` with its characters reversed.",
        "inputs": lambda r, d: [
            [r.choice(["hello", "world", "abc", "race", "open", "code", "skillplay", "generator"])]
            for _ in range(4)
        ],
        "ref": lambda text: text[::-1],
        "hints": [
            "Slice with [::-1] (Python) or split/reverse/join (JS).",
            "Flip the character order.",
        ],
        "explanations": [
            "Reversing the string flips the character order.",
            "text[::-1] reads the string backwards.",
        ],
        "py": "def reverse_text(text):\n    return text[::-1]\n",
        "js": "function reverse_text(text) {\n  return text.split('').reverse().join('');\n}\n",
    },
    {
        "family": "is_palindrome",
        "function": "is_palindrome",
        "topic": "strings",
        "prompt": "Return True if `text` reads the same forwards and backwards, else False.",
        "inputs": lambda r, d: [
            [r.choice(["racecar", "noon", "hello", "aba", "test", "level", "pullup"])]
            for _ in range(4)
        ],
        "ref": lambda text: text == text[::-1],
        "hints": ["Compare text to its reverse.", "A palindrome equals its own reversal."],
        "explanations": [
            "A palindrome equals its own reversal.",
            "text == text[::-1] is True only for palindromes.",
        ],
        "py": "def is_palindrome(text):\n    return text == text[::-1]\n",
        "js": "function is_palindrome(text) {\n  return text === text.split('').reverse().join('');\n}\n",
    },
    {
        "family": "product",
        "function": "product",
        "topic": "arithmetic",
        "prompt": "Return the product of `a` and `b`.",
        "inputs": lambda r, d: [[r.randint(-9, 9), r.randint(-9, 9)] for _ in range(5)],
        "ref": lambda a, b: a * b,
        "hints": ["Multiply the two numbers.", "a * b is their product."],
        "explanations": [
            "`a * b` is their product.",
            "Repeated addition of a, b times, gives a * b.",
        ],
        "py": "def product(a, b):\n    return a * b\n",
        "js": "function product(a, b) {\n  return a * b;\n}\n",
    },
    {
        "family": "word_count",
        "function": "word_count",
        "topic": "strings",
        "prompt": "Return the number of whitespace-separated words in `text`.",
        "inputs": lambda r, d: [[_words(r, d)] for _ in range(5)],
        "ref": lambda text: len(text.split()),
        "hints": ["Split on whitespace and count.", "len(text.split()) counts the words."],
        "explanations": [
            "`text.split()` yields the words; len() counts them.",
            "Splitting on runs of whitespace separates the words.",
        ],
        "py": "def word_count(text):\n    return len(text.split())\n",
        "js": "function word_count(text) {\n  return text.trim().split(/\\s+/).filter(Boolean).length;\n}\n",
    },
    {
        "family": "first_n",
        "function": "first_n",
        "topic": "lists",
        "prompt": "Return the first `n` elements of `nums`.",
        "inputs": lambda r, d: [[_ints(r, d), r.randint(0, _size(r, d))] for _ in range(5)],
        "ref": lambda nums, n: nums[:n],
        "hints": ["Use slicing: nums[:n].", "Keep only the leading n items."],
        "explanations": [
            "`nums[:n]` keeps only the leading n items.",
            "A slice from 0 to n selects the first n elements.",
        ],
        "py": "def first_n(nums, n):\n    return nums[:n]\n",
        "js": "function first_n(nums, n) {\n  return nums.slice(0, n);\n}\n",
    },
    {
        "family": "shout",
        "function": "shout",
        "topic": "strings",
        "prompt": "Return `text` converted to UPPERCASE with an exclamation mark appended.",
        "inputs": lambda r, d: [[_lname(r, d)] for _ in range(5)],
        "ref": lambda text: text.upper() + "!",
        "hints": ["Upper-case it and add '!'.", "text.upper() + '!' shouts."],
        "explanations": [
            "`text.upper() + '!'` shouts the string.",
            "Upper-casing then appending '!' makes it loud.",
        ],
        "py": "def shout(text):\n    return text.upper() + '!'\n",
        "js": "function shout(text) {\n  return text.toUpperCase() + '!';\n}\n",
    },
    {
        "family": "double_all",
        "function": "double_all",
        "topic": "lists",
        "prompt": "Return a new list where every number in `nums` is multiplied by 2.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(4)],
        "ref": lambda nums: [x * 2 for x in nums],
        "hints": ["Build [x * 2 for x in nums].", "Map each element through `x * 2`."],
        "explanations": [
            "Map each element through `x * 2`.",
            "A list comprehension scales every value by two.",
        ],
        "py": "def double_all(nums):\n    return [x * 2 for x in nums]\n",
        "js": "function double_all(nums) {\n  return nums.map(x => x * 2);\n}\n",
    },
    # --- G6: added families for more variety ---
    {
        "family": "is_even",
        "function": "is_even",
        "topic": "arithmetic",
        "prompt": "Return True if `n` is even, else False.",
        "inputs": lambda r, d: [[r.randint(-20, 20)] for _ in range(6)],
        "ref": lambda n: n % 2 == 0,
        "hints": ["n % 2 == 0 means even.", "Check the remainder when dividing by 2."],
        "explanations": [
            "`n % 2 == 0` is True exactly for even numbers.",
            "Even numbers leave no remainder modulo 2.",
        ],
        "py": "def is_even(n):\n    return n % 2 == 0\n",
        "js": "function is_even(n) {\n  return n % 2 === 0;\n}\n",
    },
    {
        "family": "capitalize_words",
        "function": "capitalize_words",
        "topic": "strings",
        "prompt": "Return `text` with the first letter of each word capitalized (title case).",
        "inputs": lambda r, d: [[_words(r, d)] for _ in range(5)],
        "ref": lambda text: text.title(),
        "hints": [
            "Use text.title() or capitalize each word.",
            "Upper-case the start of every word.",
        ],
        "explanations": [
            "`text.title()` capitalizes the first letter of each word.",
            "Mapping each word through capitalize reproduces title case.",
        ],
        "py": "def capitalize_words(text):\n    return text.title()\n",
        "js": "function capitalize_words(text) {\n  return text.split(' ').map(w => w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w).join(' ');\n}\n",
    },
    {
        "family": "remove_duplicates",
        "function": "remove_duplicates",
        "topic": "lists",
        "prompt": "Return `nums` with duplicates removed, keeping the original order.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(5)],
        "ref": lambda nums: list(dict.fromkeys(nums)),
        "hints": [
            "A set removes duplicates; dict.fromkeys keeps order.",
            "Keep only first-seen items.",
        ],
        "explanations": [
            "`dict.fromkeys(nums)` drops repeats while preserving order.",
            "Tracking seen items filters duplicates in order.",
        ],
        "py": "def remove_duplicates(nums):\n    return list(dict.fromkeys(nums))\n",
        "js": "function remove_duplicates(nums) {\n  return nums.filter((v, i) => nums.indexOf(v) === i);\n}\n",
    },
    {
        "family": "second_largest",
        "function": "second_largest",
        "topic": "lists",
        "prompt": "Return the second-largest distinct value in `nums` (or None if fewer than two distinct values).",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(5)],
        "ref": lambda nums: sorted(set(nums))[-2] if len(set(nums)) >= 2 else None,
        "hints": [
            "Find the distinct values, sort them, take the second from the top.",
            "Dedupe first, then pick second largest.",
        ],
        "explanations": [
            "Sorting the distinct values puts the second-largest at index -2.",
            "Removing duplicates then sorting reveals the runner-up.",
        ],
        "py": "def second_largest(nums):\n    uniq = sorted(set(nums))\n    return uniq[-2] if len(uniq) >= 2 else None\n",
        "js": "function second_largest(nums) {\n  const uniq = [...new Set(nums)].sort((a, b) => a - b);\n  return uniq.length >= 2 ? uniq[uniq.length - 2] : null;\n}\n",
    },
    {
        "family": "digit_sum",
        "function": "digit_sum",
        "topic": "arithmetic",
        "prompt": "Return the sum of the digits of the non-negative integer `n`.",
        "inputs": lambda r, d: [[r.randint(0, 9999)] for _ in range(6)],
        "ref": lambda n: sum(int(c) for c in str(abs(n))),
        "hints": ["Convert to a string, sum the digit characters.", "Add up each decimal digit."],
        "explanations": [
            "Summing int(c) for each character of str(n) adds the digits.",
            "Walking the digits and accumulating yields the digit sum.",
        ],
        "py": "def digit_sum(n):\n    return sum(int(c) for c in str(abs(n)))\n",
        "js": "function digit_sum(n) {\n  return String(Math.abs(n)).split('').reduce((a, c) => a + Number(c), 0);\n}\n",
    },
    {
        "family": "is_sorted",
        "function": "is_sorted",
        "topic": "lists",
        "prompt": "Return True if `nums` is sorted in non-decreasing order, else False.",
        "inputs": lambda r, d: [[_ints(r, d)] for _ in range(6)],
        "ref": lambda nums: nums == sorted(nums),
        "hints": [
            "Compare the list to its sorted self.",
            "Each element should be >= the previous one.",
        ],
        "explanations": [
            "`nums == sorted(nums)` is True only when already sorted.",
            "A list equals its sorted copy exactly when non-decreasing.",
        ],
        "py": "def is_sorted(nums):\n    return nums == sorted(nums)\n",
        "js": "function is_sorted(nums) {\n  for (let i = 1; i < nums.length; i++) {\n    if (nums[i] < nums[i - 1]) return false;\n  }\n  return true;\n}\n",
    },
    {
        "family": "concat",
        "function": "concat",
        "topic": "strings",
        "prompt": "Return the concatenation of `a` and `b`.",
        "inputs": lambda r, d: [[_lname(r, d), _lname(r, d)] for _ in range(6)],
        "ref": lambda a, b: a + b,
        "hints": ["Join the two strings.", "a + b appends b to a."],
        "explanations": [
            "`a + b` appends b to a.",
            "String concatenation glues the two pieces together.",
        ],
        "py": "def concat(a, b):\n    return a + b\n",
        "js": "function concat(a, b) {\n  return a + b;\n}\n",
    },
    {
        "family": "clamp",
        "function": "clamp",
        "topic": "arithmetic",
        "prompt": "Return `x` clamped to the inclusive range [lo, hi] (not below lo, not above hi).",
        "inputs": lambda r, d: [
            [r.randint(-50, 50), r.randint(-20, 0), r.randint(1, 40)] for _ in range(6)
        ],
        "ref": lambda x, lo, hi: max(lo, min(hi, x)),
        "hints": ["max(lo, min(hi, x)).", "Bound x between lo and hi."],
        "explanations": [
            "`max(lo, min(hi, x))` pins x inside [lo, hi].",
            "Clamping first caps the top, then lifts the bottom.",
        ],
        "py": "def clamp(x, lo, hi):\n    return max(lo, min(hi, x))\n",
        "js": "function clamp(x, lo, hi) {\n  return Math.max(lo, Math.min(hi, x));\n}\n",
    },
]


def _build_spec(prob: dict, lang: str, rng: random.Random, d: int) -> dict[str, Any]:
    raw_cases = prob["inputs"](rng, d)
    test_cases: list[dict[str, Any]] = []
    for args in raw_cases:
        expected = prob["ref"](*args)
        test_cases.append({"args": list(args), "expected": expected})
    code = prob["py"] if lang == "python" else prob["js"]
    return {
        "function": prob["function"],
        "test_cases": test_cases,
        "reference_code": code,
        "prompt": prob["prompt"],
        "hints": [rng.choice(prob["hints"])],
        "explanation": rng.choice(prob["explanations"]),
        "topic": prob["topic"],
        "difficulty": d,
        "xp": 10 * d,
    }


def _make_challenge(lang: str, rng: random.Random, idx: int, seed: int) -> Challenge:
    last_err: Exception | None = None
    for _ in range(12):
        prob = rng.choice(_PROBLEMS)
        d = _pick_difficulty(rng)
        spec = _build_spec(prob, lang, rng, d)
        # Deterministic, seed-based ID (G2): stable per session so SRS can track
        # and re-schedule generative challenges instead of polluting progress.json
        # with throwaway random IDs. Reproducible via `--seed`.
        ch_id = f"gen-{lang}-{seed}-{idx}"
        ch = Challenge(
            id=ch_id,
            skill=lang,
            title=f"Generated: {prob['family']}",
            topic=spec["topic"],
            difficulty=spec["difficulty"],
            xp=spec["xp"],
            type="fix_bug",
            prompt=spec["prompt"],
            answer={"reference_code": spec["reference_code"]},
            validation={
                "mode": "test_cases",
                "lang": lang,
                "function": spec["function"],
                "test_cases": spec["test_cases"],
            },
            hints=spec["hints"],
            explanation=spec["explanation"],
        )
        # Self-validate the reference solution so the challenge is always gradeable.
        if not test_cases_runtime_available(lang):
            return ch
        try:
            res = validate(ch, spec["reference_code"])
        except Exception as exc:
            last_err = exc
            continue
        if res.correct:
            return ch
        last_err = RuntimeError(res.detail)
    if last_err is not None:
        # Should be unreachable for these templates; surface for debugging.
        raise last_err
    return ch


def _resolve_seed(seed: int | None) -> int:
    """A concrete seed: use the caller's seed, else mint a fresh one so each
    auto-generated session is internally stable (SRS-trackable) yet distinct."""
    return seed if seed is not None else random.getrandbits(32)


def generate_challenge(
    skill: str = "python",
    lang: str | None = None,
    seed: int | None = None,
    progress: dict | None = None,
    kind: str = "test_cases",
) -> Challenge:
    if kind == "regex":
        return generate_regex_challenge(seed=seed)
    lang = lang or _lang_for_skill(skill)
    seed = _resolve_seed(seed)
    rng = random.Random(seed)
    return _make_challenge(lang, rng, 0, seed)


def generate_session(
    skill: str = "python",
    count: int = 8,
    lang: str | None = None,
    seed: int | None = None,
    progress: dict | None = None,
    kind: str = "test_cases",
) -> list[Challenge]:
    if kind == "regex":
        return generate_regex_session(count=count, seed=seed)
    lang = lang or _lang_for_skill(skill)
    seed = _resolve_seed(seed)
    rng = random.Random(seed)
    return [_make_challenge(lang, rng, i, seed) for i in range(count)]


def generate_pack(
    skill: str = "python",
    count: int = 8,
    lang: str | None = None,
    seed: int | None = None,
    progress: dict | None = None,
    kind: str = "test_cases",
) -> Pack:
    """A synthetic Pack of freshly generated challenges, ready to play."""
    if kind == "regex":
        return generate_regex_pack(count=count, seed=seed)
    challenges = generate_session(skill=skill, count=count, lang=lang, seed=seed, progress=progress)
    lang = lang or _lang_for_skill(skill)
    return Pack(
        id=f"generated-{lang}",
        name="Generated",
        version="0.0.0",
        skill=lang,
        description="Fresh, runtime-synthesized challenges - practice that never repeats.",
        difficulty="mixed",
        author="core",
        challenges=challenges,
    )


# ---------------------------------------------------------------------------
# regex modality (G6): generated regex_tester challenges
# ---------------------------------------------------------------------------

_REGEX_RULES: list[dict[str, Any]] = [
    {
        "family": "digits_only",
        "ref": r"^\d+$",
        "prompt": "Write a regex that matches strings consisting ONLY of digits (e.g. '42', '007').",
        "pos": ["0", "7", "12345", "908"],
        "neg": ["", "a", "12a", "9 "],
        "hint": "Anchor both ends so the whole string must be digits.",
        "explanation": r"^\\d+$ forces the entire string to be one-or-more digits.",
    },
    {
        "family": "starts_capital",
        "ref": r"^[A-Z]",
        "prompt": "Match strings that START with a capital letter.",
        "pos": ["Hello", "Z", "Cat9"],
        "neg": ["hello", "1cat", ""],
        "hint": "Use ^ to anchor the start, then a character class for capitals.",
        "explanation": r"^[A-Z] requires the first character to be A-Z.",
    },
    {
        "family": "contains_cat",
        "ref": r"cat",
        "prompt": "Match strings that CONTAIN the substring 'cat' anywhere.",
        "pos": ["cat", "category", "wildcat", "scat!"],
        "neg": ["dog", "Ct", "ca t"],
        "hint": "Just write the literal substring; no anchors needed.",
        "explanation": "A bare pattern matches if it appears anywhere in the string.",
    },
    {
        "family": "hex_color",
        "ref": r"^#([0-9a-f]{3}|[0-9a-f]{6})$",
        "prompt": "Match CSS hex colors: '#rgb' or '#rrggbb' (lowercase hex digits).",
        "pos": ["#fff", "#a1b2c3", "#000"],
        "neg": ["fff", "#xyz", "#12", "#gggggg"],
        "hint": "Anchor both ends; allow 3 or 6 hex digits via alternation.",
        "explanation": r"^#([0-9a-f]{3}|[0-9a-f]{6})$ matches short or long lowercase hex colors.",
    },
    {
        "family": "three_letters",
        "ref": r"^[A-Za-z]{3}$",
        "prompt": "Match strings that are EXACTLY three letters.",
        "pos": ["cat", "ZYX", "abc"],
        "neg": ["cat!", "ab", "abcd", ""],
        "hint": "Anchor both ends and use a count of 3.",
        "explanation": r"^[A-Za-z]{3}$ requires exactly three letters and nothing else.",
    },
    {
        "family": "emailish",
        "ref": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        "prompt": "Match simple emails: word@word.tld (no spaces, exactly one '@', a dot in the domain).",
        "pos": ["a@b.co", "user@mail.com", "x.y@z.io"],
        "neg": ["a@b", "@b.co", "a b@c.com"],
        "hint": "One '@', a dot after it, no whitespace anywhere.",
        "explanation": r"^[^@\s]+@[^@\s]+\.[^@\s]+$ enforces one @ and a dotted domain with no spaces.",
    },
]


def _make_regex_challenge(rng: random.Random, idx: int, seed: int) -> Challenge:
    last_err: Exception | None = None
    for _ in range(12):
        rule = rng.choice(_REGEX_RULES)
        d = _pick_difficulty(rng)
        ch = Challenge(
            id=f"gen-regex-{seed}-{idx}",
            skill="regex",
            title=f"Generated regex: {rule['family']}",
            topic="regex",
            difficulty=d,
            xp=10 * d,
            type="regex_tester",
            prompt=rule["prompt"],
            answer={"value": rule["ref"]},
            validation={
                "mode": "regex_tester",
                "must_match": list(rule["pos"]),
                "must_not_match": list(rule["neg"]),
            },
            hints=[rule["hint"]],
            explanation=rule["explanation"],
        )
        # Self-validate the reference regex through the same validator.
        try:
            res = validate(ch, rule["ref"])
        except Exception as exc:
            last_err = exc
            continue
        if res.correct:
            return ch
        last_err = RuntimeError(res.detail)
    if last_err is not None:
        raise last_err
    return ch


def generate_regex_challenge(seed: int | None = None, progress: dict | None = None) -> Challenge:
    seed = _resolve_seed(seed)
    rng = random.Random(seed)
    return _make_regex_challenge(rng, 0, seed)


def generate_regex_session(
    count: int = 8, seed: int | None = None, progress: dict | None = None
) -> list[Challenge]:
    seed = _resolve_seed(seed)
    rng = random.Random(seed)
    return [_make_regex_challenge(rng, i, seed) for i in range(count)]


def generate_regex_pack(
    count: int = 8, seed: int | None = None, progress: dict | None = None
) -> Pack:
    challenges = generate_regex_session(count=count, seed=seed)
    return Pack(
        id="generated-regex",
        name="Generated regex",
        version="0.0.0",
        skill="regex",
        description="Fresh, runtime-synthesized regex challenges - practice that never repeats.",
        difficulty="mixed",
        author="core",
        challenges=challenges,
    )
