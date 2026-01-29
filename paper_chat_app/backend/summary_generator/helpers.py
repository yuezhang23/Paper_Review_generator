"""
Helper functions for summary generation that are not related to LLM calls.
Includes PDF path resolution, formatting, and HTML rendering utilities.
"""

import os
import tempfile
import logging
import re
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
import httpx
import markdown

# Set up logging
logger = logging.getLogger(__name__)

# Import from parent utils module
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import file_storage, web_search_for_paper_pdf
from openreview_service import (
    fetch_and_save_openreview_paper,
    parse_openreview_info_from_text,
    search_openreview_by_title
)

# Prompt template directory
PROMPT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt_template(template_name: str) -> str:
    """
    Load a prompt template from a markdown file.
    
    Args:
        template_name: Name of the template file (without .md extension)
        
    Returns:
        Template content as string
    """
    template_path = os.path.join(PROMPT_TEMPLATE_DIR, f"{template_name}.md")
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error(f"Prompt template not found: {template_path}")
        raise
    except Exception as e:
        logger.error(f"Error loading prompt template {template_name}: {str(e)}")
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


async def resolve_pdf_path(
    file_ids: Optional[List[str]] = None,
    paper_url: Optional[str] = None,
    paper_name: Optional[str] = None,
    use_openreview: bool = None
) -> str:
    """
    Resolve PDF file path from request parameters.
    Downloads/saves PDF if needed and returns local file path.
    
    Returns:
        Path to PDF file on local filesystem
    """
    # Priority 1: Extract from uploaded files
    if file_ids and len(file_ids) > 0:
        # Use uploaded PDFs (now saved to disk during upload)
        for file_id in file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                if file_info.get('content_type') == 'application/pdf' or file_info.get('pdf_path'):
                    pdf_path = file_info.get('pdf_path')
                    if pdf_path and os.path.exists(pdf_path):
                        return pdf_path
                    else:
                        raise HTTPException(
                            status_code=404,
                            detail=f"PDF file {file_id} not found on disk. Please re-upload the file."
                        )
                        
    # Priority 2: Extract from OpenReview URL
    if paper_url and use_openreview and 'openreview.net' in paper_url:
        try:
            parsed_info = parse_openreview_info_from_text(paper_url)
            paper_ids = parsed_info.get('paper_ids', [])
            if paper_ids:
                paper_id = paper_ids[0]
                paper_data = await fetch_and_save_openreview_paper(paper_id)
                if paper_data and paper_data.get('pdf_path'):
                    return paper_data['pdf_path']
        except Exception as e:
            raise HTTPException(
                status_code=400, 
                detail=f"Error fetching paper from OpenReview: {str(e)}"
            )
    
    # Priority 3: Download from URL
    if paper_url:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(paper_url, follow_redirects=True)
                if response.status_code == 200 and 'pdf' in response.headers.get('content-type', ''):
                    # Save to temporary file
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                        tmp_file.write(response.content)
                        return tmp_file.name
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error downloading PDF from URL: {str(e)}"
            )

    # Priority 5: Paper name with OpenReview disabled — web search only
    if paper_name:
        try:
            pdf_url = await web_search_for_paper_pdf(paper_name)
            if pdf_url:
                async with httpx.AsyncClient() as client:
                    response = await client.get(pdf_url, follow_redirects=True)
                    if response.status_code != 200:
                        raise ValueError(f"HTTP {response.status_code}")
                    ctype = (response.headers.get("content-type") or "").lower()
                    is_pdf = "pdf" in ctype or pdf_url.lower().endswith(".pdf")
                    if not is_pdf and len(response.content) >= 5:
                        is_pdf = response.content[:5] == b"%PDF-"
                    if is_pdf:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                            tmp.write(response.content)
                            path = tmp.name
                        logger.info(f"[Resolve PDF] PDF path resolved from web search: {path}")
                        return path
        except Exception as e:
            logger.warning(f"[Resolve PDF] Web search for paper name failed: {e}")
        raise HTTPException(
            status_code=404,
            detail=f"No PDF found for paper '{paper_name}' via web search."
        )
    
    raise HTTPException(
        status_code=400,
        detail="No valid PDF source provided. Please provide file_ids, paper_url, or paper_name."
    )


def format_review_as_markdown(
    metadata: Dict[str, Any],
    answers: Dict[str, str]
) -> str:
    """
    Format the review answers into a structured markdown document following the template.
    Adds section anchors for navigation.
    
    Args:
        metadata: Dictionary with title, authors, year, venue
        answers: Dictionary mapping section names to answers
        
    Returns:
        Formatted markdown string with section anchors
    """
    # Format authors list
    authors_str = ", ".join(metadata.get("authors", [])) if metadata.get("authors") else "N/A"
    
    markdown = f"""# Paper Review

        ## Paper Intro

        **Title:** {metadata.get("title", "Unknown Title")}

        **Authors:** {authors_str}

        **Year:** {metadata.get("year", "N/A")}

        **Conference:** {metadata.get("venue", "N/A")}

        ## Summary

        {answers.get("summary", "No summary available.")}

        ## Strengths

        {answers.get("strengths", "No strengths analysis available.")}

        ## Weaknesses

        {answers.get("weaknesses", "No weaknesses analysis available.")}

        ## Innovations or Novelty

        {answers.get("innovations", "No innovations analysis available.")}

        ## Contributions

        {answers.get("contributions", "No contributions analysis available.")}

        ## Limitations or Questions or Ambiguities

        {answers.get("limitations", "No limitations analysis available.")}

        ## Rating Score

        {answers.get("rating", "No rating available.")}

        ---
        *This review was automatically generated using an AI-powered paper analysis system.*
    """
    return markdown


def render_markdown_to_html(markdown_content: str) -> str:
    """
    Render markdown content to HTML body content (without full document structure).
    CSS styling is handled by the frontend.
    
    Args:
        markdown_content: Markdown string to render
        
    Returns:
        HTML body content as string (ready for frontend rendering)
    """
    # Convert markdown to HTML (with fallback if extensions are not available)
    extensions = ['extra', 'tables', 'fenced_code']
    # Only add codehilite if pygments is available
    try:
        import pygments
        extensions.append('codehilite')
    except ImportError:
        logger.debug("[HTML] Pygments not available, skipping codehilite extension")
    
    try:
        html_content = markdown.markdown(
            markdown_content,
            extensions=extensions
        )
    except Exception as e:
        logger.warning(f"[HTML] Markdown extensions failed, using basic conversion: {str(e)}")
        html_content = markdown.markdown(markdown_content)
    
    # Add anchors to section headings for navigation
    def add_anchor_to_heading(match):
        heading_text = match.group(2)
        heading_level = match.group(1)
        heading_id = re.sub(r'[^\w\s-]', '', heading_text.lower()).strip().replace(' ', '-').replace('--', '-')
        return f'<h{heading_level} id="{heading_id}">{heading_text}</h{heading_level}>'
    
    html_content = re.sub(r'<h([1-6])>(.*?)</h\1>', add_anchor_to_heading, html_content)
    
    logger.info(f"[HTML] Rendered markdown to HTML content ({len(html_content)} chars)")
    return html_content


def create_split_screen_view(
    pdf_path: str,
    markdown_review: str,
    output_path: str,
    metadata: Dict[str, Any]
) -> str:
    """
    Create a split-screen HTML view with PDF on the left and summary on the right.
    Each summary section can highlight corresponding sections in the original paper.
    
    Args:
        pdf_path: Path to the original PDF file
        markdown_review: Markdown content of the review
        output_path: Path where HTML file should be saved
        metadata: Paper metadata dictionary
        
    Returns:
        Path to the generated split-screen HTML file
    """
    # Convert markdown to HTML
    extensions = ['extra', 'tables', 'fenced_code']
    try:
        import pygments
        extensions.append('codehilite')
    except ImportError:
        pass
    
    try:
        html_content = markdown.markdown(markdown_review, extensions=extensions)
    except Exception as e:
        html_content = markdown.markdown(markdown_review)
    
    # Add anchors to headings
    def add_anchor_to_heading(match):
        heading_text = match.group(2)
        heading_level = match.group(1)
        heading_id = re.sub(r'[^\w\s-]', '', heading_text.lower()).strip().replace(' ', '-').replace('--', '-')
        return f'<h{heading_level} id="{heading_id}" class="review-section">{heading_text}</h{heading_level}>'
    
    html_content = re.sub(r'<h([1-6])>(.*?)</h\1>', add_anchor_to_heading, html_content)
    
    # Get PDF filename for embedding
    pdf_filename = os.path.basename(pdf_path)
    # Use a placeholder or API endpoint for PDF serving
    # In production, this should be served via a backend endpoint
    pdf_url = f"file://{pdf_path}"  # For local development, use file:// protocol
    # Alternative: pdf_url = f"/api/files/{pdf_filename}"  # If served by backend
    
    # Create split-screen HTML
    split_html = f"""<!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Paper Review - Split View</title>
        <style>
            * {{
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }}
            
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                height: 100vh;
                overflow: hidden;
                background-color: #f5f5f5;
            }}
            
            .top-nav {{
                position: fixed;
                top: 0;
                right: 0;
                z-index: 1000;
                background-color: #ffffff;
                padding: 10px 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                border-bottom-left-radius: 8px;
            }}
            
            .nav-button {{
                background-color: #3498db;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                margin-left: 10px;
            }}
            
            .nav-button:hover {{
                background-color: #2980b9;
            }}
            
            .split-container {{
                display: flex;
                height: 100vh;
                padding-top: 60px;
            }}
            
            .left-panel {{
                width: 50%;
                height: calc(100vh - 60px);
                border-right: 2px solid #ddd;
                background-color: #ffffff;
                overflow: hidden;
                position: relative;
            }}
            
            .right-panel {{
                width: 50%;
                height: calc(100vh - 60px);
                overflow-y: auto;
                background-color: #ffffff;
                padding: 20px 40px;
            }}
            
            .pdf-viewer {{
                width: 100%;
                height: 100%;
                border: none;
            }}
            
            .pdf-placeholder {{
                display: flex;
                align-items: center;
                justify-content: center;
                height: 100%;
                color: #666;
                flex-direction: column;
                padding: 40px;
                text-align: center;
            }}
            
            .pdf-placeholder h3 {{
                margin-bottom: 20px;
                color: #333;
            }}
            
            .section-navigation {{
                position: sticky;
                top: 0;
                background-color: #ffffff;
                padding: 15px 0;
                border-bottom: 1px solid #e0e0e0;
                margin-bottom: 20px;
                z-index: 10;
            }}
            
            .section-nav-list {{
                list-style: none;
                display: flex;
                flex-wrap: wrap;
                gap: 10px;
            }}
            
            .section-nav-item {{
                background-color: #f0f0f0;
                padding: 6px 12px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 13px;
                transition: background-color 0.2s;
            }}
            
            .section-nav-item:hover {{
                background-color: #e0e0e0;
            }}
            
            .review-section {{
                scroll-margin-top: 100px;
            }}
            
            .review-section:target {{
                background-color: #fff3cd;
                padding: 10px;
                border-left: 4px solid #ffc107;
                margin-left: -14px;
                padding-left: 18px;
                transition: all 0.3s ease;
            }}
            
            h1 {{
                color: #1a1a1a;
                border-bottom: 3px solid #333;
                padding-bottom: 10px;
                margin-bottom: 30px;
            }}
            
            h2 {{
                color: #2c3e50;
                margin-top: 30px;
                border-bottom: 2px solid #e0e0e0;
                padding-bottom: 8px;
            }}
            
            h3 {{
                color: #34495e;
                margin-top: 25px;
            }}
            
            .right-panel {{
                line-height: 1.6;
                color: #333333;
            }}
            
            code {{
                background-color: #f4f4f4;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
            }}
            
            pre {{
                background-color: #f8f8f8;
                padding: 15px;
                border-radius: 5px;
                overflow-x: auto;
                border-left: 4px solid #3498db;
            }}
            
            table {{
                border-collapse: collapse;
                width: 100%;
                margin: 20px 0;
            }}
            
            th, td {{
                border: 1px solid #ddd;
                padding: 12px;
                text-align: left;
            }}
            
            th {{
                background-color: #f2f2f2;
                font-weight: bold;
            }}
            
            @media (max-width: 768px) {{
                .split-container {{
                    flex-direction: column;
                }}
                
                .left-panel, .right-panel {{
                    width: 100%;
                    height: 50vh;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="top-nav">
            <button class="nav-button" onclick="window.open(window.location.href.replace('_split_view.html', '_review.html'), '_blank')">View Full Review</button>
            <button class="nav-button" onclick="window.print()">Print Review</button>
        </div>
        
        <div class="split-container">
            <div class="left-panel">
                <iframe src="{pdf_url}" class="pdf-viewer" type="application/pdf">
                    <div class="pdf-placeholder">
                        <h3>PDF Viewer</h3>
                        <p>PDF file: {pdf_filename}</p>
                        <p><small>Note: PDF viewing requires browser PDF support or a PDF.js viewer.</small></p>
                    </div>
                </iframe>
            </div>
            
            <div class="right-panel">
                <div class="section-navigation">
                    <ul class="section-nav-list">
                        <li class="section-nav-item" onclick="scrollToSection('summary')">Summary</li>
                        <li class="section-nav-item" onclick="scrollToSection('strengths')">Strengths</li>
                        <li class="section-nav-item" onclick="scrollToSection('weaknesses')">Weaknesses</li>
                        <li class="section-nav-item" onclick="scrollToSection('innovations')">Innovations</li>
                        <li class="section-nav-item" onclick="scrollToSection('contributions')">Contributions</li>
                        <li class="section-nav-item" onclick="scrollToSection('limitations')">Limitations</li>
                        <li class="section-nav-item" onclick="scrollToSection('rating')">Rating</li>
                    </ul>
                </div>
                {html_content}
            </div>
        </div>
        
        <script>
            function scrollToSection(sectionId) {{
                const element = document.getElementById(sectionId);
                if (element) {{
                    element.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    // Update URL hash
                    window.location.hash = sectionId;
                    // Highlight the section
                    element.style.transition = 'background-color 0.3s';
                    setTimeout(() => {{
                        element.style.backgroundColor = '';
                    }}, 2000);
                }}
            }}
            
            // Handle hash changes on page load
            window.addEventListener('load', () => {{
                if (window.location.hash) {{
                    const sectionId = window.location.hash.substring(1);
                    setTimeout(() => scrollToSection(sectionId), 100);
                }}
            }});
        </script>
    </body>
    </html>"""
    
    # Save split-screen HTML file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(split_html)
    
    logger.info(f"[SplitView] Created split-screen view: {output_path}")
    return output_path
