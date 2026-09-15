import datetime
import os
from dotenv import load_dotenv
import psycopg2

BASE_DIR = os.path.dirname(os.path.abspath(__file__)) 
env_path = os.path.join(BASE_DIR, "..", ".env") 
load_dotenv(env_path)

PRODUCTS = [
    {"label": "Car Culture", "sku": "0508182"},
    {"label": "Pop Culture", "sku": "1504099"},
    {"label": "F1", "sku": "1504098"},
    {"label": "Team Transport", "sku": "0508495"},
]

STORES = [
    "Vancouver, SW Marine, BC",
    "Cambie & 7th, BC",
    "Vancouver, Grandview & Boundary, BC",
    "North Vancouver Main, BC",
]

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
        print(f"\nSuccessfully wrote manual inventory for {product_label} to PostgreSQL!")
    except Exception as e:
        print(f"\nDatabase insertion error for {product_label}: {e}")

def main():
    print("=== Canadian Tire Manual Inventory Logger ===")
    
    while True:
        print("\nSelect a product:")
        for idx, p in enumerate(PRODUCTS, 1):
            print(f"[{idx}] {p['label']} (SKU: {p['sku']})")
        print("[0] Exit")

        choice = input("\nEnter product number: ").strip()
        if choice == '0':
            break
        
        try:
            prod_idx = int(choice) - 1
            if prod_idx < 0 or prod_idx >= len(PRODUCTS):
                print("Invalid selection. Try again.")
                continue
        except ValueError:
            print("Please enter a valid number.")
            continue

        selected_product = PRODUCTS[prod_idx]
        results = {}

        print(f"\nEntering stock for: {selected_product['label']}")
        for store in STORES:
            while True:
                val = input(f"  Stock level for {store} (or press Enter to skip): ").strip()
                if val == "":
                    results[store] = -1
                    break
                try:
                    results[store] = int(val)
                    break
                except ValueError:
                    print("  Please enter a valid integer quantity.")

        save_to_postgres(selected_product['label'], selected_product['sku'], results)
        
        cont = input("\nLog another product? (y/n): ").strip().lower()
        if cont != 'y':
            break

if __name__ == "__main__":
    main()