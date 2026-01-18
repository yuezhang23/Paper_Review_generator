"""
Evaluation Pipeline for Methodology Image Generation

This module provides evaluation functions to:
1. Extract JSON structure from generated methodology images using vision models
2. Compare extracted JSON to original layer1_logic.json (ground truth)
3. Detect mismatches and calculate scores
4. Generate detailed evaluation reports

Based on the three-layer process:
- Layer 1: Logic layer (ground truth JSON structure)
- Layer 2: Layout layer (layout blueprint)
- Layer 3: Render layer (image generation prompt)
"""

import os
import json
import asyncio
import logging
import base64
import time
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import sys

# Import from parent utils module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from utils import get_ai_client
from image_methodos_generator.three_layer_generator import extract_json_from_content

# Set up logging
logger = logging.getLogger(__name__)

# Vision model for extracting JSON from images
VISION_MODEL = "supermind-vision-v1"  # Can be changed to "gpt-4o-mini" or other vision models
layer1_tmp = json.load(open(os.path.join(os.path.dirname(__file__), "layer1_temp.json"), "r"))
layer2_tmp = json.load(open(os.path.join(os.path.dirname(__file__), "layer2_temp.json"), "r"))


def load_layer1_json(json_path: str) -> Dict[str, Any]:
    """
    Load the original layer1_logic.json (ground truth) from file.
    
    Args:
        json_path: Path to layer1_logic.json file
        
    Returns:
        Dictionary containing the ground truth JSON structure
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Layer1 JSON file not found: {json_path}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from {json_path}: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Error loading layer1 JSON: {str(e)}")
        raise


def encode_image_to_base64(image_path: str) -> str:
    """
    Encode an image file to base64 string for API transmission.
    
    Args:
        image_path: Path to image file
        
    Returns:
        Base64-encoded image string
    """
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Failed to encode image {image_path}: {str(e)}")
        raise


async def extract_json_from_image(
    image_path: str,
    ground_truth_json: Dict[str, Any],
    model: str = VISION_MODEL
) -> Dict[str, Any]:
    """
    Extract JSON structure from a methodology diagram image using vision model.
    
    This function analyzes the image and extracts the methodology structure
    in the same format as layer1_logic.json.
    
    Args:
        image_path: Path to the generated methodology image
        ground_truth_json: The original layer1_logic.json for reference
        model: Vision model to use (default: "gpt-4o")
        
    Returns:
        Dictionary containing the extracted JSON structure
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")
    
    logger.info(f"Extracting JSON from image: {image_path}")
    
    # Encode image to base64
    base64_image = encode_image_to_base64(image_path)
    
    # Get image format from file extension
    image_format = "png"
    if image_path.lower().endswith(".jpg") or image_path.lower().endswith(".jpeg"):
        image_format = "jpeg"
    elif image_path.lower().endswith(".gif"):
        image_format = "gif"
    elif image_path.lower().endswith(".webp"):
        image_format = "webp"
    
    # Build system prompt
    system_prompt = f"""You are an expert at analyzing infogrphic diagram images and extracting structured JSON representations.

Your task is to analyze the workflow diagram in the image and extract its structure into a JSON format that matches the ground truth schema.

Return ONLY valid JSON, no markdown formatting, no code blocks."""

    # Build user prompt with ground truth reference
    user_prompt = f"""Analyze the methodology diagram in this image and extract its structure as JSON.

Ground Truth Schema:
{json.dumps(layer1_tmp, indent=2)}

Instructions:
1. Identify all steps/nodes in the diagram and assign IDs (S1, S2, S3, etc.)
2. Extract labels and types for each node
3. Identify key components for each step
4. Map all edges/arrows between nodes
5. Extract legend/key terms if visible
6. Identify constraints if explicitly stated
7. Return ONLY valid JSON matching the structure above, no markdown, no code blocks
8. Follow the ground truth schema strictly.

If text is illegible or uncertain, try to infer from context, but note uncertainties in a separate field if needed."""

    ai_client = get_ai_client()
    
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
            model=model,
            messages=messages,
            max_tokens=4000,
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        if not response or not hasattr(response, 'choices') or not response.choices:
            raise ValueError("Empty or invalid response from API")
        
        content = response.choices[0].message.content
        
        if not content or not content.strip():
            raise ValueError("Response content is empty")
        
        # Extract JSON from content (handles embedded JSON, markdown blocks, etc.)
        json_str = extract_json_from_content(content)
        
        # Parse JSON response
        extracted_json = json.loads(json_str)
        logger.info(f"Successfully extracted JSON from image: {image_path}")
        return extracted_json
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from extracted content: {str(e)}")
        logger.error(f"Response content: {content if 'content' in locals() else 'N/A'}")
        raise
    except Exception as e:
        logger.error(f"Error extracting JSON from image: {str(e)}")
        raise


def compare_nodes(
    ground_truth_nodes: List[Dict[str, Any]],
    extracted_nodes: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compare nodes between ground truth and extracted JSON.
    
    Args:
        ground_truth_nodes: List of nodes from layer1_logic.json
        extracted_nodes: List of nodes extracted from image
        
    Returns:
        Dictionary with comparison results:
        {
            "matched": [...],
            "missing": [...],
            "extra": [...],
            "mismatched": [...],
            "scores": {
                "precision": float,
                "recall": float,
                "f1": float
            }
        }
    """
    gt_node_map = {node["id"]: node for node in ground_truth_nodes}
    extracted_node_map = {node["id"]: node for node in extracted_nodes}
    
    matched = []
    missing = []
    extra = []
    mismatched = []
    
    # Check ground truth nodes
    for gt_node in ground_truth_nodes:
        node_id = gt_node["id"]
        if node_id in extracted_node_map:
            ext_node = extracted_node_map[node_id]
            # Check if labels and types match
            if (gt_node.get("label", "").lower().strip() == 
                ext_node.get("label", "").lower().strip() and
                gt_node.get("type") == ext_node.get("type")):
                matched.append({
                    "node_id": node_id,
                    "ground_truth": gt_node,
                    "extracted": ext_node,
                    "status": "MATCH"
                })
            else:
                mismatched.append({
                    "node_id": node_id,
                    "ground_truth": gt_node,
                    "extracted": ext_node,
                    "status": "MISMATCH",
                    "differences": {
                        "label": gt_node.get("label") != ext_node.get("label"),
                        "type": gt_node.get("type") != ext_node.get("type"),
                        "key_components": gt_node.get("key_components") != ext_node.get("key_components")
                    }
                })
        else:
            missing.append({
                "node_id": node_id,
                "ground_truth": gt_node,
                "status": "MISSING"
            })
    
    # Check for extra nodes
    for ext_node_id, ext_node in extracted_node_map.items():
        if ext_node_id not in gt_node_map:
            extra.append({
                "node_id": ext_node_id,
                "extracted": ext_node,
                "status": "EXTRA"
            })
    
    # Calculate scores
    total_gt = len(ground_truth_nodes)
    total_extracted = len(extracted_nodes)
    true_positives = len(matched)
    false_positives = len(extra)
    false_negatives = len(missing) + len(mismatched)
    
    precision = true_positives / total_extracted if total_extracted > 0 else 0.0
    recall = true_positives / total_gt if total_gt > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "scores": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives
        }
    }


def compare_edges(
    ground_truth_edges: List[Dict[str, Any]],
    extracted_edges: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Compare edges between ground truth and extracted JSON.
    
    Args:
        ground_truth_edges: List of edges from layer1_logic.json
        extracted_edges: List of edges extracted from image
        
    Returns:
        Dictionary with comparison results similar to compare_nodes
    """
    def edge_key(edge):
        return (edge["from"], edge["to"], edge.get("type", "arrow"))
    
    gt_edge_map = {edge_key(edge): edge for edge in ground_truth_edges}
    extracted_edge_map = {edge_key(edge): edge for edge in extracted_edges}
    
    matched = []
    missing = []
    extra = []
    mismatched = []
    
    # Check ground truth edges
    for gt_edge in ground_truth_edges:
        key = edge_key(gt_edge)
        if key in extracted_edge_map:
            ext_edge = extracted_edge_map[key]
            # Check if labels match (if present)
            if gt_edge.get("label") == ext_edge.get("label"):
                matched.append({
                    "edge_key": key,
                    "ground_truth": gt_edge,
                    "extracted": ext_edge,
                    "status": "MATCH"
                })
            else:
                mismatched.append({
                    "edge_key": key,
                    "ground_truth": gt_edge,
                    "extracted": ext_edge,
                    "status": "MISMATCH",
                    "differences": {
                        "label": gt_edge.get("label") != ext_edge.get("label")
                    }
                })
        else:
            missing.append({
                "edge_key": key,
                "ground_truth": gt_edge,
                "status": "MISSING"
            })
    
    # Check for extra edges
    for ext_key, ext_edge in extracted_edge_map.items():
        if ext_key not in gt_edge_map:
            extra.append({
                "edge_key": ext_key,
                "extracted": ext_edge,
                "status": "EXTRA"
            })
    
    # Calculate scores
    total_gt = len(ground_truth_edges)
    total_extracted = len(extracted_edges)
    true_positives = len(matched)
    false_positives = len(extra)
    false_negatives = len(missing) + len(mismatched)
    
    precision = true_positives / total_extracted if total_extracted > 0 else 0.0
    recall = true_positives / total_gt if total_gt > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
        "scores": {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "false_negatives": false_negatives
        }
    }


def compare_constraints(
    ground_truth_constraints: List[str],
    extracted_constraints: List[str]
) -> Dict[str, Any]:
    """
    Compare must_not_change constraints between ground truth and extracted JSON.
    
    Args:
        ground_truth_constraints: List of constraints from layer1_logic.json
        extracted_constraints: List of constraints extracted from image
        
    Returns:
        Dictionary with comparison results
    """
    matched = []
    missing = []
    extra = []
    
    # Simple string matching (can be improved with semantic similarity)
    gt_set = set(c.lower().strip() for c in ground_truth_constraints)
    extracted_set = set(c.lower().strip() for c in extracted_constraints)
    
    for constraint in ground_truth_constraints:
        if constraint.lower().strip() in extracted_set:
            matched.append(constraint)
        else:
            missing.append(constraint)
    
    for constraint in extracted_constraints:
        if constraint.lower().strip() not in gt_set:
            extra.append(constraint)
    
    compliance_rate = len(matched) / len(ground_truth_constraints) if ground_truth_constraints else 1.0
    
    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "compliance_rate": compliance_rate,
        "total_required": len(ground_truth_constraints),
        "total_matched": len(matched),
        "total_missing": len(missing)
    }


def compare_json(
    ground_truth: Dict[str, Any],
    extracted: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compare ground truth JSON with extracted JSON from image.
    
    Args:
        ground_truth: The original layer1_logic.json structure
        extracted: The JSON structure extracted from the image
        
    Returns:
        Comprehensive comparison report with scores and mismatches
    """
    # Compare nodes
    gt_nodes = ground_truth.get("nodes", [])
    ext_nodes = extracted.get("nodes", [])
    node_comparison = compare_nodes(gt_nodes, ext_nodes)
    
    # Compare edges
    gt_edges = ground_truth.get("edges", [])
    ext_edges = extracted.get("edges", [])
    edge_comparison = compare_edges(gt_edges, ext_edges)
    
    # Compare constraints
    gt_constraints = ground_truth.get("must_not_change", [])
    ext_constraints = extracted.get("must_not_change", [])
    constraint_comparison = compare_constraints(gt_constraints, ext_constraints)
    
    # Calculate overall score (weighted average)
    node_f1 = node_comparison["scores"]["f1"]
    edge_f1 = edge_comparison["scores"]["f1"]
    constraint_compliance = constraint_comparison["compliance_rate"]
    
    # Weighted overall score: nodes (40%), edges (40%), constraints (20%)
    overall_score = (node_f1 * 0.4 + edge_f1 * 0.4 + constraint_compliance * 0.2)
    
    # Determine overall status
    if overall_score >= 0.9 and constraint_comparison["compliance_rate"] >= 0.9:
        overall_status = "PASS"
    elif overall_score >= 0.7 and constraint_comparison["compliance_rate"] >= 0.7:
        overall_status = "PASS_WITH_UNCERTAINTY"
    else:
        overall_status = "FAIL"
    
    return {
        "overall_status": overall_status,
        "overall_score": overall_score,
        "node_comparison": node_comparison,
        "edge_comparison": edge_comparison,
        "constraint_comparison": constraint_comparison,
        "title_match": ground_truth.get("title", "") == extracted.get("title", ""),
        "legend_match": ground_truth.get("legend", {}) == extracted.get("legend", {}),
        "summary": {
            "total_nodes_required": len(gt_nodes),
            "total_nodes_extracted": len(ext_nodes),
            "total_edges_required": len(gt_edges),
            "total_edges_extracted": len(ext_edges),
            "total_constraints_required": len(gt_constraints),
            "total_constraints_matched": len(constraint_comparison["matched"])
        }
    }


async def evaluate_image(
    image_path: str,
    ground_truth_json_path: str,
    output_path: Optional[str] = None,
    model: str = VISION_MODEL
) -> Dict[str, Any]:
    """
    Evaluate a single methodology image against ground truth.
    
    Args:
        image_path: Path to the generated methodology image
        ground_truth_json_path: Path to layer1_logic.json
        output_path: Optional path to save evaluation results JSON
        model: Vision model to use for extraction
        
    Returns:
        Evaluation report dictionary
    """
    logger.info(f"Evaluating image: {image_path}")
    
    # Load ground truth
    ground_truth = load_layer1_json(ground_truth_json_path)
    
    # Extract JSON from image
    extracted = await extract_json_from_image(image_path, ground_truth, model)
    
    # Compare
    comparison = compare_json(ground_truth, extracted)
    
    # Add metadata
    result = {
        "image_path": image_path,
        "ground_truth_path": ground_truth_json_path,
        "evaluation_timestamp": time.time(),
        "ground_truth": ground_truth,
        "extracted": extracted,
        "comparison": comparison
    }
    
    # Save if output path provided
    if output_path:
        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info(f"Evaluation results saved to: {output_path}")
    
    return result


async def evaluate_directory(
    directory: str,
    image_pattern: str = "methodology*.png",
    ground_truth_filename: str = "layer1_logic.json",
    output_dir: Optional[str] = None,
    model: str = VISION_MODEL
) -> Dict[str, Any]:
    """
    Evaluate all methodology images in a directory.
    
    Args:
        directory: Directory containing images and layer1_logic.json
        image_pattern: Pattern to match image files (default: "methodology*.png")
        ground_truth_filename: Name of ground truth JSON file (default: "layer1_logic.json")
        output_dir: Optional directory to save individual evaluation results
        model: Vision model to use for extraction
        
    Returns:
        Aggregated evaluation report for all images
    """
    logger.info(f"Evaluating directory: {directory}")
    
    dir_path = Path(directory)
    ground_truth_path = dir_path / ground_truth_filename
    
    if not ground_truth_path.exists():
        raise FileNotFoundError(f"Ground truth JSON not found: {ground_truth_path}")
    
    # Find all matching images
    image_files = list(dir_path.glob(image_pattern))
    
    if not image_files:
        logger.warning(f"No images found matching pattern '{image_pattern}' in {directory}")
        return {"error": "No images found", "directory": directory}
    
    logger.info(f"Found {len(image_files)} images to evaluate")
    
    # Evaluate each image
    results = []
    for image_path in sorted(image_files):
        try:
            output_path = None
            if output_dir:
                output_filename = f"eval_{image_path.stem}.json"
                output_path = os.path.join(output_dir, output_filename)
            
            result = await evaluate_image(
                str(image_path),
                str(ground_truth_path),
                output_path,
                model
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Error evaluating {image_path}: {str(e)}")
            results.append({
                "image_path": str(image_path),
                "error": str(e)
            })
    
    # Aggregate results
    successful_results = [r for r in results if "error" not in r]
    
    if successful_results:
        avg_overall_score = sum(r["comparison"]["overall_score"] for r in successful_results) / len(successful_results)
        avg_node_f1 = sum(r["comparison"]["node_comparison"]["scores"]["f1"] for r in successful_results) / len(successful_results)
        avg_edge_f1 = sum(r["comparison"]["edge_comparison"]["scores"]["f1"] for r in successful_results) / len(successful_results)
        avg_constraint_compliance = sum(r["comparison"]["constraint_comparison"]["compliance_rate"] for r in successful_results) / len(successful_results)
        
        status_counts = {}
        for r in successful_results:
            status = r["comparison"]["overall_status"]
            status_counts[status] = status_counts.get(status, 0) + 1
    else:
        avg_overall_score = 0.0
        avg_node_f1 = 0.0
        avg_edge_f1 = 0.0
        avg_constraint_compliance = 0.0
        status_counts = {}
    
    aggregated = {
        "directory": directory,
        "total_images": len(image_files),
        "successful_evaluations": len(successful_results),
        "failed_evaluations": len(results) - len(successful_results),
        "average_scores": {
            "overall_score": avg_overall_score,
            "node_f1": avg_node_f1,
            "edge_f1": avg_edge_f1,
            "constraint_compliance": avg_constraint_compliance
        },
        "status_distribution": status_counts,
        "individual_results": results
    }
    
    # Save aggregated results
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        aggregated_path = os.path.join(output_dir, "aggregated_eval_results.json")
        with open(aggregated_path, 'w', encoding='utf-8') as f:
            json.dump(aggregated, f, indent=2, ensure_ascii=False)
        logger.info(f"Aggregated results saved to: {aggregated_path}")
    
    return aggregated


if __name__ == "__main__":
    # Example usage
    import argparse
    
    parser = argparse.ArgumentParser(description="Evaluate methodology images against ground truth JSON")
    parser.add_argument("--image", type=str, help="Path to single image to evaluate")
    parser.add_argument("--directory", type=str, help="Directory containing images to evaluate")
    parser.add_argument("--ground-truth", type=str, help="Path to layer1_logic.json (required for single image)")
    parser.add_argument("--output", type=str, help="Output path/directory for results")
    parser.add_argument("--model", type=str, default=VISION_MODEL, help=f"Vision model to use (default: {VISION_MODEL})")
    
    args = parser.parse_args()
    
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    if args.image:
        # Single image evaluation
        if not args.ground_truth:
            parser.error("--ground-truth is required when evaluating a single image")
        
        result = asyncio.run(evaluate_image(
            args.image,
            args.ground_truth,
            args.output,
            args.model
        ))
        
        print(json.dumps(result, indent=2))
        
    elif args.directory:
        # Directory evaluation
        result = asyncio.run(evaluate_directory(
            args.directory,
            output_dir=args.output,
            model=args.model
        ))
        
        print(json.dumps(result, indent=2))
        
    else:
        parser.error("Either --image or --directory must be provided")