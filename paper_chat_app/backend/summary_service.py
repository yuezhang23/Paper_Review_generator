"""
Summary Service - Handles paper summary functionality for the Summary tab
"""

from typing import Optional, List, Dict, Any
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel
from shared_utils import get_ai_client, extract_paper_content
from utils import PAPER_SUMMARY_TEMPLATE
from summary_logs.summary_logger import log_paper_summary_if_needed

# Create router for summary endpoints
router = APIRouter(prefix="/api", tags=["summary"])


class SummaryRequest(BaseModel):
    file_ids: Optional[List[str]] = None
    paper_url: Optional[str] = None
    paper_name: Optional[str] = None
    use_openreview: Optional[bool] = True
    model: Optional[str] = "grok-4-fast"


@router.post("/summary")
async def paper_summary(request: SummaryRequest):
    """Paper summary endpoint - directly processes paper content and generates summary.
    
    This endpoint is designed for the Summary tab where the intention is clear:
    - Paper content is provided via file upload, URL, or paper name
    - No query verification or web search needed
    - Directly extracts content and generates summary using summary template
    """
    try:
        # Extract paper content using the helper function
        paper_text, paper_metadata = await extract_paper_content(
            file_ids=request.file_ids,
            paper_url=request.paper_url,
            paper_name=request.paper_name,
            use_openreview=request.use_openreview if request.use_openreview is not None else True
        )
        
        if not paper_text or len(paper_text.strip()) < 100:
            raise HTTPException(
                status_code=400,
                detail="Could not extract sufficient text from the provided input. Please ensure the file, URL, or paper name is valid."
            )
        
        # Build messages with summary template
        messages = []
        messages.append({
            "role": "system",
            "content": PAPER_SUMMARY_TEMPLATE
        })
        
        # Add paper content as context
        paper_context = "=== PAPER CONTENT ===\n\n"
        if paper_metadata:
            if paper_metadata.get('title'):
                paper_context += f"Title: {paper_metadata['title']}\n"
            if paper_metadata.get('authors'):
                authors = paper_metadata['authors']
                if isinstance(authors, list):
                    paper_context += f"Authors: {', '.join(authors)}\n"
                else:
                    paper_context += f"Authors: {authors}\n"
            if paper_metadata.get('abstract'):
                paper_context += f"Abstract: {paper_metadata['abstract'][:500]}...\n\n"
            if paper_metadata.get('venue'):
                paper_context += f"Venue: {paper_metadata['venue']}\n\n"
        
        # Add full paper text (limit to 15000 chars to avoid token limits)
        if len(paper_text) > 15000:
            paper_context += f"Full Paper Content (first 15000 characters):\n{paper_text[:15000]}...\n"
        else:
            paper_context += f"Full Paper Content:\n{paper_text}\n"
        
        paper_context += "\nPlease provide a detailed summary and analysis of this paper."
        
        messages.append({
            "role": "user",
            "content": paper_context
        })
        
        # Generate summary using AI
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
        
        summary_response = response.choices[0].message.content
        
        # Log summary if metadata is available
        if paper_metadata:
            try:
                log_paper_summary_if_needed(
                    is_summary=True,
                    downloaded_papers=[paper_metadata] if paper_metadata.get('paper_id') else None,
                    openreview_papers=None,
                    best_matching_paper=paper_metadata if not paper_metadata.get('paper_id') else None,
                    messages=messages,
                    analysis_response=summary_response
                )
            except Exception as e:
                print(f"[Summary] Error logging summary: {str(e)}")
        
        # Build response with metadata
        response_data = {
            "message": summary_response,
            "summary": summary_response,  # For backward compatibility
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            "paper_metadata": paper_metadata,
            "text_length": len(paper_text)
        }
        
        # Add PDF links if available
        if paper_metadata:
            pdf_links = []
            if paper_metadata.get('paper_id'):
                # OpenReview paper - construct URL
                pdf_links.append({
                    "title": paper_metadata.get('title', 'Paper') or 'Paper',
                    "url": f"https://openreview.net/pdf?id={paper_metadata['paper_id']}",
                    "review_url": f"https://openreview.net/forum?id={paper_metadata['paper_id']}",
                    "source": "openreview"
                })
            elif paper_metadata.get('url'):
                # Web search paper
                pdf_links.append({
                    "title": paper_metadata.get('title', 'Paper') or 'Paper',
                    "url": paper_metadata['url'],
                    "source": "web_search"
                })
            if pdf_links:
                response_data["pdf_links"] = pdf_links
        
        return response_data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")
