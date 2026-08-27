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


def kitchen_group(usda_category: str | None) -> str:
    """Which section of a kitchen a food belongs to.

    Returns "Other" for anything unmapped, which covers two real cases:
    a USDA category nobody has classified yet, and a hand-typed pantry
    item with no food behind it at all. Fifteen of this user's
    forty-nine pantry rows are the second kind — they are typed names
    like "Flower" with no catalog match — so "Other" is a populated
    section, not a rounding error, and it is placed last rather than
    hidden.
    """
    if not usda_category:
        return "Other"
    return _USDA_TO_GROUP.get(usda_category.strip(), "Other")
