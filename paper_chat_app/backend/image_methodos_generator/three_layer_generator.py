"""
Three-Layer Methodology Representation Generator

This module generates a 3-layer representation of methodology descriptions:
- Layer 1: Logic layer (symbolic graph spec) - JSON
- Layer 2: Layout layer (single-page infographic blueprint) - JSON  
- Layer 3: Render layer (render-safe prompt for image model) - Text

Each layer is generated using a reasoning model (GPT-5) that processes
the methodology description text.
"""

import os
import json
import asyncio
import logging
import re
from typing import Dict, Any, Optional

# Set up logging
logger = logging.getLogger(__name__)

# Import from parent utils module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import get_ai_client

# Reasoning model to use for generation
REASONING_MODEL = "supermind-agent-v1"
layer_1_json = json.load(open('image_methodos_generator/layer_1.json', 'r'))
layer_2_json = json.load(open('image_methodos_generator/layer_2.json', 'r'))


def extract_json_from_content(content: str) -> str:
    """
    Robustly extract JSON content from a string that may contain:
    - Markdown code blocks (```json or ```)
    - Embedded JSON in plain text
    - Multiple code blocks (extracts the first valid JSON)
    - Extra whitespace and newlines
    
    Args:
        content: Raw content string that may contain JSON
        
    Returns:
        Cleaned JSON string ready for parsing
        
    Raises:
        ValueError: If no valid JSON can be extracted
    """
    if not content or not content.strip():
        raise ValueError("Content is empty")
    
    content = content.strip()
    
    # Strategy 1: Try to extract from markdown code blocks
    # Pattern to match code blocks: ```json...``` or ```...```
    code_block_pattern = r'```(?:json)?\s*\n?(.*?)```'
    matches = re.findall(code_block_pattern, content, re.DOTALL | re.IGNORECASE)
    
    if matches:
        # Try each match until we find valid JSON
        for match in matches:
            candidate = match.strip()
            if candidate:
                # Quick validation: check if it looks like JSON
                if candidate.startswith('{') or candidate.startswith('['):
                    try:
                        # Try parsing to validate
                        json.loads(candidate)
                        return candidate
                    except json.JSONDecodeError:
                        continue
    
    # Strategy 2: Check if the entire content is JSON (no code blocks)
    # Remove any leading/trailing whitespace and try parsing
    stripped = content.strip()
    if stripped.startswith('{') or stripped.startswith('['):
        try:
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass
    
    # Strategy 3: Try to find JSON object/array in the content using regex
    # Look for content that starts with { or [ and try to extract it
    json_object_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    json_array_pattern = r'\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]'
    
    # Try to find the largest JSON object
    for pattern in [json_object_pattern, json_array_pattern]:
        matches = re.findall(pattern, content, re.DOTALL)
        if matches:
            # Try the longest match first (likely the complete JSON)
            for match in sorted(matches, key=len, reverse=True):
                try:
                    json.loads(match)
                    return match
                except json.JSONDecodeError:
                    continue
    
    # Strategy 4: Try removing common markdown prefixes/suffixes manually
    # Handle cases like: ```json\n{...}\n``` or ```\n{...}\n```
    if content.startswith("```json"):
        content = content[7:].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    
    if content.endswith("```"):
        content = content[:-3].strip()
    
    # Try one more time after manual cleaning
    content = content.strip()
    if content:
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
    
    # If all strategies fail, raise an error
    raise ValueError(
        f"Could not extract valid JSON from content. "
        f"Content preview (first 200 chars): {content[:200]}"
    )


def load_methodology_description(file_path: str) -> str:
    """
    Load methodology description from a text file.
    
    Args:
        file_path: Path to the methodology description text file
        
    Returns:
        Content of the file as string
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Methodology description file not found: {file_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading methodology description: {str(e)}")
        raise


async def generate_layer1_logic(methodology_text: str) -> Dict[str, Any]:
    """
    Generate Layer 1: Logic layer (symbolic graph spec).
    
    This layer defines the ground-truth structure with nodes, edges, legend, etc.
    Everything else (layout + rendering) must conform to it.
    
    Args:
        methodology_text: The methodology description text
        
    Returns:
        Dictionary representing the logic layer JSON structure
    """
    system_prompt = """You are an expert at analyzing methodology descriptions and extracting structured logical representations.

Your task is to generate a JSON structure that represents the symbolic graph specification of a methodology workflow. This is the GROUND-TRUTH layer."""

    user_prompt = f"""Analyze the following methodology description and generate the logic layer JSON structure:

{methodology_text}


Valid JSON Structure Example:
{layer_1_json}

Rules:
1. Extract all steps from the methodology description
2. Assign unique IDs (S1, S2, S3, etc.) to each step
3. Identify the step type based on its function
4. Extract key components for each step
5. Map the flow between steps with edges
6. Identify loops and iteration patterns
7. Create a legend for important terms/concepts
8. List critical constraints that must not change
9. Return ONLY valid JSON, no markdown formatting, no code blocks

Generate the complete JSON structure following the format and rules specified above."""

    ai_client = get_ai_client()
    
    try:
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,  # Lower temperature for more structured output
            max_tokens=3000,
            response_format={"type": "json_object"}  # Request JSON output
        )
        
        # Validate response structure
        if not response or not hasattr(response, 'choices') or not response.choices:
            logger.error("Empty or invalid response from API")
            logger.error(f"Response object: {response}")
            raise ValueError("Empty or invalid response from API")
        
        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error("Response missing message field")
            logger.error(f"Response choices: {response.choices}")
            raise ValueError("Response missing message field")
        
        content = response.choices[0].message.content
        
        # Check if content is None or empty
        if content is None:
            logger.error("Response content is None")
            logger.error(f"Full response: {response}")
            raise ValueError("Response content is None")
        
        if not content.strip():
            logger.error("Response content is empty")
            logger.error(f"Response structure: {response}")
            raise ValueError("Response content is empty")
        
        # Extract JSON from content (handles embedded JSON, markdown blocks, etc.)
        content = extract_json_from_content(content)
        
        # Parse JSON response
        logic_layer = json.loads(content)
        logger.info("Layer 1 (Logic) generated successfully")
        return logic_layer
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Layer 1 response: {str(e)}")
        logger.error(f"Response content: {content if 'content' in locals() else 'N/A'}")
        logger.error(f"Response content length: {len(content) if 'content' in locals() and content else 0}")
        raise
    except ValueError as e:
        logger.error(f"Validation error in Layer 1: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error generating Layer 1: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        raise


async def generate_layer2_layout(logic_layer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate Layer 2: Layout layer (single-page infographic blueprint).
    
    This layer makes the graph drawable without inventing structure.
    It defines regions, arrow plans, and visual encoding.
    
    Args:
        logic_layer: The Layer 1 logic layer JSON structure
        
    Returns:
        Dictionary representing the layout layer JSON structure
    """
    system_prompt = """You are an expert at designing single-page infographic layouts for methodology workflows.

Your task is to generate a JSON structure that defines the layout blueprint for rendering the logic layer as a visual diagram. This layer makes the graph drawable without inventing structure."""

    user_prompt = f"""Given the following logic layer structure, generate the layout layer JSON:

{json.dumps(logic_layer, indent=2)}

Valid JSON Structure Example:
{layer_2_json}

Rules:
1. Analyze the logic layer structure
2. Design a single-page layout that accommodates all nodes
3. Group related nodes into regions
4. Plan arrow styles based on edge types (straight, loops, returns)
5. Assign visual encoding (colors, icons) based on node types
6. Add callouts for important details
7. Ensure the layout is visually clear and follows logical flow
8. Return ONLY valid JSON, no markdown formatting, no code blocks

Generate the complete layout layer JSON structure following the format and rules specified above."""

    ai_client = get_ai_client()
    
    try:
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.4,
            max_tokens=3000,
            response_format={"type": "json_object"}
        )
        
        # Validate response structure
        if not response or not hasattr(response, 'choices') or not response.choices:
            logger.error("Empty or invalid response from API")
            logger.error(f"Response object: {response}")
            raise ValueError("Empty or invalid response from API")
        
        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error("Response missing message field")
            logger.error(f"Response choices: {response.choices}")
            raise ValueError("Response missing message field")
        
        content = response.choices[0].message.content
        
        # Check if content is None or empty
        if content is None:
            logger.error("Response content is None")
            logger.error(f"Full response: {response}")
            raise ValueError("Response content is None")
        
        if not content.strip():
            logger.error("Response content is empty")
            logger.error(f"Response structure: {response}")
            raise ValueError("Response content is empty")
        
        # Extract JSON from content (handles embedded JSON, markdown blocks, etc.)
        content = extract_json_from_content(content)
        
        layout_layer = json.loads(content)
        logger.info("Layer 2 (Layout) generated successfully")
        return layout_layer
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Layer 2 response: {str(e)}")
        logger.error(f"Response content: {content if 'content' in locals() else 'N/A'}")
        logger.error(f"Response content length: {len(content) if 'content' in locals() and content else 0}")
        raise
    except ValueError as e:
        logger.error(f"Validation error in Layer 2: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error generating Layer 2: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        raise


async def generate_layer3_render(logic_layer: Dict[str, Any], layout_layer: Dict[str, Any]) -> str:
    """
    Generate Layer 3: Render layer (render-safe prompt for image model).
    
    This is a prompt template that describes what to draw, not the paper's logic.
    It's designed to be fed to an image generation model like GPT-4 Vision or DALL-E.
    
    Args:
        logic_layer: The Layer 1 logic layer JSON structure
        layout_layer: The Layer 2 layout layer JSON structure
        
    Returns:
        String containing the render prompt
    """
    system_prompt = """You are an expert at creating detailed image generation prompts for academic infographics.

Your task is to generate a comprehensive text prompt that describes exactly what to draw for a methodology workflow diagram. This prompt will be fed to an image generation model (like GPT-4 Vision or DALL-E).

The prompt should:
1. Describe the visual style (academic infographic, clean, professional, colorful)
2. Specify the layout structure (regions, positions)
3. List all content boxes with their labels and bullet points
4. Describe arrow connections and loop structures
5. Include legends and callouts
6. Provide important rules to ensure accuracy

Format the prompt as a clear, structured text that an image model can follow precisely. Do NOT include markdown code blocks or JSON - just the prompt text itself.

The prompt should be detailed enough that the image model can create an accurate visualization without inventing steps or changing the structure."""

    user_prompt = f"""Given the following logic and layout layers, generate a detailed render prompt for image generation:

LOGIC LAYER:
{json.dumps(logic_layer, indent=2)}

LAYOUT LAYER:
{json.dumps(layout_layer, indent=2)}

Generate a comprehensive render prompt that:
1. Describes the title and style
2. Specifies the layout structure
3. Lists all steps with their exact labels and bullet points
4. Describes all arrows and connections
5. Includes legends and visual elements
6. Provides rules to ensure accuracy

Return ONLY the prompt text, no markdown formatting, no code blocks."""

    ai_client = get_ai_client()
    
    try:
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=REASONING_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            max_tokens=4000
        )
        
        # Validate response structure
        if not response or not hasattr(response, 'choices') or not response.choices:
            logger.error("Empty or invalid response from API")
            logger.error(f"Response object: {response}")
            raise ValueError("Empty or invalid response from API")
        
        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error("Response missing message field")
            logger.error(f"Response choices: {response.choices}")
            raise ValueError("Response missing message field")
        
        content = response.choices[0].message.content
        
        # Check if content is None or empty
        if content is None:
            logger.error("Response content is None")
            logger.error(f"Full response: {response}")
            raise ValueError("Response content is None")
        
        if not content.strip():
            logger.error("Response content is empty")
            logger.error(f"Response structure: {response}")
            raise ValueError("Response content is empty")
        
        render_prompt = content.strip()
        logger.info("Layer 3 (Render) generated successfully")
        return render_prompt
        
    except ValueError as e:
        logger.error(f"Validation error in Layer 3: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error generating Layer 3: {str(e)}")
        logger.error(f"Exception type: {type(e).__name__}")
        raise


async def generate_three_layers(methodology_text: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate all three layers from a methodology description.
    
    Args:
        methodology_text: The methodology description text
        output_dir: Optional directory to save the layer files. If None, uses current directory.
        
    Returns:
        Dictionary containing all three layers:
        {
            "layer1_logic": {...},
            "layer2_layout": {...},
            "layer3_render": "..."
        }
    """
    logger.info("Starting 3-layer generation...")
    
    # Generate Layer 1 (Logic)
    logger.info("Generating Layer 1 (Logic)...")
    layer1 = await generate_layer1_logic(methodology_text)
    
    # Generate Layer 2 (Layout) - depends on Layer 1
    logger.info("Generating Layer 2 (Layout)...")
    layer2 = await generate_layer2_layout(layer1)
    
    # Generate Layer 3 (Render) - depends on both Layer 1 and Layer 2
    logger.info("Generating Layer 3 (Render)...")
    layer3 = await generate_layer3_render(layer1, layer2)
    
    result = {
        "layer1_logic": layer1,
        "layer2_layout": layer2,
        "layer3_render": layer3
    }
    
    # Save to files if output_dir is provided
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
        # Save Layer 1 as JSON
        layer1_path = os.path.join(output_dir, "layer1_logic.json")
        with open(layer1_path, 'w', encoding='utf-8') as f:
            json.dump(layer1, f, indent=2, ensure_ascii=False)
        logger.info(f"Layer 1 saved to: {layer1_path}")
        
        # Save Layer 2 as JSON
        layer2_path = os.path.join(output_dir, "layer2_layout.json")
        with open(layer2_path, 'w', encoding='utf-8') as f:
            json.dump(layer2, f, indent=2, ensure_ascii=False)
        logger.info(f"Layer 2 saved to: {layer2_path}")
        
        # Save Layer 3 as text
        layer3_path = os.path.join(output_dir, "layer3_render.txt")
        with open(layer3_path, 'w', encoding='utf-8') as f:
            f.write(layer3)
        logger.info(f"Layer 3 saved to: {layer3_path}")
    
    logger.info("3-layer generation completed successfully")
    return result


async def generate_from_file(input_file: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate three layers from a methodology description file.
    
    Args:
        input_file: Path to the methodology description text file
        output_dir: Optional directory to save the layer files. If None, uses same directory as input file.
        
    Returns:
        Dictionary containing all three layers
    """
    # Load methodology description
    methodology_text = load_methodology_description(input_file)
    
    # Determine output directory
    if output_dir is None:
        output_dir = os.path.dirname(input_file)
    
    # Generate layers
    return await generate_three_layers(methodology_text, output_dir)
