"""
OCR-based extraction for figure and table content using Tesseract OCR.

This module provides functions to extract text content from figures and tables
using Tesseract OCR. This is useful when figures/tables contain text that needs
to be extracted for analysis.
"""

import os
import logging
import pytesseract
from PIL import Image
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


def extract_figure_content_ocr(figure_path: str) -> str:
    """
    Extract text content from a figure image using Tesseract OCR.
    
    Args:
        figure_path: Path to figure image file
        
    Returns:
        Extracted text content from the figure
    """
    try:
        if not os.path.exists(figure_path):
            logger.warning(f"[OCR] Figure file not found: {figure_path}")
            return ""
        
        logger.info(f"[OCR] Extracting text from figure: {figure_path}")
        image = Image.open(figure_path)
        text = pytesseract.image_to_string(image)
        
        if text.strip():
            logger.info(f"[OCR] Extracted {len(text.strip())} characters from figure")
            return text.strip()
        else:
            logger.warning(f"[OCR] No text found in figure: {figure_path}")
            return ""
    except Exception as e:
        logger.error(f"[OCR] Failed to extract text from figure {figure_path}: {str(e)}")
        return ""


def extract_figures_content_ocr(figure_paths: List[str]) -> List[Dict[str, str]]:
    """
    Extract text content from multiple figures using OCR.
    
    Args:
        figure_paths: List of paths to figure image files
        
    Returns:
        List of dictionaries with 'figure_path' and 'content' keys
    """
    results = []
    for i, fig_path in enumerate(figure_paths):
        content = extract_figure_content_ocr(fig_path)
        results.append({
            "figure_path": fig_path,
            "figure_index": i,
            "content": content
        })
        if content:
            logger.info(f"[OCR] Figure {i+1}: Extracted {len(content)} characters")
    
    return results


def extract_table_from_image_ocr(table_image_path: str) -> str:
    """
    Extract table content from an image using OCR.
    This is useful when tables are embedded as images in the PDF.
    
    Args:
        table_image_path: Path to table image file
        
    Returns:
        Extracted table content as text
    """
    try:
        if not os.path.exists(table_image_path):
            logger.warning(f"[OCR] Table image file not found: {table_image_path}")
            return ""
        
        logger.info(f"[OCR] Extracting table from image: {table_image_path}")
        image = Image.open(table_image_path)
        
        # Use Tesseract with table-specific configuration
        custom_config = r'--oem 3 --psm 6'  # Assume a single uniform block of text (like a table)
        text = pytesseract.image_to_string(image, config=custom_config)
        
        if text.strip():
            logger.info(f"[OCR] Extracted {len(text.strip())} characters from table image")
            return text.strip()
        else:
            logger.warning(f"[OCR] No text found in table image: {table_image_path}")
            return ""
    except Exception as e:
        logger.error(f"[OCR] Failed to extract table from image {table_image_path}: {str(e)}")
        return ""


def enrich_figures_with_ocr(figure_paths: List[str], captions: List[str] = None) -> List[Dict[str, str]]:
    """
    Enrich figure captions with OCR-extracted content.
    
    Args:
        figure_paths: List of paths to figure image files
        captions: Optional list of figure captions (from GROBID)
        
    Returns:
        List of dictionaries with 'caption', 'content', and 'figure_path' keys
    """
    results = []
    for i, fig_path in enumerate(figure_paths):
        caption = captions[i] if captions and i < len(captions) else f"Figure {i+1}"
        content = extract_figure_content_ocr(fig_path)
        results.append({
            "figure_path": fig_path,
            "figure_index": i,
            "caption": caption,
            "content": content
        })
    
    return results


def enrich_tables_with_ocr(
    tables_content: List[str],
    captions: List[str] = None
) -> List[Dict[str, str]]:
    """
    Enrich table captions with pre-extracted table content.
    Table extraction should be done separately using extract_tables() from utils.
    
    Args:
        tables_content: Pre-extracted table content list (from utils.extract_tables())
        captions: Optional list of table captions (from GROBID)
        
    Returns:
        List of dictionaries with 'caption', 'content', and 'table_index' keys
    """
    results = []
    
    for i, content in enumerate(tables_content):
        caption = captions[i] if captions and i < len(captions) else f"Table {i+1}"
        results.append({
            "table_index": i,
            "caption": caption,
            "content": content
        })
    
    return results
