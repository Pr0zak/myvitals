# Meals, recipes, pantry and shopping — design plan

Status: **plan only, nothing built. TABLED 2026-08-21** at the user's
request — revisit once the SparkyFitness teardown backlog is finished.
The open question below (tracking vs awareness) is what to answer first
when it is picked back up.

The ask: a healthy-meals list with recipes, a place to record what is
already in the house, suggestions built from that, a shopping list that
reaches a Walmart cart, and a meal-prep section that handles both
single-person and family portions.

This document records the design and — more importantly — the three
places where the obvious approach does not work, so they are not
rediscovered mid-build.

---

## Why this fits myvitals specifically

Every generic meal-planning app starts cold: it knows nothing about you,
so "healthy" means whatever its editors decided. This app already knows
the weight goal and its trend, training load (CTL/ATL/TSB), fasting
schedule and protocol, sleep debt, and the day's planned workout.

That is the whole differentiator, and it should drive the feature rather
than be an afterthought. "You have a 2-hour ride tomorrow and you are 18h
into a fast" is a materially different meal question from "it is Tuesday",
and this is one of the few codebases that can tell the difference.

Concretely, suggestions should be able to say things like: higher-carb the
evening before a long ride; protein-forward on a lift day; nothing that
needs a 40-minute prep window on a day the calendar is full.

---

## The three hard parts

### 1. Recipes cannot be scraped

Recipe *text* — the method, the headnote, the photos — is copyrighted.
Ingredient lists alone are largely not, but a scraper that pulls whole
recipes off food sites and republishes them in an app is straightforward
infringement, and it would also make the repo (which is **public**)
carry that content.

**Decision: the app never ships or scrapes third-party recipes.**

What it does instead:

- **User-owned recipes.** The user enters or pastes their own. This is
  the primary path and it is not a limitation — most people cook a
  rotation of 20-40 things they already know.
- **Import by URL is import-for-personal-use, into the user's own
  private database.** Schema.org `Recipe` microdata is published by most
  food sites precisely so machines can read it. Parsing that into the
  user's own install is the same act as bookmarking. It must never be
  re-exported, and the parsed text must never land in the git repo.
- **AI generates suggestions, not reproductions.** "Chicken, rice and
  the broccoli that is about to turn, 25 minutes" is a suggestion. It
  should compose from the pantry and the user's own saved recipes, and
  say when it is inventing rather than recalling.

### 2. Walmart cart: three tiers, only one of which is reliable

Researched 2026-08-21.

| Approach | Works? | Notes |
|---|---|---|
| Per-item search deep links | **Yes, today** | `walmart.com/search?q=<item>`. No auth, no key, no item IDs. Verified 200. |
| Affiliate add-to-cart URL | Maybe, fragile | `walmart.com/affil/cart/addToCart?items=<itemId>_<qty>,…`. [Deprecated](https://walmart.io/apidocs/affiliates/gm-add-to-cart) in favour of a Consolidated Add to Cart API, and gated to Impact Radius publishers. Needs Walmart item IDs. |
| Official Add to Cart / Commerce API | **No** | [Requires approval and a "sound business case"](https://walmart.io/docs/atc/v1/add-to-cart). Not obtainable for a single-user self-hosted install. |

**Decision: build tier 1. Treat tier 2 as an experiment.**

One insight that simplifies this a lot: **the server never needs to talk
to Walmart.** A cart belongs to a logged-in browser session, so the only
thing that can populate it is the user's own browser. The server's job
ends at generating a URL.

That matters because a server-side fetch of the add-to-cart URL from this
network returns `307 → /blocked` (Akamai bot detection on the home ISP
IP) — the same wall the `homedepot` project hit and solved with a Squid
proxy on an Oracle Cloud VM. **None of that infrastructure is needed
here**, because nothing is fetched server-side.

The only thing tier 2 would need is Walmart *item IDs*, and getting those
does require a product lookup that is blocked from this IP. If tier 2 is
ever attempted, reuse the homedepot Camoufox-through-Oracle-proxy pattern
rather than inventing a second one — and expect the deprecated affiliate
endpoint to break without notice.

### 3. Portions are a household model, not a multiplier

"Meals for individuals and for family so proportions are taken into
account" is the requirement most likely to be built wrong, because the
naive version — one `servings` field and a multiplier — breaks
immediately:

- A recipe scaled 4× does not need 4× the salt, oil or spice. Scaling
  everything linearly produces inedible food, and confidently.
- People in a household do not eat equal portions. A child is not 1.0.
- Meal prep means *containers*: 5 lunches for one person is a different
  shopping list from one dinner for five, even at identical total mass.

**Decision:** a `household` config of named members each with a
`portion_factor` (adult 1.0, teen 1.2, child 0.5 — user-editable), and
per-ingredient `scaling` of `linear` | `sublinear` | `fixed`. Salt and
spices are `sublinear` or `fixed`; proteins, grains and vegetables are
`linear`. Default `linear` so a recipe entered without thought behaves
predictably, and let the user mark exceptions.

Meal-prep plans then declare *who* and *how many meals*, not a
multiplier.

---

## Data model sketch

New tables (a migration, not a JSON blob — the shopping-list computation
has to query and aggregate these, which a blob cannot do):

| Table | Purpose |
|---|---|
| `foods` | Canonical ingredient + per-100g nutrition. Seeded from USDA. |
| `recipes` | User-owned: name, method, servings, prep/cook minutes, tags. |
| `recipe_ingredients` | recipe → food, quantity, unit, `scaling`. |
| `pantry_items` | food, quantity, unit, optional `expires_on`, updated_at. |
| `meal_plans` | A dated plan: date, meal slot, recipe, servings, who. |
| `shopping_lists` | A generated list + its state (open/ordered/done). |

Config in `user_profile.extra` (free-form JSON, no migration, matching
the established pattern): `household` members and portion factors,
dietary restrictions, disliked foods, default store.

### Nutrition source: USDA FoodData Central

Public domain, lab-analysed for whole foods, bulk-downloadable. Strong
precedent in this repo: the exercise catalog is already a bundled
public-domain dataset (`data/exercises.json`, free-exercise-db,
Unlicense) with images served from `StaticFiles`. Do the same — **bundle
a filtered subset rather than calling an API at runtime**, so the feature
works offline and does not depend on an external service staying up.

Open Food Facts is the option for *barcoded packaged* goods later. Skip
for v1: whole ingredients are what recipes are made of.

---

## Endpoints

All read-heavy surfaces follow the existing rule — the server computes,
the clients render. In particular **the shopping-list subtraction happens
server-side**, so web and phone cannot disagree about what to buy.

```
GET/POST/PATCH/DELETE /meals/recipes
GET/POST              /meals/recipes/import        (schema.org URL parse)
GET/PUT               /meals/pantry
POST                  /meals/pantry/consume        (after cooking)
GET/POST              /meals/plan?week=            (the weekly grid)
POST                  /meals/shopping-list         (plan − pantry)
GET                   /meals/shopping-list/{id}/walmart   (deep links)
POST                  /ai/meals/suggest            (bounded, cached)
```

The AI surface follows the existing recipe exactly: bounded payload
builder, forced tool-use so the clients render cards rather than prose,
`_ai_cache_key` so the same pantry and goals never re-bill, and
`_check_and_bump_quota`.

---

## Build order

Each phase is independently useful — none is a prerequisite for the value
of the one before it.

1. **Foods + recipes + pantry CRUD.** Both surfaces. No AI, no
   suggestions. Being able to record what is in the house and what you
   cook is the foundation and is useful alone.
2. **Weekly plan + shopping list, with the household portion model.**
   This is where the real value lands: plan − pantry = list.
3. **Walmart tier 1.** Per-item search deep links, plus copy-to-clipboard
   for anyone who prefers pasting.
4. **AI suggestions.** Pantry + goals + training load + fasting state.
   Last, because it is only good once 1-3 give it real data to read.
5. **Optional:** recipe URL import; nutrition roll-up per day tied to the
   weight goal; Walmart tier 2 item-ID carts.

## What to decide before starting

- Is nutrition **tracking** wanted (calories/macros per day against a
  target), or only nutrition *awareness* for choosing meals? Tracking is
  a much larger feature and a daily logging habit; the ask does not
  clearly call for it.
- How many people in the household, and their portion factors.
- Whether recipe URL import is wanted at all, given it only ever writes
  to the private install.
