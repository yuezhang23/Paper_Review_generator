"""
Google Programmable Search Engine (PSE) Service Module
Handles real-time web search using Google Custom Search API
Works with OpenAI, Gemini, and DeepSeek models
"""

import os
import json
import re
from typing import Optional, List, Dict, Any
from collections import Counter
from dotenv import load_dotenv
import httpx

# Load environment variables
load_dotenv()

# Google Custom Search API configuration
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")
GOOGLE_SEARCH_BASE_URL = "https://www.googleapis.com/customsearch/v1"


def is_search_needed(query: str) -> bool:
    """
    Determine if a query needs real-time web search.
    
    Args:
        query: User's query text
        
    Returns:
        True if search is likely needed, False otherwise
    """
    query_lower = query.lower()
    
    # Keywords that indicate need for real-time search
    search_keywords = [
        "find", "search", "latest", "recent", "current", "new", "today",
        "what is", "who is", "when did", "where is", "how to",
        "papers about", "research on", "studies on", "articles about",
        "2024", "2025", "recent", "now", "current events"
    ]
    
    # Check if query contains search indicators
    has_search_keyword = any(keyword in query_lower for keyword in search_keywords)
    
    # Check if query asks about external information
    question_words = ["what", "who", "when", "where", "why", "how"]
    is_question = any(query_lower.startswith(word) for word in question_words)
    
    # Check if query mentions specific dates or time periods
    has_date = bool(re.search(r'\b(202[0-9]|202[0-9]|recent|latest|current)\b', query_lower))
    
    return has_search_keyword or (is_question and has_date) or len(query.split()) > 10


def predict_google_pse_benefit_score(query: str) -> float:
    """
    Orchestration function that predicts the likelihood (0-1) that a query would benefit from Google PSE.
    
    This function estimates how much a query would benefit from real-time web search.
    Higher scores indicate queries that would significantly benefit from Google PSE.
    
    Args:
        query: User's query text
        
    Returns:
        Float between 0.0 and 1.0 representing the prediction score
    """
    if not query or not query.strip():
        return 0.0
    
    query_lower = query.lower().strip()
    score = 0.0
    
    # Factor 1: Time-sensitive keywords (high weight: 0.3)
    time_keywords = ["latest", "recent", "current", "new", "today", "now", "2024", "2025", "2023", "2026"]
    has_time_keyword = any(keyword in query_lower for keyword in time_keywords)
    if has_time_keyword:
        score += 0.3
    
    # Factor 2: Search intent keywords (high weight: 0.25)
    search_intent_keywords = [
        "find", "search", "look for", "discover", "locate",
        "papers about", "research on", "studies on", "articles about",
        "what are", "who are", "where are"
    ]
    has_search_intent = any(keyword in query_lower for keyword in search_intent_keywords)
    if has_search_intent:
        score += 0.25
    
    # Factor 3: Question words indicating information need (medium weight: 0.2)
    question_words = ["what", "who", "when", "where", "why", "how"]
    starts_with_question = any(query_lower.startswith(word) for word in question_words)
    if starts_with_question:
        score += 0.2
    
    # Factor 4: Academic/research context (medium weight: 0.15)
    academic_keywords = ["paper", "papers", "research", "study", "studies", "article", "publication", 
                         "arxiv", "conference", "journal", "academic", "scholarly"]
    has_academic_context = any(keyword in query_lower for keyword in academic_keywords)
    if has_academic_context:
        score += 0.3
    
    # Factor 5: Query complexity/length (low weight: 0.1)
    # Longer, more complex queries often benefit more from search
    word_count = len(query.split())
    if word_count > 10:
        score += 0.1
    elif word_count > 5:
        score += 0.05
    
    # Factor 6: Specific entity/name mentions (low weight: 0.05)
    # Queries mentioning specific entities (capitalized words, proper nouns) may need current info
    has_proper_nouns = bool(re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', query))
    if has_proper_nouns and word_count > 3:
        score += 0.05
    
    # Factor 7: Comparison or evaluation requests (low weight: 0.05)
    comparison_keywords = ["compare", "difference", "versus", "vs", "better", "best", "top", "ranking"]
    has_comparison = any(keyword in query_lower for keyword in comparison_keywords)
    if has_comparison:
        score += 0.05
    
    # Penalty: Simple conversational queries (reduce score)
    simple_greetings = ["hello", "hi", "hey", "thanks", "thank you", "ok", "okay", "yes", "no"]
    if any(query_lower.strip() == greeting for greeting in simple_greetings):
        score *= 0.1  # Heavily penalize simple greetings
    
    # Penalty: Very short queries without search indicators
    if word_count <= 3 and not has_search_intent and not starts_with_question:
        score *= 0.5
    
    # Ensure score is between 0.0 and 1.0
    score = max(0.0, min(1.0, score))
    
    return round(score, 3)


async def search_google_pse(
    query: str,
    num_results: int = 10,
    search_type: str = "web"
) -> Dict[str, Any]:
    """
    Perform real-time search using Google Custom Search Engine API.
    
    Args:
        query: Search query string
        num_results: Number of results to return (max 10 per request)
        search_type: Type of search ("web" or "image")
        
    Returns:
        Dictionary containing search results and metadata
    """
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        return {
            "error": "Google PSE not configured. Please set GOOGLE_API_KEY and GOOGLE_CSE_ID in .env file",
            "results": [],
            "count": 0
        }
    
    try:
        # Prepare search query - add academic paper context if needed
        search_query = query
        if any(word in query.lower() for word in ["paper", "research", "study", "article"]):
            # Already academic-focused
            pass
        else:
            # Add academic context for better results
            search_query = f"{query} academic paper research"
        
        # Make API request
        async with httpx.AsyncClient(timeout=30.0) as client:
            params = {
                "key": GOOGLE_API_KEY,
                "cx": GOOGLE_CSE_ID,
                "q": search_query,
                "num": min(num_results, 10)  # Google API max is 10 per request
            }
            
            response = await client.get(GOOGLE_SEARCH_BASE_URL, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                # Parse results
                results = []
                items = data.get("items", [])
                
                for item in items[:num_results]:
                    result = {
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                        "display_link": item.get("displayLink", ""),
                        "formatted_url": item.get("formattedUrl", ""),
                        "source": "google_pse"
                    }
                    
                    # Extract additional metadata if available
                    if "pagemap" in item:
                        pagemap = item["pagemap"]
                        if "metatags" in pagemap:
                            metatags = pagemap["metatags"][0] if pagemap["metatags"] else {}
                            result["description"] = metatags.get("og:description", "")
                            result["image"] = metatags.get("og:image", "")
                    
                    results.append(result)
                
                return {
                    "results": results,
                    "count": len(results),
                    "total_results": data.get("searchInformation", {}).get("totalResults", "0"),
                    "search_time": data.get("searchInformation", {}).get("searchTime", 0),
                    "query": search_query,
                    "source": "google_pse"
                }
            else:
                error_data = response.json() if response.content else {}
                return {
                    "error": f"Google PSE API error: {response.status_code} - {error_data.get('error', {}).get('message', response.text)}",
                    "results": [],
                    "count": 0
                }
                
    except httpx.TimeoutException:
        return {
            "error": "Google PSE search timeout",
            "results": [],
            "count": 0
        }
    except Exception as e:
        return {
            "error": f"Google PSE search error: {str(e)}",
            "results": [],
            "count": 0
        }


async def search_google_pse_multiple_queries(
    queries: List[str],
    num_results_per_query: int = 5
) -> Dict[str, Any]:
    """
    Perform multiple Google PSE searches in parallel.
    
    Args:
        queries: List of search query strings
        num_results_per_query: Number of results per query
        
    Returns:
        Dictionary containing combined search results
    """
    if not queries:
        return {"results": [], "count": 0, "source": "google_pse"}
    
    # Execute searches in parallel
    import asyncio
    tasks = [search_google_pse(query, num_results_per_query) for query in queries]
    search_results = await asyncio.gather(*tasks)
    
    # Combine results
    all_results = []
    seen_urls = set()
    
    for result_dict in search_results:
        if "results" in result_dict:
            for result in result_dict["results"]:
                url = result.get("link", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_results.append(result)
    
    return {
        "results": all_results,
        "count": len(all_results),
        "source": "google_pse",
        "queries": queries
    }


def format_search_results_for_context(search_results: Dict[str, Any]) -> str:
    """
    Format Google PSE search results as text context for LLM.
    
    Args:
        search_results: Dictionary from search_google_pse()
        
    Returns:
        Formatted string with search results
    """
    if "error" in search_results or not search_results.get("results"):
        return ""
    
    results = search_results["results"]
    if not results:
        return ""
    
    context_parts = ["=== REAL-TIME WEB SEARCH RESULTS ===\n"]
    
    for i, result in enumerate(results, 1):
        title = result.get("title", "No title")
        link = result.get("link", "")
        snippet = result.get("snippet", "")
        display_link = result.get("display_link", "")
        
        context_parts.append(f"Result {i}:")
        context_parts.append(f"Title: {title}")
        context_parts.append(f"URL: {link}")
        if display_link:
            context_parts.append(f"Source: {display_link}")
        if snippet:
            context_parts.append(f"Summary: {snippet}")
        context_parts.append("")
    
    context_parts.append("Use the information from these search results to provide accurate, up-to-date answers. Cite sources when referencing specific information.\n")
    
    return "\n".join(context_parts)


async def enhanced_search_with_fallback(
    query: str,
    num_results: int = 10,
    use_academic_focus: bool = True
) -> Dict[str, Any]:
    """
    Enhanced search with multiple query variations and academic focus.
    
    Args:
        query: Original search query
        num_results: Number of results to return
        use_academic_focus: Whether to add academic paper context
        
    Returns:
        Dictionary with search results
    """
    # Generate query variations
    queries = [query]
    
    if use_academic_focus:
        # Add academic-focused variations
        if "paper" not in query.lower():
            queries.append(f"{query} academic paper")
        if "research" not in query.lower():
            queries.append(f"{query} research")
        if "arxiv" not in query.lower() and "paper" in query.lower():
            queries.append(f"{query} arxiv")
    
    # Limit to 3 queries to avoid too many API calls
    queries = queries[:3]
    
    # Perform search with multiple queries
    if len(queries) > 1:
        return await search_google_pse_multiple_queries(queries, num_results // len(queries))
    else:
        return await search_google_pse(query, num_results)


async def find_related_documents(
    best_matching_paper: Dict[str, Any],
    num_related: int = 5
) -> List[Dict[str, Any]]:
    """
    Find related documents/papers based on the best matching paper.
    Similar to how OpenReview provides related papers.
    
    Args:
        best_matching_paper: The best matching paper from Google PSE search
        num_related: Number of related documents to find
        
    Returns:
        List of related document dictionaries
    """
    if not best_matching_paper:
        return []
    
    related_docs = []
    title = best_matching_paper.get("title", "")
    snippet = best_matching_paper.get("snippet", "")
    
    if not title:
        return []
    
    # Extract key terms from the title and snippet
    # Remove common words and extract meaningful terms
    # Combine title and snippet for keyword extraction
    text = f"{title} {snippet}".lower()
    
    # Remove common stop words
    stop_words = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that',
        'these', 'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they',
        'what', 'which', 'who', 'when', 'where', 'why', 'how', 'about',
        'paper', 'papers', 'research', 'study', 'studies', 'method', 'methods'
    }
    
    # Extract words (3+ characters, alphanumeric)
    words = re.findall(r'\b[a-z]{3,}\b', text)
    keywords = [w for w in words if w not in stop_words]
    
    # Get most common keywords (top 3-5)
    if keywords:
        keyword_counter = Counter(keywords)
        top_keywords = [word for word, _ in keyword_counter.most_common(5)]
        
        # Create search queries for related papers
        related_queries = []
        
        # Query 1: Similar topic (use top keywords)
        if len(top_keywords) >= 2:
            related_queries.append(" ".join(top_keywords[:3]))
        
        # Query 2: Title-based search (remove common words from title)
        title_words = [w for w in re.findall(r'\b[a-z]{3,}\b', title.lower()) if w not in stop_words]
        if title_words:
            related_queries.append(" ".join(title_words[:4]))
        
        # Query 3: Academic paper search with keywords
        if top_keywords:
            related_queries.append(f"{' '.join(top_keywords[:2])} academic paper")
        
        # Limit queries to avoid too many API calls
        related_queries = related_queries[:2]
        
        # Search for related documents
        seen_urls = {best_matching_paper.get("link", "")}  # Exclude the best match itself
        
        for query in related_queries:
            try:
                search_result = await search_google_pse(query, num_results=num_related)
                if search_result.get("results"):
                    for result in search_result.get("results", []):
                        result_url = result.get("link", "")
                        # Skip if already seen or is the best match
                        if result_url and result_url not in seen_urls:
                            seen_urls.add(result_url)
                            related_docs.append({
                                "title": result.get("title", ""),
                                "url": result_url,
                                "snippet": result.get("snippet", ""),
                                "source": "google_pse",
                                "relation_type": "similar_topic"
                            })
                            # Stop if we have enough related docs
                            if len(related_docs) >= num_related:
                                break
                
                if len(related_docs) >= num_related:
                    break
            except Exception as e:
                print(f"Error finding related documents: {str(e)}")
                continue
    
    return related_docs[:num_related]


# Example usage and testing
if __name__ == "__main__":
    import asyncio
    
    async def test_search():
        """Test Google PSE search functionality"""
        print("Testing Google PSE Search Service\n")
        
        # Test 1: Basic search
        print("Test 1: Basic search")
        result = await search_google_pse("transformer architecture neural networks", num_results=5)
        print(f"Results: {result.get('count', 0)}")
        if result.get("results"):
            print(f"First result: {result['results'][0].get('title', 'N/A')}")
        print()
        
        # Test 2: Academic paper search
        print("Test 2: Academic paper search")
        result = await search_google_pse("attention mechanism 2024", num_results=5)
        print(f"Results: {result.get('count', 0)}")
        if result.get("results"):
            print(f"First result: {result['results'][0].get('title', 'N/A')}")
        print()
        
        # Test 3: Enhanced search
        print("Test 3: Enhanced search with multiple queries")
        result = await enhanced_search_with_fallback("reinforcement learning", num_results=10)
        print(f"Results: {result.get('count', 0)}")
        print(f"Queries used: {result.get('queries', [])}")
        print()
        
        # Test 4: Format results for context
        print("Test 4: Format results for LLM context")
        formatted = format_search_results_for_context(result)
        print(formatted[:500] + "..." if len(formatted) > 500 else formatted)
        print()
        
        # Test 5: Search detection
        print("Test 5: Search need detection")
        test_queries = [
            "What is a transformer?",
            "Find recent papers on GPT-4",
            "Hello, how are you?",
            "What are the latest developments in AI in 2024?"
        ]
        for q in test_queries:
            needs_search = is_search_needed(q)
            print(f"Query: '{q}' -> Needs search: {needs_search}")
    
    asyncio.run(test_search())
