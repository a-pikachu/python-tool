from playwright.sync_api import sync_playwright
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import csv, datetime, json, logging, os, random, re, smtplib, sys, time

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
env_path = os.path.join(BASE_DIR, "..", ".env") 
load_dotenv(env_path)

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    filename="monitor.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

PRODUCTS = [
    {
        "label": "Car Culture",
        "url": "https://www.canadiantire.ca/en/pdp/0508182p.html",
        "snapshot_dir": r"G:\canadian-tire\car-culture-history",
    },
    {
        "label": "Pop Culture",
        "url": "https://www.canadiantire.ca/en/pdp/1504099p.html",
        "snapshot_dir": r"G:\canadian-tire\pop-culture-history",
    },
    {
        "label": "F1",
        "url": "https://www.canadiantire.ca/en/pdp/1504098p.html",
        "snapshot_dir": r"G:\canadian-tire\f1-history",
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
    "Vancouver, SW Marine, BC": "marine vancouver",
#    "Richmond, BC": "richmond",
    "Cambie & 7th, BC": "cambie vancouver",
    "Vancouver, Grandview & Boundary, BC": "grandview vancouver",
#    "Burnaby South, BC": "marine burnaby",
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
    page.wait_for_timeout(6000)
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
        dialog = page.locator("div.nl-overlay div[role='dialog']")
        dialog.wait_for(state="visible", timeout=5000)

        item = dialog.locator(f"li:has(h3:has-text('{clean_key}'))").first
        item.wait_for(state="visible", timeout=5000)

    except Exception as e:
        logging.error(f"[{clean_key}] Filtered result never became visible -> -1 ({e})")

def wait_for_filtered_results(page, clean_key, match_name, attempt):
    try:
        page.locator(
            f"div.nl-overlay div[role='dialog'] li:has(h3:has-text('{clean_key}'))"
        ).first.wait_for(state="visible", timeout=5000)
        return True
    except:
        logging.error(f"[{match_name}] Filtered results failed on attempt {attempt}")
        return False

def search_and_scrape_first_card(page, search_text, match_name, product_label):
    logging.info(f"[{product_label}][{match_name}] Searching using text '{search_text}'")

    # 1. Wait for input container to finish animating
    try:
        container = page.locator("div.nl-overlay div[role='dialog'] .nl-textinput").first
        container.wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(300)
    except Exception:
        logging.error(f"[{product_label}][{match_name}] Input container never stabilized")
        return match_name, -1

    search = page.locator("div.nl-overlay div[role='dialog'] input[type='text']").first

    # --- RETRY ONLY AUTOCOMPLETE (same logic as your original) ---
    suggestion_clicked = False
    for attempt in range(1, 4):
        try:
            logging.info(f"[{product_label}][{match_name}] Autocomplete attempt {attempt}")

            search.click(force=True)
            search.fill("")
            page.keyboard.type(search_text, delay=25)
            page.wait_for_timeout(800)

            suggestions = page.locator("li[class*='autocomplete'], li[class*='option']")
            suggestions.first.wait_for(state="visible", timeout=2500)
            suggestions.first.click(force=True)
            page.wait_for_timeout(1200)

            suggestion_clicked = True
            break
        except Exception as e:
            logging.warning(
                f"[{product_label}][{match_name}] Autocomplete attempt {attempt} failed: {e}"
            )
            page.wait_for_timeout(400)

    if not suggestion_clicked:
        logging.error(f"[{product_label}][{match_name}] Autocomplete never appeared -> -1")
        return match_name, -1

    # Normalize match key (city only)
    clean_key = match_name.split(",")[0].strip().lower()

    # 2. Wait for modal to load filtered results
    try:
        page.locator(
            f"div.nl-overlay div[role='dialog'] li:has(h3:has-text('{clean_key}'))"
        ).first.wait_for(state="visible", timeout=5000)
    except Exception:
        logging.error(
            f"[{product_label}][{match_name}] Modal never loaded filtered results -> -1"
        )
        return match_name, -1

    # 3. Wait for real store cards (Fix #3: retry loop)
    cards = page.locator("div.nl-overlay div[role='dialog'] li:has(h3)")

    count = 0
    for attempt in range(1, 4):
        count = cards.count()
        if count > 0:
            break
        logging.warning(
            f"[{product_label}][{match_name}] No store cards on attempt {attempt}, retrying…"
        )
        page.wait_for_timeout(1200)

    if count == 0:
        logging.error(f"[{product_label}][{match_name}] Store cards never loaded -> -1")
        return match_name, -1

    # 4. Iterate through cards and match store name
    for i in range(count):
        card = cards.nth(i)

        name_el = card.locator("h3").first
        if not name_el.count():
            logging.warning(
                f"[{product_label}][{match_name}] Card {i} missing <h3>, skipping"
            )
            continue

        card_name = name_el.inner_text().strip()

        if match_name.lower() != card_name.lower():
            continue

        # Extract stock tag
        stock_el = card.locator("span.nl-tag").first
        if not stock_el.count():
            logging.error(
                f"[{product_label}][{match_name}] Store '{card_name}' missing stock tag -> -1"
            )
            return match_name, -1

        stock_text = stock_el.inner_text().strip().lower()
        logging.info(
            f"[{product_label}][{match_name}] Raw stock text for '{card_name}': '{stock_text}'"
        )

        if "out of stock" in stock_text:
            logging.info(
                f"[{product_label}][{match_name}] '{card_name}' explicitly OUT OF STOCK -> 0"
            )
            return match_name, 0

        m = re.search(r"(\d+)", stock_text)
        if m:
            qty = int(m.group(1))
            logging.info(
                f"[{product_label}][{match_name}] '{card_name}' stock parsed as {qty}"
            )
            return match_name, qty

        logging.error(
            f"[{product_label}][{match_name}] Cannot parse stock text '{stock_text}' -> -1"
        )
        return match_name, -1

    logging.error(f"[{product_label}][{match_name}] No matching card found -> -1")
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

def delete_old_snapshots(folder_path, days=15):
    cutoff = time.time() - (days * 86400)  # 15 days → seconds

    deleted = []
    for filename in os.listdir(folder_path):
        if not filename.endswith(".json"):
            continue

        full_path = os.path.join(folder_path, filename)
        try:
            mtime = os.path.getmtime(full_path)
            if mtime < cutoff:
                os.remove(full_path)
                deleted.append(filename)
        except Exception as e:
            logging.error(f"Failed to delete {full_path}: {e}")

    return deleted

def dismiss_first_popup(page):
    """
    Handles Canadian Tire's Free Local Shipping popup.
    The visible button is often blocked by an overlay, so we click the overlay container instead.
    """

    page.wait_for_timeout(20000)

    # 1. Detect the free-shipping modal container
    modal = page.locator("div.abtest-freeshipping_modal, div[class*='freeshipping']")
    if modal.count() > 0:
        print("Free-shipping modal detected")

        # 2. Try clicking the Continue Shopping button normally
        btn = modal.locator("button:has-text('Continue Shopping')")
        if btn.count() > 0:
            try:
                btn.first.click(force=True)
                page.wait_for_timeout(1200)
                print("Dismissed popup via button")
                return True
            except:
                print("Button click blocked, trying overlay click")

        # 3. Click the overlay container itself (works even when button is blocked)
        try:
            page.evaluate("el => el.click()", modal.first)
            page.wait_for_timeout(1200)
            print("Dismissed popup via overlay JS click")
            return True
        except Exception as e:
            print(f"Overlay JS click failed: {e}")

    # 4. Fallback generic selectors
    fallback = page.locator("text=Continue Shopping")
    if fallback.count() > 0:
        try:
            fallback.first.click(force=True)
            page.wait_for_timeout(1200)
            print("Dismissed popup via fallback selector")
            return True
        except:
            pass

    print("No popup dismissed")
    return False

def wait_for_free_shipping_popup(page, timeout=20000):
    """
    Wait up to 20 seconds for the free-shipping popup to appear.
    Returns True if detected.
    """

    selectors = [
        "div.abtest-freeshipping_modal",
        "div[class*='freeshipping']",
        "text=Free Local Shipping",
        "text=Continue Shopping",
    ]

    start = time.time()
    while time.time() - start < timeout / 1000:
        for sel in selectors:
            if page.locator(sel).count() > 0:
                print(f"Popup detected via selector: {sel}")
                return True

        # Keep Playwright alive
        page.wait_for_timeout(300)

    print("Popup did not appear within timeout")
    return False


def main():
    with sync_playwright() as p:
        # 1. Launch with anti-detection flags tailored for automated background tasks
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=640,480",
            ],
        )

        # 2. Create a persistent context mimicking a real user session
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 640, "height": 480},
            java_script_enabled=True,
            bypass_csp=True,
        )

        # 3. Strip out the navigator.webdriver fingerprint property
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        page = context.new_page()
        
        # 4. Increase global default navigation timeout to 60 seconds
        page.set_default_navigation_timeout(60000)

        results = {}
        first_load = True

        for product in PRODUCTS:
            label = product["label"]
            url = product["url"]
            snapshot_dir = product["snapshot_dir"]

            print(f"\n==============================")
            print(f"Checking product: {label}")
            print(f"==============================")

            results = {}
            
            # Use a more resilient network wait state or catch timeouts safely
            try:
                page.goto(url, wait_until="commit", timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"Navigation error or block encountered for {label}: {e}")
                continue

            page.wait_for_timeout(6000)
            
            if first_load:
                if wait_for_free_shipping_popup(page):
                     dismiss_first_popup(page)
                first_load = False

            for store_label, search_query in STORES.items():
                print(f"\nChecking: {store_label}")
                try:
                    page.goto(url, wait_until="commit", timeout=60000)
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception as e:
                    print(f"Navigation error on store reload for {store_label}: {e}")
                
                page.wait_for_timeout(800)

                if not open_retail_store_selector(page):
                    print(f"Skipping {store_label} — modal did not open")
                    results[store_label] = -1
                    continue
                
                quantity = -1
                for attempt in range(1, 3):
                    print(f"  → Store lookup attempt {attempt}…")
                    _, quantity = search_and_scrape_first_card(page, search_query, store_label, label)

                    if quantity != -1:
                        break

                    wait = random.uniform(1.5, 3.5)
                    print(f"    Failed (got -1). Retrying after {wait:.1f}s…")
                    time.sleep(wait)

                print(f"{store_label} → {quantity} In Stock")
                results[store_label] = quantity

            # Rest of your snapshot, diffing, and email logic remains the same...

            print("\nFinal Results:")
            for store_label, quantity in results.items():
                print(f"{store_label} -> {quantity} In Stock")

            # 1. Save snapshot
            snapshot_path = save_snapshot(results, snapshot_dir)

            deleted = delete_old_snapshots(snapshot_dir, days=15)
            if deleted:
                print(f"Deleted old snapshots: {deleted}")

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


if __name__ == "__main__":
    main()
