import os
import time
import requests
import datetime as dt
from typing import Dict

# -------- Config (env-driven) --------
AMADEUS_KEY = os.environ["AMADEUS_KEY"]
AMADEUS_SECRET = os.environ["AMADEUS_SECRET"]

ORIGINS = [x.strip() for x in os.environ.get("ORIGINS", "AUS,IAH,DFW").split(",") if x.strip()]
# You can set DEST to "TYO" (city) or "HND,NRT" (we loop them safely)
DEST_CODES = [x.strip() for x in os.environ.get("DEST", "TYO").split(",") if x.strip()]

ADULTS = int(os.environ.get("ADULTS", "1"))
CURRENCY = os.environ.get("CURRENCY", "USD")
MAX_PRICE_PER_PAX = float(os.environ.get("MAX_PRICE_PER_PAX", "5000"))
TRIP_LENGTH = int(os.environ.get("TRIP_LENGTH", "14"))

# Search window (default next year Jan 20 → May 10 as you had it)
year = int(os.environ.get("YEAR", str(dt.date.today().year + 1)))
DEPART_START = dt.date.fromisoformat(os.environ.get("DEPART_START", f"{year}-01-20"))
DEPART_END = dt.date.fromisoformat(os.environ.get("DEPART_END", f"{year}-05-10"))

# Only search Fri/Sat departures to limit API usage (0=Mon ... 6=Sun)
DEPART_WEEKDAYS = set(int(x) for x in os.environ.get("DEPART_WEEKDAYS", "4,5").split(","))

# Notifications
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Safety cap for requests per run (avoid blowing free tier)
MAX_REQUESTS_PER_RUN = int(os.environ.get("MAX_REQUESTS_PER_RUN", "80"))

def get_token() -> str:
    r = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": AMADEUS_KEY,
            "client_secret": AMADEUS_SECRET,
        },
        timeout=30,
    )
    if not r.ok:
        print(f"[Auth error {r.status_code}] {r.text[:500]}")
    r.raise_for_status()
    return r.json()["access_token"]

def send_alert(text: str):
    if not DISCORD_WEBHOOK:
        print("[discord] DISCORD_WEBHOOK not set; skipping alert.")
        return
    try:
        resp = requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=30)
        print(f"[discord] status={resp.status_code} body={resp.text[:300]}")
    except Exception as e:
        print(f"[discord] error: {e}")

def daterange(d1: dt.date, d2: dt.date):
    d = d1
    while d <= d2:
        yield d
        d += dt.timedelta(days=1)

def search_flights(token: str, origin: str, dest_code: str, depart: dt.date, ret: dt.date) -> Dict:
    """
    Flight Offers Search v2 — Self-Service.
    Note: No page[limit] or sort here; those params cause 400s.
    """
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": dest_code,     # single code per call
        "departureDate": depart.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": ADULTS,
        "currencyCode": CURRENCY,
        # Using API-side maxPrice keeps responses small (it's total for all pax)
        "maxPrice": int(MAX_PRICE_PER_PAX * ADULTS),
        "nonStop": "false",
    }

    # Simple retry/backoff for 429s
    for attempt in range(4):  # 1 try + up to 3 retries
        r = requests.get(url, headers=headers, params=params, timeout=40)
        if r.status_code == 429:
            wait = 2 ** attempt  # 1, 2, 4 seconds
            print(f"[Amadeus 429] backing off {wait}s...")
            time.sleep(wait)
            continue

        if not r.ok:
            print(f"[Amadeus error {r.status_code}] {r.text[:500]}")
            r.raise_for_status()

        return r.json()

    # If still 429 after retries, raise last response
    r.raise_for_status()

def summarize_offer(offer: Dict, origin: str, dest_shown: str) -> str:
    price_total = offer["price"]["total"]
    itineraries = offer.get("itineraries", [])

    def first_last_times(itin):
        dep = itin["segments"][0]["departure"]["at"][:10]
        arr = itin["segments"][-1]["arrival"]["at"][:10]
        return dep, arr

    out_dep, _ = first_last_times(itineraries[0])
    ret_dep, _ = first_last_times(itineraries[1])
    carriers = set(seg["carrierCode"] for itin in itineraries for seg in itin["segments"])
    carriers_str = ", ".join(sorted(carriers))

    return (
        f"✈️ {origin} → {dest_shown} (Tokyo)\n"
        f"Out: {out_dep}  |  Back: {ret_dep}\n"
        f"Total: {CURRENCY} {price_total} for {ADULTS} adult(s) (≤ {int(MAX_PRICE_PER_PAX*ADULTS)})\n"
        f"Carriers: {carriers_str}\n"
        f"Tip: Search these dates on Google Flights/Chase Travel to book."
    )

def main():
    token = get_token()
    requests_left = MAX_REQUESTS_PER_RUN
    best = None  # (price_float, text)

    for origin in ORIGINS:
        for dest_code in DEST_CODES:
            for d in daterange(DEPART_START, DEPART_END):
                if d.weekday() not in DEPART_WEEKDAYS:
                    continue
                if requests_left <= 0:
                    break
                rdate = d + dt.timedelta(days=TRIP_LENGTH)

                # Debug: show exactly what we're querying
                print(f"Searching {origin}->{dest_code} depart={d} return={rdate} pax={ADULTS}")

                try:
                    data = search_flights(token, origin, dest_code, d, rdate)
                except Exception as e:
                    print(f"[{origin}->{dest_code} {d}->{rdate}] Request failed: {e}")
                    continue

                requests_left -= 1
                offers = data.get("data", [])

                # Light result summary per query
                try:
                    min_total = min(float(o["price"]["total"]) for o in offers) if offers else None
                except Exception:
                    min_total = None
                print(f"[{origin}->{dest_code} {d}->{rdate}] offers={len(offers)} min_total={min_total}")

                for offer in offers:
                    try:
                        total = float(offer["price"]["total"])
                    except Exception:
                        continue
                    if total <= MAX_PRICE_PER_PAX * ADULTS:
                        summary = summarize_offer(offer, origin, dest_code)
                        if (best is None) or (total < best[0]):
                            best = (total, summary)

            if requests_left <= 0:
                break

    if best:
        send_alert(best[1])
        print("ALERT:", best[1])
    else:
        msg = "No deals under threshold this run."
        # Uncomment if you want a Discord ping even when nothing matches:
        # send_alert(msg)
        print(msg)

if __name__ == "__main__":
    main()
