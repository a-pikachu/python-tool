from playwright.sync_api import sync_playwright
import time
import re

PRODUCT_URL = "https://www.canadiantire.ca/en/pdp/0508182p.html"

# search_query → label
STORES = {
    "SW Marine (605)": "Southwest Marine Drive, Vancouver, BC",
    "Richmond (606)": "Richmond, BC",
    "Cambie & 7th (389)": "Cambie Street, Vancouver, BC",
    "Grandview (604)": "Grandview Hwy, Vancouver, BC",
    "Burnaby South (603)": "Southeast Marine Drive, Burnaby, BC",
}

def dismiss_geolocation_popup(page):
    try:
        btn = page.locator("button:has-text('Choose Store')")
        if btn.is_visible():
            btn.click()
            page.wait_for_timeout(600)
    except:
        pass

def dismiss_email_popup(page):
    try:
        close_btn = page.locator("button:has(svg), button[class*='close']").first
        if close_btn.is_visible():
            close_btn.click()
            page.wait_for_timeout(400)
    except:
        pass

def open_retail_store_selector(page):
    link = page.locator("text=Check other stores").first
    link.scroll_into_view_if_needed()
    link.wait_for(state="visible")
    link.click()
    page.wait_for_selector("div.nl-overlay div[role='dialog'] input[type='text']", timeout=8000)

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

def search_and_scrape_first_card(page, search_query):
    # 1. Type into modal search box
    search = page.locator("div.nl-overlay div[role='dialog'] input[type='text']").first
    search.click()
    search.fill("")
    page.keyboard.type(search_query, delay=25)
    page.wait_for_timeout(1000)

    # 2. Click first autocomplete suggestion
    suggestions = page.locator("li[class*='autocomplete'], li[class*='option']")
    suggestions.first.wait_for(state="visible", timeout=5000)
    suggestions.first.hover()
    suggestions.first.click(force=True)
    page.wait_for_timeout(1200)

    # 3. Use Distill-verified selector for the FIRST stock tag
    stock_el = page.locator(
        "div.nl-overlay div[role='dialog'] li span.nl-tag"
    ).first
    stock_el.wait_for(state="visible", timeout=5000)

    stock_text = stock_el.inner_text().strip()
    print("DEBUG stock_text =", repr(stock_text))  # TEMP DEBUG

    # 4. Extract numeric stock value safely
    m = re.search(r"(\d+)", stock_text)
    if not m:
        return "UNKNOWN", 0
    quantity = int(m.group(1))

    # 5. Climb to the parent <li> card
    card = stock_el.locator("xpath=ancestor::li[1]")

    # 6. Extract store name
    store_name = card.locator("h3").first.inner_text().strip()

    return store_name, quantity


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-geolocation",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--deny-permission-prompts",
            ],
        )

        page = browser.new_page()
        results = {}

        for label, search_query in STORES.items():
            print(f"\nChecking: {label}")
            page.goto(PRODUCT_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(800)

            dismiss_geolocation_popup(page)
            dismiss_email_popup(page)

            open_retail_store_selector(page)

            store_name, quantity = search_and_scrape_first_card(page, search_query)

            print(f"{label}: {store_name} → {quantity} In Stock")
            results[label] = (store_name, quantity)

            time.sleep(1)



        print("\nFinal Results:")
        for label, (store_name, quantity) in results.items():
            print(f"{label}: {store_name} → {quantity} In Stock")

if __name__ == "__main__":
    main()
