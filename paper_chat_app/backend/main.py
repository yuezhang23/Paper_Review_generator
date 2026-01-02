"""
FastAPI Backend for Academic Paper Analysis Chat Application
Integrates with AI Builder API (Grok) and OpenReview API
"""

import os
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import openai
import openreview
from dotenv import load_dotenv
import asyncio
import httpx

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

# Initialize OpenReview client
_openreview_client: Optional[openreview.api.OpenReviewClient] = None

def get_openreview_client():
    """Get or create OpenReview client instance"""
    global _openreview_client
    if _openreview_client is None:
        baseurl = os.getenv("OPENREVIEW_BASEURL", "https://api2.openreview.net")
        username = os.getenv("OPENREVIEW_USERNAME")
        password = os.getenv("OPENREVIEW_PASSWORD")
        
        if username and password:
            _openreview_client = openreview.api.OpenReviewClient(
                baseurl=baseurl,
                username=username,
                password=password
            )
    return _openreview_client

# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "grok-4-fast"
    paper_id: Optional[str] = None
    paper_context: Optional[Dict[str, Any]] = None

class PaperSearchRequest(BaseModel):
    query: str
    venue: Optional[str] = None
    limit: int = 10

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

# System prompt for paper analysis
PAPER_ANALYSIS_SYSTEM_PROMPT = """You are an expert academic paper analysis assistant specializing in machine learning and AI research papers. 

Your role is to:
1. Provide detailed, comprehensive summaries of academic papers
2. Analyze methodology, contributions, and experimental results
3. Explain technical concepts clearly
4. Compare papers when relevant
5. Answer questions about paper content, authors, and related work

When analyzing papers:
- Focus on key contributions and innovations
- Explain the methodology in accessible terms
- Highlight experimental results and their significance
- Discuss limitations and future work
- Reference specific sections when possible

Be thorough, accurate, and helpful. Use the provided paper context (metadata, reviews, etc.) to enhance your analysis."""

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
    """Search for papers in OpenReview, with automatic fallback to Tavily/web search"""
    try:
        or_client = get_openreview_client()
        results = []
        
        # Try OpenReview first if client is available
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
            except Exception as e:
                pass  # Fall through to web search
        
        # If no OpenReview results, use Tavily/web search
        if len(results) == 0:
            web_results = await web_search_paper(request.query, request.limit)
            results = web_results.get("results", [])
        
        return {
            "results": results,
            "count": len(results),
            "source": "openreview" if results and results[0].get("source") == "openreview" else "web_search"
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

def build_messages(request: ChatRequest) -> List[Dict[str, Any]]:
    """Build messages list with system prompt and paper context"""
    messages = []
    
    # Add system prompt
    messages.append({
        "role": "system",
        "content": PAPER_ANALYSIS_SYSTEM_PROMPT
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

@app.post("/api/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with paper context"""
    try:
        messages = build_messages(request)
        
        # Call AI Builder API with selected model
        ai_client = get_ai_client()
        model = request.model or "grok-4-fast"
        
        # Special handling for GPT-5 (temperature must be 1.0)
        temperature = 1.0 if model == "gpt-5" else 0.7
        
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=2000,
            stream=False
        )
        
        return {
            "message": response.choices[0].message.content,
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            }
        }
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

