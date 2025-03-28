import requests

def search_papers(query, fields=None, publication_types=None, open_access_pdf=False,
                  min_citation_count=None, publication_date_or_year=None, year=None,
                  venue=None, fields_of_study=None, offset=0, limit=None):
    # Base URL for the Semantic Scholar API
    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    
    # Parameters for the API request
    params = {
        "query": query,
        "offset": offset,
        "limit": limit
    }
    
    # Optional parameters
    if fields:
        params["fields"] = fields
    if publication_types:
        params["publicationTypes"] = publication_types
    if open_access_pdf:
        params["openAccessPdf"] = ""  # This parameter doesn't require a value
    if min_citation_count:
        params["minCitationCount"] = min_citation_count
    if publication_date_or_year:
        params["publicationDateOrYear"] = publication_date_or_year
    if year:
        params["year"] = year
    if venue:
        params["venue"] = venue
    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study
    
    # List to store all papers
    all_papers = []
    
    while True:
        # Make the API request
        response = requests.get(base_url, params=params)
        
        # Check if the request was successful
        if response.status_code != 200:
            print(f"Error: {response.status_code}")
            print(f"Response: {response.text}")  # Print the error message from the API
            break
        
        # Parse the JSON response
        data = response.json()
        
        # Add the papers to the list
        all_papers.extend(data.get("data", []))
        
        # Check if there is a continuation token
        continuation_token = data.get("token")
        if not continuation_token:
            break
        
        # Update the continuation token for the next request
        params["token"] = continuation_token
    
    return all_papers

# Example usage
if __name__ == "__main__":
    # Define your search query and parameters
    query = "research software metadata"
    fields = "title"
    publication_types = "Conference,JournalArticle"
    open_access_pdf = True
    min_citation_count = 10
    year = "2009-2020"
    
    # Perform the search
    papers = search_papers(
        query=query,
        fields=fields,
        publication_types=publication_types,
        open_access_pdf=open_access_pdf,
        min_citation_count=min_citation_count,
        year=year,
        limit=9999
    )


    print(papers[0].keys())
    # Print the results
    for paper in papers:
        print(f"Title: {paper.get('paperId')}")
        print(f"Title: {paper.get('title')}")
        print("-" * 40)
