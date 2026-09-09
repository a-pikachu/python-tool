from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import csv, datetime, json, logging, os, random, re, sys, time
import psycopg2  # Added for direct Postgres insertion

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
env_path = os.path.join(BASE_DIR, "..", ".env") 
load_dotenv(env_path)

sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    filename="monitor.log",
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

CANADIAN_TIRE_BASE_URL = "https://www.canadiantire.ca/en/pdp"

PRODUCTS = [
    {"label": "Car Culture", "sku": "0508182"},
    {"label": "Pop Culture", "sku": "1504099"},
    {"label": "F1", "sku": "1504098"},
    {"label": "Team Transport", "sku": "0508495"},
]

STORES = {
    "Vancouver, SW Marine, BC": "marine vancouver",
    "Cambie & 7th, BC": "cambie vancouver",
    "Vancouver, Grandview & Boundary, BC": "grandview vancouver",
    "North Vancouver Main, BC": "north vancouver",
}

def save_to_postgres(product_label, product_sku, results):
    """Inserts the scraped stock levels directly into your PostgreSQL table."""
    recorded_at = datetime.datetime.now(datetime.timezone.utc)
    
    try:
        # Update connection parameters to match your Docker Compose environment variables
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "openclaw"),
            user=os.getenv("DB_USER", "openclaw"),
            password=os.getenv("DB_PASSWORD", "openclaw"),
            host=os.getenv("DB_HOST", "localhost"),  # Use service name (e.g., 'db' or 'postgres') if Python runs inside Docker too
            port=os.getenv("DB_PORT", "6543")
        )
        cur = conn.cursor()

        for store_name, stock_level in results.items():
            # Skip failed lookups (-1) if you don't want to log errors to DB
            if stock_level < 0:
                continue

            cur.execute("""
                INSERT INTO canadian_tire_inventory 
                (recorded_at, product_label, product_sku, store_name, stock_level)
                VALUES (%s, %s, %s, %s, %s)
            """, (recorded_at, product_label, product_sku, store_name, stock_level))

        conn.commit()
        cur.close()
        conn.close()
        print(f"Successfully wrote inventory for {product_label} to PostgreSQL.")
    except Exception as e:
        print(f"Database insertion error for {product_label}: {e}")
        logging.error(f"Database insertion error for {product_label}: {e}")

def open_retail_store_selector(page):
    page.wait_for_timeout(6000)
    for attempt in range(1, 4):
        try:
            links = page.locator("text=Check other stores")
            count = links.count()
            if count == 0:
                page.wait_for_timeout(2000)
                continue
            link = links.nth(count - 1)
            link.scroll_into_view_if_needed()
            link.wait_for(state="visible")
            page.wait_for_timeout(2000)
            link.click()
            page.wait_for_selector("div.nl-overlay div[role='dialog'] input[type='text']", timeout=8000)
            return True
        except Exception:
            page.wait_for_timeout(500)
    return False

def search_and_scrape_first_card(page, search_text, match_name, product_label):
    try:
        container = page.locator("div.nl-overlay div[role='dialog'] .nl-textinput").first
        container.wait_for(state="visible", timeout=5000)
        page.wait_for_timeout(300)
    except Exception:
        return match_name, -1

    search = page.locator("div.nl-overlay div[role='dialog'] input[type='text']").first
    suggestion_clicked = False
    
    for attempt in range(1, 4):
        try:
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
        except Exception:
            page.wait_for_timeout(400)

    if not suggestion_clicked:
        return match_name, -1

    clean_key = match_name.split(",")[0].strip().lower()
    try:
        page.locator(f"div.nl-overlay div[role='dialog'] li:has(h3:has-text('{clean_key}'))").first.wait_for(state="visible", timeout=5000)
    except Exception:
        return match_name, -1

    cards = page.locator("div.nl-overlay div[role='dialog'] li:has(h3)")
    count = cards.count()

    for i in range(count):
        card = cards.nth(i)
        name_el = card.locator("h3").first
        if not name_el.count():
            continue
        card_name = name_el.inner_text().strip()
        if match_name.lower() != card_name.lower():
            continue

        stock_el = card.locator("span.nl-tag").first
        if not stock_el.count():
            return match_name, -1

        stock_text = stock_el.inner_text().strip().lower()
        if "out of stock" in stock_text:
            return match_name, 0

        m = re.search(r"(\d+)", stock_text)
        if m:
            return match_name, int(m.group(1))

    return match_name, -1

def dismiss_first_popup(page):
    page.wait_for_timeout(20000)
    modal = page.locator("div.abtest-freeshipping_modal, div[class*='freeshipping']")
    if modal.count() > 0:
        btn = modal.locator("button:has-text('Continue Shopping')")
        if btn.count() > 0:
            try:
                btn.first.click(force=True)
                page.wait_for_timeout(1200)
                return True
            except:
                pass
        try:
            page.evaluate("el => el.click()", modal.first)
            page.wait_for_timeout(1200)
            return True
        except:
            pass
    return False

def wait_for_free_shipping_popup(page, timeout=20000):
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
                return True
        page.wait_for_timeout(300)
    return False

def main():
    with sync_playwright() as p:
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

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 640, "height": 480},
            java_script_enabled=True,
            bypass_csp=True,
        )

        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        page.set_default_navigation_timeout(60000)

        first_load = True

        for product in PRODUCTS:
            label = product["label"]
            sku = product["sku"]
            url = f"{CANADIAN_TIRE_BASE_URL}/{sku}p.html"

            print(f"\n==============================")
            print(f"Checking product: {label} (SKU: {sku})")
            print(f"==============================")

            results = {}
            
            try:
                page.goto(url, wait_until="commit", timeout=60000)
                page.wait_for_load_state("domcontentloaded", timeout=30000)
            except Exception as e:
                print(f"Navigation error for {label}: {e}")
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
                    _, quantity = search_and_scrape_first_card(page, search_query, store_label, label)
                    if quantity != -1:
                        break
                    time.sleep(random.uniform(1.5, 3.5))

                print(f"{store_label} → {quantity} In Stock")
                results[store_label] = quantity

            # Directly map and write the inventory results into your PostgreSQL table
            save_to_postgres(product_label=label, product_sku=sku, results=results)

if __name__ == "__main__":
    main()