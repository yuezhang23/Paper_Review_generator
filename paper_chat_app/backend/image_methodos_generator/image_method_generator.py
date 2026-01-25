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
from typing import Optional, List, Tuple, Dict, Any
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
from summary_generator.cache import get_content_based_cache_key
from .methodology_utils import SECTION_ANCHOR_QUERIES, DETAIL_SEEKING_QUERIES

# Import from image_optimizer
from .image_optimizer import generate_and_save_image, rank_images_by_informativeness
from .image_optimizer import criticize_image_with_queries
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
    # Prefer content-based key (first paragraph) if PDF available – lightweight
    if pdf_path and os.path.exists(pdf_path):
        return get_content_based_cache_key(pdf_path)
    
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


async def _resolve_pdf_and_index(request: ImageGenerationRequest) -> Tuple[str, "VectorIndex", str]:
    """
    Step 1: Resolve PDF path and build/load RAG index from file_ids, paper_url, paper_name,
    or legacy pdf_path/file_id. Returns (pdf_path, index, cache_key).
    """
    pdf_path = None
    index = None

    if request.file_ids or request.paper_url or request.paper_name:
        from summary_generator.main import build_paper_embeddings
        start_time = time.time()
        pdf_path, index, _ = await build_paper_embeddings(
            file_ids=request.file_ids,
            paper_url=request.paper_url,
            paper_name=request.paper_name,
            use_openreview=request.use_openreview,
            figure_extraction_method=request.figure_extraction_method,
            table_extraction_method=request.table_extraction_method,
        )
        elapsed_time = time.time() - start_time
        logger.info(f"build_paper_embeddings took {elapsed_time:.2f} seconds")

    elif request.pdf_path or request.file_id:
        pdf_path = request.pdf_path
        if not pdf_path and request.file_id:
            if request.file_id in file_storage:
                file_info = file_storage[request.file_id]
                pdf_path = file_info.get("pdf_path")
                if not pdf_path or not os.path.exists(pdf_path):
                    raise HTTPException(
                        status_code=404,
                        detail=f"PDF file {request.file_id} not found on disk",
                    )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"File ID {request.file_id} not found",
                )

        if not pdf_path:
            raise HTTPException(
                status_code=400,
                detail="No PDF source provided. Please provide file_ids, paper_url, paper_name, pdf_path, or file_id.",
            )

        from summary_generator.embeddings import build_rag_index
        start_time = time.time()
        index = await build_rag_index(
            pdf_path,
            figure_extraction_method=request.figure_extraction_method or "none",
            table_extraction_method=request.table_extraction_method or "none",
        )
        elapsed_time = time.time() - start_time
        logger.info(f"build_rag_index took {elapsed_time:.2f} seconds")

    else:
        raise HTTPException(
            status_code=400,
            detail="No PDF source provided. Please provide file_ids, paper_url, paper_name, pdf_path, or file_id.",
        )

    cache_key = get_paper_cache_key(
        pdf_path=pdf_path,
        paper_url=request.paper_url,
        paper_name=request.paper_name,
        file_ids=request.file_ids,
    )
    logger.info(f"Using cache key: {cache_key[:16]}...")
    return pdf_path, index, cache_key


async def _retrieve_methodology_chunks(
    cache_key: str, index: "VectorIndex"
) -> Tuple[List[str], List[str]]:
    """
    Step 2: Load cached chunks or run section-anchor and detail-seeking queries,
    then cache results. Returns (method_zone_chunks, detail_chunks).
    """
    cached_result = load_cached_chunks(cache_key)
    if cached_result is not None:
        method_zone_chunks, detail_chunks = cached_result
        logger.info(
            f"Using cached chunks: {len(method_zone_chunks)} method zone, {len(detail_chunks)} detail"
        )
        return method_zone_chunks, detail_chunks

    logger.info("Step 3.1: Running section-anchor queries to find method zone candidates...")
    section_anchor_start_time = time.time()
    
    # Helper function to process a single section-anchor query
    async def process_section_anchor_query(query: str):
        query_emb = await asyncio.to_thread(embed_texts, [query])
        query_emb = query_emb[0]
        chunks = await asyncio.to_thread(index.query, query_emb, 10)
        return chunks
    
    # Run all section-anchor queries in parallel
    section_anchor_results = await asyncio.gather(
        *[process_section_anchor_query(query) for query in SECTION_ANCHOR_QUERIES],
        return_exceptions=True
    )
    
    # Collect chunks from all queries
    method_zone_chunks = []
    for result in section_anchor_results:
        if isinstance(result, Exception):
            logger.warning(f"Error processing section-anchor query: {str(result)}")
        else:
            method_zone_chunks.extend(result)
    
    section_anchor_elapsed = time.time() - section_anchor_start_time
    logger.info(f"Step 3.1 (section-anchor queries) total took {section_anchor_elapsed:.2f} seconds")

    method_zone_chunks = list(set(method_zone_chunks))
    logger.info(f"Found {len(method_zone_chunks)} unique method zone chunks")

    logger.info("Step 3.2: Running detail-seeking queries with bias toward method zones...")
    detail_seeking_start_time = time.time()
    
    # Helper function to process a single detail-seeking query
    async def process_detail_seeking_query(query: str):
        query_emb = await asyncio.to_thread(embed_texts, [query])
        query_emb = query_emb[0]
        chunks = await asyncio.to_thread(index.query, query_emb, 12)
        return chunks
    
    # Run all detail-seeking queries in parallel
    detail_seeking_results = await asyncio.gather(
        *[process_detail_seeking_query(query) for query in DETAIL_SEEKING_QUERIES],
        return_exceptions=True
    )
    
    # Collect chunks from all queries
    detail_chunks = []
    for result in detail_seeking_results:
        if isinstance(result, Exception):
            logger.warning(f"Error processing detail-seeking query: {str(result)}")
        else:
            detail_chunks.extend(result)
    
    detail_seeking_elapsed = time.time() - detail_seeking_start_time
    logger.info(f"Step 3.2 (detail-seeking queries) total took {detail_seeking_elapsed:.2f} seconds")

    save_cached_chunks(cache_key, method_zone_chunks, detail_chunks)
    return method_zone_chunks, detail_chunks


def _combine_and_validate_chunks(
    method_zone_chunks: List[str], detail_chunks: List[str]
) -> str:
    """
    Step 3: Combine method-zone and detail chunks (deduplicated), validate we have content,
    and return joined retrieved_content.
    """
    retrieved_chunks = method_zone_chunks.copy()
    detail_chunks_set = set(detail_chunks)
    method_zone_set = set(method_zone_chunks)
    new_detail_chunks = [c for c in detail_chunks_set if c not in method_zone_set]
    retrieved_chunks.extend(new_detail_chunks)

    logger.info(
        f"Total retrieved chunks: {len(retrieved_chunks)} ({len(method_zone_chunks)} from method zones, "
        f"{len(new_detail_chunks)} additional detail chunks)"
    )

    if not retrieved_chunks:
        raise HTTPException(
            status_code=404,
            detail="No relevant methodology content found in embeddings",
        )

    retrieved_content = "\n\n".join(retrieved_chunks)
    logger.info(f"Retrieved chunks completed: {len(retrieved_chunks)} chunks")
    return retrieved_content


async def _generate_interpretation(ai_client, retrieved_content: str) -> str:
    """
    Step 4: Generate step-by-step methodology interpretation via AI (3 runs),
    majority-vote on step count, and return the chosen interpretation_preview.
    """
    prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
    start_time = time.time()
    methodology_system_prompt = load_prompt_template(
        os.path.join(prompts_dir, "methodology_interpretation_system_prompt.md")
    )
    elapsed_time = time.time() - start_time
    logger.info(f"load_prompt_template (system) took {elapsed_time:.2f} seconds")

    start_time = time.time()
    methodology_user_prompt_template = load_prompt_template(
        os.path.join(prompts_dir, "methodology_interpretation_user_prompt.md")
    )
    elapsed_time = time.time() - start_time
    logger.info(f"load_prompt_template (user) took {elapsed_time:.2f} seconds")

    start_time = time.time()
    methodology_user_prompt = format_prompt_template(
        methodology_user_prompt_template,
        retrieved_content=retrieved_content,
    )
    elapsed_time = time.time() - start_time
    logger.info(f"format_prompt_template took {elapsed_time:.2f} seconds")

    interpretations = []
    interpretation_loop_start_time = time.time()
    
    # Helper function to generate a single interpretation
    async def generate_single_interpretation():
        interpretation_response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model="supermind-agent-v1",
            messages=[
                {"role": "system", "content": methodology_system_prompt},
                {"role": "user", "content": methodology_user_prompt},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        step_by_step_interpretation = interpretation_response.choices[0].message.content

        max_step_num = get_max_step_number(step_by_step_interpretation)

        if len(step_by_step_interpretation) > 5000:
            lines = step_by_step_interpretation.split("\n")
            step1_index = next((i for i, line in enumerate(lines) if "Step 1" in line), 0)
            interpretation_preview = "\n".join(lines[step1_index:])
        else:
            interpretation_preview = step_by_step_interpretation
        return [interpretation_preview, max_step_num]
    
    # Run all 3 interpretations in parallel
    interpretation_results = await asyncio.gather(
        *[generate_single_interpretation() for _ in range(3)],
        return_exceptions=True
    )
    
    # Collect valid interpretations
    for result in interpretation_results:
        if isinstance(result, Exception):
            logger.warning(f"Error generating interpretation: {str(result)}")
        else:
            interpretations.append(result)

    interpretation_loop_elapsed = time.time() - interpretation_loop_start_time
    logger.info(f"Interpretation loop (3 iterations) total took {interpretation_loop_elapsed:.2f} seconds")

    step_counts = [interp[1] for interp in interpretations]
    most_common_step_count = max(set(step_counts), key=step_counts.count)
    chosen = [interp[0] for interp in interpretations if interp[1] == most_common_step_count][0]
    return chosen


def _save_interpretation_and_create_request_dir(interpretation_preview: str) -> Tuple[str, str]:
    """
    Step 5: Create request directory (timestamp-based), save interpretation to file,
    and return (request_dir, interpretation_path).
    """
    timestamp = int(time.time())
    request_dir = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        f"image_methodos_generator/images/{timestamp}",
    )
    os.makedirs(request_dir, exist_ok=True)

    interpretation_filename = "interpretation.txt"
    interpretation_path = os.path.join(request_dir, interpretation_filename)
    try:
        with open(interpretation_path, "w", encoding="utf-8") as f:
            f.write(interpretation_preview)
        logger.info(f"Interpretation preview saved to: {interpretation_path}")
    except Exception as save_error:
        logger.warning(f"Failed to save interpretation preview: {str(save_error)}")

    return request_dir, interpretation_path


async def _generate_whiteboard_prompt(
    interpretation_path: str, request_dir: str
) -> str:
    """
    Step 6: Generate whiteboard diagram prompt (layer3_render) from interpretation file.
    """
    start_time = time.time()
    result = await generate_from_file(interpretation_path, request_dir)
    elapsed_time = time.time() - start_time
    logger.info(f"generate_from_file took {elapsed_time:.2f} seconds")
    return result["layer3_render"]


async def _generate_image(
    ai_client,
    whiteboard_prompt: str,
    request_dir: str,
    criticize_image: bool = True,
) -> Tuple[bytes, str, List[Dict[str, Any]]]:
    """
    Step 7: Generate and save image, run criticism loop, and optionally regenerate.
    Returns (image_bytes, image_url, criticism).
    """
    max_retries = 5
    new_image_infos = []
    image_bytes = None
    image_url = None
    image_path = None

    for i in range(max_retries):
        iter_start = time.time()
        image_result = await generate_and_save_image(
            ai_client=ai_client,
            whiteboard_prompt=whiteboard_prompt,
            model="gpt-image-1.5",
            request_dir=request_dir,
            timeout_seconds=240,
        )
        image_path = os.path.join(request_dir, f"methodology_{i}.png")
        image_bytes = image_result["image_bytes"]
        image_url = image_result["image_url"]
        with open(image_path, "wb") as f:
            new_image_infos.append({"image_index": i, "image_path": image_path, "image_bytes": image_bytes, "image_url": image_url})
            f.write(image_bytes)
        logger.info(f"Image saved to: {image_path}")

    with open(os.path.join(request_dir, "layer3_render.txt"), 'r', encoding='utf-8') as f:
        ground_truth_render_blueprint = f.read()
    
    # Rank the images by informativeness
    image_path_list = [c["image_path"] for c in new_image_infos]
    results = await rank_images_by_informativeness(ai_client, image_path_list, ground_truth_render_blueprint, request_dir)
    # print(results)
    image_bytes = new_image_infos[results[0]["image_index"]]["image_bytes"]
    image_url = new_image_infos[results[0]["image_index"]]["image_url"]
    return image_bytes, image_url

        # # Criticize the image
        # render_path = os.path.join(request_dir, "layer3_render.txt")
        # if criticize_image:
        #     criticism = await criticize_image_with_queries(ai_client, render_path, image_path)
        
        # elapsed_time = time.time() - iter_start
        # logger.info(f"generate_and_save_image (iter {i + 1}) took {elapsed_time:.2f} seconds")

        # # check if there are more than 2 true in criticism
        # if len([(c[0], c[1]) for c in criticism if isinstance(c[1], bool) and c[1] == True]) <= 2:
        #     logger.info(f"Image generated successfully within 2 mismatches")
        #     return image_bytes, image_url
        # else:
        #     logger.info(f"Image generated with more than 2 major mismatches")

async def generate_summary_image(request: ImageGenerationRequest):
    function_start_time = time.time()
    try:
        # Step 1: Resolve PDF path and build/load RAG index
        pdf_path, index, cache_key = await _resolve_pdf_and_index(request)
        
        # Step 2: Retrieve methodology chunks (with parallelized queries)
        method_zone_chunks, detail_chunks = await _retrieve_methodology_chunks(cache_key, index)
        
        # Step 3: Combine and validate chunks
        retrieved_content = _combine_and_validate_chunks(method_zone_chunks, detail_chunks)
        
        # Step 4: Generate step-by-step interpretation using AI (with parallelized calls)
        ai_client = get_ai_client()
        interpretation_preview = await _generate_interpretation(ai_client, retrieved_content)
        
        # Step 5: Save interpretation and create request directory
        request_dir, interpretation_path = _save_interpretation_and_create_request_dir(interpretation_preview)
        
        # Step 6: Generate whiteboard diagram prompt
        whiteboard_prompt = await _generate_whiteboard_prompt(interpretation_path, request_dir)
        
        # Step 7: Generate and save image
        image_bytes, image_url = await _generate_image(
            ai_client, whiteboard_prompt, request_dir, criticize_image=True
        )
        
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time: {total_elapsed_time:.2f} seconds")
        
        return {
            "image_url": image_url,
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
