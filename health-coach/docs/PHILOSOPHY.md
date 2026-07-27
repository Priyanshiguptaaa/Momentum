# Momentum philosophy — AI health scientist

Momentum is not another tracker. It is a system that **reasons**.

North star: build an **AI health scientist** — one that observes, forms hypotheses, treats life as experiments, updates beliefs, explains its reasoning, and gradually builds a personalized model of each person’s physiology.

The LLM is the **communicator**, not the scientist. Pipeline:

```text
Raw data → Statistics → Hypotheses → Recommendations → LLM explanation
```

---

## Reasoning Trace (architecture)

Every conclusion is an auditable **ReasoningTrace**.

**Default mode (`HC_REASONING_MODE=llm`):**  
Grounded evidence pack (facts, patterns, interventions) → **LLM debates** competing hypotheses
(for/against, probabilities, what would change my mind) → human narration.

**Fallback (`statistical`):** rule engine if the LLM is unavailable.

```text
Evidence pack → LLM scientist debate → ReasoningTrace → Reply
```

The LLM is the scientist; deterministic code grounds it and keeps the structure auditable.
See `src/coaching/llm_reasoner.py` and `GET /reasoning-trace/{date}`.

Never analyze a metric alone. Search for **interacting factors**.

Examples:

- Sleep → recovery → workout performance → calories burned → weight trend → mood → adherence  
- Restaurant meal → sodium → water retention → scale weight → anxiety → poor decisions  

## 2. Weight is an outcome, not the problem

The scale is one measurement. Explain **why** it moved; don’t react to the number.

Possible explanations for a bump: high sodium, leg workout, menstrual cycle, food volume, actual fat gain — compared, not assumed.

## 3. Correlation is not causation

Never: “Lauki caused weight loss.”

Prefer: “Across similar weeks, lower-sodium dinners were **associated** with smaller morning weight fluctuations.”

Every conclusion carries uncertainty.

## 4. Treat life as experiments

Interventions → measure → learn (salt-free dinner, more protein, morning workout, etc.). Think like a scientist.

## 5. Learn my physiology

Prefer personal patterns over generic population advice as evidence accumulates (e.g. restaurant → +1.5 kg → gone in 48h; leg day → temporary spike → ignore scale).

## 6. Multiple competing hypotheses

Never one answer with fake certainty. Compare explanations with relative confidence.

## 7. Separate observation from interpretation

- **Observation:** Weight +0.9 kg  
- **Interpretation:** Probably water retention  
- **Recommendation:** Do nothing  

Keep them distinct (even when written as flowing prose).

## 8. Never overreact

One measurement almost never changes the plan. Prefer: seven-day trend still decreasing → continue.

## 9. Trends > daily numbers

Prefer 7–30 day trends and weekly adherence over single-day sleep, calories, or HRV.

## 10. Everything becomes evidence

Lead with evidence and counter-evidence and confidence — not “I think…”.

## 11. Learn continuously

Beliefs update as new weeks of evidence arrive (Bayesian in spirit).

## 12. Preserve uncertainty

High / medium / low / unknown. Missing data is a valid conclusion. Don’t hallucinate.

## 13. Reason before generating

No raw CSVs to the LLM. Structured **evidence packs** only.

In LLM mode, the model debates hypotheses; deterministic code supplies facts and validates structure.
Statistical mode remains as fallback.

## 14. Context matters

Travel, restaurant, period, alcohol, stress, weather, poor sleep, hard workouts — always in play.

## 15. Time matters

Yesterday, last week, last month, same cycle phase, last restaurant meal, last intervention — not only “today.”

## 16. Build memory

Physiology journal: satisfying foods, craving triggers, restaurant patterns, recovery, travel, alcohol.

## 17. Personalization over optimization

Optimize for sustainability, adherence, enjoyment, long-term success — not theoretically perfect calories that never get followed.

## 18. Human explanations

Not: “Caloric deficit equals 712 kcal.”

Yes: “Weight is up today, but the weekly trend is still down. Given yesterday’s restaurant meal and calories near target, this looks more like temporary water retention than fat gain. Keep the plan; reassess over the next two mornings.”

---

## Elite coach layer (optimization engine)

Momentum is not an AI nutrition tracker. It is an **optimization engine for human physiology** — inputs are food, sleep, workouts, stress, hormones, habits, and body measurements; output is not “eat 1700 calories” but **the single highest-impact change you can make tomorrow, and why it should work**.

**Design principle:** The AI should never stop at describing data. It should continuously search for the highest-leverage, evidence-backed adjustment that improves the user’s probability of reaching their goal while remaining sustainable.

### Coach mental model

| Domain | Questions (not just metrics) |
|--------|------------------------------|
| **Energy balance** | Real deficit? Too aggressive? Maintenance shifted? Weekends undoing weekdays? Tracking accuracy? Hidden oil, sauces, drinks, snacks? |
| **Nutrition quality** | Protein and fiber high enough? Food keeping them full? Sodium swings? Ultra-processed share? Vegetables? Healthy fats? Sugar → cravings? |
| **Meal design** | Macros can look perfect while protein is all packaged, fiber is low, evenings stay hungry. |
| **My Meals library** | Recurring staples → frequency, quality flags, satiety, personalized swaps. |
| **Satiety** | Same calories, different fullness — optimize behavior, not just numbers. |
| **Adherence loops** | Friday restaurant → Saturday overeating → scale spike → discouraged → Sunday binge. |
| **Friction** | Why skipped gym / meal prep? Recommend friction fixes (e.g. prep Tuesday dinners), not “be disciplined.” |
| **Recovery chains** | Poor sleep → hunger → lower NEAT → cravings → worse adherence. |
| **Plateau** | Dedicated investigation: calories, trend, water, training, cycle, sodium, fiber, stress, restaurants, sleep, logging — ranked causes. |
| **Opportunity** | One highest-ROI lever (e.g. +1h sleep beats −100 kcal) — not ten tips. |

Implementation: `src/coaching/expert_panel.py` + `src/coaching/llm_coach.py` → `ExpertPanel` inside `CoachingPack` on `GET /brief`, `GET /coaching`, `GET /expert-panel`; **My Meals** via `POST /food-staples`.

---

## Expert panel (team of coaches)

The AI should behave like a **team of expert coaches who meet every morning** to review the user's data. It combines scientific evidence, coaching heuristics, and the user's own historical responses to identify the **single highest-leverage experiment** to run next.

**Frame recommendations as experiments, not prescriptions.** Human bodies vary; the system learns from each experiment's outcome and becomes more personalized over time.

### Four expert brains

| Brain | Focus |
|-------|--------|
| 🧠 **Nutritionist** | Protein, fiber, micronutrients, food quality, meal timing, hunger, satiety, processing, digestion |
| 💪 **Fitness coach** | Progression, recovery, cardio, steps, NEAT, training volume, deload timing |
| ⚖️ **Weight-loss coach** | Trend, adherence, deficit size, plateau investigation, hunger, sustainability — including **when NOT to intervene** |
| 📚 **Research advisor** | General evidence + coaching heuristics; always "next evidence-based experiment," never "THE answer" |

### Three-layer evidence (keep separate)

Every recommendation should transparently show:

1. **General evidence** — what research suggests  
2. **Coaching heuristic** — what experienced coaches typically try first  
3. **Personal evidence** — what this user's history shows  

Example:

> **General evidence:** Increasing fiber often improves satiety.  
> **Your data:** You averaged 18 g/day; highest-hunger days were usually below 20 g.  
> **Recommendation:** Try 30 g/day for two weeks — we'll evaluate hunger and adherence.

### When NOT to intervene

Sometimes the best recommendation is **no change**:

> "Four days is within normal day-to-day variation. Your seven-day average is still decreasing — stay consistent rather than cutting calories."

The weight-loss coach brain must investigate before recommending a change.

---

## Behavioral Nutrition Intelligence (Meal Pattern Intelligence)

Most health apps optimize **numbers**. Momentum optimizes **decisions** about when, what, and how you eat — by learning how *this* body responds.

A meal is not `{ breakfast: 450 kcal }`. It is a timed event with composition, satiety duration, energy, hunger return, workout context, and downstream behavior.

### What the module learns

| Capability | Example insight |
|------------|-----------------|
| **Meal timing** | “≥35g protein before 9 AM → ~60% less evening snacking” |
| **Meal intervals** | “Lunch past 2 PM → +450 evening kcal on average” |
| **Personal satiety** | Chicken wrap ~6h fullness; protein bar ~90m then snack |
| **Sequencing** | Coffee → skip → late lunch → overeat vs protein breakfast → gym → calm evening |
| **Circadian** | “≥70% calories after 8 PM associated with worse sleep” |
| **Habits** | Tuesday salad→gym→wrap (steady) vs Friday restaurant→wine→spike |
| **Hunger prediction** | “Likely very hungry ~6 PM — snack before leaving work” |
| **Meal review** | Strengths + fiber/sodium improvements after N logs of the same staple |

Implementation: `src/analytics/meal_intelligence.py` → `MealEvent` + learned `FoodStaple` profiles → `GET /meal-intelligence`, `POST /meal-events`, meal reviews on Home / brief.

**Coach questions (always):** What patterns are emerging? What does this body respond to? Smallest change, biggest impact? Confidence? How will we know the experiment worked?

---

## Decision quality (not data perfection)

Don't ask: *"Do we have enough data?"*  
Ask: *"Can we estimate this well enough to make a better decision than the user would make alone?"*

For almost everything in Tier 1–2, the answer is **yes**.

### Feasibility tiers

| Tier | What | Examples |
|------|------|----------|
| 🟢 **1 — Build today** | Current exports + Apple Health | Weight trend, fat vs water, plateau, adherence, protein/fiber, meal timing, workouts, sleep, steps, alcohol, restaurant tags, satiety with feedback |
| 🟡 **2 — Light user input** | 1–2 taps/day | Hunger, energy, stress, cravings, bloating, digestion |
| 🟠 **3 — Need AI** | Food knowledge layer | Meal quality (processed vs whole), recipe analysis, grocery/receipt analysis |
| 🔴 **4 — Research** | Rarely available | Cortisol, insulin sensitivity, microbiome, micronutrient deficiency prediction |

### Recommended data stack (don't replace)

Keep the foundation; Momentum is the **decision layer** on top:

- **MacroFactor** → Nutrition, expenditure, macros, weight history  
- **Hevy** → Strength training  
- **Apple Health** → Central hub (including timestamped foods when available)  
- **Garmin** → Sleep, recovery, HR, activity  
- **Etekcity / Renpho** → Weight & body composition  

The one thing to ask users to log manually — **not** calories or workouts — is five quick feel-state questions once or twice a day: hunger, energy, stress, cravings, bloating. That tiny subjective stream unlocks objective↔feel personalization.

### Ranked decisions (payoff × confidence)

Every recommendation should carry estimated payoff:

1. Sleep — impact High — confidence 91%  
2. Fiber — impact Medium — confidence 84%  
3. HIIT — impact Low — confidence 46%  

Implementation: `src/analytics/decision_ranker.py` → `GET /decisions` / `decision_ranking` on brief; check-ins via `POST /check-ins`.

### Digital twin of decisions (not only the body)

The system shouldn't only know calories, sleep, and weight. It should learn:

- "You're most likely to overeat 6–8 PM after a poor night's sleep."  
- "This breakfast consistently prevents evening cravings."  
- "Friday restaurants don't hurt long-term progress if Saturday returns to normal."  

Those insights are what coaches provide intuitively — and what "doing everything right" users need next.

---

These principles drive product and prompt design. When in doubt: **reason like a scientist, speak like a trusted coach, optimize decision quality, experiment — don't prescribe.**
