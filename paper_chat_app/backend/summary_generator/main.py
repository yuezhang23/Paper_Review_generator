"""
Summary Service - Handles paper summary functionality for the Summary tab
Implements the full pipeline architecture:
PDF → GROBID → structured sections → Tables (Camelot/Tabula) → Figures (image extraction)
→ Multimodal GPT analysis → Embeddings → Vector Index → Query-driven retrieval → Final synthesis
"""

import os
import tempfile
import traceback
import logging
import asyncio
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel
import httpx

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import from parent utils module (not summary_generator/utils)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import file_storage, UPLOAD_DIR
from openreview_service import fetch_and_save_openreview_paper, parse_openreview_info_from_text

# Import from summary_generator modules
from .embeddings import embed_texts, build_rag_index
from .utils import extract_tables, extract_figures

# Create router for summary endpoints
router = APIRouter(prefix="/api", tags=["summary"])

# Import AI client from parent utils
from utils import get_ai_client
ai_client = get_ai_client()


class SummaryRequest(BaseModel):
    file_ids: Optional[List[str]] = None
    paper_url: Optional[str] = None
    paper_name: Optional[str] = None
    use_openreview: Optional[bool] = True
    model: Optional[str] = "supermind-agent-v1"


async def resolve_pdf_path(
    file_ids: Optional[List[str]] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    use_openreview: bool = None
) -> str:
    """
    Resolve PDF file path from request parameters.
    Downloads/saves PDF if needed and returns local file path.
    
    Returns:
        Path to PDF file on local filesystem
    """
    # Priority 1: Extract from uploaded files
    if file_ids and len(file_ids) > 0:
        # Use uploaded PDFs (now saved to disk during upload)
        for file_id in file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                if file_info.get('content_type') == 'application/pdf' or file_info.get('pdf_path'):
                    pdf_path = file_info.get('pdf_path')
                    if pdf_path and os.path.exists(pdf_path):
                        return pdf_path
                    else:
                        raise HTTPException(
                            status_code=404,
                            detail=f"PDF file {file_id} not found on disk. Please re-upload the file."
                        )
    
    # Priority 2: Extract from OpenReview URL
    if paper_url and use_openreview and 'openreview.net' in paper_url:
        try:
            parsed_info = parse_openreview_info_from_text(paper_url)
            paper_ids = parsed_info.get('paper_ids', [])
            if paper_ids:
                paper_id = paper_ids[0]
                paper_data = await fetch_and_save_openreview_paper(paper_id)
                if paper_data and paper_data.get('pdf_path'):
                    return paper_data['pdf_path']
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Error fetching paper from OpenReview: {str(e)}"
            )
    
    # Priority 3: Download from URL
    if paper_url:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(paper_url, follow_redirects=True)
                if response.status_code == 200 and 'pdf' in response.headers.get('content-type', ''):
                    # Save to temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                        tmp_file.write(response.content)
                        return tmp_file.name
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error downloading PDF from URL: {str(e)}"
            )
    
    # Priority 4: Search by paper name (OpenReview)
    if paper_name and use_openreview:
        # This would require search functionality - for now, raise error
        raise HTTPException(
            status_code=400,
            detail="Paper name search not yet implemented. Please use paper_url or file_ids."
        )
    
    raise HTTPException(
        status_code=400,
        detail="No valid PDF source provided. Please provide file_ids, paper_url, or paper_name."
    )


@router.post("/summary")
async def paper_summary(request: SummaryRequest):
    """
    Paper summary endpoint implementing the full pipeline architecture:
    
    1. PDF → GROBID → structured sections
    2. Tables → Camelot / Tabula (text-first)
    3. Figures → extracted images
    4. Multimodal GPT → figure & table understanding (OPTIONAL, max 3 tables/3 figures)
       - Selection heuristics: mentioned in Abstract/Conclusion, labeled "Main results",
         contains SOTA comparisons or ablations
    5. Embeddings → vector index (RAG) - cached if paper processed before
    6. Query-driven retrieval
    7. Final synthesis
    """
    pdf_path = None
    try:
        logger.info(f"[Step 1] Starting summary request with: file_ids={request.file_ids}, paper_url={request.paper_url}, paper_name={request.paper_name}")
        
        # Step 1: Resolve PDF path from request
        logger.info("[Step 1] Resolving PDF path...")
        try:
            pdf_path = await resolve_pdf_path(
                file_ids=request.file_ids,
                paper_url=request.paper_url,
                paper_name=request.paper_name,
                use_openreview=request.use_openreview
            )
            logger.info(f"[Step 1] PDF path resolved: {pdf_path}")
        except Exception as e:
            logger.error(f"[Step 1] Failed to resolve PDF path: {str(e)}\n{traceback.format_exc()}")
            raise
        
        # Step 2: Check if PDF exists
        logger.info(f"[Step 2] Checking if PDF exists at: {pdf_path}")
        try:
            if not os.path.exists(pdf_path):
                logger.error(f"[Step 2] PDF file not found at path: {pdf_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"PDF file not found at path: {pdf_path}"
                )
            logger.info(f"[Step 2] PDF exists. File size: {os.path.getsize(pdf_path)} bytes")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Step 2] Error checking PDF existence: {str(e)}\n{traceback.format_exc()}")
            raise
        
        # Step 3: Build RAG index following the architecture (async optimized)
        logger.info("[Step 3] Building RAG index...")
        try:
            index = await build_rag_index(pdf_path)
            logger.info(f"[Step 3] RAG index built successfully. Index contains {len(index.texts)} text chunks")
        except Exception as e:
            logger.error(f"[Step 3] Failed to build RAG index: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error building RAG index: {str(e)}\nFull traceback: {traceback.format_exc()}"
            )
        
        # Step 4: Query-driven retrieval and final synthesis (async optimized)
        logger.info("[Step 4] Starting query-driven retrieval and synthesis...")
        try:
            model = request.model or "supermind-agent-v1"
            logger.info(f"[Step 4] Using model: {model}")
            summary = await synthesize_answer(
                index,
                "Provide a full technical summary of the paper, including methods, results, and limitations.",
                model=model
            )
            logger.info(f"[Step 4] Summary generated successfully. Length: {len(summary)} characters")
        except Exception as e:
            logger.error(f"[Step 4] Failed to synthesize answer: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error synthesizing summary: {str(e)}\nFull traceback: {traceback.format_exc()}"
            )
        
        logger.info("[Success] Summary generation completed successfully")
        return {
            "summary": summary,
            "pdf_path": pdf_path
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Unexpected Error] {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error generating summary: {str(e)}\nFull traceback: {traceback.format_exc()}"
        )
    finally:
        # Clean up temporary files if created
        if pdf_path and pdf_path.startswith(tempfile.gettempdir()):
            try:
                logger.info(f"[Cleanup] Removing temporary file: {pdf_path}")
                os.unlink(pdf_path)
            except Exception as e:
                logger.warning(f"[Cleanup] Failed to remove temporary file: {str(e)}")


async def synthesize_answer(index, query: str, model: str = "supermind-agent-v1"):
    """
    Step 6 & 7: Query-driven retrieval and final synthesis (async optimized)
    
    Args:
        index: VectorIndex built from paper content
        query: Query string for summary generation
        model: Model ID to use for synthesis (default: "supermind-agent-v1")
        
    Returns:
        Generated summary text
    """
    logger.info(f"[Synthesize] Starting synthesis with query length: {len(query)}")
    
    # Query-driven retrieval (k=8 nearest neighbors)
    logger.info("[Synthesize] Step 6: Creating query embedding...")
    try:
        # Run embedding creation in thread pool
        query_emb = await asyncio.to_thread(embed_texts, [query])
        query_emb = query_emb[0]
        logger.info(f"[Synthesize] Query embedding created. Shape: {query_emb.shape}")
    except Exception as e:
        logger.error(f"[Synthesize] Failed to create query embedding: {str(e)}\n{traceback.format_exc()}")
        raise
    
    logger.info("[Synthesize] Querying index for k=8 nearest neighbors...")
    try:
        # Index query is fast, run in thread pool
        retrieved = await asyncio.to_thread(index.query, query_emb, 8)
        logger.info(f"[Synthesize] Retrieved {len(retrieved)} text chunks")
    except Exception as e:
        logger.error(f"[Synthesize] Failed to query index: {str(e)}\n{traceback.format_exc()}")
        raise

    # Final synthesis using GPT model
    logger.info(f"[Synthesize] Step 7: Calling AI model '{model}' for final synthesis...")
    try:
        retrieved_content = chr(10).join(retrieved)
        logger.info(f"[Synthesize] Retrieved content length: {len(retrieved_content)} characters")
        
        # Run API call in thread pool for async execution
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a meticulous academic reviewer. Provide comprehensive, accurate summaries."
                },
                {
                    "role": "user",
                    "content": f"""
Using the retrieved paper content below, answer the query thoroughly.

Query:
{query}

Retrieved content:
{retrieved_content}
"""
                }
            ],
            temperature=0.2
        )
        summary = response.choices[0].message.content
        logger.info(f"[Synthesize] Summary generated. Length: {len(summary)} characters")
        return summary
    except Exception as e:
        logger.error(f"[Synthesize] Failed to call AI model: {str(e)}\n{traceback.format_exc()}")
        raise


