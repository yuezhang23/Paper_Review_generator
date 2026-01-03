#!/usr/bin/env python3
"""
Standalone test script for Google PSE (Programmable Search Engine) integration.
Tests real-time search functionality for all models except supermind-agent-v1.
"""

import asyncio
import os
import sys
from dotenv import load_dotenv

# Add parent directory to path to import service
sys.path.insert(0, os.path.dirname(__file__))

from google_pse_service import (
    search_google_pse,
    enhanced_search_with_fallback,
    format_search_results_for_context,
    is_search_needed
)

# Load environment variables
load_dotenv()


async def test_google_pse():
    """Test Google PSE search functionality"""
    print("=" * 80)
    print("Google PSE (Programmable Search Engine) Test Script")
    print("=" * 80)
    print()
    
    # Check configuration
    google_api_key = os.getenv("GOOGLE_API_KEY")
    google_cse_id = os.getenv("GOOGLE_CSE_ID")
    
    if not google_api_key or not google_cse_id:
        print("❌ ERROR: Google PSE not configured!")
        print()
        print("Please set the following environment variables in your .env file:")
        print("  GOOGLE_API_KEY=your_google_api_key")
        print("  GOOGLE_CSE_ID=your_custom_search_engine_id")
        print()
        print("To get these credentials:")
        print("  1. Go to https://console.cloud.google.com/")
        print("  2. Create a project or select an existing one")
        print("  3. Enable the Custom Search API")
        print("  4. Create credentials (API Key)")
        print("  5. Go to https://programmablesearchengine.google.com/")
        print("  6. Create a Custom Search Engine")
        print("  7. Get your Search Engine ID (CSE ID)")
        print()
        return False
    
    print("✅ Configuration found:")
    print(f"   API Key: {google_api_key[:10]}...{google_api_key[-4:]}")
    print(f"   CSE ID: {google_cse_id}")
    print()
    
    # Test 1: Search need detection
    print("-" * 80)
    print("Test 1: Search Need Detection")
    print("-" * 80)
    test_queries = [
        ("What is a transformer?", True),
        ("Find recent papers on GPT-4", True),
        ("Hello, how are you?", False),
        ("What are the latest developments in AI in 2024?", True),
        ("Summarize this paper", False),
        ("Search for papers about neural networks", True),
    ]
    
    for query, expected in test_queries:
        result = is_search_needed(query)
        status = "✅" if result == expected else "❌"
        print(f"{status} Query: '{query}'")
        print(f"  Expected: {expected}, Got: {result}")
        print()
    
    # Test 2: Basic search
    print("-" * 80)
    print("Test 2: Basic Google PSE Search")
    print("-" * 80)
    query = "transformer architecture neural networks"
    print(f"Query: '{query}'")
    print("Searching...")
    
    result = await search_google_pse(query, num_results=5)
    
    if result.get("error"):
        print(f"❌ Error: {result['error']}")
        return False
    
    print(f"✅ Found {result.get('count', 0)} results")
    if result.get("results"):
        print("\nTop 3 results:")
        for i, res in enumerate(result["results"][:3], 1):
            print(f"\n  {i}. {res.get('title', 'No title')}")
            print(f"     URL: {res.get('link', 'No URL')}")
            print(f"     Snippet: {res.get('snippet', 'No snippet')[:100]}...")
    print()
    
    # Test 3: Academic paper search
    print("-" * 80)
    print("Test 3: Academic Paper Search")
    print("-" * 80)
    query = "attention mechanism 2024"
    print(f"Query: '{query}'")
    print("Searching...")
    
    result = await search_google_pse(query, num_results=5)
    
    if result.get("error"):
        print(f"❌ Error: {result['error']}")
    else:
        print(f"✅ Found {result.get('count', 0)} results")
        if result.get("results"):
            print("\nTop result:")
            top = result["results"][0]
            print(f"  Title: {top.get('title', 'No title')}")
            print(f"  URL: {top.get('link', 'No URL')}")
    print()
    
    # Test 4: Enhanced search with multiple queries
    print("-" * 80)
    print("Test 4: Enhanced Search (Multiple Query Variations)")
    print("-" * 80)
    query = "reinforcement learning"
    print(f"Query: '{query}'")
    print("Searching with enhanced method...")
    
    result = await enhanced_search_with_fallback(query, num_results=10, use_academic_focus=True)
    
    if result.get("error"):
        print(f"❌ Error: {result['error']}")
    else:
        print(f"✅ Found {result.get('count', 0)} results")
        if result.get("queries"):
            print(f"Queries used: {result['queries']}")
        if result.get("results"):
            print(f"\nTop 3 results:")
            for i, res in enumerate(result["results"][:3], 1):
                print(f"  {i}. {res.get('title', 'No title')}")
    print()
    
    # Test 5: Format results for LLM context
    print("-" * 80)
    print("Test 5: Format Results for LLM Context")
    print("-" * 80)
    if result.get("results"):
        formatted = format_search_results_for_context(result)
        print("Formatted context (first 500 chars):")
        print(formatted[:500] + "..." if len(formatted) > 500 else formatted)
        print()
    
    # Test 6: Real-world academic queries
    print("-" * 80)
    print("Test 6: Real-World Academic Queries")
    print("-" * 80)
    academic_queries = [
        "GPT-4 architecture details",
        "latest transformer improvements 2024",
        "neural architecture search papers",
    ]
    
    for query in academic_queries:
        print(f"\nQuery: '{query}'")
        result = await search_google_pse(query, num_results=3)
        if result.get("results"):
            print(f"  ✅ Found {result.get('count', 0)} results")
            print(f"  Top result: {result['results'][0].get('title', 'N/A')[:60]}...")
        else:
            print(f"  ❌ No results or error: {result.get('error', 'Unknown')}")
    
    print()
    print("=" * 80)
    print("✅ All tests completed!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = asyncio.run(test_google_pse())
    sys.exit(0 if success else 1)
