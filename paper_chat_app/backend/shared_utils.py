"""
Shared utility functions used across different service modules
"""

import os
import re
from typing import Optional, List, Dict, Any, Tuple
from collections import Counter
import httpx
import openai
from openreview_service import (
    parse_openreview_info_from_text,
    search_openreview_by_title,
    fetch_and_save_openreview_paper
)
from utils import file_storage

# Initialize OpenAI client for AI Builder API (lazy initialization)
ai_builder_token: Optional[str] = None
client: Optional[openai.OpenAI] = None

def get_ai_client() -> openai.OpenAI:
    """Get or create OpenAI client for AI Builder API"""
    global client, ai_builder_token
    if client is None:
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            raise ValueError("AI_BUILDER_TOKEN environment variable is required. Please set it in your .env file.")
        client = openai.OpenAI(
            base_url="https://space.ai-builders.com/backend/v1",
            api_key=ai_builder_token
        )
    return client


def predict_search_benefit_score(query: str) -> float:
    """
    Predict the likelihood (0-1) that a query would benefit from real-time web search.
    
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
    
    # Factor 4: Academic/research context (medium weight: 0.3)
    academic_keywords = ["paper", "papers", "research", "study", "studies", "article", "publication", 
                         "arxiv", "conference", "journal", "academic", "scholarly"]
    has_academic_context = any(keyword in query_lower for keyword in academic_keywords)
    if has_academic_context:
        score += 0.3
    
    # Factor 5: Query complexity/length (low weight: 0.1)
    word_count = len(query.split())
    if word_count > 10:
        score += 0.1
    elif word_count > 5:
        score += 0.05
    
    # Factor 6: Specific entity/name mentions (low weight: 0.05)
    has_proper_nouns = bool(re.search(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', query))
    if has_proper_nouns and word_count > 3:
        score += 0.05
    
    # Factor 7: Comparison or evaluation requests (low weight: 0.05)
    comparison_keywords = ["compare", "difference", "versus", "vs", "better", "best", "top", "ranking"]
    has_comparison = any(keyword in query_lower for keyword in comparison_keywords)
    if has_comparison:
        score += 0.05
    
    # Penalty: Simple conversational queries
    simple_greetings = ["hello", "hi", "hey", "thanks", "thank you", "ok", "okay", "yes", "no"]
    if any(query_lower.strip() == greeting for greeting in simple_greetings):
        score *= 0.1
    
    # Penalty: Very short queries without search indicators
    if word_count <= 3 and not has_search_intent and not starts_with_question:
        score *= 0.5
    
    # Ensure score is between 0.0 and 1.0
    score = max(0.0, min(1.0, score))
    
    return round(score, 3)


async def web_search_paper(
    query: str, 
    limit: int = 10,
    use_academic_focus: bool = True
) -> Dict[str, Any]:
    """
    Enhanced web search for papers using AI Builder API.
    
    Args:
        query: Search query string
        limit: Number of results to return
        use_academic_focus: Whether to add academic paper context
        
    Returns:
        Dictionary containing search results
    """
    try:
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            return {"results": [], "count": 0, "source": "none", "error": "AI_BUILDER_TOKEN not configured"}
        
        # Generate query variations for better results
        keywords = [query]
        
        if use_academic_focus:
            # Add academic-focused variations
            if "paper" not in query.lower():
                keywords.append(f"{query} academic paper")
            if "research" not in query.lower():
                keywords.append(f"{query} research")
            if "arxiv" not in query.lower() and "paper" in query.lower():
                keywords.append(f"{query} arxiv")
        
        # Limit to 3 keywords to avoid too many API calls
        keywords = keywords[:3]
        
        # Use AI Builder API search endpoint
        async with httpx.AsyncClient(timeout=30.0) as http_client:
            response = await http_client.post(
                "https://space.ai-builders.com/backend/v1/search/",
                headers={"Authorization": f"Bearer {ai_builder_token}"},
                json={"keywords": keywords, "max_results": limit},
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                results = []
                seen_urls = set()
                
                # Process results from all queries
                for query_result in data.get("queries", []):
                    response_data = query_result.get("response", {})
                    for result in response_data.get("results", []):
                        url = result.get("url", "")
                        # Skip duplicates
                        if url and url not in seen_urls:
                            seen_urls.add(url)
                            # Convert to Google PSE-compatible format
                            results.append({
                                "title": result.get("title", ""),
                                "link": url,
                                "url": url,
                                "snippet": result.get("content", ""),
                                "content": result.get("content", ""),
                                "display_link": result.get("url", "").split("/")[2] if url else "",
                                "formatted_url": url,
                                "source": "web_search"
                            })
                            if len(results) >= limit:
                                break
                    if len(results) >= limit:
                        break
                
                return {
                    "results": results[:limit],
                    "count": len(results),
                    "source": "web_search",
                    "query": query,
                    "queries": keywords
                }
            else:
                error_data = response.json() if response.content else {}
                return {
                    "error": f"AI Builder API error: {response.status_code} - {error_data.get('detail', response.text)}",
                    "results": [],
                    "count": 0,
                    "source": "web_search"
                }
    except httpx.TimeoutException:
        return {
            "error": "AI Builder search timeout",
            "results": [],
            "count": 0,
            "source": "web_search"
        }
    except Exception as e:
        return {
            "error": f"AI Builder search error: {str(e)}",
            "results": [],
            "count": 0,
            "source": "web_search"
        }


async def find_related_documents_ai_builder(
    best_matching_paper: Dict[str, Any],
    num_related: int = 5
) -> List[Dict[str, Any]]:
    """
    Find related documents/papers based on the best matching paper using AI Builder API.
    
    Args:
        best_matching_paper: The best matching paper from search results
        num_related: Number of related documents to find
        
    Returns:
        List of related document dictionaries
    """
    if not best_matching_paper:
        return []
    
    related_docs = []
    title = best_matching_paper.get("title", "")
    snippet = best_matching_paper.get("snippet") or best_matching_paper.get("content", "")
    
    if not title:
        return []
    
    # Extract key terms from the title and snippet
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
        
        # Search for related documents using AI Builder API
        seen_urls = {best_matching_paper.get("link") or best_matching_paper.get("url", "")}
        
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            return []
        
        for query in related_queries:
            try:
                async with httpx.AsyncClient(timeout=30.0) as http_client:
                    response = await http_client.post(
                        "https://space.ai-builders.com/backend/v1/search/",
                        headers={"Authorization": f"Bearer {ai_builder_token}"},
                        json={"keywords": [query], "max_results": num_related},
                        timeout=30.0
                    )
                    if response.status_code == 200:
                        data = response.json()
                        for query_result in data.get("queries", []):
                            response_data = query_result.get("response", {})
                            for result in response_data.get("results", []):
                                result_url = result.get("url", "")
                                # Skip if already seen or is the best match
                                if result_url and result_url not in seen_urls:
                                    seen_urls.add(result_url)
                                    related_docs.append({
                                        "title": result.get("title", ""),
                                        "url": result_url,
                                        "link": result_url,
                                        "snippet": result.get("content", ""),
                                        "content": result.get("content", ""),
                                        "source": "web_search",
                                        "relation_type": "similar_topic"
                                    })
                                    # Stop if we have enough related docs
                                    if len(related_docs) >= num_related:
                                        break
                    
                    if len(related_docs) >= num_related:
                        break
            except Exception as e:
                print(f"[AI Builder Search] Error finding related documents: {str(e)}")
                continue
    
    return related_docs[:num_related]


async def extract_paper_content(
    file_ids: Optional[List[str]] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    use_openreview: bool = True
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Extract paper text content from files, URL, or paper name.
    
    Args:
        file_ids: List of file IDs from uploaded files
        paper_url: URL to paper (OpenReview or other)
        paper_name: Paper name/title to search for
        use_openreview: Whether to use OpenReview for URL/name search
    
    Returns:
        tuple: (paper_text: str, paper_metadata: Optional[Dict[str, Any]])
        paper_metadata contains title, authors, abstract, etc. if available
    """
    paper_text = ""
    paper_metadata = None
    
    # Priority 1: Extract from uploaded files
    if file_ids and len(file_ids) > 0:
        for file_id in file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                paper_text += file_info.get('text_content', '') + "\n\n"
        if paper_text:
            return paper_text.strip(), paper_metadata
    
    # Priority 2: Extract from URL (check if OpenReview URL first)
    if paper_url:
        # Check if it's an OpenReview URL
        if use_openreview and 'openreview.net' in paper_url:
            try:
                parsed_info = parse_openreview_info_from_text(paper_url)
                paper_ids = parsed_info.get('paper_ids', [])
                if paper_ids:
                    paper_id = paper_ids[0]
                    # Fetch paper from OpenReview
                    paper_data = await fetch_and_save_openreview_paper(paper_id)
                    if paper_data:
                        paper_metadata = {
                            'paper_id': paper_data.get('paper_id'),
                            'title': paper_data.get('title'),
                            'authors': paper_data.get('authors', []),
                            'abstract': paper_data.get('abstract'),
                            'venue': paper_data.get('venue'),
                            'year': paper_data.get('year')
                        }
                        # Use PDF text if available, otherwise abstract
                        if paper_data.get('pdf_text'):
                            paper_text = paper_data['pdf_text']
                        elif paper_data.get('abstract'):
                            paper_text = paper_data['abstract']
                        if paper_text:
                            return paper_text.strip(), paper_metadata
            except Exception as e:
                print(f"[Paper Extraction] Error fetching from OpenReview URL: {str(e)}")
        
        # Fallback to web search for non-OpenReview URLs
        try:
            web_search_results = await web_search_paper(paper_url, limit=1)
            if web_search_results.get("results"):
                best_match = web_search_results["results"][0]
                paper_text = best_match.get("snippet", "") or best_match.get("content", "")
                paper_metadata = {
                    'title': best_match.get('title'),
                    'url': best_match.get('link') or best_match.get('url'),
                    'source': 'web_search'
                }
                if paper_text:
                    return paper_text.strip(), paper_metadata
        except Exception as e:
            print(f"[Paper Extraction] Error fetching from URL: {str(e)}")
    
    # Priority 3: Search by paper name (try OpenReview first)
    if paper_name:
        if use_openreview:
            try:
                # Search OpenReview by title
                papers = await search_openreview_by_title(paper_name, limit=1)
                if papers and len(papers) > 0:
                    matched_paper = papers[0]
                    paper_id = matched_paper.get('id') or matched_paper.get('paper_id')
                    if paper_id:
                        # Fetch full paper from OpenReview
                        paper_data = await fetch_and_save_openreview_paper(paper_id)
                        if paper_data:
                            paper_metadata = {
                                'paper_id': paper_data.get('paper_id'),
                                'title': paper_data.get('title'),
                                'authors': paper_data.get('authors', []),
                                'abstract': paper_data.get('abstract'),
                                'venue': paper_data.get('venue'),
                                'year': paper_data.get('year')
                            }
                            # Use PDF text if available, otherwise abstract
                            if paper_data.get('pdf_text'):
                                paper_text = paper_data['pdf_text']
                            elif paper_data.get('abstract'):
                                paper_text = paper_data['abstract']
                            if paper_text:
                                return paper_text.strip(), paper_metadata
            except Exception as e:
                print(f"[Paper Extraction] Error searching OpenReview by name: {str(e)}")
        
        # Fallback to web search
        try:
            web_search_results = await web_search_paper(paper_name, limit=1)
            if web_search_results.get("results"):
                best_match = web_search_results["results"][0]
                paper_text = best_match.get("snippet", "") or best_match.get("content", "")
                paper_metadata = {
                    'title': best_match.get('title'),
                    'url': best_match.get('link') or best_match.get('url'),
                    'source': 'web_search'
                }
                if paper_text:
                    return paper_text.strip(), paper_metadata
        except Exception as e:
            print(f"[Paper Extraction] Error searching web by name: {str(e)}")
    
    return paper_text.strip(), paper_metadata
