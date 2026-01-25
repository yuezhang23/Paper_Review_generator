"""
FastAPI Backend for Academic Paper Analysis Chat Application
Integrates with AI Builder API (Grok) and OpenReview API
"""

import os
import httpx
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File as FastAPIFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from openreview_service import (
    get_openreview_client,
    search_openreview_by_title,
    fetch_and_save_openreview_paper,
)
from utils import (
    file_storage,
    PAPER_QUERY_SUGGESTIONS,
    upload_files,
    get_ai_client,
)

# Import service routers
from summary_generator.main import router as summary_router
from chatbot_service import router as chatbot_router


import logging
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Register service routers
app.include_router(summary_router)
app.include_router(chatbot_router)

# Shared Request/Response models (used by general endpoints)
class PaperSearchRequest(BaseModel):
    query: str
    venue: Optional[str] = None
    limit: int = 10
    use_openreview: bool = False  # Toggle to enable/disable OpenReview search

class PaperReviewRequest(BaseModel):
    """Request model for fetching paper reviews - accepts either query (paper name) or paper_id"""
    query: Optional[str] = None  # Paper name/title to search for
    paper_id: Optional[str] = None  # Direct paper ID from OpenReview

class PaperIdRequest(BaseModel):
    paper_id: str

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

@app.post("/api/get-paper-reviews")
async def get_paper_reviews(request: PaperReviewRequest):
    """Unified endpoint to get paper reviews from OpenReview
    
    Accepts either:
    - query: Paper name/title (searches first, then fetches reviews)
    - paper_id: Direct OpenReview paper ID (fetches reviews directly)
    
    Uses fetch_and_save_openreview_paper for consistent data retrieval.
"""
    try:
        paper_id = request.paper_id
        
        # If paper_id not provided, search by query first
        if not paper_id:
            if not request.query:
                raise HTTPException(
                    status_code=400, 
                    detail="Either 'query' or 'paper_id' must be provided"
                )
            
            # Search for papers by title/query using OpenReview
            papers = await search_openreview_by_title(request.query, limit=1)
            
            if not papers or len(papers) == 0:
                raise HTTPException(
                    status_code=404,
                    detail="No paper found matching the query"
                )
            
            # Get the first matching paper
            matched_paper = papers[0]
            paper_id = matched_paper.get('id') or matched_paper.get('paper_id')
            
            if not paper_id:
                raise HTTPException(
                    status_code=404,
                    detail="Paper ID not found in search results"
                )
        
        # Fetch paper data and reviews using fetch_and_save_openreview_paper
        paper_data = await fetch_and_save_openreview_paper(paper_id)
        
        if not paper_data:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to fetch paper data and reviews for paper_id: {paper_id}"
            )
        
        # Extract reviews from paper_data
        reviews = paper_data.get('reviews', [])
        
        # Return unified format matching PaperContext structure
        return {
            "paper_id": paper_data.get('paper_id'),
            "title": paper_data.get('title'),
            "authors": paper_data.get('authors'),
            "abstract": paper_data.get('abstract'),
            "venue": paper_data.get('venue'),
            "year": paper_data.get('year'),
            "reviews": reviews,
            "count": len(reviews),
            "metadata": {
                "forum_id": paper_data.get('forum_id'),
                "pdf_path": paper_data.get('pdf_path'),
                "reviews_path": paper_data.get('reviews_path'),
                "metadata_path": paper_data.get('metadata_path'),
                "paper_dir": paper_data.get('paper_dir')
            },
            "source": "openreview"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching paper reviews: {str(e)}"
        )

@app.post("/api/upload-files")
async def upload_files_endpoint(files: List[UploadFile] = FastAPIFile(...)):
    """Upload files and extract text content"""
    return await upload_files(files)

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

@app.get("/api/reviews/{filename}")
async def serve_review_file(filename: str):
    """Serve review HTML files from the reviews directory"""
    reviews_dir = os.path.join(os.path.dirname(__file__), "reviews")
    file_path = os.path.join(reviews_dir, filename)
    
    # Security: ensure file is in reviews directory (prevent directory traversal)
    if not os.path.abspath(file_path).startswith(os.path.abspath(reviews_dir)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Review file not found")
    
    # Determine content type
    if filename.endswith('.html'):
        return FileResponse(file_path, media_type='text/html')
    elif filename.endswith('.pdf'):
        return FileResponse(file_path, media_type='application/pdf')
    else:
        return FileResponse(file_path)

@app.post("/api/search-review-from-openreview")
async def search_review_from_openreview(request: PaperSearchRequest):
    """Search for a paper by name and retrieve reviews (DEPRECATED - use /api/get-paper-reviews instead)
    
    This endpoint is kept for backward compatibility but delegates to get_paper_reviews.
    """
    # Convert PaperSearchRequest to PaperReviewRequest and delegate
    review_request = PaperReviewRequest(query=request.query)
    return await get_paper_reviews(review_request)

@app.post("/api/get-paper-context")
async def get_paper_context(request: PaperIdRequest):
    """Get full paper context including metadata and reviews (DEPRECATED - use /api/get-paper-reviews instead)
    
    This endpoint is kept for backward compatibility but delegates to get_paper_reviews.
    """
    # Convert PaperIdRequest to PaperReviewRequest and delegate
    review_request = PaperReviewRequest(paper_id=request.paper_id)
    return await get_paper_reviews(review_request)




if __name__ == "__main__":
    import uvicorn
    # Configure timeouts for long-running requests (e.g., RAG pipeline processing)
    # timeout_keep_alive: time to keep connection alive (30 seconds)
    # timeout_graceful_shutdown: time to wait for graceful shutdown
    # Default request timeout is handled by the ASGI server (usually 120s)
    # For very long operations like RAG processing, we increase these values
    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=8000,
        timeout_keep_alive=300,  # 5 minutes - keep connections alive longer
        timeout_graceful_shutdown=30  # 30 seconds for graceful shutdown
    )
