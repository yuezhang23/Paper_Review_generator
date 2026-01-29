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
from typing import Any, Dict, Optional

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


async def generate_layer1_logic(methodology_text: str, ai_client: Optional[Any] = None) -> Dict[str, Any]:
    if ai_client is None:
        ai_client = get_ai_client()
    system_prompt = """You are an expert at analyzing methodology descriptions and extracting structured logical representations. 
Your task is to generate a COMPLETE JSON structure that represents the symbolic graph specification of a methodology workflow.

OUTPUT REQUIREMENTS:
- Return ONE valid JSON object only.
- No commentary.
- No markdown.
- No explanation.
"""

    user_prompt = f"""Analyze the following methodology description and generate the logic layer JSON structure:

{methodology_text}

Structure:
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

Follow the structure and rules specified above, Generate a full JSON structure.
"""

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,  
                max_tokens=10000,
                response_format={"type": "json_object"}  # Request JSON output
            )
            
            # Validate response structure
            if not response or not hasattr(response, 'choices') or not response.choices:
                logger.error(f"Response object: {response}")
                raise ValueError("Empty or invalid response from API")

            content = response.choices[0].message.content
            # Check if content is None or empty
            if content is None or not content.strip():
                raise ValueError("Response content is None")

            # extract the JSON object from the content
            content = content.strip()
            if content.startswith('```json') and content.endswith('```'):
                content = content[7:-3]
            elif content.startswith('```') and content.endswith('```'):
                content = content[3:-3]
            
            # Log content length for debugging
            logger.info(f"Layer 1 response content length: {len(content)} characters")

            
            # Try to parse JSON and check if it's complete
            try:
                logic_layer = json.loads(content)
                
                # check length of legend, a dictionary and number of nodes, a list
                # if len(logic_layer["legend"].items()) > len(logic_layer["nodes"]):
                #     continue

                # check if key component is too short
                key_components_too_short = False
                for node in logic_layer["nodes"]:
                    if len(node["key_components"]) > 0 and len(node["key_components"][0]) < 10:
                        key_components_too_short = True
                        break
                if key_components_too_short:
                    continue

                return logic_layer
            except json.JSONDecodeError as json_err:
                # Check if the error is due to incomplete JSON (unterminated string)
                error_msg = str(json_err)
                logger.error(f"JSON parse error: {error_msg}")
                if attempt < max_retries:
                    logger.warning(f"Incomplete JSON on attempt {attempt + 1}, retrying with higher max_tokens...")
                    continue
                raise json_err
        
        except (ValueError, json.JSONDecodeError, Exception) as e:
            if "truncated due to token limit" in str(e) or "Empty or invalid response" in str(e):
                raise
            # For other ValueErrors, retry if we have attempts left
            if attempt < max_retries:
                logger.warning(f"ValueError on attempt {attempt + 1}: {str(e)}, retrying...")
                continue
            raise e
    
async def generate_layer2_layout(logic_layer: Dict[str, Any], ai_client: Optional[Any] = None) -> Dict[str, Any]:
    if ai_client is None:
        ai_client = get_ai_client()
    system_prompt = """You are an expert at designing single-page infographic layouts for methodology workflows.

Your task is to generate a COMPLETE JSON structure that defines the layout blueprint for rendering the logic layer as a visual diagram. This layer makes the graph drawable without inventing structure.

OUTPUT REQUIREMENTS:
- Return ONE valid JSON object only.
- No commentary.
- No markdown.
- No explanation.
"""

    user_prompt = f"""Given the following logic layer structure, generate the COMPLETE layout layer JSON:

Logic layer:
{json.dumps(logic_layer, indent=2)}

Layout layer structure:
{layer_2_json}

Rules:
1. Design a single-page layout that accommodates ALL nodes in the logic layer
2. Group related nodes into regions (include ALL nodes)
3. Plan arrow styles based on edge types (straight, loops, returns)
4. Assign visual encoding (colors, icons) based on node types
5. Ensure the layout is visually clear, no overlapping nodes and follows logical flow

Generate the ENTIRE JSON structure - do not stop until you've included all regions, arrows, visual encoding.
"""

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.4,
                max_tokens=10000,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content

            # Check if content is None or empty
            if content is None or not content.strip():
                raise ValueError("Response content is None")

            # extract the JSON object from the content
            content = content.strip()
            if content.startswith('```json') and content.endswith('```'):
                content = content[7:-3]
            elif content.startswith('```') and content.endswith('```'):
                content = content[3:-3]
            try:
                layout_layer = json.loads(content)
                return layout_layer
            except json.JSONDecodeError as json_err:
                # If we haven't hit max retries, retry with higher max_tokens
                if attempt < max_retries:
                    logger.warning(f"Incomplete JSON on attempt {attempt + 1}, retrying with higher max_tokens...")
                    continue
                raise json_err
        except (ValueError, json.JSONDecodeError, Exception) as e:
            if "truncated due to token limit" in str(e) or "Empty or invalid response" in str(e):
                raise
            if attempt < max_retries:
                logger.warning(f"ValueError on attempt {attempt + 1}: {str(e)}, retrying...")
                continue
            raise e


async def generate_layer3_render(
    logic_layer: Dict[str, Any], layout_layer: Dict[str, Any], ai_client: Optional[Any] = None
) -> str:
    if ai_client is None:
        ai_client = get_ai_client()
    system_prompt = """You are an expert at converting structured workflow logic and layout JSON into a COMPLETE, deterministic Render Blueprint for a diffusion-based image generator.

Your job is NOT to summarize.  
Your job is to produce an exhaustive drawing specification.

Hard requirements:
- Expand every node, bullet, arrow, loop, legend item.
- Use exact text from the JSON. Never paraphrase.
- If any structure is ambiguous, choose ONE consistent interpretation and state it explicitly.
- Output must be self-contained and machine-checkable.
- Do NOT add artistic style language beyond minimal placeholders.
- Missing any text element is considered failure.
"""

    user_prompt = f"""Given the LOGIC LAYER and LAYOUT LAYER below, generate a Render Blueprint for an academic methodology diagram.
Your output MUST include the following sections A~B in order:

LOGIC LAYER
{json.dumps(logic_layer, indent=2)}

LAYOUT LAYER
{json.dumps(layout_layer, indent=2)}

TREE CONSTRAINTS
All substep groups (S2., S3., S4.*) must follow a strict hierarchical tree structure with parent-child alignment rules:
- Parent step box must act as the root node.
- Substeps must be aligned vertically beneath each other in a single right-side branch.
- Substeps must have equal vertical spacing and identical widths.
- No substep may appear left of or above its parent step.
- Arrows between substeps must be straight vertical connectors (no curves).
- All Arrows are only one directional.
- The dashed grouping box must tightly wrap only the substeps, not the arrows.
- All substep groups must use the exact same alignment pattern for consistency.

A. GLOBAL INVENTORY
Number and list EVERY drawable element:
- Title (verbatim)
- Node boxes (id → label → all bullets verbatim)
- Icons restated in physical visual form
- Arrows (from → to → direction → docking side → label)
- Loops (start → end → loop path → label)
- Dashed grouping boxes (group id → included nodes → padding rule)
- Legend items (label → icon description)

B. PLACEMENT ORDER
- Start with Step-by-step drawing order from canvas start to legend placement. 
- Specify the drawing direction to make the image more balanced and visually appealing.

OUTPUT CONTRACT (STRICT):
- Do NOT include introductions, commentary, explanations, markdown, or apologies.
- Do NOT restate the user request.
- Do NOT add any section outside A and B.
- Do NOT merge or omit any section.

RESPONSE MUST START EXACTLY WITH:
A. GLOBAL INVENTORY
(No whitespace, no markdown, no text before it.)

Output must include both GLOBAL INVENTORY and PLACEMENT ORDER. Any omission will be considered a failure.
"""

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model=REASONING_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                max_tokens=8000
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
                raise ValueError("Response content is None")

            # check is content is complete
            if 'A.' not in content or 'B.' not in content:
                logger.error("Response content is not complete")
                if attempt < max_retries:
                    logger.warning(f"Response content is not complete on attempt {attempt + 1}, retrying...")
                    continue
                raise ValueError("Response content is not complete")
            else:
                return content
            
        except (ValueError, Exception) as e:
            logger.error(f"Validation error in Layer 3: {str(e)}")
            raise


async def generate_three_layers(
    methodology_text: str, output_dir: Optional[str] = None, ai_client: Optional[Any] = None
) -> Dict[str, Any]:
    # Generate Layer 1 (Logic)
    logger.info(f"Generating Layer 1 (Logic)...")
    layer1 = await generate_layer1_logic(methodology_text, ai_client=ai_client)

    os.makedirs(output_dir, exist_ok=True)

    # Save Layer 1 as JSON
    layer1_path = os.path.join(output_dir, "layer1_logic.json")
    with open(layer1_path, 'w', encoding='utf-8') as f:
        json.dump(layer1, f, indent=2, ensure_ascii=False)
    logger.info(f"Layer 1 saved to: {layer1_path}")

    # Generate Layer 2 (Layout) - depends on Layer 1
    logger.info("Generating Layer 2 (Layout)...")
    layer2 = await generate_layer2_layout(layer1, ai_client=ai_client)

    # Save Layer 2 as JSON
    layer2_path = os.path.join(output_dir, "layer2_layout.json")
    with open(layer2_path, 'w', encoding='utf-8') as f:
        json.dump(layer2, f, indent=2, ensure_ascii=False)
    logger.info(f"Layer 2 saved to: {layer2_path}")

    # Generate Layer 3 (Render) - depends on both Layer 1 and Layer 2
    layer3 = await generate_layer3_render(layer1, layer2, ai_client=ai_client)
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


async def generate_from_file(
    input_file_path: str, output_dir: Optional[str] = None, ai_client: Optional[Any] = None
) -> Dict[str, Any]:
    # Load methodology description
    methodology_text = load_methodology_description(input_file_path)

    # create output directory if it doesn't exist
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Generate layers
    return await generate_three_layers(methodology_text, output_dir, ai_client=ai_client)

# from .images.test_image import generate_image
# if __name__ == "__main__":
#     base_dir = os.path.dirname(__file__)
#     input_file_path = os.path.join(base_dir, "images/1768522311_8stps/interpretation.txt")
#     output_dir = os.path.join(base_dir, "images/1768522311_8stps")
#     # sub_dir = os.path.join(output_dir, "01")
#     # sub_sub_dir = os.path.join(sub_dir, "002", "0001")
#     result = asyncio.run(generate_from_file(input_file_path, output_dir))
#     render_text = result["layer3_render"]
#     # layer1 = json.load(open(os.path.join(sub_dir, "layer1_logic.json"), "r"))
#     # layer2 = asyncio.run(generate_layer2_layout(layer1))
#     # layer2_path = os.path.join(sub_sub_dir, "layer2_layout.json")
#     # with open(layer2_path, "w") as f:
#     #     json.dump(layer2, f, indent=2, ensure_ascii=False)
#     # layer2 = json.load(open(os.path.join(sub_dir, "layer2_layout.json"), "r"))

#     # render_text = asyncio.run(generate_layer3_render(layer1, layer2))
#     # render_path = os.path.join(sub_dir, "layer3_render.txt")
#     # with open(render_path, "w") as f:
#     #     f.write(render_text)
#     # with open(render_path, "r") as f:
#     #     render_text = f.read()
#     image = generate_image(render_text, os.path.join(output_dir, "methodology_02.png"))
#     logger.info(f"Image saved")