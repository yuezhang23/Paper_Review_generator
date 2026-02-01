"""
Utility module containing constants and helper functions for the paper analysis chat application.
Includes file handling, text extraction, content matching, file upload, and API-related utilities.
"""

import os
import json
import csv
import io
import uuid
import re
from typing import Dict, Any, Optional, List, Tuple
from difflib import SequenceMatcher
from collections import Counter
from fastapi import UploadFile, File as FastAPIFile, HTTPException
import httpx
import openai
import PyPDF2
from openreview_service import (
    parse_openreview_info_from_text,
    search_openreview_by_title,
    fetch_and_save_openreview_paper
)

# File storage directory
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Summary logs directory
SUMMARY_LOGS_DIR = "summary_logs"
os.makedirs(SUMMARY_LOGS_DIR, exist_ok=True)
SUMMARY_CSV_PATH = os.path.join(SUMMARY_LOGS_DIR, "paper_summaries.csv")

# Prompts directory
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# In-memory file storage (for demo - use proper storage in production)
file_storage: Dict[str, Dict[str, Any]] = {}

# When gateway runs on port 8010, it fetches file info from main backend (8000) for file_ids
MAIN_BACKEND_URL = os.getenv("MAIN_BACKEND_URL", "").rstrip("/")


async def ensure_file_info_from_main_backend(file_ids: Optional[List[str]]) -> None:
    """
    When running on gateway (port 8010), fetch file info from main backend (8000) and populate file_storage.
    Call this at the start of chat/summary/image endpoints when request has file_ids.
    """
    if not file_ids or not MAIN_BACKEND_URL:
        return
    missing = [fid for fid in file_ids if fid not in file_storage]
    if not missing:
        return
    import logging
    log = logging.getLogger(__name__)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{MAIN_BACKEND_URL}/api/file-info",
                params={"file_ids": ",".join(missing)},
            )
            if r.status_code == 200:
                data = r.json()
                for fid, info in data.get("files", {}).items():
                    file_storage[fid] = {
                        "filename": info.get("filename"),
                        "content_type": info.get("content_type"),
                        "size": info.get("size"),
                        "text_content": info.get("text_content", ""),
                        "pdf_path": info.get("pdf_path"),
                        "file_id": fid,
                    }
                log.info(f"Fetched file info for {len(data.get('files', {}))} file(s) from main backend")
    except Exception as e:
        log.warning(f"Failed to fetch file info from main backend: {e}")


# ============================================================================
# File and Text Extraction Functions
# ============================================================================

def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file"""
    try:
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"


def extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text from various file types"""
    if filename.lower().endswith('.pdf'):
        return extract_text_from_pdf(file_content)
    elif filename.lower().endswith('.txt'):
        try:
            return file_content.decode('utf-8')
        except:
            return file_content.decode('utf-8', errors='ignore')
    else:
        return f"File type not supported for text extraction: {filename}"


async def upload_files(files: List[UploadFile] = FastAPIFile(...)):
    """Upload files and extract text content. For PDFs, also saves to disk for GROBID processing."""
    try:
        file_ids = []
        for file in files:
            # Read file content
            content = await file.read()
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Extract text based on file type
            text_content = extract_text_from_file(content, file.filename)
            
            # For PDFs, save to disk for GROBID processing
            pdf_path = None
            if file.content_type == 'application/pdf' or (file.filename and file.filename.lower().endswith('.pdf')):
                # Create safe filename
                safe_filename = re.sub(r'[^\w\-_\.]', '_', file.filename) if file.filename else f'{file_id}.pdf'
                pdf_path = os.path.join(UPLOAD_DIR, safe_filename)
                
                # Save PDF to disk
                with open(pdf_path, 'wb') as f:
                    f.write(content)
                pdf_path = pdf_path  # Store absolute path
            
            # Store file metadata and content
            file_storage[file_id] = {
                "filename": file.filename,
                "content_type": file.content_type,
                "size": len(content),
                "text_content": text_content,
                "file_id": file_id,
                "pdf_path": pdf_path  # Store PDF path if it's a PDF
            }
            
            file_ids.append(file_id)
        
        return {
            "file_ids": file_ids,
            "count": len(file_ids),
            "message": f"Successfully uploaded {len(file_ids)} file(s)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading files: {str(e)}")


# ============================================================================
# Content Matching and Similarity Functions
# ============================================================================

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity between two texts using SequenceMatcher"""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def find_best_matching_paper(query: str, search_results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Find the best matching paper from Google PSE search results based on query similarity.
    
    Args:
        query: User's search query
        search_results: List of Google PSE search results
        
    Returns:
        Best matching paper dictionary or None
    """
    if not search_results:
        return None

    query_lower = query.lower()
    query_words = set(query_lower.split())
    
    best_match = None
    best_score = 0.0
    
    for result in search_results:
        title = result.get('title', '').lower()
        snippet = result.get('snippet', '').lower()
        combined_text = f"{title} {snippet}"
        
        # Calculate multiple similarity metrics
        # 1. Title similarity
        title_similarity = calculate_similarity(query, title)
        
        # 2. Keyword overlap
        combined_words = set(combined_text.split())
        keyword_overlap = len(query_words.intersection(combined_words)) / max(len(query_words), 1)
        
        # 3. Combined text similarity
        text_similarity = calculate_similarity(query, combined_text)
        
        # Weighted score: title is most important, then keyword overlap, then text similarity
        score = (title_similarity * 0.5) + (keyword_overlap * 0.3) + (text_similarity * 0.2)
        
        # Bonus for academic domains
        if any(domain in result.get('link', '').lower() for domain in ['arxiv', 'openreview', 'edu', 'acm', 'ieee']):
            score *= 1.2
        
        if score > best_score:
            best_score = score
            best_match = result
    
    return best_match


def extract_augmented_prompt_from_messages(messages: List[Dict[str, Any]]) -> str:
    """Extract the augmented part of the prompt (system messages with paper context)"""
    augmented_parts = []
    for msg in messages:
        if msg.get("role") == "system":
            content = msg.get("content", "")
            # Only include paper-related context, not the base system prompt
            if "OPENREVIEW PAPERS" in content or "RETRIEVED PAPERS" in content or "BEST MATCHING PAPER" in content or "UPLOADED FILES" in content or "GOOGLE PSE" in content:
                augmented_parts.append(content)
    return "\n\n".join(augmented_parts)


# ============================================================================
# Prompt and Configuration Utilities
# ============================================================================

def load_prompt_template(filename: str) -> str:
    """Load a prompt template from a markdown file"""
    try:
        filepath = os.path.join(PROMPTS_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            # Skip the first line if it's a markdown header (# Title)
            content = f.read()
            lines = content.split('\n')
            # Remove markdown header if present
            if lines[0].startswith('#'):
                content = '\n'.join(lines[1:]).strip()
            return content
    except Exception as e:
        # Silently return empty string if template file doesn't exist
        return ""

def log_paper_summary(paper_metadata: Dict[str, Any], augmented_prompt: str, analysis: str):
    """Log paper summary to CSV file with 3 columns: paper_metadata, augmented_prompt, analysis"""
    try:
        # Check if CSV file exists, if not create with headers
        file_exists = os.path.exists(SUMMARY_CSV_PATH)
        
        with open(SUMMARY_CSV_PATH, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['paper_metadata', 'augmented_prompt', 'analysis']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            
            if not file_exists:
                writer.writeheader()
            
            # Prepare metadata as JSON string
            metadata_json = json.dumps(paper_metadata, ensure_ascii=False)
            
            # Python's csv module will automatically handle escaping quotes and newlines
            writer.writerow({
                'paper_metadata': metadata_json,
                'augmented_prompt': augmented_prompt,
                'analysis': analysis
            })
        
        print(f"[Summary Log] Saved paper summary to {SUMMARY_CSV_PATH}")
    except Exception as e:
        print(f"[Summary Log] Error saving summary: {str(e)}")

# Load prompt templates
PAPER_ANALYSIS_SYSTEM_PROMPT = load_prompt_template("paper_analysis_system_prompt.md")
PAPER_SUMMARY_TEMPLATE = load_prompt_template("paper_summary_template.md")

# Rating scores for paper evaluation
RATING_SCORES = {
    1: "Very Strong Reject: For instance, a paper with incorrect statements, improper (e.g., offensive) language, unaddressed ethical considerations, incorrect results and/or flawed methodology (e.g., training using a test set).",
    2: "Strong Reject: For instance, a paper with major technical flaws, and/or poor evaluation, limited impact, poor reproducibility and mostly unaddressed ethical considerations.",
    3: "reject, not good enough",
    4: "Borderline reject: Technically solid paper where reasons to reject, e.g., limited evaluation, outweigh reasons to accept, e.g., good evaluation. Please use sparingly.",
    5: "marginally below the acceptance threshold",
    6: "marginally above the acceptance threshold",
    7: "Accept: Technically solid paper, with high impact on at least one sub-area, or moderate-to-high impact on more than one areas, with good-to-excellent evaluation, resources, reproducibility, and no unaddressed ethical considerations.",
    8: "accept, good paper",
    9: "Very Strong Accept: Technically flawless paper with groundbreaking impact on at least one area of AI/ML and excellent impact on multiple areas of AI/ML, with flawless evaluation, resources, and reproducibility, and no unaddressed ethical considerations.",
    10: "strong accept, should be highlighted at the conference"
}

# Paper-related query suggestions
PAPER_QUERY_SUGGESTIONS = [
    "Summarize the main contributions of this paper",
    "What is the methodology used in this paper?",
    "Explain the experimental results",
    "What are the limitations of this work?",
    "Compare this paper with similar works",
    "What datasets were used?",
    "What are the key findings?",
    "Explain the technical approach in simple terms",
    "What future work is suggested?",
    "Who are the authors and their affiliations?"
]

def format_search_results_for_context(search_results: Dict[str, Any]) -> str:
    """
    Format AI Builder search results as text context for LLM.
    Replaces format_search_results_for_context from google_pse_service.
    
    Args:
        search_results: Dictionary from web_search_paper()
        
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
        link = result.get("link") or result.get("url", "")
        snippet = result.get("snippet") or result.get("content", "")
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


# ============================================================================
# AI Builder API and Web Search Functions
# ============================================================================

# Initialize OpenAI client for AI Builder API (lazy initialization)
ai_builder_token: Optional[str] = None
client: Optional[openai.OpenAI] = None

def get_ai_builder_base_url() -> str:
    """
    Base URL for the AI Builders-compatible gateway.

    - When USE_GATEWAY_ORCHESTRATOR=true: gateway is on same server (port 8010) by default
    - Otherwise defaults to hosted AI Builders or explicit AI_BUILDER_BASE_URL

    To use the local gateway (LiteLLM + LangGraph) on the same server:
      USE_GATEWAY_ORCHESTRATOR=true
      AI_BUILDER_TOKEN=<MCP_GATEWAY_TOKEN>  # same as gateway auth
      # Optional: GATEWAY_ORCHESTRATOR_URL="http://localhost:8010" (default when merged)
    """
    if os.getenv("USE_GATEWAY_ORCHESTRATOR", "").lower() in ("true", "1", "yes"):
        gateway_url = (os.getenv("GATEWAY_ORCHESTRATOR_URL") or "http://localhost:8010").rstrip("/")
        return f"{gateway_url}/backend/v1"
    return (os.getenv("AI_BUILDER_BASE_URL") or "https://space.ai-builders.com/backend/v1").rstrip("/")

def get_ai_client() -> openai.OpenAI:
    """
    Get or create OpenAI client for AI Builder / gateway (LiteLLM).
    Tries, in order: AI_BUILDER_TOKEN, MCP_GATEWAY_TOKEN, LITELLM_PROXY_KEY.
    When gateway is used (USE_GATEWAY_ORCHESTRATOR=true), any of these tokens can be used.
    """
    global client, ai_builder_token
    if client is None:
        ai_builder_token = (
            os.getenv("AI_BUILDER_TOKEN")
            or os.getenv("MCP_GATEWAY_TOKEN")
            or os.getenv("LITELLM_PROXY_KEY")
        )
        if not ai_builder_token:
            raise ValueError(
                "No LLM token set. Set one of: AI_BUILDER_TOKEN, MCP_GATEWAY_TOKEN, LITELLM_PROXY_KEY in .env"
            )
        client = openai.OpenAI(
            base_url=get_ai_builder_base_url(),
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
                f"{get_ai_builder_base_url()}/search/",
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


def _pdf_url_from_search_result(r: Dict[str, Any]) -> Optional[str]:
    """Derive a PDF URL from a web search result. arxiv abs→pdf; arxiv/html→pdf; arxiv/pdf, .pdf, /pdf as-is."""
    url = (r.get("link") or r.get("url") or "").strip()
    if not url:
        return None
    url_lower = url.lower()
    # arxiv.org/abs/XXX → arxiv.org/pdf/XXX.pdf
    m = re.search(r"arxiv\.org/abs/([a-zA-Z0-9\.\-]+)", url_lower)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    # arxiv.org/html/XXX → arxiv.org/pdf/XXX.pdf
    m = re.search(r"arxiv\.org/html/([a-zA-Z0-9\.\-]+)", url_lower)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    if "arxiv.org/pdf" in url_lower or url_lower.endswith(".pdf"):
        return url
    if "/pdf" in url_lower or ".pdf" in url_lower:
        return url
    return url


async def web_search_for_paper_pdf(paper_name: str) -> Optional[str]:
    """
    Use AI Builder web search (/v1/search/) to find a PDF URL for a paper.
    Prefers arxiv, .pdf links; converts arxiv/abs to /pdf. Returns best URL or None.
    """
    data = await web_search_paper(paper_name, limit=15, use_academic_focus=True)
    if data.get("error") or not data.get("results"):
        return None
    results = data["results"]
    if not results:
        return None
    pdf_like = [r for r in results if _pdf_url_from_search_result(r)]
    candidates = pdf_like if pdf_like else results
    best = find_best_matching_paper(paper_name, candidates)
    if not best:
        return None
    return _pdf_url_from_search_result(best) or (best.get("link") or best.get("url"))


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
                        f"{get_ai_builder_base_url()}/search/",
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
