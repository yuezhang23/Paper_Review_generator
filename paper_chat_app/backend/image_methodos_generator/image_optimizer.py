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

from .prompt_utils import load_prompt_template, format_prompt_template

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
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling AI Builder API image generation with model: {model}... (attempt {attempt + 1}/{max_retries})")
            
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
            # break  # Success, exit retry loop
            
        except asyncio.TimeoutError:
            last_error = f"Image generation timed out after {timeout_seconds} seconds"
            logger.warning(f"Attempt {attempt + 1} failed: {last_error}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                logger.info(f"Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                raise HTTPException(
                    status_code=504,
                    detail=f"Image generation timed out after {max_retries} attempts. The service may be experiencing high load."
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
    
    try:
        # Open image from bytes
        image = Image.open(BytesIO(image_bytes))
        original_width, original_height = image.size
        logger.info(f"Original image size: {original_width}x{original_height}")
        
        # Check if image exceeds canvas size and resize if needed
        if original_width > max_width or original_height > max_height:
            logger.info(f"Image exceeds canvas size ({max_width}x{max_height}), resizing...")
            
            # Calculate new size maintaining aspect ratio
            width_ratio = max_width / original_width
            height_ratio = max_height / original_height
            ratio = min(width_ratio, height_ratio)  # Use the smaller ratio to ensure both dimensions fit
            
            new_width = int(original_width * ratio)
            new_height = int(original_height * ratio)
            
            logger.info(f"Resizing to: {new_width}x{new_height} (ratio: {ratio:.3f})")
            
            # Resize image using high-quality resampling
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert back to bytes
            output_buffer = BytesIO()
            # Preserve original format if PNG, otherwise use PNG
            image_format = image.format if image.format else 'PNG'
            resized_image.save(output_buffer, format=image_format, optimize=True)
            image_bytes = output_buffer.getvalue()
            
            # Update base64 data
            b64_json_data = base64.b64encode(image_bytes).decode('utf-8')
            logger.info(f"Image resized and compressed. New size: {new_width}x{new_height}")
        else:
            logger.info(f"Image size ({original_width}x{original_height}) fits within canvas ({max_width}x{max_height}), no resize needed")
    except Exception as resize_error:
        logger.warning(f"Failed to check/resize image: {str(resize_error)}. Using original image.")
    
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


async def criticize_image_with_prompt(ai_client, request_dir: str, prompt: str):
    """
    Optimize diagram iteratively (placeholder for future implementation).
    
    Args:
        request_dir: Directory containing the image to optimize
        max_iterations: Maximum number of optimization iterations
    
    Returns:
        dict with optimization results
    """

    # from request_dir, read the ground_truth_json.json file
    ground_truth_json_path = os.path.join(request_dir, "layer1_logic.json")
    image_path = os.path.join(request_dir, "methodology.png")
    with open(ground_truth_json_path, "r") as f:
        GROUND_TRUTH_JSON = f.read()

    style_constraints = load_prompt_template("style_constraint")
    system_prompt = load_prompt_template("system_prompt")

    prompt = load_prompt_template("user_prompt")
    prompt = format_prompt_template(
        prompt,
        GROUND_TRUTH_JSON=GROUND_TRUTH_JSON,
        STYLE_CONSTRAINTS=style_constraints
    )

    # criticize the image with the prompt and return the criticism, use chat completion
    response = await asyncio.to_thread(
        ai_client.chat.completions.create,
        model="supermind-agent-v1",
        input= [
            {
            "role": "system",
            "content": [
                {
                "type": "input_text",
                "text": system_prompt
                }
            ]
            },
            {
            "role": "user",
            "content": [
                {
                "type": "input_text",
                "text": prompt
                },
                {
                "type": "input_image",
                "image_url": image_path
                }
            ]
            }
        ]
    )
    logger.info(f"Criticism: {response.choices[0].message.content}")
    return response.choices[0].message.content

