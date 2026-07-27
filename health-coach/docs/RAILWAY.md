# Deploy to Railway (free try-out)

Use Railway’s **For trying things out** plan ($1 credits, 0.5 GB RAM, 0.5 GB volume).

## 1. Create project

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub (this repo) **or** empty project + local `railway up` from `health-coach/`.
2. Root directory / service path: `health-coach` (where the Dockerfile lives).
3. Add a **Volume** mounted at `/data` (uses the 0.5 GB storage allotment).

## 2. Environment variables

Set these in Railway → Variables (do not commit secrets):

```text
HC_SYNC_API_KEY=<same key as Health Auto Export>
HC_OPENAI_API_KEY=<your OpenAI key>
HC_OPENAI_MODEL=gpt-4o-mini
HC_DATABASE_URL=sqlite:////data/health_coach.db
HC_DEFAULT_USER_EMAIL=demo@healthcoach.local
HC_DEFAULT_USER_NAME=Demo User
HC_CALORIE_TARGET=1700
```

`HC_CALORIE_TARGET` is only a **seed default**. Change your real target in the app (⚙ → Daily calorie target) or `PUT /preferences`. It is stored per user in the database.

`PORT` is provided by Railway automatically.

## 3. After deploy

Public URL example: `https://YOUR_SERVICE.up.railway.app`

| Use | URL |
|-----|-----|
| Health check | `GET /health` |
| Chat UI | `https://YOUR_SERVICE.up.railway.app/chat` |
| HAE sync | `https://YOUR_SERVICE.up.railway.app/sync/health-auto-export` |

In Health Auto Export, set the sync URL to the HTTPS sync endpoint and keep header `X-API-Key`.

In chat, paste the same API key once (saved in sessionStorage).

## 4. Data

Cloud SQLite starts empty. Run Manual Export from the phone against the Railway URL to populate, or copy `data/processed/health_coach.db` onto the volume once.

## 5. Credits

If the $1 monthly credits run out, the service stops until next period or you upgrade. Local Mac + Wi‑Fi remains a fallback (`uvicorn` on `:8000`).
