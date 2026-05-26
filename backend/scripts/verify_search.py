import os
import sys
from typing import Any

from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Load env
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

from config import Configuration
from services.search import dispatch_search


def _mask_key(value: str | None) -> str:
    if not value:
        return "None"
    return "*" * 8 + value[-4:]


def _print_results(results: list[dict[str, Any]]) -> None:
    for index, item in enumerate(results, 1):
        title = item.get("title") or "(untitled)"
        url = item.get("url") or "(no url)"
        authority = item.get("authority_score")
        suffix = f" authority={authority}" if authority is not None else ""
        print(f"  {index}. {title} ({url}){suffix}")


def test_search_configuration() -> None:
    print("Testing search configuration...")
    
    # Load config from env
    config = Configuration.from_env()
    
    # Print loaded keys (masked)
    tavily_key = config.tavily_api_key
    serpapi_key = config.serpapi_api_key
    
    print(f"Tavily Key: {_mask_key(tavily_key)}")
    print(f"SerpApi Key: {_mask_key(serpapi_key)}")
    print(f"Search API: {config.search_api.value}")

    available_backends = []
    if tavily_key:
        available_backends.append("tavily")
    if serpapi_key:
        available_backends.append("serpapi")
    print(f"Available Backends: {available_backends or 'None'}")

    if not available_backends:
        print("❌ No search backends available. Please check API keys.")
        return

    # Test search
    query = "DeepSeek technology overview"
    print(f"\nRunning search for: '{query}'...")
    
    try:
        response, notices, backend = dispatch_search(query, config)
        results = response.get("results", []) if response else []
        print(f"✅ Search completed using backend: {backend}")
        if notices:
            print("Notices:")
            for notice in notices:
                print(f"  - {notice}")
        print(f"Found {len(results)} results:")
        _print_results(results)
            
    except Exception as e:
        print(f"❌ Search failed: {e}")

if __name__ == "__main__":
    test_search_configuration()
