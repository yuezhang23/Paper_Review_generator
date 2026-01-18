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
from typing import Optional, List
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
from .image_optimizer import generate_and_save_image
# Import from three_layer_generator
from .three_layer_generator import generate_from_file
# Import prompt utilities
from .prompt_utils import load_prompt_template, format_prompt_template, get_max_step_number


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
    try:
        # Step 1: Resolve PDF path - try new parameters first, then fall back to legacy parameters
        pdf_path = None
        index = None
        
        # Try new parameters (file_ids, paper_url, paper_name)
        if request.file_ids or request.paper_url or request.paper_name:
            from summary_generator.main import build_paper_embeddings, resolve_pdf_path
            pdf_path, index, _ = await build_paper_embeddings(
                file_ids=request.file_ids,
                paper_url=request.paper_url,
                paper_name=request.paper_name,
                use_openreview=request.use_openreview,
                figure_extraction_method=request.figure_extraction_method,
                table_extraction_method=request.table_extraction_method
            )
        # Fall back to legacy parameters (pdf_path, file_id) for backward compatibility
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
            index = await build_rag_index(
                pdf_path,
                figure_extraction_method=request.figure_extraction_method or "none",
                table_extraction_method=request.table_extraction_method or "none"
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="No PDF source provided. Please provide file_ids, paper_url, paper_name, pdf_path, or file_id."
            )
        
        # Step 3: Two-step retrieval for methodology interpretation
        # Step 3.1: Run section-anchor queries to find "method zone" candidates
        # These queries are optimized for bge-base-en-v1.5 with proper prefix
        logger.info("Step 3.1: Running section-anchor queries to find method zone candidates...")
        method_zone_chunks = []
        for query in SECTION_ANCHOR_QUERIES:
            # Create query embedding (run in thread pool since embed_texts is synchronous)
            query_emb = await asyncio.to_thread(embed_texts, [query])
            query_emb = query_emb[0]
            
            # Query index for relevant chunks (k=10 for method zone identification)
            chunks = await asyncio.to_thread(index.query, query_emb, 10)
            method_zone_chunks.extend(chunks)
        
        # Deduplicate method zone chunks
        method_zone_chunks = list(set(method_zone_chunks))
        logger.info(f"Found {len(method_zone_chunks)} unique method zone chunks")
        
        # Step 3.2: Run detail-seeking queries, but bias toward method-zone chunks
        logger.info("Step 3.2: Running detail-seeking queries with bias toward method zones...")
        detail_chunks = []
        for query in DETAIL_SEEKING_QUERIES:
            # Create query embedding
            query_emb = await asyncio.to_thread(embed_texts, [query])
            query_emb = query_emb[0]
            
            # Query index for relevant chunks (k=12 for more context)
            chunks = await asyncio.to_thread(index.query, query_emb, 12)
            detail_chunks.extend(chunks)
        
        # Combine results: prioritize method-zone chunks, then add detail chunks not in method zones
        retrieved_chunks = method_zone_chunks.copy()  # Start with method zone chunks
        
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
        
        # Step 4: Generate step-by-step interpretation using AI
        ai_client = get_ai_client()
        retrieved_content = "\n\n".join(retrieved_chunks)
        
        # Load methodology interpretation prompts
        prompts_dir = os.path.join(os.path.dirname(__file__), "prompts")
        methodology_system_prompt = load_prompt_template(os.path.join(prompts_dir, "methodology_interpretation_system_prompt.md"))
        methodology_user_prompt_template = load_prompt_template(os.path.join(prompts_dir, "methodology_interpretation_user_prompt.md"))
        methodology_user_prompt = format_prompt_template(
            methodology_user_prompt_template,
            retrieved_content=retrieved_content
        )

        interpretations = []
        while len(interpretations) < 3:
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
            step_by_step_interpretation = interpretation_response.choices[0].message.content
            max_step_num = get_max_step_number(step_by_step_interpretation)
            # Limit the interpretation to avoid prompt being too long 
            if len(step_by_step_interpretation) > 5000:
                lines = step_by_step_interpretation.split('\n')
                step1_index = next((i for i, line in enumerate(lines) if 'Step 1' in line), 0)
                interpretation_preview = '\n'.join(lines[step1_index:])
            else:
                interpretation_preview = step_by_step_interpretation
            interpretations.append([interpretation_preview, max_step_num])
        
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
        result = await generate_from_file(interpretation_path, request_dir)
        whiteboard_prompt = result["layer3_render"]
        
        # Generate and save image using the optimized function
        image_result = await generate_and_save_image(
            ai_client=ai_client,
            whiteboard_prompt=whiteboard_prompt,
            model=request.model,
            request_dir=request_dir,
            timeout_seconds=240,
        )
        return {
            "image_url": image_result["image_url"],
            "revised_prompt": whiteboard_prompt, 
            "methodology_steps": interpretation_preview
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating image: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating image: {str(e)}"
        )
