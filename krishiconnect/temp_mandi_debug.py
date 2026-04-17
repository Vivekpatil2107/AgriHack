import requests

api_key = "579b464db66ec23bdd0000010815c9eb32984e27549690e5e7f660f8"
resource_id = "9ef84268-d588-465a-a308-a864a43d0070"


def fetch_latest_mandi_price(commodity, city):
    url = f"https://api.data.gov.in/resource/{resource_id}"
    params = {
        "api-key": api_key,
        "format": "json",
        "limit": 30,
        "filters[state]": "Maharashtra",
        "filters[district]": city.upper(),
        "filters[commodity]": commodity.upper(),
    }
    r = requests.get(url, params=params, timeout=10)
    print("REQUEST URL:", r.url)
    print("STATUS:", r.status_code)
    data = r.json()
    print("RECORD COUNT:", len(data.get("records", [])))
    print(data.get("records", [])[:3])
    return data

for city in ["Pune", "Ahmednagar", "Solapur", "Mumbai"]:
    for commodity in ["Potato", "Onion", "Wheat"]:
        print("===", city, commodity)
        try:
            fetch_latest_mandi_price(commodity, city)
        except Exception as e:
            print("ERROR:", e)
            raise
