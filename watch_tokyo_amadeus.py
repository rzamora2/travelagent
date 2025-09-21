import os
import requests
import datetime as dt
from typing import List, Dict

# -------- Config (env-driven) --------
AMADEUS_KEY = os.environ["AMADEUS_KEY"]
AMADEUS_SECRET = os.environ["AMADEUS_SECRET"]

ORIGINS = os.environ.get("ORIGINS", "AUS,IAH,DFW").split(",")
DEST = os.environ.get("DEST", "TYO")  # NOTE: Amadeus expects one code; comma will 400. Use "TYO" or loop.
ADULTS = int(os.environ.get("ADULTS", "1"))
CURRENCY = os.environ.get("CURRENCY", "USD")
MAX_PRICE_PER_PAX = float(os.environ.get("MAX_PRICE_PER_PAX", "5000"))
TRIP_LENGTH = int(os.environ.get("TRIP_LENGTH", "14"))

# Search window
year = int(os.environ.get("YEAR", str(dt.date.today().year + 1)))
DEPART_START = dt.date.fromisoformat(os.environ.get("DEPART_START", f"{year}-01-20"))
DEPART_END = dt.date.fromisoformat(os.environ.get("DEPART_END", f"{year}-05-10"))

# Weekdays to search (0=Mon ... 6=Sun)
DEPART_WEEKDAYS = set(int(x) for x in os.environ.get("DEPART_WEEKDAYS", "4,5").split(","))

# Notifications
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")

# Safety cap
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

def search_flights(token: str, origin: str, depart: dt.date, ret: dt.date) -> Dict:
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": DEST,     # NOTE: must be a single code; comma-separated will error
        "departureDate": depart.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": ADULTS,
        "currencyCode": CURRENCY,
        # Using API-side maxPrice keeps replies small; okay to keep for now
        "maxPrice": int(MAX_PRICE_PER_PAX * ADULTS),  # total for all pax
        "nonStop": "false",
        "page[limit]": 5,
        "sort": "price"
    }
    r = requests.get(url, headers=headers, params=params, timeout=40)

    if not r.ok:
        # >>> Added: print raw Amadeus error for visibility
        print(f"[Amadeus error {r.status_code}] {r.text[:500]}")
        r.raise_for_status()

    return r.json()

def summarize_offer(offer: Dict, origin: str) -> str:
    price_total = offer["price"]["total"]
    itineraries = offer.get("itineraries", [])
    def first_last_times(itin):
        dep = itin["segments"][0]["departure"]["at"][:10]
        arr = itin["segments"][-1]["arrival"]["at"][:10]
        return dep, arr
    out_dep, out_arr = first_last_times(itineraries[0])
    ret_dep, ret_arr = first_last_times(itineraries[1])
    carriers = set(seg["carrierCode"] for itin in itineraries for seg in itin["segments"])
    carriers_str = ", ".join(sorted(carriers))
    return (
        f"✈️ {origin} → TYO (Tokyo)\n"
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
        for d in daterange(DEPART_START, DEPART_END):
            if d.weekday() not in DEPART_WEEKDAYS:
                continue
            if requests_left <= 0:
                break
            rdate = d + dt.timedelta(days=TRIP_LENGTH)

            # >>> Added: show exactly what we're querying
            print(f"Searching {origin}->{DEST} depart={d} return={rdate} pax={ADULTS}")

            try:
                data = search_flights(token, origin, d, rdate)
            except Exception as e:
                # >>> Added: log the failure so we see why
                print(f"[{origin} {d}->{rdate}] Request failed: {e}")
                continue

            requests_left -= 1
            offers = data.get("data", [])
            # >>> Added: light result summary per query
            try:
                min_total = min(float(o["price"]["total"]) for o in offers) if offers else None
            except Exception:
                min_total = None
            print(f"[{origin} {d}->{rdate}] offers={len(offers)} min_total={min_total}")

            for offer in offers:
                try:
                    total = float(offer["price"]["total"])
                except Exception:
                    continue
                if total <= MAX_PRICE_PER_PAX * ADULTS:
                    summary = summarize_offer(offer, origin)
                    if (best is None) or (total < best[0]):
                        best = (total, summary)

        if requests_left <= 0:
            break

    if best:
        send_alert(best[1])
        print("ALERT:", best[1])
    else:
        msg = "No deals under threshold this run."
        # Optional: ping Discord even when no deals so you know the job finished
        # send_alert(msg)
        print(msg)

if __name__ == "__main__":
    main()
