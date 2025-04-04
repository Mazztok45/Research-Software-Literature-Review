import requests

url = "https://api.openaire.eu/search/publications"
params = {
    "keywords": "research software",
    "size": 200,
    "page": 1,
    "format": "json"
}
headers = {
    "accept": "application/json"
}

response = requests.get(url, headers=headers, params=params)

if response.status_code == 200:
    data = response.json()
    print(data["response"]["results"]["result"][0]["metadata"]["oaf:entity"]["oaf:result"]["pid"])
else:
    print(f"Failed to retrieve data: {response.status_code}")
