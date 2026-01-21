"""
Image Method Generator - Handles methodology diagram image generation
Extracts methodology content from papers and generates visual diagrams
"""

import os
import time
import base64
import traceback
import logging
import asyncio
import re
import json
import hashlib
from typing import Optional, List, Tuple
from fastapi import HTTPException
from pydantic import BaseModel

# Set up logging
logger = logging.getLogger(__name__)

# Import from parent utils module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import file_storage, get_ai_client

# Import from summary_generator modules (updated path)
from summary_generator.embeddings import embed_texts, VectorIndex
from summary_generator.cache import get_pdf_hash, load_cached_index
from .methodology_utils import SECTION_ANCHOR_QUERIES, DETAIL_SEEKING_QUERIES

# Import from image_optimizer
from .image_optimizer import generate_and_save_image, criticize_image_with_render_text, edit_image_with_issues
# Import from three_layer_generator
from .three_layer_generator import generate_from_file
# Import prompt utilities
from .prompt_utils import load_prompt_template, format_prompt_template, get_max_step_number

# Cache directory for retrieved chunks (reuse embeddings_cache directory)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "embeddings_cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def get_paper_cache_key(
    pdf_path: Optional[str] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    file_ids: Optional[List[str]] = None
) -> str:
    """
    Generate a cache key for a paper based on available identifiers.
    Prefers PDF hash (most reliable), then falls back to URL/name/file_ids hash.
    
    Args:
        pdf_path: Path to PDF file
        paper_url: URL to the paper
        paper_name: Name of the paper
        file_ids: List of file IDs
        
    Returns:
        Cache key string (MD5 hash)
    """
    # Prefer PDF hash if available (most reliable)
    if pdf_path and os.path.exists(pdf_path):
        return get_pdf_hash(pdf_path)
    
    # Fall back to hashing other identifiers
    hash_md5 = hashlib.md5()
    has_data = False
    
    if paper_url:
        hash_md5.update(f"url:{paper_url}".encode('utf-8'))
        has_data = True
    if paper_name:
        hash_md5.update(f"name:{paper_name}".encode('utf-8'))
        has_data = True
    if file_ids:
        hash_md5.update(f"files:{','.join(sorted(file_ids))}".encode('utf-8'))
        has_data = True
    
    if not has_data:
        raise ValueError("Cannot generate cache key: no paper identifier provided")
    
    return hash_md5.hexdigest()


def load_cached_chunks(cache_key: str) -> Optional[Tuple[List[str], List[str]]]:
    """
    Load cached retrieved chunks for a paper.
    
    Args:
        cache_key: Cache key for the paper
        
    Returns:
        Tuple of (method_zone_chunks, detail_chunks) if cache exists, None otherwise
    """
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}_methodology_chunks.json")
    if not os.path.exists(cache_file):
        return None
    
    try:
        logger.info(f"[Cache] Loading cached methodology chunks for key: {cache_key[:8]}...")
        with open(cache_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            method_zone_chunks = data.get('method_zone_chunks', [])
            detail_chunks = data.get('detail_chunks', [])
            logger.info(f"[Cache] Successfully loaded cached chunks: {len(method_zone_chunks)} method zone, {len(detail_chunks)} detail")
            return (method_zone_chunks, detail_chunks)
    except Exception as e:
        logger.warning(f"[Cache] Failed to load cached chunks: {str(e)}. Will re-retrieve.")
        return None


def save_cached_chunks(cache_key: str, method_zone_chunks: List[str], detail_chunks: List[str]):
    """
    Save retrieved chunks to cache.
    
    Args:
        cache_key: Cache key for the paper
        method_zone_chunks: List of method zone chunks
        detail_chunks: List of detail chunks
    """
    try:
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}_methodology_chunks.json")
        data = {
            'method_zone_chunks': method_zone_chunks,
            'detail_chunks': detail_chunks
        }
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"[Cache] Successfully cached methodology chunks for key: {cache_key[:8]}...")
    except Exception as e:
        logger.warning(f"[Cache] Failed to save cached chunks: {str(e)}")


class ImageGenerationRequest(BaseModel):
    file_ids: Optional[List[str]] = None  # List of uploaded file IDs
    paper_url: Optional[str] = None  # URL to PDF paper
    paper_name: Optional[str] = None  # Paper name for search
    use_openreview: Optional[bool] = True  # Whether to use OpenReview for paper fetching
    pdf_path: Optional[str] = None  # PDF path to retrieve embeddings (backward compatibility)
    file_id: Optional[str] = None  # File ID to retrieve PDF path (backward compatibility)
    model: Optional[str] = "gpt-image-1.5"  # Default to gpt-image-1.5 (AI Builder API default image model)
    size: Optional[str] = "1024x1024"  # Default size
    quality: Optional[str] = "auto"  # low, medium, high, or auto (AI Builder API supported values)
    figure_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"
    table_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"


async def generate_summary_image(request: ImageGenerationRequest):
    """Generate an image from paper content using AI Builder API 
    
    Steps:
    1. Resolve PDF path and build/load RAG index
    2. Query RAG index for step-by-step methodology interpretation
    3. Parse retrieved embeddings as context
    4. Generate whiteboard diagram image
    """
    function_start_time = time.time()
    logger.info("Starting generate_summary_image")
    try:
        # Step 1: Resolve PDF path - try new parameters first, then fall back to legacy parameters
        pdf_path = None
        index = None
        
        # Try new parameters (file_ids, paper_url, paper_name)
        if request.file_ids or request.paper_url or request.paper_name:
            from summary_generator.main import build_paper_embeddings, resolve_pdf_path
            start_time = time.time()
            pdf_path, index, _ = await build_paper_embeddings(
                file_ids=request.file_ids,
                paper_url=request.paper_url,
                paper_name=request.paper_name,
                use_openreview=request.use_openreview,
                figure_extraction_method=request.figure_extraction_method,
                table_extraction_method=request.table_extraction_method
            )
            elapsed_time = time.time() - start_time
            logger.info(f"build_paper_embeddings took {elapsed_time:.2f} seconds")

        elif request.pdf_path or request.file_id:
            # Resolve PDF path from legacy parameters
            pdf_path = request.pdf_path
            if not pdf_path and request.file_id:
                if request.file_id in file_storage:
                    file_info = file_storage[request.file_id]
                    pdf_path = file_info.get('pdf_path')
                    if not pdf_path or not os.path.exists(pdf_path):
                        raise HTTPException(
                            status_code=404,
                            detail=f"PDF file {request.file_id} not found on disk"
                        )
                else:
                    raise HTTPException(
                        status_code=404,
                        detail=f"File ID {request.file_id} not found"
                    )
            
            if not pdf_path:
                raise HTTPException(
                    status_code=400,
                    detail="No PDF source provided. Please provide file_ids, paper_url, paper_name, pdf_path, or file_id."
                )
            
            # Try to load cached RAG index, or build it if it doesn't exist
            from summary_generator.embeddings import build_rag_index
            start_time = time.time()
            index = await build_rag_index(
                pdf_path,
                figure_extraction_method=request.figure_extraction_method or "none",
                table_extraction_method=request.table_extraction_method or "none"
            )
            elapsed_time = time.time() - start_time
            logger.info(f"build_rag_index took {elapsed_time:.2f} seconds")
        else:
            raise HTTPException(
                status_code=400,
                detail="No PDF source provided. Please provide file_ids, paper_url, paper_name, pdf_path, or file_id."
            )
        
        # Generate cache key for this paper
        cache_key = get_paper_cache_key(
            pdf_path=pdf_path,
            paper_url=request.paper_url,
            paper_name=request.paper_name,
            file_ids=request.file_ids
        )
        logger.info(f"Using cache key: {cache_key[:16]}...")
        
        # Step 3: Two-step retrieval for methodology interpretation
        # Check cache first
        cached_result = load_cached_chunks(cache_key)
        if cached_result is not None:
            method_zone_chunks, detail_chunks = cached_result
            logger.info(f"Using cached chunks: {len(method_zone_chunks)} method zone, {len(detail_chunks)} detail")
        else:
            # Step 3.1: Run section-anchor queries to find "method zone" candidates
            # These queries are optimized for bge-base-en-v1.5 with proper prefix
            logger.info("Step 3.1: Running section-anchor queries to find method zone candidates...")
            method_zone_chunks = []
            section_anchor_start_time = time.time()
            for query in SECTION_ANCHOR_QUERIES:
                # Create query embedding (run in thread pool since embed_texts is synchronous)
                start_time = time.time()
                query_emb = await asyncio.to_thread(embed_texts, [query])
                elapsed_time = time.time() - start_time
                logger.info(f"embed_texts (section-anchor) took {elapsed_time:.2f} seconds")
                query_emb = query_emb[0]
                
                # Query index for relevant chunks (k=10 for method zone identification)
                start_time = time.time()
                chunks = await asyncio.to_thread(index.query, query_emb, 10)
                elapsed_time = time.time() - start_time
                logger.info(f"index.query (section-anchor) took {elapsed_time:.2f} seconds")
                method_zone_chunks.extend(chunks)
            section_anchor_elapsed = time.time() - section_anchor_start_time
            logger.info(f"Step 3.1 (section-anchor queries) total took {section_anchor_elapsed:.2f} seconds")
            
            # Deduplicate method zone chunks
            method_zone_chunks = list(set(method_zone_chunks))
            logger.info(f"Found {len(method_zone_chunks)} unique method zone chunks")
            
            # Step 3.2: Run detail-seeking queries, but bias toward method-zone chunks
            logger.info("Step 3.2: Running detail-seeking queries with bias toward method zones...")
            detail_chunks = []
            detail_seeking_start_time = time.time()
            for query in DETAIL_SEEKING_QUERIES:
                # Create query embedding
                start_time = time.time()
                query_emb = await asyncio.to_thread(embed_texts, [query])
                elapsed_time = time.time() - start_time
                logger.info(f"embed_texts (detail-seeking) took {elapsed_time:.2f} seconds")
                query_emb = query_emb[0]
                
                # Query index for relevant chunks (k=12 for more context)
                start_time = time.time()
                chunks = await asyncio.to_thread(index.query, query_emb, 12)
                elapsed_time = time.time() - start_time
                logger.info(f"index.query (detail-seeking) took {elapsed_time:.2f} seconds")
                detail_chunks.extend(chunks)
            detail_seeking_elapsed = time.time() - detail_seeking_start_time
            logger.info(f"Step 3.2 (detail-seeking queries) total took {detail_seeking_elapsed:.2f} seconds")
            
            # Save to cache
            save_cached_chunks(cache_key, method_zone_chunks, detail_chunks)
        
        # Combine results: prioritize method-zone chunks, then add detail chunks not in method zones
        retrieved_chunks = method_zone_chunks.copy()  
        
        # Add detail chunks that aren't already in method zones
        detail_chunks_set = set(detail_chunks)
        method_zone_set = set(method_zone_chunks)
        new_detail_chunks = [chunk for chunk in detail_chunks_set if chunk not in method_zone_set]
        retrieved_chunks.extend(new_detail_chunks)
        
        logger.info(f"Total retrieved chunks: {len(retrieved_chunks)} ({len(method_zone_chunks)} from method zones, {len(new_detail_chunks)} additional detail chunks)")

        if not retrieved_chunks:
            raise HTTPException(
                status_code=404,
                detail="No relevant methodology content found in embeddings"
            )
        logger.info(f"Retrieved chunks completed: {len(retrieved_chunks)} chunks")

        # Step 4: Generate step-by-step interpretation using AI
        ai_client = get_ai_client()
        retrieved_content = "\n\n".join(retrieved_chunks)
        
        # Load methodology interpretation prompts
        prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
        start_time = time.time()
        methodology_system_prompt = load_prompt_template(os.path.join(prompts_dir, "methodology_interpretation_system_prompt.md"))
        elapsed_time = time.time() - start_time
        logger.info(f"load_prompt_template (system) took {elapsed_time:.2f} seconds")
        
        start_time = time.time()
        methodology_user_prompt_template = load_prompt_template(os.path.join(prompts_dir, "methodology_interpretation_user_prompt.md"))
        elapsed_time = time.time() - start_time
        logger.info(f"load_prompt_template (user) took {elapsed_time:.2f} seconds")
        
        start_time = time.time()
        methodology_user_prompt = format_prompt_template(
            methodology_user_prompt_template,
            retrieved_content=retrieved_content
        )
        elapsed_time = time.time() - start_time
        logger.info(f"format_prompt_template took {elapsed_time:.2f} seconds")

        interpretations = []
        interpretation_loop_start_time = time.time()
        while len(interpretations) < 1:
            start_time = time.time()
            interpretation_response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="supermind-agent-v1",
                messages=[
                    {
                        "role": "system",
                        "content": methodology_system_prompt
                    },
                    {
                        "role": "user",
                        "content": methodology_user_prompt
                    }
                ],
                temperature=0.2,
                max_tokens=1500
            )
            elapsed_time = time.time() - start_time
            logger.info(f"ai_client.chat.completions.create (interpretation {len(interpretations) + 1}) took {elapsed_time:.2f} seconds")
            step_by_step_interpretation = interpretation_response.choices[0].message.content
            
            start_time = time.time()
            max_step_num = get_max_step_number(step_by_step_interpretation)
            elapsed_time = time.time() - start_time
            logger.info(f"get_max_step_number took {elapsed_time:.2f} seconds")
            # Limit the interpretation to avoid prompt being too long 
            if len(step_by_step_interpretation) > 5000:
                lines = step_by_step_interpretation.split('\n')
                step1_index = next((i for i, line in enumerate(lines) if 'Step 1' in line), 0)
                interpretation_preview = '\n'.join(lines[step1_index:])
            else:
                interpretation_preview = step_by_step_interpretation
            interpretations.append([interpretation_preview, max_step_num])
        interpretation_loop_elapsed = time.time() - interpretation_loop_start_time
        logger.info(f"Interpretation loop (3 iterations) total took {interpretation_loop_elapsed:.2f} seconds")
        
        # check the content of interpretations, use majority voting to choose the most common number of steps should appear in the interpretations
        most_common_step_count = max(set([interpretation[1] for interpretation in interpretations]), key=[interpretation[1] for interpretation in interpretations].count)
        interpretation_preview = [interpretation[0] for interpretation in interpretations if interpretation[1] == most_common_step_count][0]

        # Generate unique request directory using timestamp
        timestamp = int(time.time())
        request_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), f"image_methodos_generator/images/{timestamp}")
        os.makedirs(request_dir, exist_ok=True)
        
        # Save the interpretation preview locally with matching timestamp
        interpretation_filename = f"interpretation.txt"
        interpretation_path = os.path.join(request_dir, interpretation_filename)
        try:
            with open(interpretation_path, "w", encoding="utf-8") as f:
                f.write(interpretation_preview)
            logger.info(f"Interpretation preview saved to: {interpretation_path}")
        except Exception as save_error:
            logger.warning(f"Failed to save interpretation preview: {str(save_error)}")
        
        # Load whiteboard diagram prompt template
        start_time = time.time()
        result = await generate_from_file(interpretation_path, request_dir)
        elapsed_time = time.time() - start_time
        logger.info(f"generate_from_file took {elapsed_time:.2f} seconds")
        whiteboard_prompt = result["layer3_render"]
        
        # Generate and save image using the optimized function
        start_time = time.time()
        image_result = await generate_and_save_image(
            ai_client=ai_client,
            whiteboard_prompt=whiteboard_prompt,
            model=request.model,
            request_dir=request_dir,
            timeout_seconds=240,
        )
        # criticize the image
        start_time = time.time()
        criticism = await criticize_image_with_render_text(ai_client, request_dir, os.path.join(request_dir, "methodology.png"))
        elapsed_time = time.time() - start_time
        elapsed_time = time.time() - start_time
        logger.info(f"generate_and_save_image took {elapsed_time:.2f} seconds")

        # edit the image with the issues
        start_time = time.time()
        edited_image = await edit_image_with_issues(ai_client, request_dir, os.path.join(request_dir, "methodology.png"))
        elapsed_time = time.time() - start_time
        logger.info(f"edit_image_with_issues took {elapsed_time:.2f} seconds")
        
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time: {total_elapsed_time:.2f} seconds")
        
        return {
            "image_url": image_result["image_url"],
            "revised_prompt": whiteboard_prompt, 
            "methodology_steps": interpretation_preview
        }

    except HTTPException:
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time (HTTPException): {total_elapsed_time:.2f} seconds")
        raise
    except Exception as e:
        total_elapsed_time = time.time() - function_start_time
        logger.error(f"Error generating image: {str(e)}\n{traceback.format_exc()}")
        logger.info(f"generate_summary_image total execution time (Exception): {total_elapsed_time:.2f} seconds")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating image: {str(e)}"
        )
