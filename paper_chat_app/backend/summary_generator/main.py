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
import re
import time
import base64
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel
import httpx
import markdown
import requests


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import from parent utils module (not summary_generator/utils)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Import from summary_generator modules
from vector_embedding.embeddings import embed_texts, build_rag_index, VectorIndex
from vector_embedding.utils_grobid import extract_metadata_from_grobid_api

# Import helper functions (non-LLM related)
from .helpers import (
    load_prompt_template,
    format_prompt_template,
    resolve_pdf_path,
    format_review_as_markdown,
    render_markdown_to_html,
    create_split_screen_view
)

# Review queries for summary generation
REVIEW_QUERIES = {
    "summary": "Provide a comprehensive summary of the paper, including the main problem, approach, and key results.",
    "strengths": "What are the main strengths of this paper? Highlight well-executed experiments, clear contributions, and strong methodological choices.",
    "weaknesses": "What are the main weaknesses or limitations of this paper? Identify areas that need improvement or concerns about the methodology, evaluation, or presentation.",
    "innovations": "What are the key innovations or novel contributions of this paper? What makes it different from prior work?",
    "contributions": "What are the specific contributions of this paper to the field? List both technical and conceptual contributions.",
    "limitations": "What are the limitations, open questions, or ambiguities in this paper? What aspects need further investigation?",
    "rating": "Provide a rating assessment of this paper. Consider significance, novelty, technical quality, clarity, and reproducibility. Provide a score (e.g., 1-10) with justification."
}
# SECTION_ANCHOR_QUERIES and DETAIL_SEEKING_QUERIES moved to image_method_generator.py

# Create router for summary endpoints
router = APIRouter(prefix="/api", tags=["summary"])

# Import AI client from parent utils (lazy: call get_ai_client() inside endpoints to avoid startup failure when token unset)
from utils import get_ai_client, ensure_file_info_from_main_backend


class SummaryRequest(BaseModel):
    file_ids: Optional[List[str]] = None
    paper_url: Optional[str] = None
    paper_name: Optional[str] = None
    use_openreview: Optional[bool] = True
    model: Optional[str] = None
    figure_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"
    table_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"



# ImageGenerationRequest moved to image_method_generator.py
async def build_paper_embeddings(
    file_ids: Optional[List[str]] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    use_openreview: Optional[bool] = True,
    figure_extraction_method: Optional[str] = "none",
    table_extraction_method: Optional[str] = "none"
) -> tuple[str, VectorIndex, Dict[str, Any]]:
    """
    Steps 1-5: Embedding-related processing pipeline.
    Implements the embedding pipeline:
    1. PDF → GROBID → structured sections
    2. Tables → Camelot / Tabula (text-first)
    3. Figures → extracted images
    4. Multimodal GPT → figure & table understanding (OPTIONAL, max 3 tables/3 figures)
       - Selection heuristics: mentioned in Abstract/Conclusion, labeled "Main results",
         contains SOTA comparisons or ablations
    5. Embeddings → vector index (RAG) - cached if paper processed before
    
    Args:
        file_ids: Optional list of uploaded file IDs
        paper_url: Optional URL to PDF paper
        paper_name: Optional paper name for search
        use_openreview: Whether to use OpenReview for paper fetching
        figure_extraction_method: Method for figure extraction ("none", "ocr", "multimodal")
        table_extraction_method: Method for table extraction ("none", "ocr", "multimodal")
    
    Returns:
        Tuple of (pdf_path, index, metadata)
    """
    logger.info(f"[Embeddings] Starting embedding pipeline: file_ids={file_ids}, paper_url={paper_url}, paper_name={paper_name}")
    
    # Step 1: Resolve PDF path from request
    logger.info("[Embeddings Step 1] Resolving PDF path...")
    try:
        pdf_path = await resolve_pdf_path(
            file_ids=file_ids,
            paper_url=paper_url,
            paper_name=paper_name,
            use_openreview=use_openreview
        )
        logger.info(f"[Embeddings Step 1] PDF path resolved: {pdf_path}")
    except Exception as e:
        logger.error(f"[Embeddings Step 1] Failed to resolve PDF path: {str(e)}\n{traceback.format_exc()}")
        raise
    
    # Step 2: Check if PDF exists
    logger.info(f"[Embeddings Step 2] Checking if PDF exists at: {pdf_path}")
    try:
        if not os.path.exists(pdf_path):
            logger.error(f"[Embeddings Step 2] PDF file not found at path: {pdf_path}")
            raise HTTPException(
                status_code=404,
                detail=f"PDF file not found at path: {pdf_path}"
            )
        logger.info(f"[Embeddings Step 2] PDF exists. File size: {os.path.getsize(pdf_path)} bytes")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Embeddings Step 2] Error checking PDF existence: {str(e)}\n{traceback.format_exc()}")
        raise
    
    # Step 3: Build RAG index following the architecture (async optimized)
    logger.info("[Embeddings Step 3] Building RAG index...")
    try:
        figure_extraction = figure_extraction_method or "none"
        table_extraction = table_extraction_method or "none"
        logger.info(f"[Embeddings Step 3] Using figure extraction: {figure_extraction}, table extraction: {table_extraction}")
        index = await build_rag_index(
            pdf_path,
            figure_extraction_method=figure_extraction,
            table_extraction_method=table_extraction
        )
        logger.info(f"[Embeddings Step 3] RAG index built successfully. Index contains {len(index.texts)} text chunks")
    except requests.exceptions.ConnectionError as e:
        # GROBID connection error - return 503 Service Unavailable
        error_msg = str(e)
        logger.error(f"[Embeddings Step 3] GROBID connection error: {error_msg}")
        raise HTTPException(
            status_code=503,
            detail=f"GROBID service is not available. {error_msg}\n\n"
                   f"To start GROBID, run:\n"
                   f"  docker-compose -f docker-compose.grobid.yml up -d\n\n"
                   f"Or verify GROBID is running:\n"
                   f"  curl http://localhost:8070/api/isalive"
        )
    except Exception as e:
        logger.error(f"[Embeddings Step 3] Failed to build RAG index: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error building RAG index: {str(e)}"
        )
    
    # Step 4: Extract paper metadata
    logger.info("[Embeddings Step 4] Extracting paper metadata...")
    try:
        metadata = extract_metadata_from_grobid_api(pdf_path)
        logger.info(f"[Embeddings Step 4] Metadata extracted: title={metadata.get('title', 'Unknown')}")
    except Exception as e:
        logger.warning(f"[Embeddings Step 4] Failed to extract metadata: {str(e)}, using defaults")
        metadata = {
            "title": "Unknown Title",
            "authors": [],
            "year": "N/A",
            "venue": "N/A"
        }
    
    logger.info("[Embeddings] Embedding pipeline completed successfully")
    return pdf_path, index, metadata


async def query_and_synthesize_summary(
    index: VectorIndex,
    metadata: Dict[str, Any],
    model: str = "gpt-4o-mini",
    queries: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Steps 6-7: Query-related processing pipeline.
    
    Implements the query and synthesis pipeline:
    6. Query-driven retrieval
    7. Final synthesis
    
    Args:
        index: VectorIndex built from paper content
        metadata: Paper metadata dictionary
        model: Model ID to use for synthesis (default: "gpt-4o-mini")
        queries: Optional dictionary of queries (defaults to REVIEW_QUERIES if not provided)
    
    Returns:
        Dictionary with keys: answers, markdown_review, html_content
    """
    logger.info("[Query] Starting query and synthesis pipeline...")
    
    # Step 6: Generate queries based on template and execute multi-query synthesis
    logger.info("[Query Step 6] Starting multi-query retrieval and synthesis...")
    try:
        logger.info(f"[Query Step 6] Using model: {model}")
        
        # Generate queries from template
        if queries is None:
            queries = REVIEW_QUERIES
        logger.info(f"[Query Step 6] Generated {len(queries)} queries based on template")
        
        # Execute all queries in parallel
        answers = await synthesize_multiple_queries(index, queries, model=model)
        logger.info(f"[Query Step 6] Multi-query synthesis completed. Generated {len(answers)} sections")
    except Exception as e:
        logger.error(f"[Query Step 6] Failed to synthesize answers: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error synthesizing review: {str(e)}\nFull traceback: {traceback.format_exc()}"
        )
    
    # Step 7: Format review as markdown
    logger.info("[Query Step 7] Formatting review as markdown...")
    try:
        markdown_review = format_review_as_markdown(metadata, answers)
        logger.info(f"[Query Step 7] Markdown review formatted. Length: {len(markdown_review)} characters")
        # Step 7b: Render markdown to HTML content
        logger.info("[Query Step 7b] Rendering markdown to HTML...")
        html_content = None
        try:
            html_content = render_markdown_to_html(markdown_review)
            logger.info(f"[Query Step 7b] HTML review rendered ({len(html_content)} chars)")
        except Exception as e:
            logger.error(f"[Query Step 7b] Failed to render HTML: {str(e)}\n{traceback.format_exc()}")
            # Don't fail the request if HTML rendering fails, just log it
            html_content = None
        
        logger.info("[Query] Query and synthesis pipeline completed successfully")
        return {
            "answers": answers,
            "markdown_review": markdown_review,
            "html_content": html_content
        }
    except Exception as e:
        logger.error(f"[Query Step 7] Failed to format review: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error formatting review: {str(e)}\nFull traceback: {traceback.format_exc()}"
        )
    
    

@router.post("/summary")
async def paper_summary(request: SummaryRequest):
    """
    Paper summary endpoint implementing the full pipeline architecture.
    When running on gateway (8010), fetches file info from main backend (8000) for file_ids.
    
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
        # When on gateway (8010), fetch file info from main backend (8000) for file_ids
        if request.file_ids:
            await ensure_file_info_from_main_backend(request.file_ids)
        
        logger.info(f"[Step 1] Starting summary request with: file_ids={request.file_ids}, paper_url={request.paper_url}, paper_name={request.paper_name}")
        
        # Steps 1-5: Build embeddings and index
        pdf_path, index, metadata = await build_paper_embeddings(
            file_ids=request.file_ids,
            paper_url=request.paper_url,
            paper_name=request.paper_name,
            use_openreview=request.use_openreview,
            figure_extraction_method=request.figure_extraction_method,
            table_extraction_method=request.table_extraction_method
        )
        
        # Steps 6-7: Query and synthesize
        model = request.model or "gpt-4o-mini"
        query_results = await query_and_synthesize_summary(
            index=index,
            metadata=metadata,
            model=model
        )
        
        logger.info("[Success] Paper review generation completed successfully")
        return {
            "summary": query_results["markdown_review"],
            "markdown": query_results["markdown_review"],
            "html_content": query_results["html_content"],
            "metadata": {
                **metadata,
                "pdf_path": pdf_path,
                "file_ids": request.file_ids,
                "paper_url": request.paper_url,
                "paper_name": request.paper_name,
            },
            "sections": query_results["answers"],
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


async def synthesize_answer(index, query: str, model: str = "gpt-4o-mini", section_name: str = None):
    """
    Step 6 & 7: Query-driven retrieval and final synthesis (async optimized)
    
    Args:
        index: VectorIndex built from paper content
        query: Query string for summary generation
        model: Model ID to use for synthesis (default: "gpt-4o-mini")
        section_name: Optional section name to apply format constraints (e.g., "summary")
        
    Returns:
        Generated summary text with format constraints applied
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
        ai_client = get_ai_client()
        retrieved_content = chr(10).join(retrieved)
        logger.info(f"[Synthesize] Retrieved content length: {len(retrieved_content)} characters")

        user_prompt_template = None
        # Try to load synthesis template, fallback to basic prompt if not found
        try:
            user_prompt_template = load_prompt_template("synthesis_user_prompt_template")
        except Exception:
            user_prompt_template = "Query: {query}\n\nRetrieved Content:\n{retrieved_content}\n\nPlease provide a comprehensive answer based on the retrieved content."
        
        user_prompt = format_prompt_template(
            user_prompt_template,
            query=query,
            retrieved_content=retrieved_content
        )
        # Load prompt templates
        system_prompt = load_prompt_template("paper_analysis_system_prompt")
        
        # Run API call in thread pool for async execution
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
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


async def synthesize_multiple_queries(
    index, 
    queries: Dict[str, str], 
    model: str = "gpt-4o-mini"
) -> Dict[str, str]:
    """
    Execute multiple queries in parallel and synthesize answers for each.
    
    Args:
        index: VectorIndex built from paper content
        queries: Dictionary mapping section names to query strings
        model: Model ID to use for synthesis
        
    Returns:
        Dictionary mapping section names to generated answers
    """
    logger.info(f"[MultiQuery] Starting synthesis for {len(queries)} queries...")
    
    # Execute all queries in parallel, passing section names for format control
    tasks = [
        synthesize_answer(index, query, model, section_name=section)
        for section, query in queries.items()
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results and handle exceptions
    answers = {}
    for (section, query), result in zip(queries.items(), results):
        if isinstance(result, Exception):
            logger.error(f"[MultiQuery] Failed to synthesize {section}: {str(result)}")
            answers[section] = f"Error generating {section}: {str(result)}"
        else:
            answers[section] = result
            logger.info(f"[MultiQuery] Completed {section}. Length: {len(result)} characters")
    
    return answers



