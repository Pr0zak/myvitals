"""One-tap staples for filling a pantry (MEAL-6b).

Filling a pantry by searching USDA is miserable, and typing plain names
instead only appears to work. Measured against the real catalog, exactly
nine of twenty everyday staples match a concept when typed: "honey",
"chicken", "butter" and "rice" do; "eggs", "flour", "sugar", "milk",
"salt", "cheese", "bread", "potato", "tomato" and "beans" do not, because
their concepts are "whole egg", "wheat flour", "granulated sugar",
"cheddar cheese" and so on.

That is the worst possible failure mode: the item sits in the pantry
looking correct, the shopping list never cancels it, and nothing says
why. So the fix is not better free-text matching — it is not making the
user guess in the first place.

This is the model every app in the category uses. SuperCook exposes a
curated list of roughly 2,000 ingredients grouped into categories, and
you tick what you have rather than searching a nutrition database.

Each entry names a SEARCH TERM rather than a food id, because ids come
from the bundled catalog and change when it is rebuilt. The term is
resolved at request time against the same ranked search the pickers use,
so an entry that stops resolving degrades to "not offered" rather than to
a wrong food.
"""

from __future__ import annotations

#: Everyday staples, grouped the way a kitchen is. Deliberately short —
#: this is the 80% case, and anything missing is still one search away.
#: Each value is the search term used to find the catalog row.
COMMON_PANTRY: dict[str, list[tuple[str, str]]] = {
    "Meat & fish": [
        ("Chicken breast", "chicken broiler breast skinless boneless raw"),
        ("Chicken thigh", "chicken broiler thigh raw"),
        ("Ground beef", "beef ground raw"),
        ("Bacon", "pork cured bacon unprepared"),
        ("Pork chop", "pork loin chop raw"),
        ("Salmon", "fish salmon atlantic raw"),
        ("Tuna", "fish tuna light canned water"),
        ("Shrimp", "crustaceans shrimp raw"),
        ("Eggs", "egg whole raw fresh"),
    ],
    "Dairy": [
        ("Milk", "milk whole"),
        ("Butter", "butter salted"),
        ("Cheddar cheese", "cheese cheddar"),
        ("Mozzarella", "cheese mozzarella whole milk"),
        ("Parmesan", "cheese parmesan grated"),
        ("Greek yogurt", "yogurt greek plain whole milk"),
        ("Sour cream", "cream sour cultured"),
        ("Cream cheese", "cheese cream"),
    ],
    "Vegetables": [
        ("Onion", "onions raw"),
        ("Garlic", "garlic raw"),
        ("Potato", "potatoes flesh and skin raw"),
        ("Sweet potato", "sweet potato raw unprepared"),
        ("Carrot", "carrots raw"),
        ("Broccoli", "broccoli raw"),
        ("Spinach", "spinach raw"),
        ("Tomato", "tomatoes red ripe raw"),
        ("Bell pepper", "peppers sweet red raw"),
        ("Mushroom", "mushrooms white raw"),
        ("Lettuce", "lettuce romaine raw"),
        ("Celery", "celery raw"),
        ("Cucumber", "cucumber with peel raw"),
        ("Green beans", "beans snap green raw"),
        ("Frozen peas", "peas green frozen"),
        ("Corn", "corn sweet yellow raw"),
    ],
    "Fruit": [
        ("Apple", "apples raw with skin"),
        ("Banana", "bananas raw"),
        ("Lemon", "lemons raw without peel"),
        ("Lime", "limes raw"),
        ("Orange", "oranges raw"),
        ("Avocado", "avocados raw"),
        ("Strawberries", "strawberries raw"),
        ("Blueberries", "blueberries raw"),
    ],
    "Grains & pasta": [
        ("White rice", "rice white long-grain regular raw"),
        ("Brown rice", "rice brown long-grain raw"),
        ("Pasta", "pasta dry unenriched"),
        ("Bread", "bread white commercially prepared"),
        ("Tortillas", "tortillas ready-to-bake flour"),
        ("Oats", "oats"),
        ("Flour", "wheat flour white all-purpose enriched"),
        ("Breadcrumbs", "bread crumbs dry grated plain"),
    ],
    "Tins & jars": [
        ("Black beans", "beans black mature seeds canned"),
        ("Chickpeas", "chickpeas garbanzo canned"),
        ("Tinned tomatoes", "tomatoes red ripe canned"),
        ("Tomato paste", "tomato products canned paste"),
        ("Coconut milk", "nuts coconut milk canned"),
        ("Peanut butter", "peanut butter smooth"),
        ("Honey", "honey"),
        ("Maple syrup", "syrups maple"),
    ],
    "Oils & condiments": [
        ("Olive oil", "oil olive salad or cooking"),
        ("Vegetable oil", "oil vegetable canola"),
        ("Butter (again)", "butter without salt"),
        ("Soy sauce", "soy sauce made from soy and wheat"),
        ("Vinegar", "vinegar distilled"),
        ("Mayonnaise", "mayonnaise regular"),
        ("Mustard", "mustard prepared yellow"),
        ("Hot sauce", "sauce ready-to-serve pepper or hot"),
    ],
    "Baking & spices": [
        ("Sugar", "sugars granulated"),
        ("Brown sugar", "sugars brown"),
        ("Salt", "salt table"),
        ("Black pepper", "spices pepper black"),
        ("Baking powder", "leavening agents baking powder"),
        ("Baking soda", "leavening agents baking soda"),
        ("Vanilla extract", "vanilla extract"),
        ("Cinnamon", "spices cinnamon ground"),
        ("Paprika", "spices paprika"),
        ("Chilli powder", "spices chili powder"),
        ("Cumin", "spices cumin seed"),
        ("Oregano", "spices oregano dried"),
    ],
}


def flat() -> list[tuple[str, str, str]]:
    """(category, label, search term) for every entry."""
    return [
        (cat, label, term)
        for cat, items in COMMON_PANTRY.items()
        for label, term in items
    ]


# ---------------------------------------------------------------------------
# Grouping a pantry for reading
# ---------------------------------------------------------------------------

#: USDA's category -> the kitchen group this module already uses for its
#: staples. Two vocabularies for one idea would be worse than either, so
#: the curated eight above are the vocabulary and this maps onto them.
#:
#: USDA's names are a database taxonomy, not kitchen sections: "Legumes
#: and Legume Products", "Soups, Sauces, and Gravies", "Cereal Grains and
#: Pasta". Useful for classification, unreadable as headings over the
#: things in your cupboard.
_USDA_TO_GROUP: dict[str, str] = {
    "Poultry Products": "Meat & fish",
    "Beef Products": "Meat & fish",
    "Pork Products": "Meat & fish",
    "Lamb, Veal, and Game Products": "Meat & fish",
    "Finfish and Shellfish Products": "Meat & fish",
    "Sausages and Luncheon Meats": "Meat & fish",
    "Dairy and Egg Products": "Dairy",
    "Vegetables and Vegetable Products": "Vegetables",
    "Fruits and Fruit Juices": "Fruit",
    "Cereal Grains and Pasta": "Grains & pasta",
    "Baked Products": "Grains & pasta",
    "Breakfast Cereals": "Grains & pasta",
    "Spices and Herbs": "Baking & spices",
    "Sweets": "Baking & spices",
    "Nut and Seed Products": "Baking & spices",
    "Fats and Oils": "Oils & condiments",
    "Soups, Sauces, and Gravies": "Oils & condiments",
    "Legumes and Legume Products": "Tins & jars",
    "Beverages": "Drinks",
}

#: The order sections appear in. Roughly how a shop is walked and how a
#: kitchen is arranged — fresh first, cupboard staples after, the
#: uncategorised remainder last so it never sits between two real
#: sections.
GROUP_ORDER: tuple[str, ...] = (
    "Meat & fish",
    "Dairy",
    "Vegetables",
    "Fruit",
    "Grains & pasta",
    "Tins & jars",
    "Oils & condiments",
    "Baking & spices",
    "Drinks",
    "Other",
)


#: Name markers that beat the category, for categories that are
#: internally mixed.
#:
#: USDA files "Leavening agents, baking powder" and "Leavening agents,
#: baking soda" under **Baked Products** — the same category as bread
#: and tortillas. Both belong there by USDA's logic and neither belongs
#: in a "Grains & pasta" section on a kitchen shelf. The curated list
#: above settles the disagreement: it puts flour, oats, bread and
#: tortillas in Grains & pasta and baking powder and soda in Baking &
#: spices, which is how a person actually stores them.
#:
#: Deliberately tiny, and it stays tiny. This is the same trap as the
#: concept extractor's drop list: every entry added is a rule applied to
#: foods nobody checked, and the failure is silent — a thing filed on the
#: wrong shelf, found by not finding it. Add one only for a category
#: demonstrably holding two different kitchen sections.
_NAME_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("leavening agent", "Baking & spices"),
    # "Great Value Traditional Pasta Sauce" contains "pasta", so the
    # curated-name match filed a jar of sauce under Grains & pasta. The
    # noun that decides the shelf is the last one, and here it is sauce.
    ("sauce", "Oils & condiments"),
)


#: Open Food Facts' taxonomy -> kitchen group, matched as SUBSTRINGS of
#: the `en:` tag because that taxonomy is deep and specific — a jar of
#: peanut butter comes back "en:nut-butters", oats as "en:rolled-oats".
#:
#: Matching on substrings rather than exact tags is what makes this
#: tractable: OFF has thousands of leaf categories and roughly a dozen
#: words carry the shelf. Ordered most specific first, because
#: "en:nut-butters" contains both "butter" and "nut" and only one of
#: those is right.
_OFF_TO_GROUP: tuple[tuple[str, str], ...] = (
    ("nut-butter", "Oils & condiments"),
    ("peanut-butter", "Oils & condiments"),
    ("noodle", "Grains & pasta"),
    ("pasta", "Grains & pasta"),
    ("oat", "Grains & pasta"),
    ("cereal", "Grains & pasta"),
    ("bread", "Grains & pasta"),
    ("tortilla", "Grains & pasta"),
    ("rice", "Grains & pasta"),
    ("flour", "Grains & pasta"),
    ("granola", "Grains & pasta"),
    ("yogurt", "Dairy"),
    ("yoghurt", "Dairy"),
    ("cheese", "Dairy"),
    ("milk", "Dairy"),
    ("cream", "Dairy"),
    ("butter", "Dairy"),
    ("egg", "Dairy"),
    ("poultry", "Meat & fish"),
    ("chicken", "Meat & fish"),
    ("beef", "Meat & fish"),
    ("pork", "Meat & fish"),
    ("meat", "Meat & fish"),
    ("seafood", "Meat & fish"),
    ("fish", "Meat & fish"),
    ("fruit", "Fruit"),
    ("berries", "Fruit"),
    ("vegetable", "Vegetables"),
    ("legume", "Tins & jars"),
    ("canned", "Tins & jars"),
    ("soup", "Tins & jars"),
    ("sauce", "Oils & condiments"),
    ("condiment", "Oils & condiments"),
    ("dressing", "Oils & condiments"),
    ("spread", "Oils & condiments"),
    ("oil", "Oils & condiments"),
    ("beverage", "Drinks"),
    ("drink", "Drinks"),
    ("water", "Drinks"),
    ("juice", "Drinks"),
    ("coffee", "Drinks"),
    ("tea", "Drinks"),
    ("honey", "Baking & spices"),
    ("sugar", "Baking & spices"),
    ("spice", "Baking & spices"),
    ("herb", "Baking & spices"),
    ("baking", "Baking & spices"),
    ("snack", "Baking & spices"),
    ("sweet", "Baking & spices"),
    ("protein-powder", "Drinks"),
)


def kitchen_group(usda_category: str | None, name: str | None = None) -> str:
    """Which section of a kitchen a food belongs to.

    Returns "Other" for anything unmapped, which covers two real cases:
    a USDA category nobody has classified yet, and a hand-typed pantry
    item with no food behind it at all. Fifteen of this user's
    forty-nine pantry rows are the second kind — they are typed names
    like "Flower" with no catalog match — so "Other" is a populated
    section, not a rounding error, and it is placed last rather than
    hidden.
    """
    # The name is checked FIRST, because it is only consulted for cases
    # where the category is known to be mixed — so where it matches, it
    # is the more specific signal of the two.
    lowered = (name or "").lower()
    for marker, group in _NAME_OVERRIDES:
        if marker in lowered:
            return group
    cat = (usda_category or "").strip()
    # Open Food Facts categories arrive as "en:rolled-oats". Its taxonomy
    # is not USDA's, so it gets its own map.
    if cat.startswith("en:"):
        tag = cat[3:]
        for marker, group in _OFF_TO_GROUP:
            if marker in tag:
                return group
        # Unrecognised, so no information — fall through to the name.
        # A real case: OFF gives "Great Value Traditional Pasta Sauce"
        # the tag "en:Groceries", which says nothing, while the product's
        # own name says exactly where it goes. Returning "Other" here
        # would let a useless category outrank a clear name.
    elif cat:
        mapped = _USDA_TO_GROUP.get(cat)
        if mapped is not None:
            return mapped
        # Same reasoning for an unmapped USDA category.

    # No category at all — a hand-typed pantry line. The curated staples
    # list already says which shelf "eggs" or "flour" belongs on, so it
    # is asked rather than a third set of rules being written. A typo
    # like "flower" simply misses and lands in Other, which is honest:
    # the app cannot know what was meant.
    if lowered:
        best: tuple[int, str] | None = None
        for group, entries in COMMON_PANTRY.items():
            for entry in entries:
                label = (entry[0] if isinstance(entry, (tuple, list)) else str(entry))
                low = label.lower()
                if low == lowered:
                    return group
                # People type "pepper" for "Black pepper" and "unsweetened
                # almond milk" for "Almond milk", so containment either
                # way counts — but only for labels long enough that a
                # chance substring is unlikely. "Oats" inside "goats" is
                # the shape of mistake this guards against.
                if len(low) >= 4 and (low in lowered or lowered in low):
                    # Longest match wins: "almond milk" must beat "milk".
                    if best is None or len(low) > best[0]:
                        best = (len(low), group)
        if best is not None:
            return best[1]
    return "Other"
