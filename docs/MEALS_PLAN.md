# Meals, recipes, pantry and shopping — design plan

Status: **plan only, nothing built.** Tabled 2026-08-21, scope settled
2026-08-22.

The ask: a healthy-meals list with recipes, a place to record what is
already in the house, suggestions built from that, a shopping list that
reaches a Walmart cart, and a meal-prep section that handles both
single-person and family portions.

Scope settled 2026-08-22: **calorie tracking and nutrition awareness,
both**. Cooking for one, so the household portion model is cut. No
allergies, so the allergen system is not built. One condition — gall
bladder removed — which makes **fat per meal** the nutrient that matters,
and per-meal rather than per-day is the whole point of it. Logging will
be intermittent, and that is designed for rather than worked around.

This document records the design and — more importantly — the places
where the obvious approach does not work, so they are not
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

## The hard parts

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

### 3. Portions — CUT. Cooking for one.

The original plan built a household model: named members, per-person
portion factors, per-ingredient linear/sublinear/fixed scaling so that a
recipe scaled 4x did not also get 4x the salt.

**None of it is needed.** Confirmed 2026-08-22: single person, cooking
for one.

What survives is much smaller. A recipe has a `servings` count and meal
prep asks "how many containers", which is a plain multiplier on a recipe
already sized for one or two. The sublinear-scaling machinery only earns
its keep at 4x and above, and that case no longer exists.

Recorded rather than deleted because the reasoning was sound and would
apply immediately if this ever cooked for a household — but building it
now would be a subsystem serving nobody, which is the same mistake the
teardown backlog kept surfacing elsewhere.

### 4. Allergens — not needed here, and the reasoning is kept anyway

Confirmed 2026-08-22: no allergies or intolerances. So the allergen
warning system is **not built**.

The reasoning is kept because it decides how it would be built if that
ever changes, and because it is the kind of thing that gets added
casually later:

An app that hides recipes containing peanuts is implicitly telling a
peanut-allergic person that what remains is safe to eat. It cannot know
that. Ingredient data describes what a food IS, not what a production
line also handles — "may contain traces of" exists on packaging precisely
because the ingredient list is insufficient — and a user-typed recipe is
only as complete as they typed it. So allergens would be a **warning
system, never a filter that promises safety**: matches flagged on the
recipe rather than silently removed, anything unresolvable marked
*unverified* rather than clean, wording that describes the recipe
("contains almonds") rather than making a claim about the world ("safe
for you"), and any AI suggestion re-checked afterwards by a deterministic
matcher — the layered pattern `fasting_coach()` already uses, because a
prompt rule is a request rather than a guarantee.

### 5. The condition here is a cholecystectomy, and it is a PER-MEAL limit

Confirmed 2026-08-22: gall bladder removed. No allergies, no other
conditions. That collapses hard part 4's allergen system to a stub and
makes this the one that matters.

**Why it is per-meal and not per-day.** The gall bladder stores and
concentrates bile and releases it as a bolus when a fatty meal arrives.
Without it, bile drips continuously into the small intestine instead. The
total daily capacity is not really the constraint — the constraint is how
much fat turns up *at once*, because a large single load has no
concentrated bile waiting for it.

So the tracked nutrient is **fat per meal**, not fat per day. A day
totalling 70 g spread evenly across four meals and a day where 60 g of
that arrives at dinner are the same number and completely different
experiences, and a tracker that only shows the daily total cannot tell
them apart.

This is the same shape as the diabetes case the earlier draft used as its
example — carbohydrate per meal rather than per day — which is a useful
confirmation that per-meal targets were the right thing to design for
rather than a special case.

**What the app must not do.** It must not invent a gram threshold.
Tolerance after cholecystectomy varies widely between people and commonly
improves over months, so a number this app made up could be wrong in
either direction. The design position is unchanged and now load-bearing:
the app tracks and displays fat per meal, flags meals that are unusually
high *relative to the user's own logged history*, and any absolute target
is user-entered — ideally whatever a clinician actually said. As
elsewhere in this codebase, the app reports where a number came from.

Worth surfacing but not enforcing: fat-soluble vitamins (A, D, E, K)
depend on fat absorption, so if the tracked nutrient set is being made
configurable anyway, those are cheap to include as awareness.

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

Config in `user_profile.extra` (free-form JSON, no migration, matching
the established pattern): dietary preferences, disliked foods, default
store, `tracked_nutrients`, and any user-entered per-meal targets.

### Nutrition source: USDA FoodData Central

Public domain, lab-analysed for whole foods, bulk-downloadable. Strong
precedent in this repo: the exercise catalog is already a bundled
public-domain dataset (`data/exercises.json`, free-exercise-db,
Unlicense) with images served from `StaticFiles`. Do the same — **bundle
a filtered subset rather than calling an API at runtime**, so the feature
works offline and does not depend on an external service staying up.

Open Food Facts covers *barcoded packaged* goods and is **phase 2, not
cut**. Confirmed 2026-08-22: roughly half the diet is packaged. USDA
still goes first because recipes are made of whole ingredients, but
without barcode scanning, logging packaged food means typing — which is
precisely the friction that ends intermittent logging for good. Add it
once the log exists and the friction is measurable rather than
predicted.

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

**Intermittent logging is the design assumption, not a failure mode.**
Confirmed 2026-08-22: logging will be inconsistent. That is a
requirement, not a caveat, and it rules out the pattern most trackers
use — streaks, "you missed a day", a dashboard that degrades into
red the moment you stop.

Concretely:

- A day is marked **complete or partial**, and partial days are excluded
  from anything derived. A half-logged day reads as "you barely ate"
  rather than "you barely logged", which is worse than no number.
- Gaps are shown as gaps. No interpolation, no zero-filling — the same
  rule the rest of this codebase already follows for a day the watch was
  not worn.
- Nothing nags. No streak, no completion percentage, no notification for
  an unlogged meal.
- The nutrition *awareness* half works with **zero** logging: seeing what
  a planned meal contains before cooking it needs a recipe, not a log.
  Awareness is the floor; the log is opt-in on top and can lie fallow for
  months without the feature becoming useless.
- Per-meal fat (hard part 5) is the one thing worth logging even
  sporadically, because a single meal is the unit of interest — you do
  not need a complete week to learn that a particular dinner was a
  problem.

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
GET/PUT               /meals/diet-profile          (tracked nutrients,
                                                    per-meal targets)
GET                   /meals/energy-balance        (derived TDEE, or why not)
POST                  /ai/meals/suggest            (bounded, cached)
```

The AI surface follows the existing recipe exactly: bounded payload
builder, forced tool-use so the clients render cards rather than prose,
`_ai_cache_key` so the same pantry and goals never re-bill, and
`_check_and_bump_quota`.

---

## Build order

Each phase is independently useful. Sized for one person who logs
sometimes, not for a household that logs daily.

1. **Foods + recipes + pantry.** Both surfaces. Foods seeded from a
   bundled USDA subset. No AI, no logging. Being able to record what is
   in the house and what you cook is the foundation and is useful alone.
2. **Nutrition awareness + per-meal fat.** What a planned meal contains,
   with fat shown per meal rather than per day. Needs no logging at all,
   and is the piece that actually addresses the cholecystectomy.
3. **Weekly plan + shopping list.** Plan minus pantry equals list,
   computed server-side. No portion model — servings and container
   counts only.
4. **Walmart tier 1.** Per-item search deep links plus copy-to-clipboard.
5. **Food log.** Complete/partial days, gaps shown as gaps, nothing that
   nags. Designed to survive months of disuse.
6. **AI suggestions.** Pantry + goals + training load + fasting state +
   per-meal fat. Last, because it is only good once the rest give it real
   data to read.
7. **Barcode scanning** via Open Food Facts, once the log exists and the
   typing friction is measurable.
8. **Derived energy balance**, once enough complete days exist to make it
   honest — and refusing with a reason until then.
9. **Weekend component prep planner** (MEAL-9, shipped v0.26.0). Batch
   cooking for the week ahead, sized to computed energy and protein
   targets, with a shopping list built from the components.

### 9. Why the prep planner is components rather than seven dinners

This was the one design decision in the whole meals feature where the
obvious implementation is actively worse than the alternative, so the
reasoning is worth recording.

A conventional meal-prep planner produces a grid: one named meal per day,
each cooked separately or portioned into its own container. It demos
beautifully and it fails in week two, for a reason that has nothing to do
with the software. Eat out on Wednesday and the grid is broken —
Wednesday's container is now a science experiment, and Thursday assumed
you had already eaten it. The user is now behind a plan they cannot catch
up on, and the rational move is to delete it.

Component batch cooking inverts the unit of work. You cook four to six
*parts* at the weekend — a protein, a grain, a tray of roast vegetables,
a sauce — and assemble them into different meals through the week. A
missed day does not break anything. It leaves portions in the fridge, and
the app's job is to say so: `leftover_ledger` compares portions cooked
against portions the live plan consumes, so skipping Wednesday produces
"two portions of chicken spare, Thursday's bowl still works on Saturday"
rather than silent drift away from a plan nobody is following any more.

Three consequences that are load-bearing:

- **`skipped` and `eating_out` are first-class outcomes, not failures.**
  There is no adherence score, no completion percentage, no streak. A
  test asserts those words do not appear in the module.
- **Variety comes from assembly, not from more cooking.** The same
  chicken and rice becomes a burrito bowl, a stir-fry, a salad and a wrap
  depending on sauce and what is added fresh. Otherwise the feature just
  prescribes the same container five times, which is the *other* reason
  people quit meal prep.
- **Cooked food has a shelf life and the planner checks it.** Protein
  four days, grain and vegetables five, sauce seven. A language model
  will assign day-five chicken cheerfully, because the grid still looks
  balanced.

### The AI in this phase proposes, it does not calculate

Every other AI surface in this app narrates observations, and some of
them accept a model estimate and then re-judge it (the suggestion card
asks for `est_fat_g`). The prep planner does not, and the tool schema has
no nutrition field at all.

The difference is what the output is *for*. A suggestion card describes
one hypothetical meal, and a rough estimate is honest as a rough
estimate. A prep plan is a week of instructions aimed at a deliberate
calorie deficit, rendered as a wall of numbers — and a wall of numbers a
model made up looks exactly as authoritative as a real one. A 20% error
does not stay a 20% error; it compounds across fifteen meals into a plan
that does the opposite of what it claims to do.

So the model returns a `food_search` term per component — a plain
ingredient name, no brand, no cooking method — and the server resolves it
through the same catalog search the food pickers use. The plan's chicken
is the food log's chicken, and every gram, calorie and protein figure is
computed from the catalog by `analytics/prep.py`.

## Decided

All confirmed 2026-08-22.

| Question | Answer | Consequence |
|---|---|---|
| Who eats | Just me | Household/portion model **cut** |
| Allergies | None | Allergen warning system **not built** |
| Condition | Gall bladder removed | Track **fat per meal**, target user-entered |
| Logging | Intermittent | Gaps are a requirement, not a failure mode |
| Food type | Half packaged | USDA first, barcodes phase 2 rather than cut |

## Still open

- Whether the prep planner's targets should switch from the Mifflin-St
  Jeor estimate to a derivation from observed intake and weight change
  once enough complete food-log days exist. `target_basis` is already
  stored per plan so the two can be told apart in hindsight; the open
  question is how many complete days is enough for the observed figure to
  beat the equation rather than just be noisier.
- Whether recipe URL import is wanted at all, given it only ever writes
  to the private install.
- Whether to surface fat-soluble vitamins (A, D, E, K) as awareness,
  since fat absorption is the mechanism in play and the nutrient set is
  configurable anyway.
- Whether the per-meal fat flag should be relative to logged history from
  the start, or wait until there is enough history for "unusually high"
  to mean anything.
