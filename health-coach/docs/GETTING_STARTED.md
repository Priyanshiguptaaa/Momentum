# How to use Momentum (simple guide)

Momentum is **not** another calorie tracker. It reads your existing health data and coaches you — what’s going on, what to try next, and why.

---

## One-time setup (about 15–20 minutes)

### A. Get data into Apple Health

| App | What to turn on |
|-----|-----------------|
| **MacroFactor** | More → Integrations → **Apple Health** (food + weight) |
| **Scale (VeSync / Etekcity / Renpho)** | Connect scale → **Apple Health** |
| **Garmin / Apple Watch** | Share sleep, steps, activity with **Apple Health** |
| **Hevy** (optional) | Share workouts if available |

Open the iPhone **Health** app and confirm recent weight and calories show up.

### B. Push Apple Health → Momentum

1. Install **[Health Auto Export](https://apps.apple.com/us/app/health-auto-export-json-csv/id1115567069)** (REST automations usually need Premium).
2. Allow Health permissions: weight, dietary energy, protein, fiber, sodium, steps, sleep, active energy, workouts.
3. Create an automation → **REST API**:
   - **URL (cloud):** `https://YOUR-RAILWAY-URL.up.railway.app/sync/health-auto-export`
   - **URL (local Mac):** `http://YOUR-MAC-IP:8000/sync/health-auto-export`
   - **Header:** `X-API-Key` = same secret as `HC_SYNC_API_KEY` in Railway / `.env`
   - **Format:** JSON  
   - **Aggregate:** Days  
   - **Metrics:** weight, dietary energy, protein, fiber, sodium, steps, sleep, active energy  
4. Tap **Manual Export** once for the last **14–30 days** (first fill).

Detailed HAE steps: [HEALTH_AUTO_EXPORT.md](HEALTH_AUTO_EXPORT.md) · Railway: [RAILWAY.md](RAILWAY.md)

### C. Open Momentum

1. Go to `https://YOUR-RAILWAY-URL.up.railway.app` (or `http://YOUR-MAC-IP:8000`).
2. Tap **⚙** → paste your **sync API key** → Save.
3. Home should load your brief (weight, coaching, decisions).

---

## Daily / weekly use

| When | What to do |
|------|------------|
| **Automatic** | Keep logging food in MacroFactor, weigh in, wear your watch. Apple Health fills; HAE syncs. |
| **Open Momentum** | Check **Home** (brief + decision ranking) or **Ask** a question. |
| **1–2× per day** | Tap **How do you feel?** (hunger / energy / stress / cravings / bloating) — this is the main *manual* thing. |
| **When you eat a usual meal** | Add it under **My Meals**, then **Log today** with how long you stayed full. |
| **When coaching suggests an experiment** | Tap **Start this experiment** and run it for ~1–2 weeks. |

You do **not** re-enter calories or workouts in Momentum. Those come from your stack.

---

## When do I manually update / export?

| Situation | Action |
|-----------|--------|
| **First setup** | HAE **Manual Export** last 14–30 days |
| **Cloud DB looks empty** | Manual Export again to Railway URL |
| **Data looks stale** | Open Health Auto Export → Manual Export (or wait for scheduled automation) |
| **Away from home (local Mac only)** | Use **Railway URL** instead of Mac IP, or turn Mac + same Wi‑Fi on |
| **Automation didn’t fire** | iOS is flaky — Manual Export fixes it; open HAE occasionally |
| **Calorie target** | Leave **Use auto** (from your body). Override in ⚙ only if you really want a fixed number |
| **Feelings / satiety** | Manual check-ins and meal logs — apps don’t capture these well |

**Rule of thumb:**  
- **Automatic:** weight, food, sleep, steps  
- **Manual (quick):** check-ins + meal satiety + starting experiments  

---

## What each Home section means

- **Expert panel / next experiment** — one highest-leverage thing to try (or “stay the course”)
- **Decision ranking** — options ordered by impact × confidence  
- **Hunger forecast** — likely evening hunger based on today’s meals  
- **Meal patterns / reviews** — what *your* meals do for fullness and snacking  
- **My Meals** — your recurring foods (library), not a full food diary  
- **Ask** — chat with evidence from your data  

---

## Your data stack (keep these)

```
MacroFactor  → food / macros / weight history
Scale        → morning weight
Watch/Garmin → sleep, steps, activity
Hevy         → lifting (optional)
Apple Health → hub
Health Auto Export → sends hub data to Momentum
Momentum     → coaching layer
```

---

## Quick troubleshooting

| Problem | Fix |
|---------|-----|
| “Save API key” / empty Home | Paste `HC_SYNC_API_KEY` in ⚙ |
| No weight / calories | Check Health app; then HAE Manual Export |
| Sync fails on phone | URL must be HTTPS (Railway) or same Wi‑Fi + Mac IP; header `X-API-Key` exact |
| Coaching feels generic | Add check-ins + 3–5 My Meals with satiety logs |
| Railway down / credits | Run locally: see README quick start |

---

## Minimal routine (recommended)

1. Live normally in MacroFactor + scale + watch.  
2. Once a day: open Momentum → glance at **#1 decision** → optional 30-second check-in.  
3. Once a week: Ask *“Why have I plateaued?”* or *“What’s my highest-leverage change?”*  
4. Manual Export in HAE only when data looks behind.
