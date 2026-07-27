# Production checklist (Railway)

Use this after the app is deployed and syncing.

## Must-have

- [ ] **Public domain** generated (`https://….up.railway.app`)
- [ ] **Variables set:** `HC_SYNC_API_KEY`, `HC_OPENAI_API_KEY`, `HC_OPENAI_MODEL`
- [ ] **Hevy (optional but recommended):** `HC_HEVY_API_KEY`, `HC_HEVY_AUTO_SYNC_ENABLED=true`, hour/minute
- [ ] **Volume** mounted at `/data` + `HC_DATABASE_URL=sqlite:////data/health_coach.db`  
      (without this, redeploys can wipe your DB)
- [ ] **Health Auto Export** points at `https://YOUR-DOMAIN/sync/health-auto-export` with `X-API-Key`
- [ ] **Scheduled / automatic export** in HAE (not only Manual Export)
- [ ] Open app once → **Save API key** (stays on that phone until Clear)
- [ ] First **Manual Export** 14–30 days, then confirm Home shows weight

## Speed / UX (in app)

- [x] Home loads **fast** (metrics first; AI coaching fills in after)
- [x] Coaching responses are **cached ~1 hour** so refreshes don’t re-hit OpenAI every time
- [x] Tabs: **Today / Meals / Body / Ask**

## Nice-to-have

- [ ] Railway notifications / check logs after a failed sync
- [ ] Rotate sync + OpenAI keys if they were ever pasted in chat
- [ ] Keep `$1` free credits in mind — local Mac is the fallback

## Do not

- Put secrets in GitHub
- Rely on private `.railway.internal` URLs from your phone
- Set a Custom Start Command with bare `$PORT` (breaks deploy)
