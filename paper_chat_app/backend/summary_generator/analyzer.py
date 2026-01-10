"""
Image and table analysis using AI Builder API chat endpoint.
Supports both image URLs and local file paths for figure analysis.
"""

import base64
import os
import sys
import asyncio
from urllib.parse import urlparse

# Import from parent utils module (not summary_generator/utils)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import get_ai_client


def _is_url(path_or_url: str) -> bool:
    """Check if the input is a URL or a local file path"""
    try:
        result = urlparse(path_or_url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def _image_to_data_uri(image_path: str) -> str:
    """Convert local image file to base64 data URI"""
    with open(image_path, "rb") as f:
        image_data = f.read()
        b64 = base64.b64encode(image_data).decode()
        # Try to detect image format from file extension
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp'
        }.get(ext, 'image/png')
        return f"data:{mime_type};base64,{b64}"


async def analyze_figure(image_path_or_url: str) -> str:
    """
    Analyze an academic figure using AI Builder API chat endpoint (async).
    
    Args:
        image_path_or_url: Either a local file path or a URL to an image
        
    Returns:
        Analysis text explaining what the figure shows and why it matters
    """
    client = get_ai_client()
    
    # Determine if input is URL or local path
    if _is_url(image_path_or_url):
        # Use URL directly - AI Builder API supports image URLs
        image_url = image_path_or_url
    else:
        # Convert local file to data URI (run in thread pool to avoid blocking)
        image_url = await asyncio.to_thread(_image_to_data_uri, image_path_or_url)
    
    # Run API call in thread pool for async execution
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model="gemini-2.5-pro",  # Gemini supports vision and is available via AI Builder API
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analyze this academic figure. Explain what it shows and why it matters."
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    }
                ]
            }
        ],
        temperature=0.2
    )
    return response.choices[0].message.content


async def analyze_table(csv_text: str, table_image_url: str = None) -> str:
    """
    Analyze an academic results table using AI Builder API chat endpoint (async).
    
    Args:
        csv_text: Table data as CSV text
        table_image_url: Optional URL to a table image (if provided, will analyze the image instead)
        
    Returns:
        Analysis text explaining variables, trends, and conclusions
    """
    client = get_ai_client()
    
    # If table image URL is provided, use multimodal analysis
    if table_image_url:
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """You are analyzing an academic results table.

Explain:
1. What variables are shown
2. Key trends
3. Main conclusions

Table data (for reference):
{csv_text}""".format(csv_text=csv_text)
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": table_image_url}
                    }
                ]
            }
        ]
    else:
        # Text-only analysis
        messages = [
            {
                "role": "user",
                "content": """You are analyzing an academic results table.

Explain:
1. What variables are shown
2. Key trends
3. Main conclusions

Table:
{csv_text}""".format(csv_text=csv_text)
            }
        ]
    
    # Run API call in thread pool for async execution
    response = await asyncio.to_thread(
        client.chat.completions.create,
        model="gemini-2.5-pro",  # Using Gemini via AI Builder API
        messages=messages,
        temperature=0.2
    )
    return response.choices[0].message.content

