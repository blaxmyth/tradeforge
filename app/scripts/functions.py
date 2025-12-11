import requests
import bs4 as bs # Using bs4 directly as per your function structure

def get_sp500_symbols():
    """
    Scrapes the Wikipedia S&P 500 page to retrieve current constituent tickers.
    
    Uses BeautifulSoup and requests directly, including a User-Agent header 
    to bypass 403 Forbidden errors.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    
    # Define a custom header to mimic a standard web browser.
    # This is required to resolve the 403 Forbidden error.
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # Pass the headers dictionary with the request
        response = requests.get(url, headers=headers)
        
        # This will raise an HTTPError if the response status code is 4XX or 5XX
        response.raise_for_status() 
        
        # Use 'lxml' or 'html.parser' (using 'html.parser' to match your input)
        soup = bs.BeautifulSoup(response.text, "html.parser") 
        
        # Find the table by its ID 'constituents' as defined in your function
        table = soup.find("table", {"id": "constituents"})
        sp500 = []

        if table:
            # Skip header row [1:]
            rows = table.find_all("tr")[1:] 
            for row in rows:
                cols = row.find_all("td")
                if cols:
                    # Ticker symbol is in the first column (index 0)
                    symbol = cols[0].text.strip()
                    # Clean up dots (e.g., BRK.B -> BRK-B) for Alpaca/Yahoo compatibility
                    cleaned_symbol = symbol.replace('.', '-')
                    sp500.append(cleaned_symbol)
        
        return sp500

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error occurred: {e}. Ensure the User-Agent header is still working.")
        return []
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return []

# Example usage:
# sp500_list = get_sp500_tickers()
# print(f"Retrieved {len(sp500_list)} S&P 500 tickers.")
# print(sp500_list[:5])