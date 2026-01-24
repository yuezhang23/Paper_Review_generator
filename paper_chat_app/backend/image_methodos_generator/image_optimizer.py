"""
Image Optimizer - Handles image generation and optimization
"""

import os
import base64
import asyncio
import logging
import json
import re
from io import BytesIO
from fastapi import HTTPException
from PIL import Image
from typing import Dict, Any, List
# Import from parent utils module
import sys
import openai
from google import genai
from dotenv import load_dotenv
load_dotenv()

# o_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# g_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from image_methodos_generator.prompt_utils import load_prompt_template, format_prompt_template, fix_imamge_size

# Set up logging
logger = logging.getLogger(__name__)

async def generate_step_image_component(ai_client, step_text: str, model: str, request_dir: str, timeout_seconds: int = 240) -> dict:
    prompt = f"""
    You are generating an 16:9 landscape academic infographic image. You MUST follow the provided Render Blueprint exactly.
    """
    response = await asyncio.wait_for(
        asyncio.to_thread(
            ai_client.images.generate,
            prompt=prompt,
            model=model,
            n=1
        ),
        timeout=timeout_seconds
    )
    return response.data[0].b64_json


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

    response = None
    last_error = None

    prompt = f"""You are generating an academic infographic image. You MUST follow the provided Render Blueprint exactly.

    CANVAS:
    - Direction: portrait
    - Background: pure white or extremely light gray
    - Include left-most white margin and right-most white margin
    - No box, arrow, or text may touch or cross the canvas edge.

    TEXT HIERARCHY (MANDATORY):
    - Step labels (e.g., “Step 2: …”):
    Bold sans-serif font, approximately 28–32 pt.
    These must be the largest text elements inside their grouping boxes.

    - Substep titles (e.g., “Substep 2.1: …”):
    Semi-bold sans-serif font, approximately 22–24 pt.
    These must be smaller than step labels but larger than bullet points.

    - Bullet point text:
    Regular sans-serif font, approximately 16–18 pt.
    Each bullet must appear on its own line and remain fully readable.

    - Legend items:
    Regular sans-serif font, approximately 16 pt.

    - Arrow labels and inline annotations:
    Regular or italic sans-serif font, approximately 14–15 pt.
    These must not visually compete with bullets or titles.

    RENDER BLUEPRINT (AUTHORITATIVE):
    {whiteboard_prompt}
    """
    
    try:
        # Use asyncio.wait_for to add timeout protection
        response = await asyncio.wait_for(
            asyncio.to_thread(
                ai_client.images.generate,
                prompt=prompt,
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
    b64_json_data = base64.b64encode(image_bytes).decode('utf-8')
    # Convert base64 to data URL for frontend
    image_url = f"data:image/png;base64,{b64_json_data}"
    
    return {
        "image_url": image_url,
        # "image_path": image_path,
        "image_bytes": image_bytes
    }


def extract_ground_truth_from_layer3_render(layer3_render_path: str) -> Dict[str, Any]:
    try:
        with open(layer3_render_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        logger.error(f"Layer3 render file not found: {layer3_render_path}")
        raise
    except Exception as e:
        logger.error(f"Error reading layer3_render file: {str(e)}")
        raise
    
    # Extract section D: VERBATIM TEXT TABLE
    # Look for "D. VERBATIM TEXT TABLE" section
    section_d_match = re.search(r'D\.\s*VERBATIM TEXT TABLE\s*\n(.*?)(?:\n[A-Z]\.|$)', content, re.DOTALL | re.IGNORECASE)
    
    if not section_d_match:
        # Try alternative pattern
        section_d_match = re.search(r'D\.\s*VERBATIM TEXT TABLE\s*\n(.*)', content, re.DOTALL | re.IGNORECASE)
    
    if not section_d_match:
        logger.warning("Could not find VERBATIM TEXT TABLE section, extracting all text strings")
        # Fallback: extract all lines that look like text strings
        lines = content.split('\n')
        text_strings = []
        for line in lines:
            line = line.strip()
            if line and line.startswith('-') and len(line) > 2:
                text_strings.append(line[1:].strip().strip('"'))
        return {
            "title": "",
            "step_labels": [],
            "step_bullets": [],
            "substep_labels": [],
            "substep_bullets": [],
            "arrow_labels": [],         
            "legend_labels": [],
            "legend_descriptions": [],
            "all_text_strings": text_strings
        }
    text_table_content = section_d_match.group(1).strip()
    
    lines = text_table_content.split('\n')
    all_text_strings = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('-'):
            text = line[1:].strip()
            text = text.strip('"').strip("'")
            if text:
                all_text_strings.append(text)
    
    # Also extract from section A (GLOBAL INVENTORY) for better categorization
    section_a_match = re.search(r'A\.\s*GLOBAL INVENTORY\s*\n(.*?)(?:\n[B-Z]\.|$)', content, re.DOTALL | re.IGNORECASE)
    
    # Categorize text strings
    title = ""
    step_labels = []
    step_bullets = []
    substep_labels = []
    substep_bullets = []
    arrow_labels = []
    legend_labels = []
    legend_descriptions = []
    
    for text in all_text_strings:
        text_lower = text.lower()
        
        # Title (usually the first item or contains "optimization", "methodology", etc.)
        if not title and (len(text) > 20 and not text.startswith("Step") and not text.startswith("Substep")):
            # Check if it's likely a title (no step number, longer text)
            if not re.match(r'^(Step|Substep|CRITICAL|Begin|Continue|Terminate)', text):
                title = text
                continue
        
        # Step labels
        if re.match(r'^Step \d+:', text):
            step_labels.append(text)
        # Substep labels
        elif re.match(r'^Substep \d+\.\d+:', text):
            substep_labels.append(text)
        # Arrow labels
        elif text in ["Begin Optimization Loop", "Continue Iteration", "Terminate"]:
            arrow_labels.append(text)
        elif any(keyword in text_lower for keyword in ["llm", "trajectory", "meta-prompt", "<ins>", "placeholder"]):
            if len(text) > 50:  # Likely a description
                legend_descriptions.append(text)
            else:  # Likely a label
                legend_labels.append(text)
        else:
            # Check if it's a bullet point (usually shorter, descriptive text)
            if len(text) < 150 and not text.startswith("The ") and not text.startswith("A "):
                if "Step" in text or "Substep" in text:
                    continue  
                if any(substep_label in text for substep_label in substep_labels):
                    substep_bullets.append(text)
                else:
                    step_bullets.append(text)
            else:
                legend_descriptions.append(text)
    
    # If title wasn't found, try to get it from section A
    if not title and section_a_match:
        section_a_content = section_a_match.group(1)
        title_match = re.search(r'- Title:\s*"([^"]+)"', section_a_content)
        if title_match:
            title = title_match.group(1)
    
    return {
        "title": title,
        "step_labels": step_labels,
        "step_bullets": step_bullets,
        "substep_labels": substep_labels,
        "substep_bullets": substep_bullets,
        "arrow_labels": arrow_labels,
        "legend_labels": legend_labels,
        "legend_descriptions": legend_descriptions,
        "all_text_strings": all_text_strings
    }


async def criticize_image_with_render_text(ai_client, request_dir: str, image_path: str, overflow_check: bool = False, missing_step_check: bool = False):
    # Find layer3_render.txt file (could be layer3_render.txt or layer3_render_1.txt)
    layer3_render_path = None
    possible_names = ["layer3_render.txt", "layer3_render_01.txt", "layer_3_render.txt"]
    for name in possible_names:
        path = os.path.join(request_dir, name)
        print(path)
        if os.path.exists(path):
            layer3_render_path = path
            break
    
    if not layer3_render_path:
        raise HTTPException(
            status_code=404,
            detail=f"Layer3 render file not found in {request_dir}. Looked for: {possible_names}"
        )
    
    # load the ground truth render blueprint
    with open(layer3_render_path, 'r', encoding='utf-8') as f:
        ground_truth_render_blueprint = f.read()

    # critize the image with the ground_truth, return the a list of issues
    system_prompt = """You are an expert at analyzing academic infographic images and extracting all visible text content with high accuracy."""

    user_prompt = f"""Compare the image with the RENDER_TEXT below and return the mismatched issues in the following JSON format:
    
    RENDER_TEXT:
    {ground_truth_render_blueprint}

    Given the issues discovered in the image, return the issues in the following JSON format:
    Return the issues in the following JSON format:
    [
        {{
            "issue_type": "node | key_component | must_not_change | arrow | legend | other",
            "issue_description": "string",
            "fix_description": "string",
        }}
    ]

    ONLY RETURN THE JSON OBJECT. 
    """
    if overflow_check:
        user_prompt = f"""which side of the image is overflowed?"""
    if missing_step_check:
        user_prompt = f"""which steps are missing from the image?"""

    attemps = 3
    for attempt in range(attemps):
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_format = "png"
            
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
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
                model="gemini-3-flash-preview",
                messages=messages,
                temperature=0.2,
                response_format={"type": "text"}
            )       
            result_content = response.choices[0].message.content

            if result_content is None or result_content.strip() == "":
                logger.error(f"No content returned from the model")
                continue

            if overflow_check or missing_step_check:
                return result_content

            try:
                if result_content.startswith("```json"):
                    result_content = result_content[7:  -3]
                if result_content.endswith("```"):
                    result_content = result_content[3 : -3]
                result_content = result_content.strip()
                try:    
                    extracted_text = json.loads(result_content)
                    return extracted_text
                except json.JSONDecodeError as e:
                    if attempt < attemps:
                        logger.error(f"JSON decode error: {str(e)}, retrying...")
                        continue
                    raise e
            except Exception as e:
                if attempt < attemps:
                    logger.error(f"Error criticizing image: {str(e)}, retrying...")
                    continue
                raise e
        except Exception as e:
            if attempt < attemps:
                logger.error(f"Error criticizing image: {str(e)}, retrying...")
                continue
            raise e


async def criticize_image_with_queries(ai_client, layer3_render_path: str, image_path: str):
    queries = [
        "is there any Node missing from the image?",
        "is there any Legend item missing from the image?",
        "Are there over 2 Nodes that have missing key_components from the image?",
        "is there any Node repeated from the image?",
        "is there any Legend item repeated from the image?",
        "is there any key_components repeated for the same Node from the image?",
        "is there any side of the image is overflowed?",
    ]

    with open(layer3_render_path, 'r', encoding='utf-8') as f:
        ground_truth_render_blueprint = f.read()

    # Helper function to process a single query
    async def process_query(query: str):
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_format = "png"

            user_prompt = f"""Compare the image with the RENDER_TEXT below:
            
            RENDER_TEXT:
            {ground_truth_render_blueprint}

            TASK: Based on the mismatched issues in the image, answer the following question:

            Question:
            {query}

            Answer ONLY Yes or No:\n
            """         
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
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
                temperature=0.2,
                response_format={"type": "text"}
            )       
            result_content = response.choices[0].message.content

            if result_content is None or result_content.strip() == "":
                logger.error(f"No content returned from the model")
                return None
            
            if result_content.strip().lower() == "yes":
                return f"{query}: True"
            else:
                return f"{query}: False"
        except Exception as e:
            logger.error(f"Error criticizing image: {str(e)}, retrying...")
            return None

    # Run all queries in parallel
    results = await asyncio.gather(
        *[process_query(query) for query in queries],
        return_exceptions=True
    )
    
    # Filter out None values and exceptions
    answers = [result for result in results if result is not None and not isinstance(result, Exception)]
    return answers


def regenerate_on_issues(issues: List[Dict[str, Any]]):
    for issue in issues:
        if issue["issue_type"] == "missing_step":
            return True
        if issue["issue_type"] == "margin_error":
            return True
        if issue["issue_type"] == "legend_error":
            return True
    return False
