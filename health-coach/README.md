# Health Coach — Personalized AI Health Intelligence Backend

Momentum is an **AI health scientist**, not another tracker.

It observes longitudinal data, forms competing hypotheses, treats life as experiments,
updates beliefs, and explains reasoning in human language — gradually building a
personalized model of one person’s physiology.

The statistical engine calculates evidence; the LLM communicates it.
Philosophy: [docs/PHILOSOPHY.md](docs/PHILOSOPHY.md).

## Version 0 success criterion

> Given today’s weight and the previous 14 days, return the most likely
> explanations and whether the plan should change.

## Core principle

```
Ingestion → Normalization → Analytics → Hypotheses → Recommendations → Explanation
```

The LLM must not invent conclusions from raw files. It only narrates
structured evidence produced by deterministic analytics.

---

## 1. Folder structure

```
health-coach/
├── data/
│   ├── raw/                 # Immutable source exports
│   │   ├── apple_health/
│   │   ├── macrofactor/
│   │   ├── hevy/
│   │   ├── garmin/
│   │   ├── scale/
│   │   ├── diet_plans/
│   │   └── synthetic/       # Sample CSV for local prototype
│   └── processed/           # Derived artifacts (gitignored)
├── src/
│   ├── api/                 # FastAPI routes
│   ├── analytics/           # Trends, hypotheses, daily summaries
│   ├── coaching/            # Recommendations + explanation stubs
│   ├── db/                  # SQLAlchemy models + session
│   ├── ingestion/           # Source-specific importers
│   ├── models/              # Pydantic request/response schemas
│   └── normalization/       # Units, source priority, mappings
├── tests/
├── notebooks/
├── scripts/
├── requirements.txt
└── README.md
```

---

## 2. Database schema (v0)

| Table | Purpose |
|-------|---------|
| `users` | Person the data belongs to |
| `source_files` | Imported file registry + checksum |
| `measurements` | Continuous metrics (weight, steps, sleep, macros…) |
| `meals` | Meal-level nutrition (future) |
| `workouts` | Workout sessions (future) |
| `exercise_sets` | Strength sets (future) |
| `daily_contexts` | Soft signals: restaurant, alcohol, cycle, notes |
| `interventions` | Deliberate experiments (future) |
| `daily_summaries` | One analytical row per day (primary analytics table) |
| `hypotheses` | Ranked explanations for a date |
| `recommendations` | Traceable actions for a date |

Preferred-source priorities (used when building summaries):

| Domain | Priority |
|--------|----------|
| Nutrition | MacroFactor |
| Weight | smart scale > manual > wearable |
| Steps | Apple Watch > Garmin > iPhone |
| Sleep | selected wearable (one source) |
| Strength | Hevy |
| Cycle | selected cycle tracker |

All raw records are kept; summaries pick one preferred source per metric.

---

## 3. Pydantic API models (v0)

- `DailySummaryResponse` — metrics for one day
- `HypothesisResult` — name, score, confidence, evidence, counterevidence
- `RecommendationItem` — action + rationale
- `WeightExplanationResponse` — summary + ranked hypotheses + recommendations
- `ImportResult` — rows imported / skipped

See `src/models/schemas.py`.

---

## 4. Synthetic sample dataset

`data/raw/synthetic/daily_metrics.csv` — ~21 days of weight, calories,
protein, fiber, sodium, steps, sleep, restaurant/alcohol flags, cycle day,
and notes. Includes intentional patterns:

- Day with restaurant + high sodium → large scale bump
- Stable calorie adherence with downward 7-day trend
- One noisy weigh-in without supporting signals

---

## 5. Milestone plan

| # | Milestone | Status |
|---|-----------|--------|
| M1 | Repo, schema, SQLite, Pydantic models | **this slice** |
| M2 | CSV import → normalize → store measurements + context | **this slice** |
| M3 | Build `daily_summaries` + 7-day weight trend | **this slice** |
| M4 | Three hypotheses: noise, water retention, calorie surplus | **this slice** |
| M5 | `GET /weight-explanation/{date}` | **this slice** |
| M6 | Apple Health / MacroFactor / Hevy importers | **Health Auto Export live sync** |
| M7 | Intervention evaluation | **basic experiments API** |
| M8 | LLM explanation layer | **multi-turn chat + philosophy prompt** |
| M9 | Evaluation set of 20–30 historical questions | later |
| M10 | Personal physiology pattern memory | **auto patterns from summaries** |

---

## Live sync (no custom iOS app)

Use **Health Auto Export** on iPhone to push Apple Health → this backend.
MacroFactor / VeSync / Garmin data reaches us once they write into Apple Health.

See [docs/HEALTH_AUTO_EXPORT.md](docs/HEALTH_AUTO_EXPORT.md).

```bash
# On your Mac (same Wi‑Fi as phone)
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --app-dir .
# Phone automation URL: http://YOUR_MAC_IP:8000/sync/health-auto-export
# AI chat UI: http://YOUR_MAC_IP:8000/chat  (needs HC_OPENAI_API_KEY in .env)
```

Deploy to Railway free try-out: [docs/RAILWAY.md](docs/RAILWAY.md).

## Quick start

```bash
cd health-coach
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Load synthetic data and build summaries
python -m scripts.bootstrap

# Run API
uvicorn src.api.main:app --reload --app-dir .

# Example
curl http://127.0.0.1:8000/weight-explanation/2026-07-20
```

## Tests

```bash
pytest -q
```

## Safety rules (enforced in coaching layer)

- No diagnosis
- Prefer trends over single weigh-ins
- Do not recommend calorie cuts from one day of scale change
- Always surface missing data and confidence
- Separate observation → hypothesis → recommendation
