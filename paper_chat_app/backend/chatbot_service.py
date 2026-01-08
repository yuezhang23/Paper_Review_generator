"""
Chatbot Service - Handles chatbot functionality for the Chat tab
"""

import json
import re
import asyncio
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException, APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openreview_service import (
    parse_openreview_info_from_text,
    fetch_and_save_openreview_paper,
    get_meta_reviews_for_single_paper
)
from shared_utils import (
    get_ai_client,
    predict_search_benefit_score,
    web_search_paper,
    find_related_documents_ai_builder
)
from utils import (
    file_storage,
    load_prompt_template,
    PAPER_ANALYSIS_SYSTEM_PROMPT,
    PAPER_SUMMARY_TEMPLATE,
    PLAGIARISM_ANALYSIS_TEMPLATE,
    format_search_results_for_context
)
from content_extraction import find_best_matching_paper
from summary_logs.summary_logger import log_paper_summary_if_needed

# Create router for chatbot endpoints
router = APIRouter(prefix="/api", tags=["chatbot"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = "grok-4-fast"
    paper_id: Optional[str] = None
    paper_context: Optional[Dict[str, Any]] = None
    use_openreview: Optional[bool] = False
    file_ids: Optional[List[str]] = None
    mode: Optional[str] = "chat"  # "summary", "plagiarism", or "chat" - determines which prompt template to use


class MultiModelChatRequest(BaseModel):
    messages: List[ChatMessage]
    models: List[str]  # List of model IDs to use
    paper_id: Optional[str] = None
    paper_context: Optional[Dict[str, Any]] = None


def build_messages(request: ChatRequest, openreview_papers: List[Dict[str, Any]] = None, downloaded_papers: List[Dict[str, Any]] = None, web_search_results: Optional[Dict[str, Any]] = None, is_summary_query: bool = False) -> List[Dict[str, Any]]:
    """Build messages list with system prompt and paper context
    
    Args:
        request: ChatRequest with mode field indicating which tab is being used
        openreview_papers: List of papers from OpenReview
        downloaded_papers: List of downloaded papers with full content
        web_search_results: Web search results
        is_summary_query: Legacy parameter for backward compatibility
    
    Returns:
        List of message dictionaries with appropriate prompt templates
    """
    messages = []
    
    # Determine mode from request or fallback to is_summary_query for backward compatibility
    mode = request.mode or ("summary" if is_summary_query else "chat")
    
    # Add system prompt based on mode/tab
    if mode == "summary":
        # Summary tab: Use summary template
        messages.append({
            "role": "system",
            "content": PAPER_SUMMARY_TEMPLATE
        })
    elif mode == "plagiarism":
        # Plagiarism tab: Use plagiarism analysis template
        messages.append({
            "role": "system",
            "content": PLAGIARISM_ANALYSIS_TEMPLATE
        })
    else:
        # Chat tab (default): Use general paper analysis prompt
        messages.append({
            "role": "system",
            "content": PAPER_ANALYSIS_SYSTEM_PROMPT
        })
    
    # Legacy support: If is_summary_query is True but mode is not set, add summary template
    if is_summary_query and mode != "summary":
        messages.append({
            "role": "system",
            "content": PAPER_SUMMARY_TEMPLATE
        })
    
    # Add web search results if available (before other context)
    if web_search_results and web_search_results.get("results"):
        search_context = format_search_results_for_context(web_search_results)
        if search_context:
            messages.append({
                "role": "system",
                "content": search_context
            })
    
    # Add uploaded files context if available
    if request.file_ids and len(request.file_ids) > 0:
        files_context = "=== UPLOADED FILES ===\n\n"
        for file_id in request.file_ids:
            if file_id in file_storage:
                file_info = file_storage[file_id]
                files_context += f"File: {file_info['filename']}\n"
                files_context += f"Size: {file_info['size']} bytes\n"
                files_context += f"Content Type: {file_info['content_type']}\n"
                files_context += f"Extracted Text:\n{file_info['text_content'][:5000]}\n"  # Limit to first 5000 chars
                if len(file_info['text_content']) > 5000:
                    files_context += "... (truncated)\n"
                files_context += "\n"
        
        files_context += "\nUse the information from these uploaded files to answer questions. Reference specific files when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": files_context
        })
    
    # Add downloaded OpenReview papers with full PDF text and reviews (priority)
    if downloaded_papers and len(downloaded_papers) > 0:
        context_text = "=== OPENREVIEW PAPERS (DOWNLOADED AND PROCESSED) ===\n\n"
        for i, paper in enumerate(downloaded_papers, 1):
            context_text += f"Paper {i}:\n"
            context_text += f"Title: {paper.get('title', 'N/A')}\n"
            context_text += f"Paper ID: {paper.get('paper_id', 'N/A')}\n"
            context_text += f"Authors: {', '.join(paper.get('authors', []))}\n"
            context_text += f"Venue: {paper.get('venue', 'N/A')}\n"
            context_text += f"Abstract: {paper.get('abstract', 'N/A')[:500]}...\n\n"
            
            # Add full PDF text if available
            if paper.get('pdf_text'):
                pdf_text = paper['pdf_text']
                # Limit PDF text to avoid token limits (keep first 10000 chars)
                if len(pdf_text) > 10000:
                    context_text += f"PDF Content (first 10000 characters):\n{pdf_text[:10000]}...\n\n"
                else:
                    context_text += f"PDF Content:\n{pdf_text}\n\n"
            
            # Add reviews if available
            if paper.get('reviews_text'):
                context_text += f"Reviews:\n{paper['reviews_text']}\n"
            elif paper.get('reviews'):
                context_text += f"Reviews ({len(paper['reviews'])}):\n"
                for j, review in enumerate(paper['reviews'], 1):
                    context_text += f"  Review {j} (Rating: {review.get('rating', 'N/A')}):\n"
                    context_text += f"  {review.get('summary', '')[:500]}...\n\n"
            
            context_text += "\n" + "="*50 + "\n\n"
        
        context_text += "\nUse the FULL CONTENT from these downloaded papers (including PDF text and reviews) to provide accurate, detailed, and comprehensive answers. Reference specific sections, findings, and reviews when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add OpenReview retrieved papers if available (fallback, metadata only)
    if openreview_papers and len(openreview_papers) > 0:
        context_text = "=== RETRIEVED PAPERS FROM OPENREVIEW (METADATA) ===\n\n"
        for i, paper in enumerate(openreview_papers, 1):
            context_text += f"Paper {i}:\n"
            context_text += f"Title: {paper.get('title', 'N/A')}\n"
            context_text += f"Authors: {', '.join(paper.get('authors', []))}\n"
            context_text += f"Abstract: {paper.get('abstract', 'N/A')[:500]}...\n"
            context_text += f"Venue: {paper.get('venue', 'N/A')}\n"
            if paper.get('pdf_url'):
                context_text += f"PDF Link: {paper.get('pdf_url')}\n"
            if paper.get('review_url'):
                context_text += f"Review Page: {paper.get('review_url')}\n"
            if paper.get('reviews'):
                context_text += f"Reviews ({len(paper['reviews'])}):\n"
                for j, review in enumerate(paper['reviews'], 1):
                    context_text += f"  Review {j}: {review.get('summary', '')[:300]}...\n"
            context_text += "\n"
        
        context_text += "\nUse the information from these retrieved papers to provide accurate and comprehensive answers. Reference specific papers when relevant.\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add paper context if available
    if request.paper_context:
        context_text = f"""Paper Context:Title: {request.paper_context.get('title', 'N/A')}
        Authors: {', '.join(request.paper_context.get('authors', []))}
        Abstract: {request.paper_context.get('abstract', 'N/A')}
        Venue: {request.paper_context.get('venue', 'N/A')}
        """
        if request.paper_context.get('reviews'):
            context_text += f"Official Reviews ({len(request.paper_context['reviews'])}):\n"
            for i, review in enumerate(request.paper_context['reviews'][:3], 1):
                review_content = review.get('content', {})
                if isinstance(review_content, dict):
                    summary = review_content.get('summary', {}).get('value', '') if isinstance(review_content.get('summary'), dict) else str(review_content.get('summary', ''))
                    context_text += f"Review {i}: {summary[:200]}...\n"
        
        messages.append({
            "role": "system",
            "content": context_text
        })
    
    # Add conversation messages
    for msg in request.messages:
        messages.append({
            "role": msg.role,
            "content": msg.content
        })
    
    return messages


async def check_query_clarity(query: str, paper_context_available: bool, model: str = "grok-4-fast") -> Tuple[bool, Optional[str]]:
    """Check if the query is clear enough to proceed, or if clarification is needed.
    
    Args:
        query: The user's query
        paper_context_available: Whether paper context is available
        model: Model to use for checking
    
    Returns:
        tuple: (is_clear: bool, clarification_question: Optional[str])
        If is_clear is False, clarification_question contains the question to ask the user
    """
    try:
        ai_client = get_ai_client()
        
        context_note = "Paper context is available." if paper_context_available else "No paper context is currently available."
        
        # Load clarity check template and format it
        clarity_template = load_prompt_template("query_clarity_check_template.md")
        clarity_prompt = clarity_template.format(context_note=context_note, query=query)

        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that evaluates query clarity. Always respond with valid JSON only."},
                {"role": "user", "content": clarity_prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        result_text = response.choices[0].message.content.strip()
        
        try:
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]
                result_text = result_text.strip()
            
            result = json.loads(result_text)
            is_clear = result.get("is_clear", True)
            clarification_question = result.get("clarification_question")
            
            print(f"[Query Clarity] is_clear: {is_clear}, clarification: {clarification_question}")
            return is_clear, clarification_question
        except json.JSONDecodeError:
            print(f"[Query Clarity] Failed to parse response, assuming query is clear")
            return True, None
    except Exception as e:
        print(f"[Query Clarity] Error: {str(e)}, assuming query is clear")
        return True, None


def is_summary_query(query: str) -> bool:
    """Check if the query is asking for a paper summary/analysis."""
    query_lower = query.lower()
    summary_keywords = [
        'summarize', 'summary', 'overview', 'tell me about', 'what is this paper',
        'analyze', 'analysis', 'explain this paper', 'describe', 'what are', 'how does',
        'review', 'evaluate', 'assess', 'critique', 'rate', 'rating', 'score'
    ]
    return any(keyword in query_lower for keyword in summary_keywords)


async def summarize_meta_reviews(meta_reviews_data: Dict[str, Any], model: str = "grok-4-fast") -> str:
    """Summarize meta reviews from OpenReview for a paper.
    
    Args:
        meta_reviews_data: Dictionary from get_meta_reviews_for_single_paper with paper_id, metareviews, and decision
        model: Model to use for summarization
    
    Returns:
        Summarized text of all meta reviews
    """
    try:
        metareviews = meta_reviews_data.get('metareviews', [])
        decision = meta_reviews_data.get('decision', '')
        
        if not metareviews:
            return "No meta reviews available for this paper."
        
        # Build summary text from meta reviews
        summary_parts = [f"=== META REVIEWS SUMMARY ===\n"]
        summary_parts.append(f"Total Reviews: {len(metareviews)}\n")
        
        if decision:
            summary_parts.append(f"Decision: {decision}\n\n")
        
        for i, review in enumerate(metareviews, 1):
            values = review.get('values', [])
            rebuttal = review.get('rebuttal', '')
            
            summary_parts.append(f"--- Review {i} ---\n")
            
            # Extract fields (same order as fields list: summary, soundness, presentation, contribution, strengths, weaknesses, questions, limitations, rating, confidence)
            if len(values) > 0 and values[0] and values[0] != 'not_provided':
                summary_parts.append(f"Summary: {values[0]}\n")
            if len(values) > 4 and values[4] and values[4] != 'not_provided':
                summary_parts.append(f"Strengths: {values[4]}\n")
            if len(values) > 5 and values[5] and values[5] != 'not_provided':
                summary_parts.append(f"Weaknesses: {values[5]}\n")
            if len(values) > 7 and values[7] and values[7] != 'not_provided':
                summary_parts.append(f"Limitations: {values[7]}\n")
            if len(values) > 8 and values[8] and values[8] != 'not_provided':
                summary_parts.append(f"Rating: {values[8]}\n")
            if len(values) > 9 and values[9] and values[9] != 'not_provided':
                summary_parts.append(f"Confidence: {values[9]}\n")
            
            if rebuttal:
                summary_parts.append(f"Rebuttal/Comments: {rebuttal[:500]}...\n" if len(rebuttal) > 500 else f"Rebuttal/Comments: {rebuttal}\n")
            
            summary_parts.append("\n")
        
        return "\n".join(summary_parts)
    except Exception as e:
        print(f"[Meta Reviews Summary] Error summarizing reviews: {str(e)}")
        return "Error summarizing meta reviews."


async def verify_and_rephrase_paper_query(query: str, model: str = "grok-4-fast") -> Tuple[bool, str]:
    """Verify if the query is about a paper and rephrase it to better capture the intention.
    
    Returns:
        tuple: (is_about_paper: bool, rephrased_query: str)
    """
    try:
        ai_client = get_ai_client()
        
        # Load verification template and format it
        verification_template = load_prompt_template("paper_query_verification_template.md")
        verification_prompt = verification_template.format(query=query)

        response = ai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that analyzes queries to determine if they are about academic papers. You MUST respond with ONLY valid JSON, no additional text, no explanations. The response must be a JSON object with exactly two fields: 'is_about_paper' (boolean) and 'rephrased_query' (string)."},
                {"role": "user", "content": verification_prompt}
            ],
            temperature=0.3,
            max_tokens=200
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Debug: log the raw response
        print(f"[OpenReview] Raw verification response: {result_text[:200]}...")
        
        # Try to parse JSON response
        try:
            # Remove markdown code blocks if present
            if result_text.startswith("```"):
                parts = result_text.split("```")
                if len(parts) >= 2:
                    result_text = parts[1]
                    if result_text.startswith("json"):
                        result_text = result_text[4:]
                    result_text = result_text.strip()
            
            # Try to find JSON object in the response (in case there's extra text)
            json_match = re.search(r'\{[^{}]*"is_about_paper"[^{}]*\}', result_text)
            if json_match:
                result_text = json_match.group(0)
            
            # Try to parse JSON
            result = json.loads(result_text)
            
            # Validate that result is a dictionary
            if not isinstance(result, dict):
                print(f"[OpenReview] Response is not a JSON object, got: {type(result)}, value: {result}")
                return False, query
            
            # Extract values with proper type checking
            is_about_paper = result.get("is_about_paper", False)
            rephrased_query = result.get("rephrased_query", query)
            
            # Ensure boolean type
            if isinstance(is_about_paper, str):
                is_about_paper = is_about_paper.lower() in ("true", "1", "yes")
            elif not isinstance(is_about_paper, bool):
                is_about_paper = bool(is_about_paper)
            
            # Ensure string type for rephrased_query
            if not isinstance(rephrased_query, str):
                rephrased_query = str(rephrased_query) if rephrased_query else query
            
            print(f"[OpenReview] Query verification - is_about_paper: {is_about_paper}, rephrased: {rephrased_query[:100]}...")
            return is_about_paper, rephrased_query
            
        except json.JSONDecodeError as json_err:
            print(f"[OpenReview] JSON decode error: {str(json_err)}")
            print(f"[OpenReview] Failed to parse verification response: {result_text[:200]}...")
            print(f"[OpenReview] Defaulting to NOT paper-related (will use prediction score)")
            # If JSON parsing fails, default to False (not paper-related) so prediction score can be used
            return False, query
    except Exception as e:
        print(f"[OpenReview] Error in query verification: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"[OpenReview] Traceback: {traceback.format_exc()}")
        print(f"[OpenReview] Defaulting to NOT paper-related (will use prediction score)")
        # On error, default to False (not paper-related) so prediction score can be used instead
        return False, query


@router.post("/chat")
async def chat(request: ChatRequest):
    """Chat endpoint with paper context and optional OpenReview integration.
    
    Flow:
    1. Verify if query is about a paper and rephrase if needed
    2. Determine if we should use real-time search based on query
    3. If query is related to paper and openreview is on, retrieve and summarize reviews
    4. Build full message context (system prompt + paper context + conversation history)
    5. Let the model generate response (model will naturally ask clarifying questions if needed)
    
    Note: Clarifications are handled naturally by the model after full context is built,
    allowing for context-aware questions based on conversation history.
    """
    try:
        model = request.model or "grok-4-fast"
        
        # Extract query from the last user message
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message found")
        
        original_query = user_messages[-1].content
        # ============================================================================
        # STEP 1: Verify if query is about a paper and rephrase if needed
        # ============================================================================
        print(f"[Step 1] Verifying if query is about a paper: {original_query[:100]}...")
        is_about_paper, clear_query = await verify_and_rephrase_paper_query(
            original_query,
            model=model
        )
        print(f"[Step 1] is_about_paper: {is_about_paper}, rephrased_query: {clear_query[:100]}...")

        # ============================================================================
        # STEP 2: Determine if we should use real-time search
        # ============================================================================
        print(f"[Step 2] Determining if real-time search should be used for: {clear_query[:100]}...")
        
        should_use_web_search = False
        prediction_score = 0.0
        if is_about_paper:
            # Paper-related questions always enable real-time search (skip prediction)
            should_use_web_search = True
            print(f"[Step 2] Query is paper-related, enabling web search")
        else:
            # Non-paper queries: use prediction score
            prediction_score = predict_search_benefit_score(clear_query)
            should_use_web_search = prediction_score >= 0.3
            print(f"[Step 2] Prediction score: {prediction_score:.3f}, {'ENABLED' if should_use_web_search else 'DISABLED'} (threshold: 0.3)")
        
        # Perform web search if needed
        web_search_results = None
        best_matching_paper = None
        related_documents = []
        web_search_actually_used = False
        
        if should_use_web_search:
            print(f"[Step 2] Performing web search for query: {clear_query[:100]}...")
            try:
                web_search_results = await web_search_paper(
                    clear_query,
                    limit=10,
                    use_academic_focus=True
                )                  
                if web_search_results.get("results"):
                    web_search_actually_used = True
                    print(f"[Step 2] Found {web_search_results.get('count', 0)} web search results")
                    # Find the best matching paper from search results
                    best_matching_paper = find_best_matching_paper(clear_query, web_search_results.get("results", []))
                    if best_matching_paper:
                        print(f"[Step 2] Best match: {best_matching_paper.get('title', 'N/A')[:60]}...")
                        # Find related documents
                        try:
                            related_documents = await find_related_documents_ai_builder(best_matching_paper, num_related=5)
                            print(f"[Step 3] Found {len(related_documents)} related documents")
                        except Exception as e:
                            print(f"[Step 3] Error finding related documents: {str(e)}")
                            related_documents = []
            except Exception as e:
                print(f"[Step 3] Error during web search: {str(e)}")
                web_search_results = None
        
        # ============================================================================
        # STEP 4: If query is related to paper and openreview is on, retrieve and summarize reviews
        # ============================================================================
        openreview_papers = []
        downloaded_papers = []
        meta_reviews_summary = ""  # Will contain summarized meta reviews
        
        if is_about_paper and request.use_openreview and best_matching_paper:
            print(f"[Step 4] Query is about a paper and OpenReview is enabled")
            
            # Check if best_matching_paper is from OpenReview
            paper_url = best_matching_paper.get('link') or best_matching_paper.get('url', '')
            if 'openreview.net' in paper_url:
                print(f"[Step 4] Best matching paper is from OpenReview: {paper_url}")
                
                # Extract paper ID from URL
                parsed_info = parse_openreview_info_from_text(paper_url)
                paper_ids = parsed_info['paper_ids']
                
                if paper_ids:
                    paper_id = paper_ids[0]  # Use the first paper ID found
                    print(f"[Step 4] Extracted paper ID: {paper_id}")
                    
                    # Download paper PDF and metadata
                    paper_data = await fetch_and_save_openreview_paper(paper_id)
                    if paper_data:
                        downloaded_papers.append(paper_data)
                        print(f"[Step 4] Successfully downloaded paper: {paper_data.get('title', paper_id)}")
                        
                        # Download meta reviews CSV and summarize
                        try:
                            meta_reviews_data = get_meta_reviews_for_single_paper(paper_id)
                            if meta_reviews_data.get('metareviews'):
                                meta_reviews_summary = await summarize_meta_reviews(meta_reviews_data, model=model)
                                print(f"[Step 4] Retrieved {len(meta_reviews_data.get('metareviews', []))} meta reviews for paper {paper_id}")
                            else:
                                print(f"[Step 4] No meta reviews found for paper {paper_id}")
                        except Exception as e:
                            print(f"[Step 4] Error retrieving meta reviews for {paper_id}: {str(e)}")
                    else:
                        print(f"[Step 4] Failed to download paper by openreview id {paper_id}")
                else:
                    print(f"[Step 4] Could not extract paper ID from openreview URL: {paper_url}")
            else:
                print(f"[Step 4] Best matching paper is not from OpenReview: {paper_url}")
        else:
            if not is_about_paper:
                print(f"[Step 4] Query is not about a paper, skipping OpenReview")
            else:
                print(f"[Step 4] No best matching paper found, skipping OpenReview")
        
        openreview_has_results = len(downloaded_papers) > 0 or len(openreview_papers) > 0
        
        # Check if this is a summary query (for backward compatibility)
        is_summary = is_summary_query(clear_query)
        print(f"[Summary Detection] Is summary query: {is_summary}")
        
        # Determine mode from request, or infer from query if not provided
        if not request.mode:
            # Auto-detect mode based on query if not explicitly set
            if is_summary:
                request.mode = "summary"
            else:
                request.mode = "chat"  # Default to chat mode
        
        # Build messages with OpenReview context, meta reviews summary, and web search results
        messages = build_messages(request, openreview_papers, downloaded_papers, web_search_results, is_summary_query=is_summary)
        
        # Add meta reviews summary as additional context if available
        if meta_reviews_summary:
            messages.insert(-len(request.messages), {  # Insert before user messages
                "role": "system",
                "content": f"=== OPENREVIEW META REVIEWS SUMMARY ===\n\n{meta_reviews_summary}\n\nUse this comprehensive summary of all meta reviews to provide detailed insights about the paper's evaluation, strengths, weaknesses, and reviewer feedback."
            })
            print(f"[Context] Added meta reviews summary to prompt")
        
        # Add best matching paper context if available
        if best_matching_paper and not openreview_has_results:
            best_match_context = f"""=== BEST MATCHING PAPER FROM WEB SEARCH ===
Title: {best_matching_paper.get('title', 'N/A')}
URL: {best_matching_paper.get('link') or best_matching_paper.get('url', 'N/A')}
Summary: {best_matching_paper.get('snippet') or best_matching_paper.get('content', 'N/A')}
Source: AI Builder Web Search

This paper was identified as the best match for your query. Please use this information to provide accurate answers.
"""
            messages.insert(-len(request.messages), {  # Insert before user messages
                "role": "system",
                "content": best_match_context
            })
        
        # Call AI Builder API with selected model
        ai_client = get_ai_client()
        
        # Special handling for GPT-5 (temperature must be 1.0)
        temperature = 1.0 if model == "gpt-5" else 0.7
        
        response = ai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=2000,
            stream=False
        )
        
        # Extract analysis response
        analysis_response = response.choices[0].message.content
        
        # Log paper summary if this is a summary query and we have paper context
        log_paper_summary_if_needed(
            is_summary=is_summary,
            downloaded_papers=downloaded_papers,
            openreview_papers=openreview_papers,
            best_matching_paper=best_matching_paper,
            messages=messages,
            analysis_response=analysis_response
        )
        
        # Collect all document links from different sources
        document_links = []
        seen_urls = set()  # Track seen URLs to avoid duplicates
        
        # Add OpenReview links if OpenReview API was actually used
        if openreview_has_results and openreview_papers:
            for paper in openreview_papers:
                pdf_url = paper.get('pdf_url')
                if pdf_url and isinstance(pdf_url, str) and pdf_url.strip() and pdf_url not in seen_urls:
                    seen_urls.add(pdf_url)
                    review_url = paper.get('review_url')
                    document_links.append({
                        "title": paper.get('title', 'Paper') or 'Paper',
                        "url": pdf_url,
                        "review_url": review_url if (review_url and isinstance(review_url, str) and review_url.strip()) else None,
                        "source": "openreview"
                    })
        
        # Add web search links if web search API was actually used
        if web_search_actually_used and web_search_results and web_search_results.get("results"):
            # Add best matching paper first
            if best_matching_paper:
                url = best_matching_paper.get("link") or best_matching_paper.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    document_links.append({
                        "title": best_matching_paper.get("title", "Best Match"),
                        "url": url,
                        "snippet": best_matching_paper.get("snippet") or best_matching_paper.get("content", ""),
                        "source": "web_search",
                        "is_best_match": True
                    })
            
            # Add related documents (similar to OpenReview's related papers)
            if related_documents:
                for related_doc in related_documents:
                    url = related_doc.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        document_links.append({
                            "title": related_doc.get("title", ""),
                            "url": url,
                            "snippet": related_doc.get("snippet") or related_doc.get("content", ""),
                            "source": "web_search",
                            "is_best_match": False,
                            "is_related": True,
                            "relation_type": related_doc.get("relation_type", "similar_topic")
                        })
            
            # Add other top results (if we don't have enough from related docs)
            remaining_slots = max(0, 5 - len(related_documents))
            for r in web_search_results.get("results", [])[:remaining_slots]:
                # Skip if already added as best match or related doc
                result_url = r.get("link") or r.get("url", "")
                if result_url in seen_urls:
                    continue
                best_match_url = (best_matching_paper.get("link") if best_matching_paper else None) or (best_matching_paper.get("url") if best_matching_paper else None)
                if best_matching_paper and result_url == best_match_url:
                    continue
                if any(doc.get("url") == result_url for doc in related_documents):
                    continue
                seen_urls.add(result_url)
                document_links.append({
                    "title": r.get("title", ""),
                    "url": result_url,
                    "snippet": r.get("snippet") or r.get("content", ""),
                    "source": "web_search",
                    "is_best_match": False,
                    "is_related": False
                })
        
        # Create simplified pdf_links from document_links for backward compatibility
        all_pdf_links = []
        for doc in document_links:
            pdf_link = {
                "title": doc.get("title", "Paper") or "Paper",
                "url": doc.get("url")
            }
            if doc.get("review_url"):
                pdf_link["review_url"] = doc.get("review_url")
            if doc.get("source"):
                pdf_link["source"] = doc.get("source")
            all_pdf_links.append(pdf_link)
        
        response_data = {
            "message": analysis_response,
            "model": model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens
            },
            "pdf_links": all_pdf_links if all_pdf_links else None,
            "is_summary": is_summary
        }
        
        # Add search_results metadata if web search was actually used
        if web_search_actually_used:
            response_data["search_results"] = {
                "source": "web_search",
                "count": web_search_results.get("count", 0) if web_search_results else 0,
                "best_match": {
                    "title": best_matching_paper.get("title", "") if best_matching_paper else None,
                    "url": (best_matching_paper.get("link") or best_matching_paper.get("url", "")) if best_matching_paper else None,
                    "snippet": (best_matching_paper.get("snippet") or best_matching_paper.get("content", "")) if best_matching_paper else None
                } if best_matching_paper else None,
                "related_count": len(related_documents) if related_documents else 0
            }
        
        # Add all document links to response
        if document_links:
            response_data["document_links"] = document_links
        
        return response_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating response: {str(e)}")


@router.post("/chat/multi-model")
async def chat_multi_model(request: MultiModelChatRequest):
    """Chat endpoint with multiple models for parallel responses"""
    try:
        # Build messages (reuse ChatRequest structure)
        chat_request = ChatRequest(
            messages=request.messages,
            paper_id=request.paper_id,
            paper_context=request.paper_context
        )
        messages = build_messages(chat_request)
        
        ai_client = get_ai_client()
        
        # Create tasks for parallel execution
        async def get_model_response(model_id: str):
            try:
                # Special handling for GPT-5 (temperature must be 1.0)
                temperature = 1.0 if model_id == "gpt-5" else 0.7
                
                response = await asyncio.to_thread(
                    ai_client.chat.completions.create,
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=2000,
                    stream=False
                )
                
                return {
                    "model": model_id,
                    "message": response.choices[0].message.content,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    },
                    "error": None
                }
            except Exception as e:
                return {
                    "model": model_id,
                    "message": None,
                    "usage": None,
                    "error": str(e)
                }
        
        # Execute all models in parallel
        tasks = [get_model_response(model_id) for model_id in request.models]
        responses = await asyncio.gather(*tasks)
        
        return {
            "responses": responses,
            "count": len(responses)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating multi-model responses: {str(e)}")


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint"""
    async def generate():
        try:
            messages = []
            messages.append({"role": "system", "content": PAPER_ANALYSIS_SYSTEM_PROMPT})
            
            if request.paper_context:
                context_text = f"""Paper Context:
Title: {request.paper_context.get('title', 'N/A')}
Authors: {', '.join(request.paper_context.get('authors', []))}
Abstract: {request.paper_context.get('abstract', 'N/A')}
"""
                messages.append({"role": "system", "content": context_text})
            
            for msg in request.messages:
                messages.append({"role": msg.role, "content": msg.content})
            
            ai_client = get_ai_client()
            stream = ai_client.chat.completions.create(
                model="grok-4-fast",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
                stream=True
            )
            
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield f"data: {json.dumps({'content': chunk.choices[0].delta.content})}\n\n"
            
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")
