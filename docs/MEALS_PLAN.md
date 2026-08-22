# Meals, recipes, pantry and shopping — design plan

Status: **plan only, nothing built.** Tabled 2026-08-21, scope settled
2026-08-22.

The ask: a healthy-meals list with recipes, a place to record what is
already in the house, suggestions built from that, a shopping list that
reaches a Walmart cart, and a meal-prep section that handles both
single-person and family portions.

Scope settled since: **calorie tracking AND nutrition awareness, both**,
plus **allergies and medical conditions that affect diet**. The allergy
requirement changes the safety posture of the whole feature and is
treated as a hard part in its own right below.

This document records the design and — more importantly — the five
places where the obvious approach does not work, so they are not
rediscovered mid-build. Two of them are about safety rather than
correctness, and those are the ones to read first.

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

## The five hard parts

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

### 4. Allergen filtering is a safety claim, and must not be made

This is the part most likely to hurt someone, so it gets stated before
any of the pleasant parts.

An app that hides recipes containing peanuts is implicitly telling a
peanut-allergic person that what remains is safe to eat. It cannot know
that, and the gap between what it knows and what it implies is where the
harm lives:

* **Ingredient lists are not allergen labels.** USDA FoodData Central
  describes what a food IS, not what a manufacturing line also handles.
  "May contain traces of" exists on packaging precisely because the
  ingredient list is insufficient, and none of that reaches this app.
* **A recipe the user typed is only as complete as they typed it.**
  "Sauce" is one ingredient to the database and a dozen to an allergist.
* **An AI suggestion is generated text.** It can invent a dish, and it
  can omit an ingredient it did not think to mention. It must never be
  the layer standing between a user and an allergen.

**Decision: allergens are a WARNING system, never a filter that promises
safety.**

Concretely:

- Matching ingredients are **flagged prominently on the recipe**, not
  silently removed from the list. Removal hides the reason; a flag
  teaches the user which recipes to avoid and why.
- The wording never claims safety. "Contains almonds" is a statement
  about the recipe. "Safe for your allergies" is a claim about the world,
  and the app is not entitled to make it.
- Anything the app could not check says so. An imported recipe with a
  free-text ingredient it could not resolve to a food row is marked
  **unverified**, not clean.
- The AI meal suggester is given the allergen list and told to avoid
  them, and its output is **re-checked by the same deterministic matcher
  afterwards** — belt and braces, following the pattern
  `fasting_coach()` already uses for religious-fast safeguards: a prompt
  rule plus an application-layer override, because a prompt rule alone
  is a request, not a guarantee.
- A severity distinction is worth carrying: an intolerance is a bad
  evening, an anaphylactic allergy is an ambulance. The UI should not
  render them identically.

### 5. Medical conditions imply different numbers, not just different lists

"Conditions that affect diet" is not one feature. Each condition changes
*which nutrient matters*, and a tracker that only counts calories cannot
express any of them:

| Condition | What actually needs tracking |
|---|---|
| Type 2 diabetes | Carbohydrate per meal, not per day; fibre |
| Hypertension | Sodium |
| Chronic kidney disease | Potassium, phosphorus, and *limited* protein |
| Coeliac disease | Gluten as an allergen-style flag |
| High cholesterol | Saturated fat |
| IBS | FODMAP groups — which USDA does not carry |

Two consequences for the design:

1. The tracked nutrient set must be **configurable**, not a fixed
   calories/protein/carbs/fat quartet. A condition switches additional
   nutrients on.
2. **The app suggests, it does not prescribe.** Kidney disease in
   particular has targets that depend on labs and stage, and a number
   invented by a health tracker could do real harm. Conditions set what
   is *displayed and warned on*; any actual target is user-entered, ideally
   from what a clinician told them. The app should say where a target
   came from, exactly as the sleep-need work does now.

Note that IBS/FODMAP is deliberately listed as a gap rather than
promised: USDA does not carry FODMAP data, so it would need a separate
dataset and should not ship as a half-answer.

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
| `food_log` | What was eaten, when, how much. The tracking half. |
| `food_allergens` | food -> allergen tags, so matching is a join not a text search. |

Config in `user_profile.extra` (free-form JSON, no migration, matching
the established pattern): `household` members and portion factors,
dietary preferences, disliked foods, default store, `allergens` (with a
severity per entry), `conditions`, and `tracked_nutrients`.

Allergens go in config but are matched through `food_allergens` rather
than by substring. "Nut" matching "nutmeg" and missing "marzipan" is
exactly the failure mode a warning system cannot afford.

### Nutrition source: USDA FoodData Central

Public domain, lab-analysed for whole foods, bulk-downloadable. Strong
precedent in this repo: the exercise catalog is already a bundled
public-domain dataset (`data/exercises.json`, free-exercise-db,
Unlicense) with images served from `StaticFiles`. Do the same — **bundle
a filtered subset rather than calling an API at runtime**, so the feature
works offline and does not depend on an external service staying up.

Open Food Facts is the option for *barcoded packaged* goods later. Skip
for v1: whole ingredients are what recipes are made of.

### Calorie tracking, and the one thing this app can do that others cannot

Tracking needs a `food_log` and a daily target. The target is where this
differs from every other tracker.

Most apps estimate TDEE from an equation — Mifflin-St Jeor on height,
weight, age and an activity multiplier the user guesses at. This app has
something better already in the database: **observed weight trend and
measured training load**. Once intake is being logged, energy balance can
be derived from what actually happened rather than predicted from a
formula:

    TDEE ≈ mean intake − (weight change in kg × ~7700 kcal/kg) / days

That is only trustworthy over a few weeks and only while logging is
reasonably complete, so it must carry the same honesty the projection
work already does: report `confidence`, and REFUSE with a reason when
logging is too sparse or the weight trend is too noisy — the same
pattern as `derive_sleep_need`, which currently refuses on this user's
data and says why.

Until it can be derived, the target is the equation-based estimate,
clearly labelled as an estimate, and user-overridable. `analytics/energy.py`
(TD-4) already computes per-workout kcal from heart rate, so the
expenditure side of the day is partly answered.

**Awareness without obligation.** Tracking every meal is a habit most
people abandon, and a half-logged day produces a number worse than no
number — it reads as "you barely ate" rather than "you barely logged".
So: a day is marked complete or partial by the user, partial days are
excluded from any derived TDEE, and the nutrition *awareness* half —
seeing what a planned meal contains before cooking it — works with zero
logging. Awareness is the floor; tracking is opt-in on top.

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
GET/POST/DELETE       /meals/log?date=             (the tracking half)
GET                   /meals/nutrition?date=       (day roll-up vs targets)
GET/PUT               /meals/diet-profile          (allergens, conditions,
                                                    tracked nutrients)
GET                   /meals/energy-balance        (derived TDEE, or why not)
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
4. **Diet profile: allergens and conditions.** Before AI suggestions, not
   after — the suggester must never be the first thing that has to know
   about an allergy. Flags on recipes, configurable tracked nutrients.
5. **Nutrition awareness.** What a planned meal contains, against the
   tracked nutrient set. No logging required.
6. **Calorie tracking.** `food_log`, day roll-up, complete/partial days.
7. **AI suggestions.** Pantry + goals + training load + fasting state +
   the diet profile, with a deterministic allergen re-check after the
   model returns. Last, because it is only good once the rest give it
   real data to read.
8. **Derived energy balance**, once enough complete days exist to make
   it honest.
9. **Optional:** recipe URL import; Walmart tier 2 item-ID carts;
   FODMAP data from a source other than USDA.

## Decided

- **Both** calorie tracking and nutrition awareness (2026-08-22).
  Awareness is the floor and needs no logging; tracking is opt-in on top.
- **Allergens and medical conditions are in scope**, as a warning system
  rather than a safety filter — see hard part 4.

## Still to decide before starting

- Household members and their portion factors.
- Which conditions actually apply, since each one switches on a
  different nutrient rather than a generic "healthy" mode.
- Whether recipe URL import is wanted at all, given it only ever writes
  to the private install.
