"""
Image Optimizer - Handles image generation and optimization
"""

import os
import base64
import asyncio
import logging
from io import BytesIO
from fastapi import HTTPException
from PIL import Image
# Import from parent utils module
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from image_methodos_generator.prompt_utils import load_prompt_template, format_prompt_template, fix_imamge_size

# Set up logging
logger = logging.getLogger(__name__)


async def generate_and_save_image(
    ai_client,
    whiteboard_prompt: str,
    model: str,
    request_dir: str,
    max_retries: int = 3,
    timeout_seconds: int = 240,
    retry_delay: int = 2,
    max_width: int = 1536,
    max_height: int = 1024
) -> dict:
    """
    Generate an image using AI Builder API and save it to disk.
    
    Args:
        ai_client: The AI client instance
        whiteboard_prompt: The prompt for image generation
        model: The model to use for image generation
        request_dir: Directory to save the image
        max_retries: Maximum number of retry attempts (default: 3)
        timeout_seconds: Timeout for each attempt in seconds (default: 240)
        retry_delay: Initial retry delay in seconds (default: 2)
        max_width: Maximum image width (default: 1536)
        max_height: Maximum image height (default: 1024)
    
    Returns:
        dict with keys:
            - image_url: Base64 data URL of the image
            - image_path: Path where the image was saved
            - image_bytes: The image bytes
    
    Raises:
        HTTPException: If image generation fails after all retries
    """
    response = None
    last_error = None

    
    try:
        # Use asyncio.wait_for to add timeout protection
        response = await asyncio.wait_for(
            asyncio.to_thread(
                ai_client.images.generate,
                prompt=whiteboard_prompt,
                model=model,
                n=1
            ),
            timeout=timeout_seconds
        )
        
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Image generation timed out after {timeout_seconds} seconds. The service may be experiencing high load."
        )

    if response is None:
        raise HTTPException(
            status_code=500,
            detail="Image generation failed: No response received"
        )
    
    b64_json_data = response.data[0].b64_json
    logger.info(f"Image returned as base64 JSON (length: {len(b64_json_data)} characters)")
    
    # Decode image and check dimensions
    image_bytes = base64.b64decode(b64_json_data)
    image_bytes = fix_imamge_size(image_bytes, max_width, max_height)

    
    b64_json_data = base64.b64encode(image_bytes).decode('utf-8')
    # Convert base64 to data URL for frontend
    image_url = f"data:image/png;base64,{b64_json_data}"
    
    # Save the image locally in the request directory
    image_filename = "methodology.png"
    image_path = os.path.join(request_dir, image_filename)
    
    # Save image to disk
    try:
        with open(image_path, "wb") as f:
            f.write(image_bytes)
        logger.info(f"Image saved to: {image_path} ({len(image_bytes)} bytes)")
    except Exception as e:
        logger.warning(f"Failed to save image to disk: {str(e)}")
    
    return {
        "image_url": image_url,
        "image_path": image_path,
        "image_bytes": image_bytes
    }



async def criticize_image_with_prompt(ai_client, request_dir: str):
    prompt = load_prompt_template(os.path.join(request_dir, "layer_3_render.txt"))
    image = Image.open(os.path.join(request_dir, "methodology.png"))
    
    query_prompt = """

    """

async def criticize_image_with_prerequisites(ai_client, request_dir: str):
    # from request_dir, read the ground_truth_json.json file
    ground_truth_json_path = os.path.join(request_dir, "layer1_logic.json")
    image_path = os.path.join(request_dir, "methodology.png")
    with open(ground_truth_json_path, "r") as f:
        GROUND_TRUTH_JSON = f.read()

    
    base_dir = os.path.dirname(__file__)       
    style_constraints = load_prompt_template(os.path.join(base_dir, "prompts", "style_constraint.md"))
    system_prompt = load_prompt_template(os.path.join(base_dir, "prompts", "system_prompt.md"))
    prompt = load_prompt_template(os.path.join(base_dir, "prompts", "user_prompt.md"))
    prompt = format_prompt_template(
        prompt,
        GROUND_TRUTH_JSON=GROUND_TRUTH_JSON,
        STYLE_CONSTRAINTS=style_constraints
    )

    try:
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        image_format = "png"
        messages = [
            {
                "role": "system",
                "content": [
                    { "type": "text", "text": system_prompt }
                ]
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/{image_format};base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
        # Run in thread pool for async execution
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model="supermind-agent-v1",
            messages=messages,
            max_tokens=1000,
            temperature=0.2
        )
    except Exception as e:
        logger.error(f"Error criticizing image: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error criticizing image: {str(e)}"
        )
    return response.choices[0].message.content

