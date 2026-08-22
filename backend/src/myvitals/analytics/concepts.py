"""Canonical pantry concepts over the USDA catalog (MEAL-6).

WHY THIS EXISTS. USDA rows are NUTRITION rows. "Chicken, broiler or
fryers, breast, skinless, boneless, meat only, raw" and the same food
"cooked, braised" are separate ids with genuinely different nutrition —
correctly so. But they are ONE thing to have in the house, so matching a
pantry item to a recipe ingredient on `food_id` fails and the shopping
list tells you to buy chicken you already have. This module is the coarse
layer that fixes that. Nutrition always still comes from the specific row.

Every app in this space makes the same split: SuperCook exposes roughly
2,000 pantry ingredients over millions of indexed recipes.

## The rule that decides every case

Drop ONLY what was done to a food *after it was bought*. Keep everything
that changes which package leaves the shop.

That phrasing is doing real work. An earlier, more ambitious version of
this module dropped 266 different segment types — physical form, pack
medium, marketing words, sweetness, "intensity descriptors" — on the
theory that none of them changed the food. Three adversarial passes over
the real catalog found roughly fifty merges that were simply wrong, and
every single one traced to that breadth:

  * chocolate MILK filed as chocolate SYRUP (a "prepared with" segment
    was eaten, so the milk vanished)
  * a Kraft flavoured coffee mix at 19.2 g fat merged with plain instant
    coffee at 0.5 g — a 38x error on the nutrient this app exists to
    track
  * whole-wheat bread, tortillas and crackers folded into their white
    equivalents
  * silken tofu merged with firm; soft pretzels with hard; frozen chips
    with plain boiled potatoes at 36x the fat

So the drop list here is deliberately tiny and covers one idea:
preparation, doneness, and the USDA bookkeeping that is not part of any
product name. Everything else survives into the concept.

## The asymmetry, and how it is carried structurally

Under-merging is an annoyance: the shopping list fails to cancel one item
and you buy a second bag of rice. Over-merging is a correctness failure:
counting peanut butter as butter puts the wrong food on a list and the
wrong number into a per-meal fat total, which is the figure a
cholecystectomy makes matter. Three structural guarantees, not blocklists:

1. The head segment is never split on whitespace. "Peanut butter" is one
   comma-segment, so it cannot shed a word and decay to "butter".
2. Qualifiers are DROP-listed, never keep-listed. Unrecognised vocabulary
   therefore splits a concept (safe) rather than fusing two (unsafe).
3. A prepared dish returns None rather than a guess, so "has a concept"
   is exactly the question "is this stockable".

`backend/tests/test_concepts.py` holds the battery, plus the specific
counterexamples the adversarial passes found. Any replacement must keep
the signature and pass all of them.

KNOWN LIMIT, recorded rather than hidden: this under-merges heavily —
beef and pork cuts fragment, and brands split from their plain
equivalents. That costs a duplicated shopping line and is the direction
chosen on purpose.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- gates

#: Whole categories that are prepared food, never a pantry ingredient.
PREPARED_CATEGORIES = frozenset({
    "Fast Foods",
    "Restaurant Foods",
    "Meals, Entrees, and Side Dishes",
})

#: Composed dishes leak into ingredient categories — "Spinach souffle" is
#: filed under Vegetables. Narrow on purpose: "stew" is absent because
#: "Beef, chuck for stew" is a cut of stewing beef.
_DISH_WORDS = re.compile(
    r"\b(souffle|casserole|sandwich|sandwiches|pizza|lasagna|enchilada|"
    r"quiche|pot pie|nachos|burger|cheeseburger|stroganoff|a la king|"
    r"chop suey|jambalaya|goulash|au gratin|meatloaf|meat loaf|"
    r"chowder|bisque|gumbo|ravioli|tamale|manicotti|risotto|"
    r"meatball|salisbury|chow mein|pad thai|paella)\b"
)

#: Heads that are a dish rather than an ingredient.
_DISH_HEADS = frozenset({
    "soup", "soups", "stew", "chili", "gravy", "gravies", "entree",
    "entrees", "meal", "meals", "dinner", "casserole", "pizza",
    "sandwich", "burrito", "taco", "babyfood", "baby food",
    "infant formula", "formulated bar", "formulated bars",
})

# ------------------------------------------------------- the drop list
#
# ONE idea only: what was done to the food after it was bought, plus USDA
# bookkeeping that appears in no product name. Matched as WHOLE segments,
# so "french fried" survives (it is a form you buy) while a bare "fried"
# does not.

_DROP_SEGMENTS = frozenset({
    # doneness
    "raw", "cooked", "boiled", "braised", "grilled", "roasted", "baked",
    "broiled", "stewed", "steamed", "microwaved", "simmered", "poached",
    "blanched", "parboiled", "fried", "pan-fried", "cooked in water",
    "roasted or baked", "baked or roasted", "cooked without added fat",
    "cooked with added fat", "unprepared", "uncooked", "unheated",
    # what is left after cooking
    "drained", "rinsed", "reheated",
    # salt, which the battery requires to collapse for butter and spinach
    "with salt", "without salt", "salted", "unsalted", "no salt added",
    "with added salt", "salt added", "salt not added",
    # trim state — NOT "separable fat" or "skin", which are their own food
    "skinless", "boneless", "meat only", "bone removed", "bone in",
    "bone-in", "trimmed to 0 fat", "trimmed to 1/8 fat",
    "trimmed to 1/4 fat",
    # USDA bookkeeping that appears in no product name
    "broilers or fryers", "broiler or fryers", "all grades",
    "all classes", "choice grade", "select grade", "prime grade",
    "usda choice", "usda select", "usda prime", "retail cuts",
    "nfs", "composite of trimmed retail cuts",
    "includes foods for usda's food distribution program",
    "includes usda commodity food a099",
    # Use-case blurbs. Not part of any product name, and they leak into
    # the concept as trailing nonsense ("olive oil salad or").
    "salad or cooking", "for cooking", "cooking", "table use",
    "industrial use", "principal uses", "for baking",
})

#: Segment PATTERNS with the same one idea. Kept few and anchored, since a
#: loose pattern is how "prepared with whole milk" ate the milk.
_DROP_PATTERNS = (
    # "93% lean meat / 7% fat" — the battery requires ground-beef fat
    # percentages to collapse.
    re.compile(r"^\d+% lean meat\b"),
    re.compile(r"^\d+% lean\b"),
    # "cooked, boiled, drained" arrives already split; these catch the
    # compound spellings.
    re.compile(r"^cooked,? (boiled|braised|roasted|grilled|baked|stewed)"),
    re.compile(r"^(raw|cooked) and ", ),
)

#: Never dropped, whatever else matches. Each is a real shopping
#: distinction that an earlier version lost.
_KEEP_ALWAYS = frozenset({
    "whole wheat", "whole-wheat", "whole grain", "whole-grain",
    "separable fat", "skin", "skin only", "separable lean only",
    "separable lean and fat", "liquid", "drained solids", "solids",
    "french fried", "hard", "soft", "silken", "firm", "extra firm",
    "smooth", "chunky", "creamy",
})

#: A finished concept that is exactly one of these is a compound that
#: decayed to its head noun — the catastrophic failure. Belt and braces
#: over guarantee 1.
_BARE_HEADS = frozenset({
    "butter", "milk", "cream", "oil", "sauce", "sugar", "flour",
    "cheese", "juice", "syrup", "powder", "extract", "paste",
})

#: Heads English qualifies from the front: "olive oil", not "oil olive".
#: These are materials rather than things — the qualifier names which
#: kind, and the kind comes first in every shop.
_REVERSED_HEADS = frozenset({
    "oil", "oils", "juice", "juices", "cheese", "cheeses", "flour",
    "flours", "vinegar", "sugar", "syrup", "milk", "cream", "butter",
    "rice", "beans", "bean", "nuts", "seeds", "sauce", "broth", "stock",
    "yogurt", "pasta", "bread", "salt", "pepper", "tea", "coffee",
    "wine", "water",
})

#: Heads that are a SHELF LABEL rather than a food. USDA files things
#: under a taxonomy ("Mollusks, clam, ...") or a department ("Beverages,
#: ...", "Alcoholic Beverage, wine, ..."), and carrying that prefix makes
#: every concept in the group longer without making any of them more
#: distinct from each other.
#:
#: Promoting past a shared prefix cannot merge two members of the group —
#: they keep whatever distinguished them. It only merges across groups,
#: which is correct: chocolate syrup filed under Beverages and the same
#: syrup filed under Sweets is one thing to buy.
_CONTAINER_HEADS = frozenset({
    "beverages", "beverage", "alcoholic beverage", "alcoholic beverages",
    "snacks", "snack", "mollusks", "crustaceans", "fish", "finfish",
    "cereals", "cereals ready-to-eat", "cereal", "candies", "candy",
    "nuts", "seeds", "spices", "leavening agents", "syrups",
    "toppings", "desserts", "puddings", "sweeteners",
    "vegetarian foods", "meat extender", "formulated bar",
})

#: A REDUCED fat tier is identity, never noise, and is exempt from the
#: word cap. Full-fat is the unmarked default and is dropped.
#:
#: This exists because the cap silently ate it: "Salad dressing, blue or
#: roquefort cheese dressing, fat-free" (1.0 g) and the same dressing
#: "regular" (51.1 g) both truncated to the same seven words, merging a
#: 50 g/100 g fat gap. For a user whose per-meal fat is medically
#: load-bearing, a low-fat variant must never fold into its full-fat
#: parent.
_FAT_TIER = {
    "fat-free": "fat-free", "fat free": "fat-free", "nonfat": "nonfat",
    "non-fat": "nonfat", "no fat": "fat-free", "skim": "nonfat",
    "lowfat": "lowfat", "low fat": "lowfat", "low-fat": "lowfat",
    "reduced fat": "reduced fat", "reduced-fat": "reduced fat",
    "light": "light", "lite": "light", "part-skim": "part-skim",
    "part skim": "part-skim", "lower fat": "lowfat",
    "extra light": "extra light", "reduced calorie": "reduced calorie",
}

#: Connectives that must never end a concept. The word cap can cut a
#: phrase in half and leave one of these trailing.
_DANGLING = frozenset({
    "with", "without", "added", "and", "or", "of", "in", "to", "from",
    "for", "the", "a", "an", "plus", "including",
})

_PAREN = re.compile(r"\([^)]*\)")
_WS = re.compile(r"\s+")
# Seven, not four.
#
# The cap exists so a concept stays readable, but truncation makes a
# concept LESS specific, which MERGES — the opposite of the asymmetry
# this module is built around. At four words, "Bread, french or vienna,
# whole wheat" lost its whole-wheat, canned clams merged with clam juice,
# and every beef organ meat collapsed into one "beef variety meat".
# Readability yields to correctness here.
_MAX_WORDS = 7


def _drop(seg: str) -> bool:
    if seg in _KEEP_ALWAYS:
        return False
    if seg in _DROP_SEGMENTS:
        return True
    return any(p.search(seg) for p in _DROP_PATTERNS)


#: Words that end in "s" without being plural. Stripping them produced
#: "specy" from "species" and "potatoe" from "potatoes".
_NON_PLURAL = frozenset({
    "species", "molasses", "asparagus", "hummus", "couscous", "swiss",
    "watercress", "cress", "grits", "oats", "greens", "beans", "peas",
    "lentils", "chives", "capers", "sprouts", "leaves", "berries",
})


def _singularish(word: str) -> str:
    """Crude de-pluralisation. Wrong occasionally, and wrong here means a
    split concept rather than a merged one — the safe direction."""
    # Never touch a possessive: "quaker mother's" became "mother'".
    if "'" in word:
        return word
    if word in _NON_PLURAL:
        return word
    if word.endswith("oes") and len(word) > 4:
        return word[:-2]          # potatoes -> potato, tomatoes -> tomato
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith("es") and word[-3] in "shxz":
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def concept_for(row: dict[str, Any]) -> str | None:
    """Map one catalog row to a coarse pantry concept, or None.

    None means "not a pantry ingredient" — a prepared dish — rather than
    "could not work it out", so callers can treat it as the stockable
    test.
    """
    category = (row.get("category") or "").strip()
    name = (row.get("name") or "").strip()
    if not name or category in PREPARED_CATEGORIES:
        return None

    cleaned = _PAREN.sub("", name).strip().strip(",").strip()
    if not cleaned or _DISH_WORDS.search(cleaned.lower()):
        return None

    segments = [
        _WS.sub(" ", s.strip().lower())
        for s in cleaned.split(",")
        if s.strip()
    ]
    if not segments:
        return None

    head, rest = segments[0], segments[1:]
    if head in _DISH_HEADS:
        return None

    # Promote past a shelf label to the first real noun that follows.
    if head in _CONTAINER_HEADS:
        for i, seg in enumerate(rest):
            if _drop(seg) or seg in _FAT_TIER:
                continue
            head, rest = seg, rest[i + 1:]
            break

    # A reduced-fat marker is pulled out before anything else so the word
    # cap can never eat it.
    tier = ""
    for seg in rest:
        if seg in _FAT_TIER:
            tier = _FAT_TIER[seg]
            break

    # Qualifiers, in the order USDA wrote them, minus preparation. Order
    # is preserved rather than sorted, so the concept reads the way the
    # name did.
    quals = [s for s in rest if not _drop(s) and s not in _FAT_TIER]

    # USDA writes some foods variety-first ("Oil, olive") where English
    # writes them the other way round ("olive oil"), and others head-first
    # ("Chicken, ..., breast") where English agrees ("chicken breast").
    # Reversing everything produced "breast chicken", so the reversal is
    # limited to heads that are a MATERIAL rather than a thing — the ones
    # English qualifies from the front.
    if quals and head in _REVERSED_HEADS:
        first = quals[0]
        if len(first.split()) <= 2:
            phrase = f"{first} {head}"
            tail = quals[1:]
        else:
            phrase = head
            tail = quals
    else:
        phrase = head
        tail = quals

    words = phrase.split() + [w for q in tail for w in q.split()]
    words = [_singularish(w) for w in words[:_MAX_WORDS]]
    # The word cap can land mid-phrase and leave a dangling connective —
    # "chicken breast with added" reads as a mistake rather than as a
    # distinction. Trim back to the last word that carries meaning.
    while words and words[-1] in _DANGLING:
        words.pop()
    concept = " ".join(words).strip()
    if tier:
        concept = f"{tier} {concept}".strip()

    if not concept:
        return None
    # Guarantee 3, belt and braces: a compound must never have decayed to
    # its bare head noun.
    if concept in _BARE_HEADS and _singularish(head.split()[-1]) != concept:
        return None
    return concept[:80]
