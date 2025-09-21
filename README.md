# Tokyo Flight Watcher (Amadeus)

Watches roundtrip fares for **AUS/IAH/HOU/DFW/DAL → Tokyo (TYO)** around **September 2026** for **2 adults** and alerts you if total price ≤ **$3000** (i.e., **≤ $1500 per person**).

Runs on **GitHub Actions (free)** twice per week to stay under Amadeus’ free tier (500 requests/month). Sends alerts to **Telegram** and/or **Discord**.

---

## 1) Get credentials (free)

- **Amadeus Self-Service** → create an app and get `client_id` and `client_secret`: https://developers.amadeus.com/
- **Telegram** (optional): create a bot with `@BotFather` → get `BOT_TOKEN`; get your `CHAT_ID` via `@userinfobot` or the `getUpdates` API.
- **Discord** (optional): create a **Webhook URL** in your server.

---

## 2) Files

- `watch_tokyo_amadeus.py` – the watcher script
- `.github/workflows/amadeus_tokyo_watcher.yml` – the scheduler

---

## 3) Add GitHub Action secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

Required:
- `AMADEUS_KEY` – your Amadeus client_id
- `AMADEUS_SECRET` – your Amadeus client_secret

Optional (choose at least one for alerts):
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT`
- `DISCORD_WEBHOOK`

---

## 4) Schedule & limits

- Default schedule: **Tue & Sat 15:00 UTC**.
- Default search:
  - Origins: `AUS,IAH,HOU,DFW,DAL`
  - Destination: `TYO`
  - Trip length: 14 nights
  - Window: 2026-08-20 → 2026-10-10
  - Depart days: Friday or Saturday (can change via `DEPART_WEEKDAYS`)
  - Max price per person: 1500 USD
- Safety cap: `MAX_REQUESTS_PER_RUN=80`

Tweak any of these as **env vars** inside the workflow.

---

## 5) Why no booking links?

Amadeus’ test/free tier doesn’t provide a direct booking deep link. The alert includes **exact dates and airlines**; copy those into **Google Flights** or **Chase Travel** to book.

---

## 6) Test locally

```bash
pip install requests
export AMADEUS_KEY=xxx AMADEUS_SECRET=yyy
python watch_tokyo_amadeus.py
```

Add optional env for testing:
```
export TELEGRAM_TOKEN=...
export TELEGRAM_CHAT=...
export DISCORD_WEBHOOK=...
```

---

## 7) Customize

- Search different months: change `YEAR`, `DEPART_START`, `DEPART_END`.
- Different trip length: change `TRIP_LENGTH`.
- More/less frequent runs: edit the cron in the workflow.
- Different origins/dests: change `ORIGINS`, `DEST`.
