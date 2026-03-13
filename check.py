"""
NYC Housing Connect Lottery Monitor - GitHub Actions version
Runs once per invocation, persists seen IDs in seen_lotteries.json
"""
import requests
import json
import os
import sys

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = os.environ.get("TELEGRAM_CHAT_IDS", "").split(",")
HC_API_URL = "https://a806-housingconnectapi.nyc.gov/HPDPublicAPI/api/Lottery/SearchLotteries"
HC_SEARCH_BODY = {
    "UnitTypes": [], "NearbyPlaces": [], "NearbySubways": [], "Amenities": [],
    "Applied": None, "HPDUserId": None, "Boroughs": [], "Neighborhoods": [],
    "HouseholdSize": None, "Income": "", "HouseholdType": 1, "OwnerTypes": [],
    "PreferanceTypes": [], "LotteryTypes": [], "Min": None, "Max": None, "RentalSubsidy": None
}
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_lotteries.json")


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
        print("No TELEGRAM_BOT_TOKEN set")
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
                print("[ERROR] Telegram send to {}: {} {}".format(chat_id, resp.status_code, resp.text))
                success = False
        except Exception as e:
            print("[ERROR] Telegram send to {}: {}".format(chat_id, e))
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
        print("[ERROR] Fetch: {}".format(e))
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


def main():
    seen = load_seen()
    first_run = len(seen) == 0

    lotteries = fetch_active_lotteries()
    if not lotteries:
        print("No lotteries fetched")
        sys.exit(1)

    if first_run:
        print("First run - saving {} lotteries silently".format(len(lotteries)))
        for lot in lotteries:
            lid = str(lot.get("lotteryId", ""))
            if lid:
                seen.add(lid)
        save_seen(seen)
        return

    new_count = 0
    for lot in lotteries:
        lid = str(lot.get("lotteryId", ""))
        if lid and lid not in seen:
            send_telegram(format_lottery(lot))
            seen.add(lid)
            new_count += 1
            print("New: {} {}".format(lid, (lot.get("lotteryName") or "").strip()))

    save_seen(seen)
    print("Active: {}, New: {}, Seen: {}".format(len(lotteries), new_count, len(seen)))

    if new_count > 0:
        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
            f.write("has_new=true\n")


if __name__ == "__main__":
    main()
