import requests

url = "https://api.openaire.eu/search/publications"
params = {
    "title": "research software OR software citation OR metadata",
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
    print(data)
else:
    print(f"Failed to retrieve data: {response.status_code}")
