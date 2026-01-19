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
layer_1_json = json.load(open(os.path.join(os.path.dirname(__file__), 'layer_1_temp.json'), 'r'))
layer_2_json = json.load(open(os.path.join(os.path.dirname(__file__), 'layer_2_temp.json'), 'r'))


def extract_json_from_content(content: str, pattern: Optional[Dict[str, Any]] = None) -> str:
    """
    Robustly extract JSON content from a string using pattern JSON keys as markers.
    
    This function uses the first and last keys from the pattern JSON to locate
    where the actual JSON starts and ends in the content.
    
    Args:
        content: Raw content string that may contain JSON
        pattern: Optional pattern JSON (dict) to extract first/last keys from.
                 If None or not provided, falls back to general extraction methods.
        
    Returns:
        Cleaned JSON string ready for parsing
        
    Raises:
        ValueError: If no valid JSON can be extracted
    """
    if not content or not content.strip():
        raise ValueError("Content is empty")
    
    original_content = content
    content = content.strip()
    
    # Helper function to find balanced JSON object starting at a given position
    def find_json_object_starting_at(key_pos: int) -> Optional[str]:
        """Find a complete JSON object by finding opening brace before key_pos and counting braces."""
        # If key_pos is 0 and content starts with '{', use that directly
        if key_pos == 0 and content.startswith('{'):
            brace_pos = 0
        else:
            # Look backwards from key_pos to find the opening brace
            brace_pos = content.rfind('{', 0, key_pos + 1)
            if brace_pos == -1:
                # No opening brace found before key_pos, this is not a valid JSON start
                return None
        
        # Count braces to find matching closing brace
        brace_count = 0
        in_string = False
        escape_next = False
        
        for i in range(brace_pos, len(content)):
            char = content[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"':
                in_string = not in_string
                continue
            
            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # Found matching closing brace
                        candidate = content[brace_pos:i + 1]
                        try:
                            json.loads(candidate)
                            return candidate
                        except json.JSONDecodeError:
                            return None
        
        return None
    
    # Strategy 1: Try simple extraction if content is pure JSON or starts with {
    # First, try stripping and parsing directly - this handles pure JSON files
    stripped = content.strip()
    
    # Remove any leading/trailing whitespace and try parsing
    if stripped:
        try:
            # Try parsing the entire stripped content as-is
            json.loads(stripped)
            return stripped
        except json.JSONDecodeError:
            pass
    
    # If direct parse fails and content starts with {, try to extract complete JSON object
    # This handles cases where there's extra text after the JSON
    if stripped.startswith('{') or stripped.startswith('['):
        candidate = find_json_object_starting_at(0)
        if candidate:
            try:
                # Validate the extracted JSON
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                pass
    
    # Strategy 2: If pattern is provided, use first/last key strategy
    if pattern and isinstance(pattern, dict):
        keys = list(pattern.keys())
        if not keys:
            raise ValueError("Pattern JSON must have at least one key")
        
        first_key = keys[0]
        last_key = keys[-1]
        
        # Escape keys for regex
        first_key_escaped = re.escape(first_key)
        last_key_escaped = re.escape(last_key)
        
        # Find first occurrence of first_key
        first_key_match = re.search(rf'["\']?{first_key_escaped}["\']?\s*:', content, re.IGNORECASE)
        
        if first_key_match:
            first_key_pos = first_key_match.start()
            
            # Try to extract JSON starting from the opening brace before first_key
            candidate = find_json_object_starting_at(first_key_pos)
            
            if candidate:
                try:
                    parsed = json.loads(candidate)
                    # Verify it contains the first key (required for pattern matching)
                    # Return if JSON is valid and has first key
                    # We don't strictly require last_key (handles truncated/incomplete JSON)
                    if first_key in parsed:
                        return candidate
                except json.JSONDecodeError:
                    pass
    
    # Strategy 3: Try to extract from markdown code blocks
    code_block_pattern = r'```(?:json)?\s*\n?(.*?)```'
    matches = re.findall(code_block_pattern, content, re.DOTALL | re.IGNORECASE)
    
    if matches:
        for match in matches:
            candidate = match.strip()
            if candidate and (candidate.startswith('{') or candidate.startswith('[')):
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue
    
    # Strategy 4: Try removing markdown code block markers and parse
    if content.startswith("```json"):
        content = content[7:].strip()
    elif content.startswith("```"):
        content = content[3:].strip()
    
    if content.endswith("```"):
        content = content[:-3].strip()
    
    content = content.strip()
    if content and (content.startswith('{') or content.startswith('[')):
        try:
            json.loads(content)
            return content
        except json.JSONDecodeError:
            pass
    
    # Strategy 5: Try to find JSON by searching for opening brace and counting
    # This is a last resort - find the first { and try to extract complete object
    first_brace = content.find('{')
    if first_brace != -1:
        candidate = find_json_object_starting_at(first_brace)
        if candidate:
            return candidate
    
    # If all strategies fail, raise an error
    raise ValueError(
        f"Could not extract valid JSON from content. "
        f"Content preview (first 200 chars): {original_content[:200]}"
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
3. Assign unique IDs (SN.1, SN.2, SN.3, etc.) to each substep SN.x
3. Identify the step and substep types based on its function
4. Extract key components for each step and each substep
5. Map the flow between steps and substeps with edges
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
            max_tokens=6000,
            response_format={"type": "json_object"}  # Request JSON output
        )
        
        # Validate response structure
        if not response or not hasattr(response, 'choices') or not response.choices:
            logger.error(f"Response object: {response}")
            raise ValueError("Empty or invalid response from API")
        
        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error(f"Response choices: {response.choices}")
            raise ValueError("Response missing message field")
        
        content = response.choices[0].message.content
        
        # Check if content is None or empty
        if content is None or not content.strip():
            raise ValueError("Response content is None")
        
        # Extract JSON from content (handles embedded JSON, markdown blocks, etc.)
        content = extract_json_from_content(content, layer_1_json)
        
        # Parse JSON response
        logic_layer = json.loads(content)
        logger.info("Layer 1 (Logic) generated successfully")
        return logic_layer
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Layer 1 response: {str(e)}")
        raise
    except ValueError as e:
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

    user_prompt = f"""Given the following logic layer structure, generate the COMPLETE layout layer JSON:

{json.dumps(logic_layer, indent=2)}

Valid JSON Structure Example:
{layer_2_json}

Rules:
1. Analyze the logic layer structure COMPLETELY
2. Design a single-page layout that accommodates ALL nodes
3. Group related nodes into regions (include ALL nodes)
4. Plan arrow styles based on edge types (straight, loops, returns)
5. Assign visual encoding (colors, icons) based on node types
6. Add callouts for important details
7. Ensure the layout is visually clear, no overlapping nodes and follows logical flow
8. Generate the ENTIRE JSON structure - do not stop until you've included all regions, arrows, visual encoding, and callouts

IMPORTANT: Your response must be a complete, valid JSON object. Count the nodes in the logic layer and ensure every single one appears in your layout JSON."""

    ai_client = get_ai_client()
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=5000,  
                response_format={"type": "json_object"}
            )
            
            # Validate response structure
            if not response or not hasattr(response, 'choices') or not response.choices:
                raise ValueError("Empty or invalid response from API")
            
            if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
                raise ValueError("Response missing message field")
            
            content = response.choices[0].message.content
            
            extracted_content = extract_json_from_content(content, layer_2_json)
            layout_layer = json.loads(extracted_content)
            
            # Validate that we got a reasonable structure
            if not isinstance(layout_layer, dict):
                raise ValueError("Parsed JSON is not a dictionary")
            
            # Check for essential keys
            required_keys = ['canvas', 'regions']
            missing_keys = [key for key in required_keys if key not in layout_layer]
            if missing_keys:
                logger.warning(f"JSON missing some keys: {missing_keys}, but continuing...")
            
            logger.info("Successfully generated and parsed Layer 2 layout JSON")
            return layout_layer
            
        except ValueError as e:
            # Re-raise ValueError (these are our validation errors, don't retry)
            if "truncated due to token limit" in str(e) or "Empty or invalid response" in str(e):
                raise
            # For other ValueErrors, retry if we have attempts left
            if attempt < max_retries:
                logger.warning(f"ValueError on attempt {attempt + 1}: {str(e)}, retrying...")
                continue
            raise
        except Exception as e:
            # For other exceptions, retry if we have attempts left
            if attempt < max_retries:
                logger.warning(f"Exception on attempt {attempt + 1}: {str(e)}, retrying...")
                continue
            raise    
    # Should not reach here, but just in case
    raise ValueError("Failed to generate layout layer after all retry attempts")


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
    system_prompt = """
    You are an expert at writing strict, unambiguous image render prompts for academic methodology diagrams.

Your goal is not to summarize the workflow, but to translate structured logic and layout into hard visual drawing instructions for a diffusion-based image generator (e.g., GPT-image-1.5).

You must:

1. Treat every node, legend item, arrow, label, and bullet as mandatory drawable elements.
2. Explicitly restate icons in visual terms (never rely on symbolic names).
3. Forbid the model from removing or merging text even if redundant.
4. Enforce grouping, hierarchy, and spatial relationships.
5. Convert abstract structure into concrete visual placement rules.
6. Over-specify arrows, loops, and directionality so iteration is visually dominant.
7. Ensure legends are drawn as standalone labeled objects.

Never produce vague wording like “show”, “represent”, or “illustrate”.
Always use directive wording like “draw”, “place”, “attach”, “connect”, “must include”.

The render prompt must prevent the image model from:

- dropping bullets
- compressing labels
- replacing icons
- flattening hierarchy
- detaching callouts
- omitting legend entries

Output only the final render prompt text.
"""

    user_prompt = f"""Given the following logic and layout layers, generate a detailed render prompt for image generation:

LOGIC LAYER:
{json.dumps(logic_layer, indent=2)}

LAYOUT LAYER:
{json.dumps(layout_layer, indent=2)}

TREE LAYOUT CONSTRAINTS (MANDATORY):
All substep groups (S2., S3., S4.*) must follow a strict hierarchical tree structure with parent-child alignment rules:

1. Parent step box must act as the root node.

2. Substeps must be aligned vertically beneath each other in a single right-side branch.

3. Each substep must be horizontally indented to the right of its parent container.

4. Substeps must have equal vertical spacing and identical widths.

5. Arrows between substeps must be straight vertical connectors (no curves).

6. The dashed grouping box must tightly wrap only the substeps, not the arrows.

7. The parent step must connect to the dashed grouping box with a single anchor arrow entering from the left side of the grouping box.

8. No substep may appear left of or above its parent step.

9. The structure must visually resemble a clean academic tree diagram (root → branch → leaves).

10. All three substep groups must use the exact same alignment pattern for consistency.


Generate a comprehensive render prompt that:
1. Describe the visual style (academic infographic, clean, professional, colorful)

2. Specify the aspect ratio (16:9 landscape) and Describes the title

3. The canvas background must be pure white or very light gray (whiteboard style).

4. Specify the layout structure (regions, positions) and tree layout constraints

5  Lists all steps in content boxes with their exact labels and bullet points

6. Describe arrow connections and loop structures

7. Include legends under the main layout structure

8. Append each callout context to the node it is attached to and visual elements

9. Provide important bullet points rules to ensure accuracy on every component.

10. Add a TEXT PRESERVATION RULE section that explicitly forbids removing bullets or labels.

11. Add a VISUAL HIERARCHY RULE section specifying which arrows must be thicker or dominant.

12. Add a VISUAL GROUPING RULE section forcing multi-input composition where required.

13. Explicitly restate each icon in physical visual form (e.g., “stacked list with timestamps” instead of “trajectory icon”).

14. Add a LEGEND RENDERING RULE that each legend item must appear as an independent labeled object with icon.

15. Add a NO ABSTRACTION RULE: prohibit the image model from simplifying wording or merging steps.

16. Add a STRICT LABEL RULE: arrow labels must appear exactly as written.
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
            temperature=0.4,
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
        if content is None or not content.strip():
            logger.error("Response content is None")
            logger.error(f"Full response: {response}")
            raise ValueError("Response content is None")
        
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
    logger.info(f"Generating Layer 1 (Logic)...")
    layer1 = await generate_layer1_logic(methodology_text)
    
    os.makedirs(output_dir, exist_ok=True)
    
    # Save Layer 1 as JSON
    layer1_path = os.path.join(output_dir, "layer1_logic.json")
    with open(layer1_path, 'w', encoding='utf-8') as f:
        json.dump(layer1, f, indent=2, ensure_ascii=False)
    logger.info(f"Layer 1 saved to: {layer1_path}")

    # Generate Layer 2 (Layout) - depends on Layer 1
    logger.info("Generating Layer 2 (Layout)...")
    layer2 = await generate_layer2_layout(layer1)
    
    # Save Layer 2 as JSON
    layer2_path = os.path.join(output_dir, "layer2_layout.json")
    with open(layer2_path, 'w', encoding='utf-8') as f:
        json.dump(layer2, f, indent=2, ensure_ascii=False)
    logger.info(f"Layer 2 saved to: {layer2_path}")

    # Generate Layer 3 (Render) - depends on both Layer 1 and Layer 2
    logger.info("Generating Layer 3 (Render)...")
    layer3 = await generate_layer3_render(layer1, layer2)
    # Save Layer 3 as text
    layer3_path = os.path.join(output_dir, "layer3_render.txt")
    with open(layer3_path, 'w', encoding='utf-8') as f:
        f.write(layer3)
    logger.info(f"Layer 3 saved to: {layer3_path}")
    
    result = {
        "layer1_logic": layer1,
        "layer2_layout": layer2,
        "layer3_render": layer3
    }
    return result


async def generate_from_file(input_file_path: str, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate three layers from a methodology description file.
    
    Args:
        input_file: Path to the methodology description text file
        output_dir: Optional directory to save the layer files. If None, uses same directory as input file.
        
    Returns:
        Dictionary containing all three layers
    """
    # Load methodology description
    methodology_text = load_methodology_description(input_file_path)
    
    # create output directory if it doesn't exist
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Generate layers
    return await generate_three_layers(methodology_text, output_dir)

from .images.test_image import generate_image

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    input_file_path = os.path.join(base_dir, "images/1768522311_8stps/interpretation.txt")
    output_dir = os.path.join(base_dir, "images/1768522311_8stps")
    # sub_dir = os.path.join(output_dir, "01")
    # sub_sub_dir = os.path.join(sub_dir, "002", "0001")
    result = asyncio.run(generate_from_file(input_file_path, output_dir))
    render_text = result["layer3_render"]
    # layer1 = json.load(open(os.path.join(sub_dir, "layer1_logic.json"), "r"))
    # layer2 = asyncio.run(generate_layer2_layout(layer1))
    # layer2_path = os.path.join(sub_sub_dir, "layer2_layout.json")
    # with open(layer2_path, "w") as f:
    #     json.dump(layer2, f, indent=2, ensure_ascii=False)
    # layer2 = json.load(open(os.path.join(sub_dir, "layer2_layout.json"), "r"))

    # render_text = asyncio.run(generate_layer3_render(layer1, layer2))
    # render_path = os.path.join(sub_dir, "layer3_render.txt")
    # with open(render_path, "w") as f:
    #     f.write(render_text)
    # with open(render_path, "r") as f:
    #     render_text = f.read()
    image = generate_image(render_text, os.path.join(output_dir, "methodology_02.png"))
    logger.info(f"Image saved")