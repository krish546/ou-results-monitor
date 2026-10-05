import os
import json
import hashlib
from urllib.parse import urljoin

import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


OU_RESULTS_URL = "https://www.osmania.ac.in/examination-results.php"
SEEN_FILE = "seen_results.json"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def get_results():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120 Safari/537.36"
        )
    }

    retry_strategy = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )

    session = requests.Session()

    session.mount(
        "https://",
        HTTPAdapter(max_retries=retry_strategy)
    )

    response = session.get(
        OU_RESULTS_URL,
        headers=headers,
        timeout=45,
        verify=False
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.find_all("a", href=True):
        title = " ".join(
            link.get_text(" ", strip=True).split()
        )

        href = link.get("href", "").strip()

        if not title or not href:
            continue

        # OU examination result links are under /res07/
        absolute_url = urljoin(OU_RESULTS_URL, href)

        if "/res07/" not in absolute_url.lower():
            continue

        # Find the table row containing this result.
        row = link.find_parent("tr")

        release_date = ""

        if row:
            cells = row.find_all(["td", "th"])

            cell_text = [
                " ".join(
                    cell.get_text(" ", strip=True).split()
                )
                for cell in cells
            ]

            if len(cell_text) >= 2:
                release_date = cell_text[-1]

        # Generate a permanent unique ID for this result.
        unique_string = f"{title}|{absolute_url}"

        result_id = hashlib.sha256(
            unique_string.encode("utf-8")
        ).hexdigest()

        results.append({
            "id": result_id,
            "title": title,
            "date": release_date,
            "url": absolute_url
        })

    # Remove duplicate result links while preserving page order.
    unique_results = []
    seen_ids = set()

    for result in results:
        if result["id"] not in seen_ids:
            unique_results.append(result)
            seen_ids.add(result["id"])

    return unique_results

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return None

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return set(data)
    except (json.JSONDecodeError, OSError):
        return set()


def save_seen(ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as file:
        json.dump(sorted(ids), file, indent=2)


def send_telegram(result):
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing."
        )

    message = (
        "🔔 <b>New OU Result Published</b>\n\n"
        f"<b>{result['title']}</b>\n\n"
    )

    if result["date"]:
        message += f"📅 <b>Date:</b> {result['date']}\n"

    message += (
        f"🔗 <a href=\"{result['url']}\">Check Result</a>\n\n"
        "Osmania University"
    )

    telegram_url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    )

    response = requests.post(
        telegram_url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        },
        timeout=30
    )

    response.raise_for_status()


def main():
    print("Checking Osmania University results...")

    current_results = get_results()

    print(f"Found {len(current_results)} result entries.")

    if not current_results:
        raise RuntimeError(
            "No result entries were found. "
            "Stopping to prevent accidental state corruption."
        )

    current_ids = {result["id"] for result in current_results}
    seen_ids = load_seen()
       
    # First run:
    # Save existing results without sending alerts.
    if seen_ids is None:
        print("First run detected.")
        print("Saving existing results without sending alerts.")

        save_seen(current_ids)

        print("Initial result database created.")
        return

    new_results = [
        result
        for result in current_results
        if result["id"] not in seen_ids
    ]

    if not new_results:
        print("No new OU results found.")
    else:
        print(f"Found {len(new_results)} NEW result(s).")

        # Send older new entries first.
        for result in reversed(new_results):
            print(f"Sending alert: {result['title']}")
            send_telegram(result)

    # Remember everything we've seen.
    save_seen(seen_ids | current_ids)

    print("Monitoring check completed.")


if __name__ == "__main__":
    main()
