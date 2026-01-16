"""
Summary Service - Handles paper summary functionality for the Summary tab
Implements the full pipeline architecture:
PDF → GROBID → structured sections → Tables (Camelot/Tabula) → Figures (image extraction)
→ Multimodal GPT analysis → Embeddings → Vector Index → Query-driven retrieval → Final synthesis
"""

import os
import tempfile
import traceback
import logging
import asyncio
import re
import time
import base64
from typing import Optional, List, Dict, Any
from fastapi import HTTPException, APIRouter
from pydantic import BaseModel
import httpx
import markdown


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import from parent utils module (not summary_generator/utils)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from .summary_utils import extract_metadata_from_grobid_api
from utils import file_storage, UPLOAD_DIR
from openreview_service import fetch_and_save_openreview_paper, parse_openreview_info_from_text

# Import from summary_generator modules
from .embeddings import embed_texts, build_rag_index, VectorIndex
from summary_generator.summary_utils import grobid_parse, parse_tei_xml, REVIEW_QUERIES
from .cache import get_pdf_hash, load_cached_index
# SECTION_ANCHOR_QUERIES and DETAIL_SEEKING_QUERIES moved to image_method_generator.py

# Create router for summary endpoints
router = APIRouter(prefix="/api", tags=["summary"])

# Import AI client from parent utils
from utils import get_ai_client
ai_client = get_ai_client()

# Prompt template directory
PROMPT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "prompt_template")


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


class SummaryRequest(BaseModel):
    file_ids: Optional[List[str]] = None
    paper_url: Optional[str] = None
    paper_name: Optional[str] = None
    use_openreview: Optional[bool] = True
    model: Optional[str] = "supermind-agent-v1"
    figure_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"
    table_extraction_method: Optional[str] = "none"  # "none", "ocr", "multimodal"


# ImageGenerationRequest moved to image_method_generator.py


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
    
    # Priority 4: Search by paper name (OpenReview)
    if paper_name and use_openreview:
        # This would require search functionality - for now, raise error
        raise HTTPException(
            status_code=400,
            detail="Paper name search not yet implemented. Please use paper_url or file_ids."
        )
    
    raise HTTPException(
        status_code=400,
        detail="No valid PDF source provided. Please provide file_ids, paper_url, or paper_name."
    )


@router.post("/summary")
async def paper_summary(request: SummaryRequest):
    """
    Paper summary endpoint implementing the full pipeline architecture:
    
    1. PDF → GROBID → structured sections
    2. Tables → Camelot / Tabula (text-first)
    3. Figures → extracted images
    4. Multimodal GPT → figure & table understanding (OPTIONAL, max 3 tables/3 figures)
       - Selection heuristics: mentioned in Abstract/Conclusion, labeled "Main results",
         contains SOTA comparisons or ablations
    5. Embeddings → vector index (RAG) - cached if paper processed before
    6. Query-driven retrieval
    7. Final synthesis
    """
    pdf_path = None
    try:
        logger.info(f"[Step 1] Starting summary request with: file_ids={request.file_ids}, paper_url={request.paper_url}, paper_name={request.paper_name}")
        
        # Step 1: Resolve PDF path from request
        logger.info("[Step 1] Resolving PDF path...")
        try:
            pdf_path = await resolve_pdf_path(
                file_ids=request.file_ids,
                paper_url=request.paper_url,
                paper_name=request.paper_name,
                use_openreview=request.use_openreview
            )
            logger.info(f"[Step 1] PDF path resolved: {pdf_path}")
        except Exception as e:
            logger.error(f"[Step 1] Failed to resolve PDF path: {str(e)}\n{traceback.format_exc()}")
            raise
        
        # Step 2: Check if PDF exists
        logger.info(f"[Step 2] Checking if PDF exists at: {pdf_path}")
        try:
            if not os.path.exists(pdf_path):
                logger.error(f"[Step 2] PDF file not found at path: {pdf_path}")
                raise HTTPException(
                    status_code=404,
                    detail=f"PDF file not found at path: {pdf_path}"
                )
            logger.info(f"[Step 2] PDF exists. File size: {os.path.getsize(pdf_path)} bytes")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[Step 2] Error checking PDF existence: {str(e)}\n{traceback.format_exc()}")
            raise
        
        # Step 3: Build RAG index following the architecture (async optimized)
        logger.info("[Step 3] Building RAG index...")
        try:
            figure_extraction = request.figure_extraction_method or "none"
            table_extraction = request.table_extraction_method or "none"
            logger.info(f"[Step 3] Using figure extraction: {figure_extraction}, table extraction: {table_extraction}")
            index = await build_rag_index(
                pdf_path,
                figure_extraction_method=figure_extraction,
                table_extraction_method=table_extraction
            )
            logger.info(f"[Step 3] RAG index built successfully. Index contains {len(index.texts)} text chunks")
        except Exception as e:
            logger.error(f"[Step 3] Failed to build RAG index: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error building RAG index: {str(e)}\nFull traceback: {traceback.format_exc()}"
            )
        
        # Step 4: Extract paper metadata
        logger.info("[Step 4] Extracting paper metadata...")
        try:
            metadata = extract_metadata_from_grobid_api(pdf_path)
            logger.info(f"[Step 4] Metadata extracted: title={metadata.get('title', 'Unknown')}")
        except Exception as e:
            logger.warning(f"[Step 4] Failed to extract metadata: {str(e)}, using defaults")
            metadata = {
                "title": "Unknown Title",
                "authors": [],
                "year": "N/A",
                "venue": "N/A"
            }
        
        # Step 5: Generate queries based on template and execute multi-query synthesis
        logger.info("[Step 5] Starting multi-query retrieval and synthesis...")
        try:
            model = request.model or "supermind-agent-v1"
            logger.info(f"[Step 5] Using model: {model}")
            
            # Generate queries from template
            queries = REVIEW_QUERIES
            logger.info(f"[Step 5] Generated {len(queries)} queries based on template")
            
            # Execute all queries in parallel
            answers = await synthesize_multiple_queries(index, queries, model=model)
            logger.info(f"[Step 5] Multi-query synthesis completed. Generated {len(answers)} sections")
        except Exception as e:
            logger.error(f"[Step 5] Failed to synthesize answers: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error synthesizing review: {str(e)}\nFull traceback: {traceback.format_exc()}"
            )
        
        # Step 6: Format review as markdown
        logger.info("[Step 6] Formatting review as markdown...")
        try:
            markdown_review = format_review_as_markdown(metadata, answers)
            logger.info(f"[Step 6] Markdown review formatted. Length: {len(markdown_review)} characters")
        except Exception as e:
            logger.error(f"[Step 6] Failed to format review: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(
                status_code=500,
                detail=f"Error formatting review: {str(e)}\nFull traceback: {traceback.format_exc()}"
            )
        
        # Step 7: Render markdown to HTML content
        logger.info("[Step 7] Rendering markdown to HTML...")
        html_content = None
        try:
            html_content = render_markdown_to_html(markdown_review)
            logger.info(f"[Step 7] HTML review rendered ({len(html_content)} chars)")
        except Exception as e:
            logger.error(f"[Step 7] Failed to render HTML: {str(e)}\n{traceback.format_exc()}")
            # Don't fail the request if HTML rendering fails, just log it
            html_content = None
        
        logger.info("[Success] Paper review generation completed successfully")
        return {
            "summary": markdown_review,
            "markdown": markdown_review,
            "html_content": html_content,
            "metadata": metadata,
            "sections": answers,
            "pdf_path": pdf_path
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Unexpected Error] {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=500, 
            detail=f"Error generating summary: {str(e)}\nFull traceback: {traceback.format_exc()}"
        )
    finally:
        # Clean up temporary files if created
        if pdf_path and pdf_path.startswith(tempfile.gettempdir()):
            try:
                logger.info(f"[Cleanup] Removing temporary file: {pdf_path}")
                os.unlink(pdf_path)
            except Exception as e:
                logger.warning(f"[Cleanup] Failed to remove temporary file: {str(e)}")


async def synthesize_answer(index, query: str, model: str = "supermind-agent-v1", section_name: str = None):
    """
    Step 6 & 7: Query-driven retrieval and final synthesis (async optimized)
    
    Args:
        index: VectorIndex built from paper content
        query: Query string for summary generation
        model: Model ID to use for synthesis (default: "supermind-agent-v1")
        section_name: Optional section name to apply format constraints (e.g., "summary")
        
    Returns:
        Generated summary text with format constraints applied
    """
    logger.info(f"[Synthesize] Starting synthesis with query length: {len(query)}")
    
    # Query-driven retrieval (k=8 nearest neighbors)
    logger.info("[Synthesize] Step 6: Creating query embedding...")
    try:
        # Run embedding creation in thread pool
        query_emb = await asyncio.to_thread(embed_texts, [query])
        query_emb = query_emb[0]
        logger.info(f"[Synthesize] Query embedding created. Shape: {query_emb.shape}")
    except Exception as e:
        logger.error(f"[Synthesize] Failed to create query embedding: {str(e)}\n{traceback.format_exc()}")
        raise
    
    logger.info("[Synthesize] Querying index for k=8 nearest neighbors...")
    try:
        # Index query is fast, run in thread pool
        retrieved = await asyncio.to_thread(index.query, query_emb, 8)
        logger.info(f"[Synthesize] Retrieved {len(retrieved)} text chunks")
    except Exception as e:
        logger.error(f"[Synthesize] Failed to query index: {str(e)}\n{traceback.format_exc()}")
        raise

    # Final synthesis using GPT model
    logger.info(f"[Synthesize] Step 7: Calling AI model '{model}' for final synthesis...")
    try:
        retrieved_content = chr(10).join(retrieved)
        logger.info(f"[Synthesize] Retrieved content length: {len(retrieved_content)} characters")
        
        # Build format constraints based on section type
        format_instructions = ""
        if section_name == "summary":
            format_instructions = load_prompt_template("summary_format_instructions")
        else:
            format_instructions = load_prompt_template("section_format_instructions")
        
        # Load prompt templates
        system_prompt = load_prompt_template("paper_analysis_system_prompt")
        user_prompt_template = load_prompt_template("synthesis_user_prompt_template")
        user_prompt = format_prompt_template(
            user_prompt_template,
            query=query,
            retrieved_content=retrieved_content
        )
        
        # Append format instructions to user prompt
        if format_instructions:
            user_prompt = f"{user_prompt}\n\n{format_instructions}"
        
        # Run API call in thread pool for async execution
        response = await asyncio.to_thread(
            ai_client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            temperature=0.2
        )
        summary = response.choices[0].message.content
        logger.info(f"[Synthesize] Summary generated. Length: {len(summary)} characters")
        return summary
    except Exception as e:
        logger.error(f"[Synthesize] Failed to call AI model: {str(e)}\n{traceback.format_exc()}")
        raise


async def synthesize_multiple_queries(
    index, 
    queries: Dict[str, str], 
    model: str = "supermind-agent-v1"
) -> Dict[str, str]:
    """
    Execute multiple queries in parallel and synthesize answers for each.
    
    Args:
        index: VectorIndex built from paper content
        queries: Dictionary mapping section names to query strings
        model: Model ID to use for synthesis
        
    Returns:
        Dictionary mapping section names to generated answers
    """
    logger.info(f"[MultiQuery] Starting synthesis for {len(queries)} queries...")
    
    # Execute all queries in parallel, passing section names for format control
    tasks = [
        synthesize_answer(index, query, model, section_name=section)
        for section, query in queries.items()
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Process results and handle exceptions
    answers = {}
    for (section, query), result in zip(queries.items(), results):
        if isinstance(result, Exception):
            logger.error(f"[MultiQuery] Failed to synthesize {section}: {str(result)}")
            answers[section] = f"Error generating {section}: {str(result)}"
        else:
            answers[section] = result
            logger.info(f"[MultiQuery] Completed {section}. Length: {len(result)} characters")
    
    return answers


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
    
    # Section mapping for anchors
    section_anchors = {
        "summary": "summary",
        "strengths": "strengths",
        "weaknesses": "weaknesses",
        "innovations": "innovations",
        "contributions": "contributions",
        "limitations": "limitations",
        "rating": "rating"
    }
    
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
    import re
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
    import re
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


# Import image generation functionality from separate module
from image_methodos_generator.image_method_generator import ImageGenerationRequest, generate_summary_image


@router.post("/generate-summary-image")
async def generate_summary_image_endpoint(request: ImageGenerationRequest):
    """Generate an image from summary text using AI Builder API 
    
    Steps:
    1. Query RAG index for step-by-step methodology interpretation
    2. Parse retrieved embeddings as context
    3. Generate whiteboard diagram image
    """
    return await generate_summary_image(request)

