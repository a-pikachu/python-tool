from playwright.sync_api import sync_playwright
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import csv, datetime, json, logging, os, re, smtplib, sys, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
env_path = os.path.join(BASE_DIR, "..", ".env") 
load_dotenv(env_path)

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    filename="monitor.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

PRODUCTS = [
    {
        "label": "Car Culture",
        "url": "https://www.canadiantire.ca/en/pdp/0508182p.html",
        "snapshot_dir": r"G:\canadian-tire\car-culture-history",
    },
    {
        "label": "Team Transport",
        "url": "https://www.canadiantire.ca/en/pdp/0508495p.html",
        "snapshot_dir": r"G:\canadian-tire\team-transport-history",
    },
]

smtp_server = "smtp.gmail.com"
smtp_port = 587
username = os.getenv("SMTP_USERNAME")
password = os.getenv("SMTP_PASSWORD")
raw = os.getenv("RECIPIENTS", "")
recipients = [email.strip() for email in raw.split(",") if email.strip()]

# search_query → label
STORES = {
    "Vancouver, SW Marine, BC": "Southwest Marine Drive, Vancouver, BC",
    "Richmond, BC": "Richmond, BC",
    "Cambie & 7th, BC": "Cambie Street, Vancouver, BC",
    "Vancouver, Grandview & Boundary, BC": "Grandview Hwy, Vancouver, BC",
    "Burnaby South, BC": "Southeast Marine Drive, Burnaby, BC",
    "North Vancouver Main, BC": "north vancouver",
}

def normalize_quantity(q):
    if isinstance(q, str) and q.strip().lower() == "out of stock":
        return 0
    try:
        return int(q)
    except:
        return 0

def open_retail_store_selector(page):
    for attempt in range(1, 4):
        try:
            print(f"Attempt {attempt} to open store selector…")

            # Re-locate each attempt (CT rehydrates DOM often)
            links = page.locator("text=Check other stores")
            count = links.count()

            if count == 0:
                print("No 'Check other stores' links found")
                page.wait_for_timeout(2000)
                continue

            # Always click the last one
            link = links.nth(count - 1)

            link.scroll_into_view_if_needed()
            link.wait_for(state="visible")
            page.wait_for_timeout(2000)

            link.click()

            # Wait for modal input
            page.wait_for_selector(
                "div.nl-overlay div[role='dialog'] input[type='text']",
                timeout=8000
            )

            print("Store selector opened successfully")
            return True

        except Exception as e:
            print(f"Attempt {attempt} failed: {e}")
            page.wait_for_timeout(500)

    print("Failed to open store selector after 3 attempts")
    return False


def click_first_suggestion(page):
    # Suggestions are rendered OUTSIDE the modal in a React portal
    suggestions = page.locator("li[class*='autocomplete'], li[class*='option']")

    # Wait for suggestions to appear
    suggestions.first.wait_for(state="visible", timeout=5000)

    # Hover to activate (required for some variants)
    suggestions.first.hover()
    page.wait_for_timeout(150)

    # Click with force to bypass overlays
    suggestions.first.click(force=True)
    page.wait_for_timeout(800)

    # NEW: Wait for modal to load filtered results
    try:
        page.locator(
            f"div.nl-overlay div[role='dialog'] li:has(h3:has-text('{clean_key}'))"
        ).first.wait_for(state="visible", timeout=5000)
    except:
        logging.error(f"[{clean_key}] Modal never loaded filtered results -> -1")

def search_and_scrape_first_card(page, search_text, match_name):
    logging.info(f"Searching for '{match_name}' using text '{search_text}'")

    # 1. Type into modal search box
    search = page.locator("div.nl-overlay div[role='dialog'] input[type='text']").first
    search.click()
    search.fill("")
    page.keyboard.type(search_text, delay=25)
    page.wait_for_timeout(1000)

    # 2. Click first autocomplete suggestion
    suggestions = page.locator("li[class*='autocomplete'], li[class*='option']")
    try:
        suggestions.first.wait_for(state="visible", timeout=5000)
    except Exception as e:
        logging.error(f"[{match_name}] autocomplete never appeared → -1 ({e})")
        return match_name, -1

    suggestions.first.click(force=True)
    page.wait_for_timeout(1200)

    # Normalize match key (city only)
    clean_key = match_name.split(",")[0].strip().lower()

    # Wait for modal to load filtered results (store names containing the city)
    try:
        page.locator(
            f"div.nl-overlay div[role='dialog'] li:has(h3:has-text('{clean_key}'))"
        ).first.wait_for(state="visible", timeout=5000)
    except Exception:
        logging.error(f"[{match_name}] Modal never loaded filtered results -> -1")
        return match_name, -1

    # 3. Wait for real store cards (those containing <h3>)
    try:
        page.locator("div.nl-overlay div[role='dialog'] li h3").first.wait_for(
            state="visible", timeout=5000
        )
    except Exception:
        logging.error(f"[{match_name}] No real store cards loaded -> -1")
        return match_name, -1

    # Now select only real cards (li elements that contain an h3)
    cards = page.locator("div.nl-overlay div[role='dialog'] li:has(h3)")
    count = cards.count()
    logging.info(f"[{match_name}] Found {count} real store cards")

    for i in range(count):
        card = cards.nth(i)

        # Extract store name
        name_el = card.locator("h3").first
        if not name_el.count():
            logging.warning(f"[{match_name}] Card {i} missing <h3>, skipping")
            continue

        card_name = name_el.inner_text().strip()

        # Match using cleaned city key
        if clean_key not in card_name.lower():
            continue

        # Extract stock tag
        stock_el = card.locator("span.nl-tag").first
        if not stock_el.count():
            logging.error(f"[{match_name}] Store '{card_name}' missing stock tag -> -1")
            return match_name, -1

        stock_text = stock_el.inner_text().strip().lower()
        logging.info(f"[{match_name}] Raw stock text for '{card_name}': '{stock_text}'")

        # Explicit out of stock
        if "out of stock" in stock_text:
            logging.info(f"[{match_name}] '{card_name}' explicitly OUT OF STOCK -> 0")
            return match_name, 0

        # Extract number
        m = re.search(r"(\d+)", stock_text)
        if m:
            qty = int(m.group(1))
            logging.info(f"[{match_name}] '{card_name}' stock parsed as {qty}")
            return match_name, qty

        # Unexpected format
        logging.error(f"[{match_name}] Cannot parse stock text '{stock_text}' -> -1")
        return match_name, -1

    logging.error(f"[{match_name}] No matching card found -> -1")
    return match_name, -1

def save_snapshot(results, folder_path):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}.json"
    full_path = os.path.join(folder_path, filename)

    with open(full_path, "w") as f:
        json.dump(results, f, indent=2)

    return full_path

def load_snapshots(folder_path):
    files = sorted(os.listdir(folder_path))
    if len(files) < 2:
        return None, None

    latest = os.path.join(folder_path, files[-1])
    previous = os.path.join(folder_path, files[-2])

    with open(previous) as f:
        old = json.load(f)
    with open(latest) as f:
        new = json.load(f)

    return old, new

def diff_snapshots(old, new):
    increases = {}
    for store in new:
        new_val = new[store]

        # Ignore unreachable or invalid values
        if new_val < 0:
            continue

        old_val = old.get(store, -1)

        # Ignore old unreachable values too
        if old_val < 0:
            continue

        # Only report if stock increased
        if new_val > old_val:
            increases[store] = (old_val, new_val)

    return increases

def print_increases(increases):
    if not increases:
        print("No new stock arrived")
        return

    print("New stock arrivals:")
    for store, (old_val, new_val) in increases.items():
        print(f"{store}: {old_val} → {new_val}")

def update_google_sheet(results, csv_path):
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Store Name", "Stock"])

        for store_name, quantity in results.items():
            writer.writerow([store_name, quantity])

def append_history(results, csv_path):
    file_exists = os.path.exists(csv_path)

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        if not file_exists:
            writer.writerow(["Timestamp", "Store Name", "Stock"])

        timestamp = datetime.datetime.now().isoformat()

        for store_name, quantity in results.items():
            writer.writerow([timestamp, store_name, quantity])

def send_email_alert(
    smtp_server,
    smtp_port,
    username,
    password,
    recipients,
    increases,
    product_label: str,
):

    if not increases:
        return  # nothing to alert

    # Build message body
    lines = [f"New Stock Arrivals for {product_label}:"]
    for store, (old_val, new_val) in increases.items():
        lines.append(f"- {store}: {old_val} → {new_val}")

    body = "\n".join(lines)

    # Email structure
    msg = MIMEMultipart()
    msg["From"] = username
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = f"Canadian Tire Stock Alert – {product_label}"
    msg.attach(MIMEText(body, "plain"))

    # Send email
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, recipients, msg.as_string())


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-geolocation",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--deny-permission-prompts",
            ],
        )

        page = browser.new_page()
        results = {}

        for product in PRODUCTS:
            label = product["label"]
            url = product["url"]
            snapshot_dir = product["snapshot_dir"]

            print(f"\n==============================")
            print(f"Checking product: {label}")
            print(f"==============================")

            results = {}
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(30000)

            for store_label, search_query in STORES.items():
                print(f"\nChecking: {store_label}")
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(800)

                if not open_retail_store_selector(page):
                    print(f"Skipping {store_label} — modal did not open")
                    results[store_label] = -1   # unreachable / failed check
                    continue
                
                _, quantity = search_and_scrape_first_card(page, search_query, store_label)

                print(f"{store_label} → {quantity} In Stock")
                results[store_label] = (quantity)

                time.sleep(1)

            print("\nFinal Results:")
            for store_label, quantity in results.items():
                print(f"{store_label} -> {quantity} In Stock")

            # 1. Save snapshot
            snapshot_path = save_snapshot(results, snapshot_dir)

            # 2. Load previous + latest snapshots
            old, new = load_snapshots(snapshot_dir)

            # 3. Compute increases only
            if old and new:
                increases = diff_snapshots(old, new)

                # 4. Print increases
                print_increases(increases)
 
                send_email_alert(
                    smtp_server,
                    smtp_port,
                    username,
                    password,
                    recipients,
                    increases,
                    product_label=label,   # optional: include product name in email
                )
            else:
                print("Not enough snapshots to compare yet")

            # 5. Update current stock sheet (overwrite)
            update_google_sheet(
                results, fr"G:\canadian-tire\current_stock_{label}.csv"
            )

            # 6. Append to history sheet
            #append_history(
            #    results, fr"G:\canadian-tire\history_{label}.csv"
            #)


if __name__ == "__main__":
    main()
