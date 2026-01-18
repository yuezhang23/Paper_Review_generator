import os
import logging
from io import BytesIO
from PIL import Image
import base64
import re
from typing import Optional


# Set up logging
logger = logging.getLogger(__name__)

def load_prompt_template(template_path: str) -> str:
    """
    Load a prompt template from a markdown file.
    
    Args:
        template_name: Name of the template file (without .md extension)
        
    Returns:
        Template content as string
    """
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt template not found: {template_path}")
        raise
    except Exception as e:
        raise


def format_prompt_template(template: str, **kwargs) -> str:
    """
    Format a prompt template by replacing placeholders.
    
    Args:
        template: Template string with placeholders like {query}, {retrieved_content}, etc.
        **kwargs: Values to replace placeholders
        
    Returns:
        Formatted prompt string
    """
    return template.format(**kwargs)

def fix_imamge_size(image_bytes: bytes, max_width: int = 1536, max_height: int = 1024) -> bytes:
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
            resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Convert back to bytes
            output_buffer = BytesIO()
            # Preserve original format if PNG, otherwise use PNG
            image_format = image.format if image.format else 'PNG'
            resized_image.save(output_buffer, format=image_format, optimize=True)
            return output_buffer.getvalue()
        else:
            logger.info(f"Image size ({original_width}x{original_height}) fits within canvas ({max_width}x{max_height}), no resize needed")
            return image_bytes
    except Exception as resize_error:
        logger.warning(f"Failed to check/resize image: {str(resize_error)}. Using original image.")
        return image_bytes

def get_max_step_number(text: str) -> Optional[int]:
    """Find the largest number that follows the 'step N' pattern (case-insensitive)."""
    matches = re.findall(r'step\s+(\d+)', text, re.IGNORECASE)
    if not matches:
        return None
    return max(int(m) for m in matches)


# def extract_steps_content(text: str) -> tuple[str, Optional[int]]:
#     """Extract steps-related content from text, handling various step formats.
    
#     Looks for common step patterns:
#     - "Step 1", "Step 2", etc.
#     - "1.", "2.", etc.
#     - "1)", "2)", etc.
#     - "First", "Second", "Third", etc.
#     - Other numbered sequences
    
#     Also extracts the largest number from 'step N' patterns in the result.
    
#     Args:
#         text: The input text that may contain step-by-step content
        
#     Returns:
#         Tuple of (extracted text, max step number from 'step N' patterns or None)
#     """
#     if not text or len(text) <= 5000:
#         return (text, _get_max_step_number(text))
    
#     lines = text.split('\n')
    
#     # Patterns to match various step formats
#     step_patterns = [
#         # "Step 1", "Step 2", etc. (case-insensitive)
#         re.compile(r'^\s*step\s+\d+', re.IGNORECASE),
#         # "1.", "2.", etc. at start of line (with optional whitespace)
#         re.compile(r'^\s*\d+\.\s+'),
#         # "1)", "2)", etc. at start of line
#         re.compile(r'^\s*\d+\)\s+'),
#         # Ordinal numbers: "First", "Second", "Third", etc.
#         re.compile(r'^\s*(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)', re.IGNORECASE),
#         # Markdown-style numbered lists: "1. " or "- 1."
#         re.compile(r'^\s*[-*]\s*\d+\.\s+'),
#         # "Phase 1", "Phase 2", etc.
#         re.compile(r'^\s*phase\s+\d+', re.IGNORECASE),
#     ]
    
#     # Find the first line that matches any step pattern
#     for i, line in enumerate(lines):
#         for pattern in step_patterns:
#             if pattern.search(line):
#                 extracted = '\n'.join(lines[i:])
#                 logger.info(f"Found step content starting at line {i+1} with pattern: {pattern.pattern}")
#                 return (extracted, _get_max_step_number(extracted))
    
#     # If no step pattern found, try to find content after common section headers
#     # that might precede steps (e.g., "Steps:", "Methodology:", "Process:")
#     section_headers = [
#         re.compile(r'^\s*(steps?|methodology|process|procedure|workflow|algorithm|approach):', re.IGNORECASE),
#     ]
    
#     for i, line in enumerate(lines):
#         for header_pattern in section_headers:
#             if header_pattern.search(line):
#                 # Return from the next line (after the header)
#                 logger.info(f"Found section header at line {i+1}, extracting content from line {i+2}")
#                 if i + 1 < len(lines):
#                     extracted = '\n'.join(lines[i:])
#                     return (extracted, _get_max_step_number(extracted))
#                 break
    
#     # If still no pattern found, try to find where numbered content appears in the middle of text
#     # Look for the first occurrence of any numbered pattern anywhere in the text
#     for i, line in enumerate(lines):
#         # Check if line contains a step-like pattern even if not at start
#         if re.search(r'\b(step\s+\d+|phase\s+\d+|\d+\.\s+[A-Z])', line, re.IGNORECASE):
#             extracted = '\n'.join(lines[i:])
#             logger.info(f"Found embedded step content at line {i+1}")
#             return (extracted, _get_max_step_number(extracted))
    
#     # Fallback: if text is too long and no steps found, truncate intelligently
#     # Try to find a good breaking point (e.g., after first paragraph or section)
#     if len(text) > 5000:
#         logger.warning("No step patterns found, using fallback truncation")
#         # Take last 5000 characters to preserve the most recent/relevant content
#         fallback = text[-5000:]
#         return (fallback, _get_max_step_number(fallback))
#     return (text, _get_max_step_number(text))

