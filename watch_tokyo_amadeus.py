import os
import requests
import datetime as dt
from typing import List, Dict

# -------- Config (env-driven) --------
AMADEUS_KEY = os.environ["AMADEUS_KEY"]
AMADEUS_SECRET = os.environ["AMADEUS_SECRET"]

ORIGINS = os.environ.get("ORIGINS", "AUS,IAH,DFW").split(",")
DEST = os.environ.get("DEST", "HND,NRT")  # Tokyo area (HND/NRT)
ADULTS = int(os.environ.get("ADULTS", "1"))
CURRENCY = os.environ.get("CURRENCY", "USD")
MAX_PRICE_PER_PAX = float(os.environ.get("MAX_PRICE_PER_PAX", "5000"))
TRIP_LENGTH = int(os.environ.get("TRIP_LENGTH", "14"))

# Search window (default: late Aug to early Oct next year to cover September trips)
year = int(os.environ.get("YEAR", str(dt.date.today().year + 1)))
DEPART_START = dt.date.fromisoformat(os.environ.get("DEPART_START", f"{year}-01-20"))
DEPART_END = dt.date.fromisoformat(os.environ.get("DEPART_END", f"{year}-05-10"))

# Only search Fri/Sat departures to limit API usage (change if you want daily)
DEPART_WEEKDAYS = set(int(x) for x in os.environ.get("DEPART_WEEKDAYS", "4,5").split(","))  # 0=Mon ... 6=Sun

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
    r.raise_for_status()
    return r.json()["access_token"]

def send_alert(text: str):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT, "text": text, "disable_web_page_preview": True},
                timeout=30,
            )
        except Exception:
            pass
    if DISCORD_WEBHOOK:
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": text}, timeout=30)
        except Exception:
            pass

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
        "destinationLocationCode": DEST,
        "departureDate": depart.isoformat(),
        "returnDate": ret.isoformat(),
        "adults": ADULTS,
        "currencyCode": CURRENCY,
        # Amadeus supports maxPrice, but it's total (all pax)
        "maxPrice": int(MAX_PRICE_PER_PAX * ADULTS),
        "nonStop": "false",
        "page[limit]": 5,
        "sort": "price"
    }
    r = requests.get(url, headers=headers, params=params, timeout=40)
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
    # No deeplink available in Amadeus test; advise searching exact dates
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
            try:
                data = search_flights(token, origin, d, rdate)
            except requests.HTTPError as e:
                # Skip on errors to keep run alive
                continue
            requests_left -= 1
            offers = data.get("data", [])
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
        print("No deals under threshold this run.")

if __name__ == "__main__":
    main()
