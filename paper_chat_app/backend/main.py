"""
FastAPI Backend for Academic Paper Analysis Chat Application
Integrates with AI Builder API (Grok) and OpenReview API
"""

import os
import json
import uuid
import io
import re
import csv
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File as FastAPIFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import openai
from dotenv import load_dotenv
import asyncio
import httpx
import PyPDF2
from difflib import SequenceMatcher
from openreview_service import (
    get_openreview_client,
    parse_openreview_info_from_text,
    search_openreview_by_title,
    fetch_and_save_openreview_paper,
    retrieve_openreview_papers,
    create_papers_selection_list
)
from google_pse_service import (
    search_google_pse,
    enhanced_search_with_fallback,
    format_search_results_for_context,
    is_search_needed,
    find_related_documents
)
from utils import (
    UPLOAD_DIR,
    SUMMARY_LOGS_DIR,
    SUMMARY_CSV_PATH,
    PROMPTS_DIR,
    file_storage,
    load_prompt_template,
    PAPER_ANALYSIS_SYSTEM_PROMPT,
    PAPER_SUMMARY_TEMPLATE,
    RATING_SCORES,
    PAPER_QUERY_SUGGESTIONS
)

# Load environment variables
load_dotenv()

app = FastAPI(title="Paper Analysis Chat API")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

# Constants and utilities are imported from utils module

# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "grok-4-fast"
    paper_id: Optional[str] = None
    paper_context: Optional[Dict[str, Any]] = None
    use_openreview: Optional[bool] = False
    file_ids: Optional[List[str]] = None
    use_google_pse: Optional[bool] = True  # Enable Google PSE search for non-supermind models

class PaperSearchRequest(BaseModel):
    query: str
    venue: Optional[str] = None
    limit: int = 10
    use_openreview: bool = False  # Toggle to enable/disable OpenReview search

class TavilySearchRequest(BaseModel):
    keywords: List[str]
    max_results: int = 6

class MultiModelChatRequest(BaseModel):
    messages: List[ChatMessage]
    models: List[str]  # List of model IDs to use
    paper_id: Optional[str] = None
    paper_context: Optional[Dict[str, Any]] = None

class PaperContext(BaseModel):
    paper_id: str
    title: str
    authors: List[str]
    abstract: str
    venue: Optional[str] = None
    reviews: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any]

# Constants are imported from utils module

@app.get("/")
async def root():
    return {"message": "Paper Analysis Chat API", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/suggestions")
async def get_suggestions():
    """Get paper-related query suggestions"""
    return {"suggestions": PAPER_QUERY_SUGGESTIONS}

@app.get("/api/models")
async def get_available_models():
    """Get list of available AI models"""
    try:
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            raise HTTPException(status_code=500, detail="AI_BUILDER_TOKEN not configured")
        
        # Get models from AI Builder API
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(
                "https://space.ai-builders.com/backend/v1/models",
                headers={"Authorization": f"Bearer {ai_builder_token}"}
            )
            if response.status_code == 200:
                models_data = response.json()
                # Filter and format available models
                available_models = [
                {
                    "id": "grok-4-fast",
                    "name": "Grok-4 Fast",
                    "description": "Fast and efficient model from X.AI"
                },
                {
                    "id": "gpt-5",
                    "name": "GPT-5",
                    "description": "OpenAI GPT-5 model"
                },
                {
                    "id": "gemini-2.5-pro",
                    "name": "Gemini 2.5 Pro",
                    "description": "Google's Gemini 2.5 Pro model"
                },
                {
                    "id": "gemini-3-flash-preview",
                    "name": "Gemini 3 Flash",
                    "description": "Fast Gemini reasoning model"
                },
                {
                    "id": "deepseek",
                    "name": "DeepSeek",
                    "description": "Fast and cost-effective chat model"
                },
                {
                    "id": "supermind-agent-v1",
                    "name": "Supermind Agent",
                    "description": "Multi-tool agent with web search capabilities"
                }
                ]
                return {"models": available_models}
            else:
                # Return default models if API call fails
                return {
                    "models": [
                        {"id": "grok-4-fast", "name": "Grok-4 Fast", "description": "Fast and efficient model"},
                        {"id": "gpt-5", "name": "GPT-5", "description": "OpenAI GPT-5 model"},
                        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Google's Gemini model"},
                        {"id": "deepseek", "name": "DeepSeek", "description": "Fast and cost-effective"},
                        {"id": "supermind-agent-v1", "name": "Supermind Agent", "description": "Multi-tool agent with search"}
                    ]
                }
    except Exception as e:
        # Return default models on error
        return {
            "models": [
                {"id": "grok-4-fast", "name": "Grok-4 Fast", "description": "Fast and efficient model"},
                {"id": "gpt-5", "name": "GPT-5", "description": "OpenAI GPT-5 model"},
                {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "description": "Google's Gemini model"},
                {"id": "deepseek", "name": "DeepSeek", "description": "Fast and cost-effective"},
                {"id": "supermind-agent-v1", "name": "Supermind Agent", "description": "Multi-tool agent with search"}
            ]
        }

@app.post("/api/search-paper")
async def search_paper(request: PaperSearchRequest):
    """Search for papers with optional OpenReview integration
    
    If use_openreview is True:
        - Search OpenReview first
        - Fallback to AI Builder API (web search) if not found in OpenReview
    If use_openreview is False:
        - Use AI Builder API (web search) only
    """
    try:
        results = []
        source_used = "web_search"
        
        # If OpenReview toggle is enabled, try OpenReview first
        if request.use_openreview:
            or_client = get_openreview_client()
            if or_client:
                try:
                    search_results = or_client.search_notes(
                        term=request.query,
                        limit=request.limit
                    ) if hasattr(or_client, 'search_notes') else []
                    
                    for note in search_results[:request.limit]:
                        note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                        content = note_dict.get('content', {})
                        
                        results.append({
                            "id": note_dict.get('id'),
                            "title": content.get('title', {}).get('value', '') if isinstance(content.get('title'), dict) else str(content.get('title', '')),
                            "authors": content.get('authors', {}).get('value', []) if isinstance(content.get('authors'), dict) else (content.get('authors', []) if isinstance(content.get('authors'), list) else []),
                            "abstract": content.get('abstract', {}).get('value', '') if isinstance(content.get('abstract'), dict) else str(content.get('abstract', '')),
                            "venue": note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else '',
                            "forum": note_dict.get('forum'),
                            "source": "openreview"
                        })
                    
                    if results:
                        source_used = "openreview"
                except Exception as e:
                    # OpenReview search failed, will fallback to web search
                    pass
        
        # If no OpenReview results (either toggle is off or no results found), use AI Builder API web search
        if len(results) == 0:
            web_results = await web_search_paper(request.query, request.limit)
            results = web_results.get("results", [])
            source_used = "web_search"
        
        return {
            "results": results,
            "count": len(results),
            "source": source_used
        }
    except Exception as e:
        # Final fallback to web search
        return await web_search_paper(request.query, request.limit)

@app.post("/api/search-tavily")
async def search_tavily(request: TavilySearchRequest):
    """Search for papers using Tavily search engine"""
    try:
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            raise HTTPException(status_code=500, detail="AI_BUILDER_TOKEN not configured")
        
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://space.ai-builders.com/backend/v1/search/",
                headers={"Authorization": f"Bearer {ai_builder_token}"},
                json={
                    "keywords": request.keywords,
                    "max_results": request.max_results
                },
                timeout=30.0
            )
            
            if response.status_code == 200:
                data = response.json()
                results = []
                
                # Process search results
                for query_result in data.get("queries", []):
                    keyword = query_result.get("keyword", "")
                    response_data = query_result.get("response", {})
                    
                    for result in response_data.get("results", []):
                        results.append({
                            "id": result.get("url", ""),
                            "title": result.get("title", ""),
                            "content": result.get("content", ""),
                            "url": result.get("url", ""),
                            "score": result.get("score", 0),
                            "published_date": result.get("published_date"),
                            "author": result.get("author"),
                            "keyword": keyword,
                            "source": "tavily"
                        })
                
                return {
                    "results": results,
                    "count": len(results),
                    "combined_answer": data.get("combined_answer"),
                    "source": "tavily"
                }
            else:
                raise HTTPException(status_code=response.status_code, detail=response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Tavily search error: {str(e)}")

async def web_search_paper(query: str, limit: int = 10):
    """Fallback web search for papers not in OpenReview"""
    try:
        ai_builder_token = os.getenv("AI_BUILDER_TOKEN")
        if not ai_builder_token:
            return {"results": [], "count": 0, "source": "none", "error": "AI_BUILDER_TOKEN not configured"}
        
        # Use AI Builder API search endpoint
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(
                "https://space.ai-builders.com/backend/v1/search/",
                headers={"Authorization": f"Bearer {ai_builder_token}"},
                json={"keywords": [f"{query} academic paper", f"{query} arxiv"], "max_results": limit},
                timeout=30.0
            )
            if response.status_code == 200:
                data = response.json()
                results = []
                for query_result in data.get("queries", []):
                    response_data = query_result.get("response", {})
                    for result in response_data.get("results", [])[:limit]:
                        results.append({
                            "id": result.get("url", ""),
                            "title": result.get("title", ""),
                            "authors": [],
                            "abstract": result.get("content", ""),
                            "venue": "",
                            "forum": result.get("url", ""),
                            "source": "web_search",
                            "url": result.get("url", "")
                        })
                return {
                    "results": results[:limit],
                    "count": len(results),
                    "source": "web_search"
                }
    except Exception as e:
        pass
    
    return {"results": [], "count": 0, "source": "none", "error": str(e)}

class PaperIdRequest(BaseModel):
    paper_id: str

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

@app.post("/api/upload-files")
async def upload_files(files: List[UploadFile] = FastAPIFile(...)):
    """Upload files and extract text content"""
    try:
        file_ids = []
        for file in files:
            # Read file content
            content = await file.read()
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Extract text based on file type
            text_content = extract_text_from_file(content, file.filename)
            
            # Store file metadata and content
            file_storage[file_id] = {
                "filename": file.filename,
                "content_type": file.content_type,
                "size": len(content),
                "text_content": text_content,
                "file_id": file_id
            }
            
            file_ids.append(file_id)
        
        return {
            "file_ids": file_ids,
            "count": len(file_ids),
            "message": f"Successfully uploaded {len(file_ids)} file(s)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading files: {str(e)}")

@app.get("/api/files/{file_id}")
async def get_file(file_id: str):
    """Get file information by ID"""
    if file_id not in file_storage:
        raise HTTPException(status_code=404, detail="File not found")
    
    file_info = file_storage[file_id]
    return {
        "file_id": file_id,
        "filename": file_info["filename"],
        "content_type": file_info["content_type"],
        "size": file_info["size"],
        "text_content": file_info["text_content"][:1000] + "..." if len(file_info["text_content"]) > 1000 else file_info["text_content"]
    }

@app.post("/api/get-paper-context")
async def get_paper_context(request: PaperIdRequest):
    """Get full paper context including metadata and reviews"""
    paper_id = request.paper_id
    try:
        or_client = get_openreview_client()
        if not or_client:
            raise HTTPException(status_code=503, detail="OpenReview client not configured")
        
        # Get paper note
        note = or_client.get_note(paper_id)
        note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
        content = note_dict.get('content', {})
        
        # Get reviews
        reviews = []
        try:
            review_notes = or_client.get_notes(forum=paper_id, invitation='~/-/Official_Review')
            for review in review_notes:
                review_dict = review.to_json() if hasattr(review, 'to_json') else dict(review)
                reviews.append(review_dict)
        except:
            pass
        
        # Extract paper information
        title = content.get('title', {}).get('value', '') if isinstance(content.get('title'), dict) else str(content.get('title', ''))
        authors = content.get('authors', {}).get('value', []) if isinstance(content.get('authors'), dict) else (content.get('authors', []) if isinstance(content.get('authors'), list) else [])
        abstract = content.get('abstract', {}).get('value', '') if isinstance(content.get('abstract'), dict) else str(content.get('abstract', ''))
        
        context = PaperContext(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            venue=note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else None,
            reviews=reviews,
            metadata={
                "forum": note_dict.get('forum'),
                "invitation": note_dict.get('invitation'),
                "created": note_dict.get('cdate'),
                "modified": note_dict.get('mdate'),
                "full_content": content
            }
        )
        
        return context.dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching paper context: {str(e)}")


def build_messages(request: ChatRequest, openreview_papers: List[Dict[str, Any]] = None, downloaded_papers: List[Dict[str, Any]] = None, google_pse_results: Optional[Dict[str, Any]] = None, is_summary_query: bool = False) -> List[Dict[str, Any]]:
    """Build messages list with system prompt and paper context"""
    messages = []
    
    # Add system prompt
    messages.append({
        "role": "system",
        "content": PAPER_ANALYSIS_SYSTEM_PROMPT
    })
    
    # If this is a summary query, add the summary template
    if is_summary_query:
        messages.append({
            "role": "system",
            "content": PAPER_SUMMARY_TEMPLATE
        })
    
    # Add Google PSE search results if available (before other context)
    if google_pse_results and google_pse_results.get("results"):
        search_context = format_search_results_for_context(google_pse_results)
        if search_context:
            messages.append({
                "role": "system",
                "content": search_context
    })
    
    # Add uploaded files context if available
    if request.file_ids and len(request.file_ids) > 0:
        files_context = "=== UPLOADED FILES ===\n\n"
        for file_id in request.file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                files_context += f"File: {file_info['filename']}\n"
                files_context += f"Size: {file_info['size']} bytes\n"
                files_context += f"Content Type: {file_info['content_type']}\n"
                files_context += f"Extracted Text:\n{file_info['text_content'][:5000]}\n"  # Limit to first 5000 chars
                if len(file_info['text_content']) > 5000:
                    files_context += "... (truncated)\n"
                files_context += "\n"
        
        files_context += "\nUse the information from these uploaded files to answer questions. Reference specific files when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": files_context
        })
    
    # Add downloaded OpenReview papers with full PDF text and reviews (priority)
    if downloaded_papers and len(downloaded_papers) > 0:
        context_text = "=== OPENREVIEW PAPERS (DOWNLOADED AND PROCESSED) ===\n\n"
        for i, paper in enumerate(downloaded_papers, 1):
            context_text += f"Paper {i}:\n"
            context_text += f"Title: {paper.get('title', 'N/A')}\n"
            context_text += f"Paper ID: {paper.get('paper_id', 'N/A')}\n"
            context_text += f"Authors: {', '.join(paper.get('authors', []))}\n"
            context_text += f"Venue: {paper.get('venue', 'N/A')}\n"
            context_text += f"Abstract: {paper.get('abstract', 'N/A')[:500]}...\n\n"
            
            # Add full PDF text if available
            if paper.get('pdf_text'):
                pdf_text = paper['pdf_text']
                # Limit PDF text to avoid token limits (keep first 10000 chars)
                if len(pdf_text) > 10000:
                    context_text += f"PDF Content (first 10000 characters):\n{pdf_text[:10000]}...\n\n"
                else:
                    context_text += f"PDF Content:\n{pdf_text}\n\n"
            
            # Add reviews if available
            if paper.get('reviews_text'):
                context_text += f"Reviews:\n{paper['reviews_text']}\n"
            elif paper.get('reviews'):
                context_text += f"Reviews ({len(paper['reviews'])}):\n"
                for j, review in enumerate(paper['reviews'], 1):
                    context_text += f"  Review {j} (Rating: {review.get('rating', 'N/A')}):\n"
                    context_text += f"  {review.get('summary', '')[:500]}...\n\n"
            
            context_text += "\n" + "="*50 + "\n\n"
        
        context_text += "\nUse the FULL CONTENT from these downloaded papers (including PDF text and reviews) to provide accurate, detailed, and comprehensive answers. Reference specific sections, findings, and reviews when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add OpenReview retrieved papers if available (fallback, metadata only)
    if openreview_papers and len(openreview_papers) > 0:
        context_text = "=== RETRIEVED PAPERS FROM OPENREVIEW (METADATA) ===\n\n"
        for i, paper in enumerate(openreview_papers, 1):
            context_text += f"Paper {i}:\n"
            context_text += f"Title: {paper.get('title', 'N/A')}\n"
            context_text += f"Authors: {', '.join(paper.get('authors', []))}\n"
            context_text += f"Abstract: {paper.get('abstract', 'N/A')[:500]}...\n"
            context_text += f"Venue: {paper.get('venue', 'N/A')}\n"
            if paper.get('pdf_url'):
                context_text += f"PDF Link: {paper.get('pdf_url')}\n"
            if paper.get('review_url'):
                context_text += f"Review Page: {paper.get('review_url')}\n"
            if paper.get('reviews'):
                context_text += f"Reviews ({len(paper['reviews'])}):\n"
                for j, review in enumerate(paper['reviews'], 1):
                    context_text += f"  Review {j}: {review.get('summary', '')[:300]}...\n"
            context_text += "\n"
        
        context_text += "\nUse the information from these retrieved papers to provide accurate and comprehensive answers. Reference specific papers when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add paper context if available
    if request.paper_context:
        context_text = f"""Paper Context:
Title: {request.paper_context.get('title', 'N/A')}
Authors: {', '.join(request.paper_context.get('authors', []))}
Abstract: {request.paper_context.get('abstract', 'N/A')}
Venue: {request.paper_context.get('venue', 'N/A')}

"""
        if request.paper_context.get('reviews'):
            context_text += f"Official Reviews ({len(request.paper_context['reviews'])}):\n"
            for i, review in enumerate(request.paper_context['reviews'][:3], 1):
                review_content = review.get('content', {})
                if isinstance(review_content, dict):
                    summary = review_content.get('summary', {}).get('value', '') if isinstance(review_content.get('summary'), dict) else str(review_content.get('summary', ''))
                    context_text += f"Review {i}: {summary[:200]}...\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add conversation messages
    for msg in request.messages:
        messages.append({
            "role": msg.role,
            "content": msg.content
        })
    
    return messages

async def check_query_clarity(query: str, paper_context_available: bool, model: str = "grok-4-fast") -> Tuple[bool, Optional[str]]:
    """Check if the query is clear enough to proceed, or if clarification is needed.
    
    Args:
        query: The user's query
        paper_context_available: Whether paper context is available
        model: Model to use for checking
    
    Returns:
        tuple: (is_clear: bool, clarification_question: Optional[str])
        If is_clear is False, clarification_question contains the question to ask the user
    """
    try:
        ai_client = get_ai_client()
        
        context_note = "Paper context is available." if paper_context_available else "No paper context is currently available."
        
        # Load clarity check template and format it
        clarity_template = load_prompt_template("query_clarity_check_template.md")
        clarity_prompt = clarity_template.format(context_note=context_note, query=query)

        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that evaluates query clarity. Always respond with valid JSON only."},
                {"role": "user", "content": clarity_prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        result_text = response.choices[0].message.content.strip()
        
        try:
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            result = json.loads(result_text)
            is_clear = result.get("is_clear", True)
            clarification_question = result.get("clarification_question")
            
            print(f"[Query Clarity] is_clear: {is_clear}, clarification: {clarification_question}")
            return is_clear, clarification_question
        except json.JSONDecodeError:
            print(f"[Query Clarity] Failed to parse response, assuming query is clear")
            return True, None
    except Exception as e:
        print(f"[Query Clarity] Error: {str(e)}, assuming query is clear")
        return True, None

def is_summary_query(query: str) -> bool:
    """Check if the query is asking for a paper summary/analysis."""
    query_lower = query.lower()
    summary_keywords = [
        'summarize', 'summary', 'overview', 'tell me about', 'what is this paper',
        'analyze', 'analysis', 'explain this paper', 'describe', 'what are', 'how does',
        'review', 'evaluate', 'assess', 'critique', 'rate', 'rating', 'score'
    ]
    return any(keyword in query_lower for keyword in summary_keywords)

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

async def verify_and_rephrase_paper_query(query: str, model: str = "grok-4-fast") -> Tuple[bool, str]:
    """Verify if the query is about a paper and rephrase it to better capture the intention.
    
    Returns:
        tuple: (is_about_paper: bool, rephrased_query: str)
    """
    try:
        ai_client = get_ai_client()
        
        # Load verification template and format it
        verification_template = load_prompt_template("paper_query_verification_template.md")
        verification_prompt = verification_template.format(query=query)

        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes queries to determine if they are about academic papers. Always respond with valid JSON only."},
                {"role": "user", "content": verification_prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Try to parse JSON response
        try:
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            result = json.loads(result_text)
            is_about_paper = result.get("is_about_paper", False)
            rephrased_query = result.get("rephrased_query", query)
            
            print(f"[OpenReview] Query verification - is_about_paper: {is_about_paper}, rephrased: {rephrased_query[:100]}...")
            return is_about_paper, rephrased_query
        except json.JSONDecodeError:
            print(f"[OpenReview] Failed to parse verification response, defaulting to original query")
            # If JSON parsing fails, try to extract boolean from text
            result_lower = result_text.lower()
            is_about_paper = "true" in result_lower or "is_about_paper" in result_lower and "false" not in result_lower
            return is_about_paper, query
    except Exception as e:
        print(f"[OpenReview] Error in query verification: {str(e)}, defaulting to original query")
        # On error, assume it might be about a paper and use original query
        return True, query

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with paper context and optional OpenReview integration"""
    try:
        openreview_papers = []
        downloaded_papers = []
        
        # If OpenReview is enabled and model is not supermind-agent, use it as additional search tool
        if request.use_openreview and request.model != "supermind-agent-v1":
            print(f"[OpenReview] Processing enabled for model: {request.model}")
            # Extract query from the last user message
            user_messages = [msg for msg in request.messages if msg.role == "user"]
            if user_messages:
                original_query = user_messages[-1].content
                print(f"[OpenReview] Original query: {original_query[:100]}...")
                
                # Verify if query is about a paper and rephrase if needed
                is_about_paper, rephrased_query = await verify_and_rephrase_paper_query(
                    original_query, 
                    model=request.model or "grok-4-fast"
                )
                
                if not is_about_paper:
                    print(f"[OpenReview] Query is not about a paper, skipping OpenReview API call")
                    downloaded_papers = []
                    openreview_papers = []
                else:
                    # Use rephrased query for OpenReview search
                    query = rephrased_query
                    print(f"[OpenReview] Using rephrased query: {query[:100]}...")
                    
                    # Parse OpenReview URLs/IDs and titles from the rephrased prompt
                    parsed_info = parse_openreview_info_from_text(query)
                    paper_ids = parsed_info['paper_ids']
                    titles = parsed_info['titles']
                    
                    print(f"[OpenReview] Found {len(paper_ids)} paper IDs and {len(titles)} titles")
                    
                    # Fetch papers by IDs/URLs (limit to top 3)
                    if paper_ids:
                        print(f"[OpenReview] Fetching papers by IDs: {paper_ids[:3]}")
                        for paper_id in paper_ids[:3]:
                            print(f"[OpenReview] Downloading paper: {paper_id}")
                            paper_data = await fetch_and_save_openreview_paper(paper_id)
                            if paper_data:
                                downloaded_papers.append(paper_data)
                                print(f"[OpenReview] Successfully downloaded paper: {paper_data.get('title', paper_id)}")
                            else:
                                print(f"[OpenReview] Failed to download paper: {paper_id}")
                    
                    # Search and fetch papers by titles (limit to top 2 per title, max 3 titles)
                    if titles and len(downloaded_papers) < 3:
                        print(f"[OpenReview] Searching papers by titles: {titles[:3]}")
                        for title in titles[:3]:
                            if len(downloaded_papers) >= 3:
                                break
                            print(f"[OpenReview] Searching for title: {title}")
                            search_results = await search_openreview_by_title(title, limit=2)
                            print(f"[OpenReview] Found {len(search_results)} papers for title: {title}")
                            
                            for paper in search_results:
                                if len(downloaded_papers) >= 3:
                                    break
                                # Check if we already have this paper
                                if not any(d['paper_id'] == paper['id'] for d in downloaded_papers):
                                    print(f"[OpenReview] Downloading paper from title search: {paper['id']}")
                                    paper_data = await fetch_and_save_openreview_paper(paper['id'])
                                    if paper_data:
                                        downloaded_papers.append(paper_data)
                                        print(f"[OpenReview] Successfully downloaded paper: {paper_data.get('title', paper['id'])}")
                    
                    # If no specific IDs or titles found, try general search-based retrieval (limit to 3)
                    if not paper_ids and not titles and len(downloaded_papers) == 0:
                        print(f"[OpenReview] No IDs/titles found, trying general search")
                        openreview_papers = await retrieve_openreview_papers(query, limit=3)
                        print(f"[OpenReview] General search found {len(openreview_papers)} papers")
                        
                        # Download top papers automatically (limit to 3)
                        for paper in openreview_papers[:3]:
                            paper_id = paper.get('id', '')
                            if paper_id:
                                print(f"[OpenReview] Downloading paper from general search: {paper_id}")
                                paper_data = await fetch_and_save_openreview_paper(paper_id)
                                if paper_data:
                                    downloaded_papers.append(paper_data)
                                    print(f"[OpenReview] Successfully downloaded paper: {paper_data.get('title', paper_id)}")
                        
                        # Keep remaining as metadata if not downloaded
                        openreview_papers = openreview_papers[len(downloaded_papers):]
            
            print(f"[OpenReview] Total downloaded papers: {len(downloaded_papers)}, metadata papers: {len(openreview_papers)}")
        else:
            if request.use_openreview:
                print(f"[OpenReview] Skipped (model is supermind-agent-v1)")
            else:
                print(f"[OpenReview] Disabled")
        
        # Determine if we should use Google PSE search
        # Google PSE is always available when enabled (works alongside OpenReview)
        model = request.model or "grok-4-fast"
        openreview_has_results = len(downloaded_papers) > 0 or len(openreview_papers) > 0
        should_use_google_pse = (
            request.use_google_pse and 
            model != "supermind-agent-v1"
        )
        
        google_pse_results = None
        best_matching_paper = None
        related_documents = []
        
        if should_use_google_pse:
            # Extract query from the last user message
            user_messages = [msg for msg in request.messages if msg.role == "user"]
            if user_messages:
                query = user_messages[-1].content
                
                print(f"[Google PSE] Searching for query: {query[:100]}...")
                try:
                    google_pse_results = await enhanced_search_with_fallback(
                        query,
                        num_results=10,
                        use_academic_focus=True
                    )
                    if google_pse_results.get("results"):
                        # Filter out OpenReview sources if OpenReview is disabled
                        results = google_pse_results.get("results", [])
                        if not request.use_openreview:
                            print(f"[Google PSE] Filtering out OpenReview sources (OpenReview is disabled)")
                            filtered_results = [
                                r for r in results 
                                if 'openreview.net' not in r.get('link', '').lower() 
                                and 'openreview.net' not in r.get('display_link', '').lower()
                            ]
                            google_pse_results["results"] = filtered_results
                            google_pse_results["count"] = len(filtered_results)
                            print(f"[Google PSE] Filtered to {len(filtered_results)} results (removed {len(results) - len(filtered_results)} OpenReview sources)")
                        
                        if google_pse_results.get("results"):
                            print(f"[Google PSE] Found {google_pse_results.get('count', 0)} results")
                            # Find the best matching paper from Google PSE results
                            best_matching_paper = find_best_matching_paper(query, google_pse_results.get("results", []))
                            if best_matching_paper:
                                print(f"[Google PSE] Best match: {best_matching_paper.get('title', 'N/A')[:60]}...")
                                
                                # Find related documents similar to OpenReview's related papers feature
                                print(f"[Google PSE] Finding related documents...")
                                try:
                                    related_documents = await find_related_documents(best_matching_paper, num_related=5)
                                    print(f"[Google PSE] Found {len(related_documents)} related documents")
                                except Exception as e:
                                    print(f"[Google PSE] Error finding related documents: {str(e)}")
                                    related_documents = []
                        else:
                            print(f"[Google PSE] No results after filtering")
                    else:
                        print(f"[Google PSE] No results found or error: {google_pse_results.get('error', 'Unknown')}")
                except Exception as e:
                    print(f"[Google PSE] Error during search: {str(e)}")
                    google_pse_results = None
        
        # Build messages with OpenReview context and Google PSE results (prioritize downloaded papers)
        # If we have a best matching paper from Google PSE, add it to the context
        if best_matching_paper and not openreview_has_results:
            # Add best matching paper as a special context
            best_match_context = f"""=== BEST MATCHING PAPER FROM WEB SEARCH ===
Title: {best_matching_paper.get('title', 'N/A')}
URL: {best_matching_paper.get('link', 'N/A')}
Summary: {best_matching_paper.get('snippet', 'N/A')}
Source: Google PSE Search

This paper was identified as the best match for your query. Please use this information to provide accurate answers.
"""
            # We'll add this to messages after building them
        else:
            best_match_context = None
        
        # Check if this is a summary query
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        is_summary = False
        if user_messages:
            last_query = user_messages[-1].content
            is_summary = is_summary_query(last_query)
            print(f"[Summary Detection] Is summary query: {is_summary}")
        
        # Check query clarity before proceeding (only if we have paper context)
        paper_context_available = len(downloaded_papers) > 0 or len(openreview_papers) > 0 or best_matching_paper is not None
        
        if paper_context_available and user_messages:
            last_user_message = user_messages[-1].content
            is_clear, clarification_question = await check_query_clarity(
                last_user_message, 
                paper_context_available,
                model=model
            )
            
            if not is_clear and clarification_question:
                print(f"[Query Clarity] Query needs clarification: {clarification_question}")
                return {
                    "requires_clarification": True,
                    "message": clarification_question,
                    "model": model
                }
        
        messages = build_messages(request, openreview_papers, downloaded_papers, google_pse_results, is_summary_query=is_summary)
        
        # Add best matching paper context if available
        if best_match_context:
            messages.insert(-len(request.messages), {  # Insert before user messages
                "role": "system",
                "content": best_match_context
            })
        
        # Call AI Builder API with selected model
        ai_client = get_ai_client()
        
        # Special handling for GPT-5 (temperature must be 1.0)
        temperature = 1.0 if model == "gpt-5" else 0.7
        
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=2000,
            stream=False
        )
        
        # Extract analysis response
        analysis_response = response.choices[0].message.content
        
        # Log paper summary if this is a summary query and we have paper context
        if is_summary and (downloaded_papers or openreview_papers or best_matching_paper):
            # Get paper metadata
            paper_metadata = {}
            if downloaded_papers:
                paper = downloaded_papers[0]  # Use first paper
                paper_metadata = {
                    'paper_id': paper.get('paper_id', ''),
                    'title': paper.get('title', ''),
                    'authors': paper.get('authors', []),
                    'venue': paper.get('venue', ''),
                    'year': paper.get('year')
                }
            elif openreview_papers:
                paper = openreview_papers[0]
                paper_metadata = {
                    'paper_id': paper.get('id', ''),
                    'title': paper.get('title', ''),
                    'authors': paper.get('authors', []),
                    'venue': paper.get('venue', ''),
                    'year': paper.get('year')
                }
            elif best_matching_paper:
                paper_metadata = {
                    'title': best_matching_paper.get('title', ''),
                    'url': best_matching_paper.get('link', ''),
                    'source': 'google_pse'
                }
            
            # Extract augmented prompt (paper context parts)
            augmented_prompt = extract_augmented_prompt_from_messages(messages)
            
            # Log to CSV
            if paper_metadata:
                log_paper_summary(paper_metadata, augmented_prompt, analysis_response)
        
        # Extract PDF links from downloaded and retrieved papers
        # Use a set to track seen paper IDs/URLs to avoid duplicates
        seen_paper_ids = set()
        seen_urls = set()
        pdf_links = []
        
        # Process downloaded papers first (priority)
        if downloaded_papers:
            for paper in downloaded_papers:
                paper_id = paper.get('paper_id')
                # Validate paper_id is not None, not empty, and is a valid string
                if paper_id and isinstance(paper_id, str) and paper_id.strip():
                    # Check for duplicates by paper_id
                    if paper_id not in seen_paper_ids:
                        seen_paper_ids.add(paper_id)
                        forum_id = paper.get('forum_id') or paper_id
                        # Ensure forum_id is also valid
                        if forum_id and isinstance(forum_id, str) and forum_id.strip():
                            pdf_links.append({
                                'title': paper.get('title', 'Paper') or 'Paper',
                                'url': f"https://openreview.net/pdf?id={paper_id}",
                                'review_url': f"https://openreview.net/forum?id={forum_id}"
                            })
        
        # Process openreview papers (fallback, avoid duplicates)
        if openreview_papers:
            for paper in openreview_papers:
                pdf_url = paper.get('pdf_url')
                # Validate pdf_url is not None, not empty, and is a valid URL
                if pdf_url and isinstance(pdf_url, str) and pdf_url.strip():
                    # Check for duplicates by URL
                    if pdf_url not in seen_urls:
                        # Also check if this paper_id was already added from downloaded_papers
                        paper_id_from_url = None
                        # Extract paper_id from URL if possible
                        url_match = re.search(r'[?&]id=([A-Za-z0-9_~\-]+)', pdf_url)
                        if url_match:
                            paper_id_from_url = url_match.group(1)
                        
                        # Skip if this paper_id was already processed
                        if not paper_id_from_url or paper_id_from_url not in seen_paper_ids:
                            seen_urls.add(pdf_url)
                            if paper_id_from_url:
                                seen_paper_ids.add(paper_id_from_url)
                            
                            review_url = paper.get('review_url')
                            # Only add review_url if it's valid
                            pdf_links.append({
                                'title': paper.get('title', 'Paper') or 'Paper',
                                'url': pdf_url,
                                'review_url': review_url if (review_url and isinstance(review_url, str) and review_url.strip()) else None
                            })
        
        # Prepare response with search metadata and document links
        # Format Google PSE results as pdf_links for frontend compatibility (similar to OpenReview)
        google_pse_pdf_links = []
        if best_matching_paper:
            google_pse_pdf_links.append({
                "title": best_matching_paper.get("title", "Best Match"),
                "url": best_matching_paper.get("link", ""),
                "source": "google_pse"
            })
        if related_documents:
            for related_doc in related_documents:
                google_pse_pdf_links.append({
                    "title": related_doc.get("title", ""),
                    "url": related_doc.get("url", ""),
                    "source": "google_pse"
                })
        
        # Combine OpenReview and Google PSE links for pdf_links (frontend compatibility)
        all_pdf_links = pdf_links + google_pse_pdf_links
        
        response_data = {
            "message": analysis_response,
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            "pdf_links": all_pdf_links if all_pdf_links else None
        }
        
        # Collect all document links from different sources
        document_links = []
        
        # Add OpenReview links if available
        if openreview_has_results:
            for link in pdf_links:
                document_links.append({
                    "title": link.get('title', 'Paper'),
                    "url": link.get('url', ''),
                    "review_url": link.get('review_url'),
                    "source": "openreview"
                })
        
        # Add Google PSE links if available
        if google_pse_results and google_pse_results.get("results"):
            # Add best matching paper first
            if best_matching_paper:
                document_links.append({
                    "title": best_matching_paper.get("title", "Best Match"),
                    "url": best_matching_paper.get("link", ""),
                    "snippet": best_matching_paper.get("snippet", ""),
                    "source": "google_pse",
                    "is_best_match": True
                })
            
            # Add related documents (similar to OpenReview's related papers)
            if related_documents:
                for related_doc in related_documents:
                    document_links.append({
                        "title": related_doc.get("title", ""),
                        "url": related_doc.get("url", ""),
                        "snippet": related_doc.get("snippet", ""),
                        "source": "google_pse",
                        "is_best_match": False,
                        "is_related": True,
                        "relation_type": related_doc.get("relation_type", "similar_topic")
                    })
            
            # Add other top results (if we don't have enough from related docs)
            remaining_slots = max(0, 5 - len(related_documents))
            for r in google_pse_results.get("results", [])[:remaining_slots]:
                # Skip if already added as best match or related doc
                result_url = r.get("link", "")
                if best_matching_paper and result_url == best_matching_paper.get("link"):
                    continue
                if any(doc.get("url") == result_url for doc in related_documents):
                    continue
                document_links.append({
                    "title": r.get("title", ""),
                    "url": result_url,
                    "snippet": r.get("snippet", ""),
                    "source": "google_pse",
                    "is_best_match": False,
                    "is_related": False
                })
            
            response_data["search_results"] = {
                "source": "google_pse",
                "count": google_pse_results.get("count", 0),
                "best_match": {
                    "title": best_matching_paper.get("title", "") if best_matching_paper else None,
                    "url": best_matching_paper.get("link", "") if best_matching_paper else None,
                    "snippet": best_matching_paper.get("snippet", "") if best_matching_paper else None
                } if best_matching_paper else None,
                "related_count": len(related_documents)
            }
        
        # Add all document links to response
        if document_links:
            response_data["document_links"] = document_links
        
        return response_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating response: {str(e)}")

@app.post("/api/chat/multi-model")
async def chat_multi_model(request: MultiModelChatRequest):
    """Chat endpoint with multiple models for parallel responses"""
    try:
        # Build messages (reuse ChatRequest structure)
        chat_request = ChatRequest(
            messages=request.messages,
            paper_id=request.paper_id,
            paper_context=request.paper_context
        )
        messages = build_messages(chat_request)
        
        ai_client = get_ai_client()
        
        # Create tasks for parallel execution
        async def get_model_response(model_id: str):
            try:
                # Special handling for GPT-5 (temperature must be 1.0)
                temperature = 1.0 if model_id == "gpt-5" else 0.7
                
                response = await asyncio.to_thread(
                    ai_client.chat.completions.create,
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=2000,
                    stream=False
                )
                
                return {
                    "model": model_id,
                    "message": response.choices[0].message.content,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    },
                    "error": None
                }
            except Exception as e:
                return {
                    "model": model_id,
                    "message": None,
                    "usage": None,
                    "error": str(e)
                }
        
        # Execute all models in parallel
        tasks = [get_model_response(model_id) for model_id in request.models]
        responses = await asyncio.gather(*tasks)
        
        return {
            "responses": responses,
            "count": len(responses)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating multi-model responses: {str(e)}")

@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint"""
    async def generate():
        try:
            messages = []
            messages.append({"role": "system", "content": PAPER_ANALYSIS_SYSTEM_PROMPT})
            
            if request.paper_context:
                context_text = f"""Paper Context:
Title: {request.paper_context.get('title', 'N/A')}
Authors: {', '.join(request.paper_context.get('authors', []))}
Abstract: {request.paper_context.get('abstract', 'N/A')}
"""
                messages.append({"role": "system", "content": context_text})
            
            for msg in request.messages:
                messages.append({"role": msg.role, "content": msg.content})
            
            ai_client = get_ai_client()
            stream = ai_client.chat.completions.create(
                model="grok-4-fast",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'content': chunk.choices[0].delta.content})}\n\n"
            
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

