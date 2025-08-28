import json
import requests
from pathlib import Path
from time import sleep


class SemanticScholarClient:
    """Simple client for Semantic Scholar API"""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, delay=1.0):
        self.delay = delay
        self.session = requests.Session()

    def search_papers(self, query, limit=10):
        """Simple search for papers"""
        params = {
            "query": query,
            "fields": "paperId,title,abstract,year,citationCount,externalIds,url",
            "limit": limit
        }

        try:
            response = self.session.get(f"{self.BASE_URL}/paper/search", params=params)
            response.raise_for_status()
            sleep(self.delay)
            return response.json()
        except Exception as e:
            print(f"Error: {e}")
            return {"data": []}


# Initialize client
client = SemanticScholarClient()

# Simple search
query = "research software metadata"
print(f"Searching for: '{query}'")

# Perform search
result = client.search_papers(query, limit=20)
papers = result.get("data", [])

print(f"Found {len(papers)} papers:")
print("-" * 50)

# Display results
for i, paper in enumerate(papers):
    title = paper.get("title", "No title")
    year = paper.get("year", "N/A")
    citations = paper.get("citationCount", 0)

    print(f"{i + 1}. {title} ({year})")
    print(f"   Citations: {citations}")

    # Get DOI from externalIds
    external_ids = paper.get("externalIds", {})
    doi = external_ids.get("DOI")
    if doi:
        print(f"   DOI: {doi}")

    if paper.get("url"):
        print(f"   URL: {paper.get('url')}")

    print()

# Save raw results to file
output_file = "simple_search_results.json"
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(papers, f, indent=2, ensure_ascii=False)

print(f"Results saved to {output_file}")