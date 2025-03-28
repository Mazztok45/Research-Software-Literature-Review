import requests

url = "https://api.openaire.eu/graph/v1/researchProducts"
params = {
    "search": "research software metadata",
    "type": "publication",
    "page": 1,
    "pageSize": 10,
    "sortBy": "relevance DESC"
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
