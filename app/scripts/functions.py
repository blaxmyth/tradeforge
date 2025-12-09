import bs4 as bs
import requests

def get_sp500_symbols():
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    response = requests.get(url)
    response.raise_for_status()  # Raises HTTPError if status != 200

    soup = bs.BeautifulSoup(response.text, "html.parser")

    table = soup.find("table", {"id": "constituents"})
    sp500 = []

    if table:
        rows = table.find_all("tr")[1:]  # Skip header
        for row in rows:
            cols = row.find_all("td")
            if cols:
                symbol = cols[0].text.strip()
                sp500.append(symbol)
    return sp500

    