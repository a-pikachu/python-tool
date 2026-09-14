from playwright.sync_api import sync_playwright
import datetime
import os
import random
import re
import shutil
import sys
import tempfile
import time
from dotenv import load_dotenv
import psycopg2

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
env_path = os.path.join(BASE_DIR, "..", ".env") 
load_dotenv(env_path)

sys.stdout.reconfigure(encoding='utf-8')

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
    recorded_at = datetime.datetime.now(datetime.timezone.utc)
    try:
        conn = psycopg2.connect(
            dbname=os.getenv("DB_NAME", "openclaw"),
            user=os.getenv("DB_USER", "openclaw"),
            password=os.getenv("DB_PASSWORD", "openclaw"),
            host=os.getenv("DB_HOST", "localhost"), 
            port=os.getenv("DB_PORT", "6543")
        )
        cur = conn.cursor()

        for store_name, stock_level in results.items():
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

def dismiss_any_popup(page):
    """Aggressively checks for and clears any active modals/popups blocking interaction."""
    selectors = [
        "div.abtest-freeshipping_modal button:has-text('Continue Shopping')",
        "div[class*='freeshipping'] button:has-text('Continue Shopping')",
        "button:has-text('Continue Shopping')",
        "div.abtest-freeshipping_modal",
        "div[class*='freeshipping']"
    ]
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                el.click(force=True, timeout=2000)
                page.wait_for_timeout(1000)
                print("Successfully dismissed a popup/modal.")
                return True
        except:
            pass
    return False

def search_and_navigate_to_product(page, sku):
    """Dismisses any blocking popups first, then uses the header search bar to find the SKU."""
    try:
        # Always clear potential popups before interacting with the search bar
        dismiss_any_popup(page)

        search_input = page.locator("input[type='search'], input[placeholder*='Search']").first
        search_input.wait_for(state="visible", timeout=10000)
        
        # Ensure input is enabled and clickable
        search_input.click(force=True)
        search_input.fill("")
        page.keyboard.type(sku, delay=50)
        page.wait_for_timeout(1000)
        
        page.keyboard.press("Enter")
        page.wait_for_timeout(4000)
        return True
    except Exception as e:
        print(f"Search navigation error for SKU {sku}: {e}")
        return False

def open_retail_store_selector(page):
    page.wait_for_timeout(4000)
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
            page.wait_for_timeout(1000)
            link.click()
            page.wait_for_selector("div.nl-overlay div[role='dialog'] input[type='text']", timeout=8000)
            return True
        except Exception:
            page.wait_for_timeout(500)
    return False

def search_and_scrape_first_card(page, search_text, match_name):
    """Scrapes store inventory results from the open modal overlay."""
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

def main():
    user_data_dir = tempfile.mkdtemp(prefix="chrome_profile_")
    print(f"Using isolated profile directory: {user_data_dir}")

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=False,
                viewport={"width": 1280, "height": 800},
                permissions=["geolocation"],
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            
            context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = context.new_page()
            url = "https://www.canadiantire.ca"
            
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            for product in PRODUCTS:
                label = product["label"]
                sku = product["sku"]

                print(f"\n==============================")
                print(f"Searching product: {label} (SKU: {sku})")
                print(f"==============================")

                if not search_and_navigate_to_product(page, sku):
                    # Fallback refresh if search failed
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    continue
                    
                results = {}
                for store_label, search_query in STORES.items():
                    print(f"\nChecking store: {store_label}")
                    if not open_retail_store_selector(page):
                        print(f"Skipping {store_label} — modal did not open")
                        results[store_label] = -1
                        continue
                    
                    quantity = -1
                    for attempt in range(1, 3):
                        _, quantity = search_and_scrape_first_card(page, search_query, store_label)
                        if quantity != -1:
                            break
                        time.sleep(random.uniform(1.5, 3.5))

                    print(f"{store_label} → {quantity} In Stock")
                    results[store_label] = quantity

                    try:
                        close_btn = page.locator("div.nl-overlay button[aria-label='Close'], div.nl-overlay button.nl-dialog__close").first
                        if close_btn.count() > 0:
                            close_btn.click(force=True)
                            page.wait_for_timeout(500)
                    except:
                        pass

                save_to_postgres(product_label=label, product_sku=sku, results=results)
                
                # Head back to homepage for the next product
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                sleep_duration = random.uniform(15.0, 30.0)
                print(f"\nSleeping for {sleep_duration:.1f} seconds...")
                time.sleep(sleep_duration)

            context.close()
    finally:
        shutil.rmtree(user_data_dir, ignore_errors=True)
        print("Cleaned up profile directory.")

if __name__ == "__main__":
    main()