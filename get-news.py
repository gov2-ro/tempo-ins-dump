filename = "data/insse_news.csv"

import requests
import pandas as pd
from bs4 import BeautifulSoup

URL = "http://statistici.insse.ro:8077/tempo-ins/news/"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'http://statistici.insse.ro:8077/tempo-online/',
    'Connection': 'keep-alive',
}

def download_table():
    try:
        print(f"Connecting to {URL}...")
        response = requests.get(URL, headers=HEADERS, timeout=15)
        
        # --- HEALTH CHECK ---
        if response.status_code != 200:
            print(f"❌ Page load failed. Status Code: {response.status_code}")
            return
        
        if "<table" not in response.text.lower():
            print("❌ Page loaded, but no <table> found in the HTML source.")
            return
            
        print("✅ Page loaded successfully. Extracting table...")
        # ---------------------

        # Use Pandas to read the HTML directly (it uses BeautifulSoup under the hood)
        # matches=['Activitatea'] tells pandas to find the table containing that specific header text
        tables = pd.read_html(response.text, flavor='bs4')
        
        if tables:
            # Usually, it's the first table on this specific news page
            df = tables[0]
            
            # Clean up: the first row might be used as headers automatically
            # Save with utf-8-sig so Romanian characters show up correctly in Excel
            
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            
            print(f"Done! Saved {len(df)} rows to {filename}")
            print(df.head()) # Preview the first few rows
        else:
            print("Could not find any tables on the page.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    download_table()