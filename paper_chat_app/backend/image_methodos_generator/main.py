import time
import traceback
import logging
from fastapi import HTTPException, APIRouter
from .image_method_generator import ImageGenerationRequest, resolve_pdf_and_index, retrieve_methodology_chunks, combine_and_validate_chunks, generate_interpretation, save_interpretation_and_create_request_dir, generate_whiteboard_prompt, generate_image
from utils import get_ai_client

router = APIRouter(prefix="/api", tags=["image-generation"])
logger = logging.getLogger(__name__)

@router.post("/generate-summary-image")
async def generate_summary_image(request: ImageGenerationRequest):
    function_start_time = time.time()
    try:
        # Step 1: Resolve PDF path and build/load RAG index
        pdf_path, index, cache_key = await resolve_pdf_and_index(request)
        
        # Step 2: Retrieve methodology chunks (with parallelized queries)
        method_zone_chunks, detail_chunks = await retrieve_methodology_chunks(cache_key, index)
        
        # Step 3: Combine and validate chunks
        retrieved_content = combine_and_validate_chunks(method_zone_chunks, detail_chunks)
        
        # Step 4: Generate step-by-step interpretation using AI (with parallelized calls)
        ai_client = get_ai_client()
        interpretation_preview = await generate_interpretation(ai_client, retrieved_content)
        
        # Step 5: Save interpretation and create request directory
        request_dir, interpretation_path = save_interpretation_and_create_request_dir(interpretation_preview)
        
        # Step 6: Generate whiteboard diagram prompt
        whiteboard_prompt = await generate_whiteboard_prompt(interpretation_path, request_dir)
        
        # Step 7: Generate and save image
        image_bytes, image_url = await generate_image(
            ai_client, whiteboard_prompt, request_dir, criticize_image=True
        )
        
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time: {total_elapsed_time:.2f} seconds")
        
        return {
            "image_url": image_url,
            "image_bytes": image_bytes,
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
