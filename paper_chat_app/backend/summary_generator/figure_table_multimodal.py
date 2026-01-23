"""
Multi-modal extraction for figure and table content using vision models.

This module provides functions to extract and analyze content from figures and tables
using multi-modal AI models (e.g., GPT-4 Vision, Claude Vision) for understanding
visual content.
"""

import os
import base64
import logging
import asyncio
from typing import List, Dict, Optional
import sys

# Import AI client from parent utils
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import get_ai_client

logger = logging.getLogger(__name__)


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
        logger.error(f"[Multimodal] Failed to encode image {image_path}: {str(e)}")
        return ""


async def analyze_figure_multimodal(
    figure_path: str,
    caption: str = None,
    model: str = "gpt-4o"
) -> str:
    """
    Analyze a figure image using multi-modal AI model to extract content and insights.
    
    Args:
        figure_path: Path to figure image file
        caption: Optional caption for the figure (from GROBID)
        model: AI model to use (default: "gpt-4o" for vision capabilities)
        
    Returns:
        Extracted content and analysis of the figure
    """
    try:
        if not os.path.exists(figure_path):
            logger.warning(f"[Multimodal] Figure file not found: {figure_path}")
            return ""
        
        logger.info(f"[Multimodal] Analyzing figure: {figure_path}")
        
        # Encode image to base64
        base64_image = encode_image_to_base64(figure_path)
        if not base64_image:
            logger.error(f"[Multimodal] Failed to encode image: {figure_path}")
            return ""
        
        # Get image format from file extension
        image_format = "png"
        if figure_path.lower().endswith(".jpg") or figure_path.lower().endswith(".jpeg"):
            image_format = "jpeg"
        elif figure_path.lower().endswith(".gif"):
            image_format = "gif"
        elif figure_path.lower().endswith(".webp"):
            image_format = "webp"
        
        # Build prompt
        prompt = """Analyze this figure from an academic paper and provide a detailed description of:
1. The main content and visual elements
2. Any text, labels, or annotations visible in the figure
3. The key information, data, or concepts shown
4. How this figure relates to the paper's content

Provide a comprehensive but concise analysis."""
        
        if caption:
            prompt = f"""Analyze this figure from an academic paper.

Figure Caption: {caption}

Provide a detailed description of:
1. The main content and visual elements
2. Any text, labels, or annotations visible in the figure
3. The key information, data, or concepts shown
4. How this figure relates to the caption and paper's content

Provide a comprehensive but concise analysis."""
        
        # Call AI client with vision capabilities
        ai_client = get_ai_client()
        
        # Use OpenAI vision API format
        messages = [
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
            model=model,
            messages=messages,
            max_tokens=1000,
            temperature=0.2
        )
        
        content = response.choices[0].message.content
        logger.info(f"[Multimodal] Extracted {len(content)} characters from figure analysis")
        return content
        
    except Exception as e:
        logger.error(f"[Multimodal] Failed to analyze figure {figure_path}: {str(e)}")
        return ""


async def analyze_table_multimodal(
    table_content: str,
    caption: str = None,
    model: str = "gpt-4o"
) -> str:
    """
    Analyze table content using multi-modal AI model.
    For tables that are images, use analyze_figure_multimodal instead.
    
    Args:
        table_content: Text content of the table (from Camelot/Tabula)
        caption: Optional caption for the table (from GROBID)
        model: AI model to use
        
    Returns:
        Analysis and insights about the table content
    """
    try:
        logger.info(f"[Multimodal] Analyzing table content (length: {len(table_content)} chars)")
        
        # Build prompt
        prompt = f"""Analyze this table from an academic paper and provide:

1. A summary of the table's structure (rows, columns, headers)
2. Key data points, trends, or patterns in the table
3. Important findings or conclusions that can be drawn
4. How this table relates to the paper's content

Table Content:
{table_content}
"""
        
        if caption:
            prompt = f"""Analyze this table from an academic paper.

Table Caption: {caption}

Provide:
1. A summary of the table's structure (rows, columns, headers)
2. Key data points, trends, or patterns in the table
3. Important findings or conclusions that can be drawn
4. How this table relates to the caption and paper's content

Table Content:
{table_content}
"""
        
        # Call AI client
        ai_client = get_ai_client()
        
        # Run in thread pool for async execution
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert at analyzing academic tables and extracting key insights."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=1000,
            temperature=0.2
        )
        
        content = response.choices[0].message.content
        logger.info(f"[Multimodal] Extracted {len(content)} characters from table analysis")
        return content
        
    except Exception as e:
        logger.error(f"[Multimodal] Failed to analyze table: {str(e)}")
        return ""


async def enrich_figures_with_multimodal(
    figure_paths: List[str],
    captions: List[str] = None,
    model: str = "gpt-4o"
) -> List[Dict[str, str]]:
    """
    Enrich figure captions with multi-modal AI analysis.
    
    Args:
        figure_paths: List of paths to figure image files
        captions: Optional list of figure captions (from GROBID)
        model: AI model to use for vision analysis
        
    Returns:
        List of dictionaries with 'caption', 'content', and 'figure_path' keys
    """
    results = []
    tasks = []
    
    for i, fig_path in enumerate(figure_paths):
        caption = captions[i] if captions and i < len(captions) else f"Figure {i+1}"
        task = analyze_figure_multimodal(fig_path, caption, model)
        tasks.append((i, fig_path, caption, task))
    
    # Execute all analyses in parallel
    for i, fig_path, caption, task in tasks:
        try:
            content = await task
            results.append({
                "figure_path": fig_path,
                "figure_index": i,
                "caption": caption,
                "content": content
            })
            logger.info(f"[Multimodal] Figure {i+1}: Extracted {len(content)} characters")
        except Exception as e:
            logger.error(f"[Multimodal] Failed to analyze figure {i+1}: {str(e)}")
            results.append({
                "figure_path": fig_path,
                "figure_index": i,
                "caption": caption,
                "content": f"Error: {str(e)}"
            })
    
    return results


async def enrich_tables_with_multimodal(
    tables_content: List[str],
    captions: List[str] = None,
    model: str = "gpt-4o"
) -> List[Dict[str, str]]:
    """
    Enrich table captions with multi-modal AI analysis.
    
    Args:
        tables_content: List of table content strings (from Camelot/Tabula)
        captions: Optional list of table captions (from GROBID)
        model: AI model to use for analysis
        
    Returns:
        List of dictionaries with 'caption', 'content', and 'table_index' keys
    """
    results = []
    tasks = []
    
    for i, content in enumerate(tables_content):
        caption = captions[i] if captions and i < len(captions) else f"Table {i+1}"
        task = analyze_table_multimodal(content, caption, model)
        tasks.append((i, content, caption, task))
    
    # Execute all analyses in parallel
    for i, content, caption, task in tasks:
        try:
            analysis = await task
            results.append({
                "table_index": i,
                "caption": caption,
                "content": content,
                "analysis": analysis
            })
            logger.info(f"[Multimodal] Table {i+1}: Extracted {len(analysis)} characters")
        except Exception as e:
            logger.error(f"[Multimodal] Failed to analyze table {i+1}: {str(e)}")
            results.append({
                "table_index": i,
                "caption": caption,
                "content": content,
                "analysis": f"Error: {str(e)}"
            })
    
    return results
