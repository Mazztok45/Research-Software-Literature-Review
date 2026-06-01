import requests
import json
import os
import time
from datetime import datetime

# Create output directory
output_dir = "scopus-data"
os.makedirs(output_dir, exist_ok=True)

# API configuration
api_key = os.environ["SCOPUS_API_KEY"]
base_url = "https://api.elsevier.com/content/search/scopus"

# Your set of queries with field-specific syntax preserved
queries = [
    "research software metadata",
    "scientific software metadata",
    "software citation metadata",
    "code metadata reproducibility",
    "software discovery metadata",
    "codemeta",
    "CITATION.cff",
    "citation file format",
    "ROCrate software",
    "research software codemeta",
    "software metadata schema.org",
    "software metadata FAIR",
    "FAIR principles software",
    "software metadata reuse",
    "software preservation metadata",
    "software credit metadata",
    "software documentation metadata",
    "research software engineer metadata",
    "software sustainability metadata",
    "package metadata research",
]


# Convert simple queries to field-specific queries for better precision
def enhance_query(query):
    """Less restrictive query enhancement"""
    if any(op in query for op in ['TITLE(', 'ABS(', 'KEY(', 'TITLE-ABS-KEY(']):
        return query

    # Use OR instead of AND for broader results
    terms = query.split()
    if len(terms) > 1:
        return f'TITLE-ABS-KEY({" OR ".join(terms)})'
    else:
        return f'TITLE-ABS-KEY({query})'


# Apply query enhancement
enhanced_queries = [enhance_query(query) for query in queries]


def search_scopus(query, api_key, start=0, count=25):
    """Search Scopus API with a given query"""
    params = {
        "query": query,
        "apiKey": api_key,
        "count": count,
        "start": start,
        "sort": "-coverDate",  # Most recent first
        "field": "title,creator,coverDate,publicationName,doi,description,authkeywords,citedby-count"
        # Request specific fields
    }

    try:
        response = requests.get(base_url, params=params, headers={'Accept': 'application/json'})
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error for query '{query}': {e}")
        return None


def process_results(data, original_query, enhanced_query):
    """Process and return results from Scopus response"""
    if not data or 'search-results' not in data:
        return []

    results = []
    entries = data['search-results'].get('entry', [])

    for article in entries:
        result = {
            'original_query': original_query,
            'enhanced_query': enhanced_query,
            'title': article.get('dc:title', 'No Title'),
            'creator': article.get('dc:creator', 'No Creator'),
            'publication_name': article.get('prism:publicationName', 'No Publication Name'),
            'cover_date': article.get('prism:coverDate', 'No Date'),
            'doi': article.get('prism:doi', 'No DOI'),
            'abstract': article.get('dc:description', 'No abstract'),
            'cited_by_count': article.get('citedby-count', 0),
            'keywords': article.get('authkeywords', 'No keywords'),
            'scopus_id': article.get('dc:identifier', '').split(':')[-1] if 'dc:identifier' in article else '',
            'search_timestamp': datetime.now().isoformat()
        }
        results.append(result)

    return results


def export_to_json(data, filename):
    """Export data to JSON file"""
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported {len(data)} results to {filepath}")


def main():
    all_results = []
    query_stats = []

    for i, (original_query, enhanced_query) in enumerate(zip(queries, enhanced_queries)):
        print(f"\n{'=' * 80}")
        print(f"Processing query {i + 1}/{len(queries)}")
        print(f"Original: '{original_query}'")
        print(f"Enhanced: '{enhanced_query}'")
        print(f"{'=' * 80}")

        # Search Scopus
        data = search_scopus(enhanced_query, api_key)

        if data:
            # Process results
            results = process_results(data, original_query, enhanced_query)
            total_results = int(data['search-results'].get('opensearch:totalResults', 0))

            print(f"Found {total_results} total results, processing {len(results)} articles")

            # Add to combined results
            all_results.extend(results)

            # Save individual query results
            if results:
                # Create safe filename from original query
                safe_query = "".join(c for c in original_query if c.isalnum() or c in (' ', '-', '_')).rstrip()
                safe_query = safe_query.replace(' ', '_')[:50]  # Limit length
                filename = f"scopus_{safe_query}_{datetime.now().strftime('%Y%m%d')}.json"
                export_to_json({
                    'metadata': {
                        'original_query': original_query,
                        'enhanced_query': enhanced_query,
                        'total_results': total_results,
                        'processed_results': len(results),
                        'execution_time': datetime.now().isoformat()
                    },
                    'results': results
                }, filename)

            # Store statistics
            query_stats.append({
                'original_query': original_query,
                'enhanced_query': enhanced_query,
                'total_results': total_results,
                'processed_results': len(results),
                'execution_time': datetime.now().isoformat()
            })

            # Add delay to respect API rate limits
            time.sleep(1)
        else:
            print(f"No results or error for query: '{original_query}'")
            query_stats.append({
                'original_query': original_query,
                'enhanced_query': enhanced_query,
                'total_results': 0,
                'processed_results': 0,
                'error': 'API request failed',
                'execution_time': datetime.now().isoformat()
            })

    # Export combined results
    if all_results:
        combined_filename = f"scopus_combined_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        export_to_json({
            'metadata': {
                'total_queries': len(queries),
                'total_articles': len(all_results),
                'execution_time': datetime.now().isoformat()
            },
            'results': all_results
        }, combined_filename)

    # Export query statistics
    stats_filename = f"scopus_query_statistics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    export_to_json(query_stats, stats_filename)

    # Print summary
    print(f"\n{'=' * 80}")
    print("SEARCH SUMMARY")
    print(f"{'=' * 80}")
    total_articles = len(all_results)
    successful_queries = sum(1 for stat in query_stats if stat.get('processed_results', 0) > 0)

    print(f"Total queries processed: {len(queries)}")
    print(f"Successful queries: {successful_queries}")
    print(f"Total articles found: {total_articles}")

    # Print top queries by results
    print(f"\nTop queries by results:")
    sorted_stats = sorted([s for s in query_stats if s.get('processed_results', 0) > 0],
                          key=lambda x: x.get('processed_results', 0), reverse=True)

    for i, stat in enumerate(sorted_stats[:5], 1):  # Top 5
        print(f"  {i}. '{stat['original_query']}': {stat['processed_results']} results")
        print(f"     (Enhanced: '{stat['enhanced_query']}')")


if __name__ == "__main__":
    main()