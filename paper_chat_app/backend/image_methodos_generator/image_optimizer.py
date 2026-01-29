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
from httpx import request
import openai
from google import genai
from dotenv import load_dotenv
load_dotenv()

# o_client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
# g_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from .prompt_utils import load_prompt_template, format_prompt_template, fix_imamge_size

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
    - Legend items must be placed on the bottom left corner of the canvas.
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

    # Read image file once before retry loop to avoid redundant I/O
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    image_format = "png"

    attemps = 3
    for attempt in range(attemps):
        try:
            
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

QUERIES = [
    "is there any step missing from the image?",
    "is there any Legend item missing from the image?",
    "Are there over 2 Node boxes that have missing key_components or bullet points from the image?",
    "is there any Node box repeated from the image?",
    "is there any new Node box added to the image?",
    "is there any new Legend item added to the image?",
    "is there any key_components repeated for the same Node box from the image?",
    "is there any side of the image overflowed?",
]

async def criticize_image_with_queries(ai_client, layer3_render_path: str, image_path: str):
    queries = QUERIES.copy()
    with open(layer3_render_path, 'r', encoding='utf-8') as f:
        ground_truth_render_blueprint = f.read()

    # Read image file once and encode it for all parallel queries
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    image_format = "png"

    # Helper function to process a single query
    async def process_query(i: int, query: str):
        try:

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
            
            if result_content.strip().lower() == "yes" or result_content.strip().lower() == "true":
                return True
            else:
                return False
        except Exception as e:
            logger.error(f"Error criticizing image: {str(e)}, retrying...")
            return None

    # Run all queries in parallel
    results = await asyncio.gather(
        *[process_query(i, query) for i, query in enumerate(queries)],
        return_exceptions=True
    )
    
    # Filter out None values and exceptions
    answers = [(queries[i], result) for i, result in enumerate(results) if result is not None and not isinstance(results[i], Exception)]
    return answers



async def extract_all_text_from_image(ai_client, image_path: str, max_retries: int = 3):
    """Extract all text from an image using LLM with error handling and retries."""
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    image_format = "png"

    user_prompt = f"""Extract all text from the image and return the text in the following JSON format:
    [
        {{
            "text": "string",
        }}
    ]
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
    
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="gemini-3-flash-preview",
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            if not response or not response.choices:
                logger.error(f"No response or choices from LLM (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)  # Brief delay before retry
                    continue
                return None
            
            result_content = response.choices[0].message.content
            if result_content is None or result_content.strip() == "":
                logger.warning(f"Empty content from LLM (attempt {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
            
            # Clean up markdown code blocks
            if result_content.startswith("```json"):
                result_content = result_content[7:]
            if result_content.startswith("```"):
                result_content = result_content[3:]
            if result_content.endswith("```"):
                result_content = result_content[:-3]
            result_content = result_content.strip()
            
            try:
                extracted_text = json.loads(result_content)
                # print(extracted_text)

                if isinstance(extracted_text, list):
                    return [text.get("text", "") for text in extracted_text if isinstance(text, dict) and "text" in text]
                elif isinstance(extracted_text, dict):
                    # Handle case where JSON is wrapped in an object
                    if "text" in extracted_text:
                        return [extracted_text["text"]]
                    # Try to find a list of texts
                    for key in extracted_text:
                        if isinstance(extracted_text[key], list):
                            return [item.get("text", "") if isinstance(item, dict) else str(item) for item in extracted_text[key]]
                logger.warning(f"Unexpected JSON format from LLM: {type(extracted_text)}")
                return None
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                logger.debug(f"Failed to parse content: {result_content[:200]}...")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None
        except Exception as e:
            logger.error(f"Error extracting text from image (attempt {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            return None   
    return None

from collections import Counter
import string

def compare_all_text_with_ground_truth(all_text: List[str], ground_truth: str):
    # find all the text existing in both all_text and in ground_truth_render_blueprint, count the length of the text
    all_txt_len = len(ground_truth)
    # remove text included in ()
    ground_truth = ground_truth.lower()
    ground_truth = re.sub(r'\([^)]*\)', '', ground_truth)
    # remove all punctuation from ground_truth_render_blueprint
    ground_truth = re.sub(r'[^\w\s]', '', ground_truth)

    # check duplicate text
    counter = Counter(all_text)
    is_duplicate = True if any(count > 1 for count in counter.values()) else False

    unique_text = list(counter.keys())
    # check len of text exist in all_text but not in all_text_in_ground_truth
    new_text_length = 0
    matched_text_length = 0
    matched_text = []
    for text in unique_text:
        if text.startswith("•"):
            text = text[1:]
        text = text.strip()
        # remove text included in ()
        text = re.sub(r'\([^)]*\)', '', text)
        # remove all punctuation from text
        text = re.sub(r'[^\w\s]', '', text)
        text = text.lower()
        if text not in ground_truth:
            # print(f"new text: {text}")
            new_text_length += len(text) / all_txt_len
        if text in ground_truth:
            # print(f"matched text: {text}")
            matched_text.append(text)
            matched_text_length += len(text) / all_txt_len

    return matched_text_length, new_text_length, is_duplicate, matched_text

async def rank_images_by_informativeness(
    ai_client, image_path_list: List[str], ground_truth_render_blueprint: str, request_path: str
):
    """Run all LLM extractions in parallel, then score and rank."""
    extraction_tasks = [
        extract_all_text_from_image(ai_client, path) for path in image_path_list
    ]
    all_results = await asyncio.gather(*extraction_tasks, return_exceptions=False)

    informativeness_scores = []
    for i, (image_path, all_text) in enumerate(zip(image_path_list, all_results)):
        # Handle failed extractions (extract_all_text_from_image returns None)
        texts = all_text if all_text is not None else []
        matched_score, new_text_score, is_duplicate, matched_text = compare_all_text_with_ground_truth(
            texts, ground_truth_render_blueprint
        )
        informativeness_scores.append({
            "image_path": image_path,
            "image_index": i,
            "matched_score": matched_score,
            "new_text_score": new_text_score,
            "is_duplicate": is_duplicate,
            "matched_text": matched_text
        })
    with open(os.path.join(request_path, "informativeness_scores.json"), "w", encoding='utf-8') as f:
        json.dump(informativeness_scores, f, ensure_ascii=False, indent=4)
    return sorted(informativeness_scores, key=lambda x: x["matched_score"], reverse=True)

# import sys
# sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
# from utils import get_ai_client

# if __name__ == "__main__":
#     image_path = os.path.join(os.path.dirname(__file__), "images", "1769233588")
#     with open(os.path.join(image_path, "layer3_render.txt"), 'r', encoding='utf-8') as f:
#         ground_truth_render_blueprint = f.read()
    
#     ai_client = get_ai_client()
#     # for i in range(2, 5):
#     #     image_result = asyncio.run(generate_and_save_image(ai_client, ground_truth_render_blueprint, "gpt-image-1.5", image_path))
#     #     image_bytes = image_result["image_bytes"]
#     #     with open(os.path.join(image_path, f"methodology_{i}.png"), "wb") as f:
#     #         f.write(image_bytes)

#     image_name = ["methodology_4.png"]
#     image_path_list = [os.path.join(image_path, name) for name in image_name]
#     results = asyncio.run(rank_images_by_informativeness(ai_client, image_path_list, ground_truth_render_blueprint, image_path))
#     print(results)