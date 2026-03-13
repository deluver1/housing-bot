"""
NYC Housing Connect Lottery Monitor Bot
Runs as a web service on Render.com with background checking loop
"""
import requests
import json
import time
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
CHECK_INTERVAL_SECONDS = 300
HC_API_URL = "https://a806-housingconnectapi.nyc.gov/HPDPublicAPI/api/Lottery/SearchLotteries"
HC_SEARCH_BODY = {
    "UnitTypes": [], "NearbyPlaces": [], "NearbySubways": [], "Amenities": [],
    "Applied": None, "HPDUserId": None, "Boroughs": [], "Neighborhoods": [],
    "HouseholdSize": None, "Income": "", "HouseholdType": 1, "OwnerTypes": [],
    "PreferanceTypes": [], "LotteryTypes": [], "Min": None, "Max": None, "RentalSubsidy": None
}
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_lotteries.json")

last_check = {"time": None, "active": 0, "new": 0, "seen": 0}


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN:
        print("No TELEGRAM_BOT_TOKEN set", flush=True)
        return False
    url = "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_BOT_TOKEN)
    success = True
    for chat_id in TELEGRAM_CHAT_IDS:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if not resp.ok:
                print("[ERROR] Telegram send to {}: {} {}".format(chat_id, resp.status_code, resp.text), flush=True)
                success = False
        except Exception as e:
            print("[ERROR] Telegram send to {}: {}".format(chat_id, e), flush=True)
            success = False
    return success


def fetch_active_lotteries():
    try:
        resp = requests.post(HC_API_URL, json=HC_SEARCH_BODY, headers={"Content-Type": "application/json"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        all_lotteries = []
        for lot in data.get("rentals", []):
            lot["_type"] = "Rental"
            all_lotteries.append(lot)
        for lot in data.get("sales", []):
            lot["_type"] = "Sale"
            all_lotteries.append(lot)
        return all_lotteries
    except Exception as e:
        print("[ERROR] Fetch: {}".format(e), flush=True)
        return []


def format_lottery(lot):
    NL = chr(10)
    lid = lot.get("lotteryId", "?")
    name = (lot.get("lotteryName") or "Unknown").strip()
    lot_type = lot.get("_type", "?")
    borough = (lot.get("borough") or "?").strip()
    end_date = (lot.get("lotteryEndDate") or "")[:10]
    end_in = lot.get("endIn", "?")
    address = ""
    zipcode = ""
    markers = lot.get("markers") or []
    if markers:
        m = markers[0]
        address = (m.get("address") or "").strip()
        zipcode = (m.get("zip") or "").strip()
    neighborhood = (lot.get("neighborhood") or "").strip()
    units = lot.get("units", "?")
    unit_parts = []
    for val, label in [(lot.get("studios"), "Studio"), (lot.get("oneBR"), "1BR"),
                       (lot.get("twoBR"), "2BR"), (lot.get("threeBR"), "3BR"),
                       (lot.get("fourBR"), "4BR")]:
        if val:
            unit_parts.append("{}x {}".format(val, label))
    unit_breakdown = ", ".join(unit_parts) if unit_parts else "N/A"
    rents = (lot.get("rents") or "").strip()
    prices = (lot.get("prices") or "").strip()
    min_income = lot.get("minIncome")
    max_income = lot.get("maxIncome")
    income_str = ""
    if min_income and max_income:
        income_str = "${:,} - ${:,}".format(int(min_income), int(max_income))
    elif max_income:
        income_str = "up to ${:,}".format(int(max_income))
    trains = (lot.get("trains") or "").strip()
    link = "https://housingconnect.nyc.gov/PublicWeb/details/{}".format(lid)
    parts = []
    parts.append("\U0001f3e0 <b>NEW LOTTERY!</b>")
    parts.append("")
    parts.append("<b>{}</b>".format(name))
    if address:
        parts.append("\U0001f4cd {} | {}, {}".format(address, borough, zipcode))
    else:
        parts.append("\U0001f4cd {}".format(borough))
    if neighborhood:
        parts.append("\U0001f3d8 {}".format(neighborhood))
    parts.append("\U0001f3d7 Type: {}".format(lot_type))
    parts.append("\U0001f3e2 Units: {} ({})".format(units, unit_breakdown))
    if rents:
        parts.append("\U0001f4b5 Rents: ${}".format(rents.replace(",", ", $")))
    if prices:
        parts.append("\U0001f4b5 Prices: ${}".format(prices.replace(",", ", $")))
    if income_str:
        parts.append("\U0001f4b0 Income: {}".format(income_str))
    parts.append("\U0001f4c5 Deadline: {} ({} days left)".format(end_date, end_in))
    if trains:
        parts.append("\U0001f687 Trains: {}".format(trains))
    parts.append("")
    parts.append('<a href="{}">APPLY HERE</a>'.format(link))
    return NL.join(parts)


def check_and_notify():
    global last_check
    seen = load_seen()
    first_run = len(seen) == 0
    lotteries = fetch_active_lotteries()
    if not lotteries:
        print("[{}] No lotteries fetched".format(datetime.now()), flush=True)
        return

    if first_run:
        print("First run - saving {} lotteries silently".format(len(lotteries)), flush=True)
        for lot in lotteries:
            lid = str(lot.get("lotteryId", ""))
            if lid:
                seen.add(lid)
        save_seen(seen)
        send_telegram("\u2705 <b>Housing Connect Bot started!</b>" + chr(10) + "Monitoring {} active lotteries...".format(len(lotteries)))
        last_check = {"time": str(datetime.now()), "active": len(lotteries), "new": 0, "seen": len(seen)}
        return

    new_count = 0
    for lot in lotteries:
        lid = str(lot.get("lotteryId", ""))
        if lid and lid not in seen:
            send_telegram(format_lottery(lot))
            seen.add(lid)
            new_count += 1
            print("  -> New: {} {}".format(lid, (lot.get("lotteryName") or "").strip()), flush=True)
            time.sleep(1)

    save_seen(seen)
    last_check = {"time": str(datetime.now()), "active": len(lotteries), "new": new_count, "seen": len(seen)}
    print("[{}] Active: {}, New: {}, Seen: {}".format(datetime.now(), len(lotteries), new_count, len(seen)), flush=True)


def bot_loop():
    while True:
        try:
            check_and_notify()
        except Exception as e:
            print("[ERROR] {}".format(e), flush=True)
        time.sleep(CHECK_INTERVAL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "last_check": last_check}).encode())

    def log_message(self, format, *args):
        pass


def main():
    print("Starting Housing Connect Monitor...", flush=True)

    bot_thread = threading.Thread(target=bot_loop, daemon=True)
    bot_thread.start()

    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print("Web server on port {}".format(port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
