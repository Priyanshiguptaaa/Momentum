# Health Auto Export → Momentum bridge

Use the existing iOS app **Health Auto Export** so you do **not** build your own app.
It reads Apple Health on your phone and POSTs JSON to our FastAPI backend.

App Store: https://apps.apple.com/us/app/health-auto-export-json-csv/id1115567069  
JSON format wiki: https://github.com/Lybron/health-auto-export/wiki/API-Export---JSON-Format

## What this gives you

| Source | How it reaches Momentum |
|--------|-------------------------|
| MacroFactor | Enable MF → Apple Health write → HAE syncs nutrition |
| VeSync / Etekcity | Enable VeSync → Apple Health → HAE syncs weight |
| Garmin / watch | Sync to Apple Health → HAE syncs steps/sleep/activity |
| Apple Health itself | HAE reads HealthKit directly |

## 1. Phone setup (data into Apple Health)

1. **MacroFactor** → More → Integrations → enable **Apple Health** (nutrition + weight).
2. **VeSync** → scale settings → **Connect to Apple Health** (weight).
3. **Garmin Connect** → settings → enable Apple Health sharing (optional).
4. Confirm recent weight/calories appear in the iPhone **Health** app.

## 2. Backend setup (on your Mac)

```bash
cd health-coach
source .venv/bin/activate

# Optional but recommended: set a sync key
cp .env.example .env
# edit HC_SYNC_API_KEY=some-long-secret

uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --app-dir .
```

Find your Mac’s LAN IP (phone must be on the same Wi‑Fi):

```bash
ipconfig getifaddr en0
```

Endpoint the phone will call:

```text
http://YOUR_MAC_IP:8000/sync/health-auto-export
```

Header:

```text
X-API-Key: <same value as HC_SYNC_API_KEY>
```

If `HC_SYNC_API_KEY` is empty, the endpoint accepts requests without a key (local-only convenience).

## 3. Health Auto Export automation

1. Install **Health Auto Export** on iPhone.
2. Grant Health read permissions (weight, dietary energy, protein, fiber, sodium, steps, sleep, workouts, alcohol if used).
3. Automations → New → type **REST API**.
4. Configure roughly:
   - **URL:** `http://YOUR_MAC_IP:8000/sync/health-auto-export`
   - **Headers:** `X-API-Key` = your secret
   - **Export format:** JSON
   - **Data:** Health Metrics (start with weight, dietary_energy, protein, fiber, sodium, step_count, sleep_analysis, active_energy)
   - **Aggregate:** Days (good for coaching summaries)
   - **Batch requests:** On
5. Save, then use **Manual Export** for the last 14–30 days to test.

Optional second automation for **Workouts**.

## 4. Verify

```bash
curl http://YOUR_MAC_IP:8000/health
# after a manual export:
curl http://YOUR_MAC_IP:8000/daily-summary/2026-07-20
curl http://YOUR_MAC_IP:8000/weight-explanation/2026-07-20
```

## Notes

- REST automations are typically a **Premium** feature of Health Auto Export.
- Phone and Mac must be on the **same Wi‑Fi** for a local IP URL. For away-from-home sync later, use a tunnel (ngrok / Cloudflare) or deploy the API.
- Opening the app occasionally helps iOS deliver background exports.
- We do **not** reverse-engineer MacroFactor; Apple Health is the supported live path.
