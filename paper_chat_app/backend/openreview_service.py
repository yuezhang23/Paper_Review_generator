"""
OpenReview Service Module
Handles all OpenReview API interactions and paper processing
"""

import os
import json
import re
import csv
from typing import Optional, List, Dict, Any
import openreview
from dotenv import load_dotenv
import httpx
import PyPDF2
import io
import logging

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize OpenReview client
_openreview_client: Optional[openreview.api.OpenReviewClient] = None

# OpenReview documents directory (using openreview_mcp/docs structure)
# Go up from backend/ to paper_chat_app/ to workspace root, then to openreview_mcp/docs
OPENREVIEW_DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "openreview_mcp", "docs")
os.makedirs(OPENREVIEW_DOCS_DIR, exist_ok=True)


def get_openreview_client():
    """Get or create OpenReview client instance"""
    global _openreview_client
    if _openreview_client is None:
        baseurl = os.getenv("OPENREVIEW_BASEURL", "https://api2.openreview.net")
        username = os.getenv("OPENREVIEW_USERNAME")
        password = os.getenv("OPENREVIEW_PASSWORD")
        
        if username and password:
            _openreview_client = openreview.api.OpenReviewClient(
                baseurl=baseurl,
                username=username,
                password=password
            )
    return _openreview_client


def extract_year_from_timestamp(timestamp: Optional[int]) -> Optional[int]:
    """Extract year from OpenReview timestamp (milliseconds since epoch)"""
    if not timestamp:
        return None
    try:
        # OpenReview timestamps are in milliseconds
        from datetime import datetime
        dt = datetime.fromtimestamp(timestamp / 1000)
        return dt.year
    except:
        return None


def parse_openreview_info_from_text(text: str) -> Dict[str, List[str]]:
    """Parse OpenReview paper IDs, URLs, and titles from text"""
    result = {
        'paper_ids': [],
        'urls': [],
        'titles': []
    }
    
    # Pattern for OpenReview URLs: https://openreview.net/forum?id=... or https://openreview.net/pdf?id=...
    url_pattern = r'https?://openreview\.net/(?:forum|pdf)\?id=([A-Za-z0-9_~\-]+)'
    url_matches = re.findall(url_pattern, text)
    result['paper_ids'].extend(url_matches)
    # Also store full URLs
    full_url_pattern = r'(https?://openreview\.net/(?:forum|pdf)\?id=[A-Za-z0-9_~\-]+)'
    full_urls = re.findall(full_url_pattern, text)
    result['urls'].extend(full_urls)
    
    # Pattern for direct paper IDs (e.g., ~Author1/Submission1 or forum:abc123)
    id_pattern = r'(?:paper[_\s]*id|id|forum)[:=]\s*([A-Za-z0-9_~\-/]+)'
    id_matches = re.findall(id_pattern, text, re.IGNORECASE)
    result['paper_ids'].extend(id_matches)
    
    # Pattern for standalone paper IDs (format: ~Author/Submission or alphanumeric)
    standalone_pattern = r'\b([~]?[A-Za-z0-9_~\-/]{10,})\b'
    standalone_matches = re.findall(standalone_pattern, text)
    # Filter to likely OpenReview IDs (contain ~ or /)
    for match in standalone_matches:
        if '~' in match or '/' in match:
            if match not in result['paper_ids']:
                result['paper_ids'].append(match)
    
    # Extract paper titles - look for patterns like "paper: Title", "title: Title", or quoted titles
    # Pattern 1: "paper: Title" or "title: Title"
    title_pattern1 = r'(?:paper|title|about)[:\s]+["\']?([^"\'\n]{10,200})["\']?'
    title_matches1 = re.findall(title_pattern1, text, re.IGNORECASE)
    result['titles'].extend([t.strip() for t in title_matches1 if len(t.strip()) > 10])
    
    # Pattern 2: Quoted titles
    quoted_pattern = r'["\']([^"\']{15,200})["\']'
    quoted_matches = re.findall(quoted_pattern, text)
    result['titles'].extend([t.strip() for t in quoted_matches if len(t.strip()) > 15])
    
    # Pattern 3: Titles after "summarize", "analyze", "review" etc. (handles typos like "summerize")
    action_pattern = r'(?:summ[ae]rize|analyze|review|discuss|explain)[:\s]+["\']?([^"\'\n]{10,200})["\']?'
    action_matches = re.findall(action_pattern, text, re.IGNORECASE)
    result['titles'].extend([t.strip() for t in action_matches if len(t.strip()) > 10])
    
    # Remove duplicates
    result['paper_ids'] = list(set(result['paper_ids']))
    result['urls'] = list(set(result['urls']))
    result['titles'] = list(set(result['titles']))
    
    return result


async def search_openreview_by_title(title: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Search OpenReview for papers by title using the API"""
    try:
        or_client = get_openreview_client()
        if not or_client:
            return []
        
        papers = []
        search_results = []
        
        try:
            # Use search_notes with title parameter (similar to openreview_mcp.py)
            if hasattr(or_client, 'search_notes'):
                try:
                    # Try searching by title
                    search_results = or_client.search_notes(title=title, limit=limit)
                except:
                    try:
                        # Fallback: search by content (title might be in content)
                        search_results = or_client.search_notes(content=title, limit=limit)
                    except:
                        try:
                            # Last fallback: search by term
                            search_results = or_client.search_notes(term=title, limit=limit)
                        except:
                            pass
            
            # Process search results
            for note in list(search_results)[:limit]:
                try:
                    note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                    content = note_dict.get('content', {})
                    
                    # Extract paper information
                    paper_title = content.get('title', {}).get('value', '') if isinstance(content.get('title'), dict) else str(content.get('title', ''))
                    authors = content.get('authors', {}).get('value', []) if isinstance(content.get('authors'), dict) else (content.get('authors', []) if isinstance(content.get('authors'), list) else [])
                    abstract = content.get('abstract', {}).get('value', '') if isinstance(content.get('abstract'), dict) else str(content.get('abstract', ''))
                    
                    paper_id = note_dict.get('id', '')
                    forum_id = note_dict.get('forum', paper_id)
                    
                    # Extract year from creation date
                    cdate = note_dict.get('cdate')
                    year = extract_year_from_timestamp(cdate)
                    
                    # Only add if title matches (fuzzy match)
                    title_lower = title.lower()
                    paper_title_lower = paper_title.lower()
                    if title_lower in paper_title_lower or paper_title_lower in title_lower or any(word in paper_title_lower for word in title_lower.split() if len(word) > 3):
                        papers.append({
                            'id': paper_id,
                            'title': paper_title,
                            'authors': authors,
                            'abstract': abstract,
                            'venue': note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else '',
                            'year': year,
                            'forum_id': forum_id
                        })
                except Exception as e:
                    print(f"Error processing search result: {str(e)}")
                    continue
        except Exception as e:
            print(f"Error searching OpenReview by title: {str(e)}")
            return []
        
        return papers
    except Exception as e:
        print(f"Error in search_openreview_by_title: {str(e)}")
        return []


async def download_pdf_from_openreview(paper_id: str) -> Optional[bytes]:
    """Download PDF from OpenReview"""
    try:
        pdf_url = f"https://openreview.net/pdf?id={paper_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(pdf_url)
            if response.status_code == 200:
                return response.content
    except Exception as e:
        print(f"Error downloading PDF for {paper_id}: {str(e)}")
    return None


def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from PDF file"""
    try:
        pdf_file = io.BytesIO(file_content)
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"


def format_review_as_text(review_dict: Dict[str, Any], review_content: Dict[str, Any]) -> str:
    """Format a review into the full text format as shown in the example"""
    text_parts = []
    
    # Summary
    summary = review_content.get('summary', {}).get('value', '') if isinstance(review_content.get('summary'), dict) else str(review_content.get('summary', ''))
    if summary:
        text_parts.append(f"REVIEW \nSummary:\n{summary}\n")
    
    # Soundness
    soundness = review_content.get('soundness', {}).get('value', '') if isinstance(review_content.get('soundness'), dict) else str(review_content.get('soundness', ''))
    if soundness:
        text_parts.append(f"Soundness:\n{soundness}\n")
    
    # Presentation
    presentation = review_content.get('presentation', {}).get('value', '') if isinstance(review_content.get('presentation'), dict) else str(review_content.get('presentation', ''))
    if presentation:
        text_parts.append(f"Presentation:\n{presentation}\n")
    
    # Contribution
    contribution = review_content.get('contribution', {}).get('value', '') if isinstance(review_content.get('contribution'), dict) else str(review_content.get('contribution', ''))
    if contribution:
        text_parts.append(f"Contribution:\n{contribution}\n")
    
    # Strengths
    strengths = review_content.get('strengths', {}).get('value', '') if isinstance(review_content.get('strengths'), dict) else str(review_content.get('strengths', ''))
    if strengths:
        text_parts.append(f"Strengths:\n{strengths}\n")
    
    # Weaknesses
    weaknesses = review_content.get('weaknesses', {}).get('value', '') if isinstance(review_content.get('weaknesses'), dict) else str(review_content.get('weaknesses', ''))
    if weaknesses:
        text_parts.append(f"Weaknesses:\n{weaknesses}\n")
    
    # Limitations
    limitations = review_content.get('limitations', {}).get('value', '') if isinstance(review_content.get('limitations'), dict) else str(review_content.get('limitations', ''))
    if limitations:
        text_parts.append(f"Limitations:\n{limitations}\n")
    
    # Rating
    rating = review_content.get('rating', {}).get('value', '') if isinstance(review_content.get('rating'), dict) else str(review_content.get('rating', ''))
    if rating:
        text_parts.append(f"Rating:\n{rating}\n")
    
    # Confidence
    confidence = review_content.get('confidence', {}).get('value', '') if isinstance(review_content.get('confidence'), dict) else str(review_content.get('confidence', ''))
    if confidence:
        text_parts.append(f"Confidence:\n{confidence}\n")
    
    return "\n".join(text_parts)


async def fetch_and_save_openreview_paper(paper_id: str) -> Optional[Dict[str, Any]]:
    """Fetch paper data, download PDF, and save reviews from OpenReview"""
    try:
        or_client = get_openreview_client()
        if not or_client:
            return None
        
        # Get paper note
        try:
            note = or_client.get_note(paper_id)
        except:
            # Try with forum ID if direct note fails
            try:
                notes = or_client.get_notes(forum=paper_id)
                note = list(notes)[0] if notes else None
                if not note:
                    return None
            except:
                return None
        
        note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
        content = note_dict.get('content', {})
        
        # Extract paper information
        title = content.get('title', {}).get('value', '') if isinstance(content.get('title'), dict) else str(content.get('title', ''))
        authors = content.get('authors', {}).get('value', []) if isinstance(content.get('authors'), dict) else (content.get('authors', []) if isinstance(content.get('authors'), list) else [])
        abstract = content.get('abstract', {}).get('value', '') if isinstance(content.get('abstract'), dict) else str(content.get('abstract', ''))
        
        # Get paper ID and forum
        actual_paper_id = note_dict.get('id', paper_id)
        forum_id = note_dict.get('forum', actual_paper_id)
        
        # Extract year from creation date
        cdate = note_dict.get('cdate')
        year = extract_year_from_timestamp(cdate)
        
        # Create directory for this paper: openreview_mcp/docs/{paper_id}/
        paper_dir = os.path.join(OPENREVIEW_DOCS_DIR, actual_paper_id)
        os.makedirs(paper_dir, exist_ok=True)
        
        # Save metadata as JSON
        metadata = {
            'paper_id': actual_paper_id,
            'forum_id': forum_id,
            'title': title,
            'authors': authors,
            'abstract': abstract,
            'venue': note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else '',
            'year': year,
            'invitation': note_dict.get('invitation', ''),
            'created': note_dict.get('cdate'),
            'modified': note_dict.get('mdate'),
            'full_content': content
        }
        metadata_path = os.path.join(paper_dir, 'metadata.json')
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        
        # Download PDF
        pdf_content = await download_pdf_from_openreview(actual_paper_id)
        pdf_text = ""
        pdf_path = None
        
        if pdf_content:
            # Save PDF locally in paper directory
            safe_filename = re.sub(r'[^\w\-_\.]', '_', title[:100]) if title else 'paper'
            pdf_filename = f"{safe_filename}.pdf"
            pdf_path = os.path.join(paper_dir, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(pdf_content)
            
            # Extract text from PDF and save as text file
            pdf_text = extract_text_from_pdf(pdf_content)
            pdf_text_path = os.path.join(paper_dir, 'pdf_text.txt')
            with open(pdf_text_path, 'w', encoding='utf-8') as f:
                f.write(pdf_text)
        
        # Get and save reviews as CSV
        reviews = []
        csv_path = None
        
        try:
            review_notes = or_client.get_notes(forum=forum_id, invitation='~/-/Official_Review')
            if review_notes:
                csv_path = os.path.join(paper_dir, 'reviews.csv')
                
                with open(csv_path, 'w', encoding='utf-8', newline='') as csvfile:
                    # Write header with semicolon separator
                    csvfile.write('id;text;label\n')
                    
                    for review in review_notes:
                        review_dict = review.to_json() if hasattr(review, 'to_json') else dict(review)
                        review_content = review_dict.get('content', {})
                        review_id = review_dict.get('id', '')
                        
                        if review_id:
                            # Format full review text
                            review_text = format_review_as_text(review_dict, review_content)
                            
                            # Get rating for label (extract number if possible)
                            rating = review_content.get('rating', {}).get('value', '') if isinstance(review_content.get('rating'), dict) else str(review_content.get('rating', ''))
                            # Extract numeric rating (e.g., "5: marginally below" -> 5)
                            label = '0'
                            if rating:
                                rating_match = re.search(r'(\d+)', str(rating))
                                if rating_match:
                                    label = rating_match.group(1)
                            
                            # Escape quotes in text for CSV (double quotes)
                            review_text_escaped = review_text.replace('"', '""')
                            
                            # Write CSV row with semicolon separator
                            # Text field is quoted and can contain newlines
                            csvfile.write(f'{review_id};"{review_text_escaped}";{label}\n')
                            
                            reviews.append({
                                'review_id': review_id,
                                'text': review_text,
                                'label': label,
                                'rating': rating
                            })
        except Exception as e:
            print(f"Error fetching reviews for {paper_id}: {str(e)}")
        
        return {
            'paper_id': actual_paper_id,
            'forum_id': forum_id,
            'title': title,
            'authors': authors,
            'abstract': abstract,
            'venue': note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else '',
            'year': year,
            'pdf_path': pdf_path,
            'pdf_text': pdf_text,
            'reviews': reviews,
            'reviews_path': csv_path,
            'metadata_path': metadata_path,
            'paper_dir': paper_dir
        }
    except Exception as e:
        print(f"Error fetching OpenReview paper {paper_id}: {str(e)}")
        return None


async def retrieve_openreview_papers(query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Retrieve papers from OpenReview based on query"""
    try:
        or_client = get_openreview_client()
        if not or_client:
            return []
        
        # Search OpenReview for papers
        search_results = []
        try:
            if hasattr(or_client, 'search_notes'):
                # Try with term parameter
                try:
                    search_results = or_client.search_notes(term=query, limit=limit)
                except:
                    # Fallback: try with content parameter
                    try:
                        search_results = or_client.search_notes(content=query, limit=limit)
                    except:
                        # Last fallback: try without limit
                        try:
                            all_results = or_client.search_notes(term=query)
                            search_results = list(all_results)[:limit] if all_results else []
                        except:
                            pass
        except Exception as e:
            # If search fails, return empty list
            return []
        
        papers = []
        for note in search_results[:limit]:
            try:
                note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                content = note_dict.get('content', {})
                
                # Extract paper information
                title = content.get('title', {}).get('value', '') if isinstance(content.get('title'), dict) else str(content.get('title', ''))
                authors = content.get('authors', {}).get('value', []) if isinstance(content.get('authors'), dict) else (content.get('authors', []) if isinstance(content.get('authors'), list) else [])
                abstract = content.get('abstract', {}).get('value', '') if isinstance(content.get('abstract'), dict) else str(content.get('abstract', ''))
                
                # Get paper ID and forum
                paper_id = note_dict.get('id', '')
                forum_id = note_dict.get('forum', paper_id)
                
                # Extract year from creation date
                cdate = note_dict.get('cdate')
                year = extract_year_from_timestamp(cdate)
                
                # Construct PDF and review page URLs
                pdf_url = f"https://openreview.net/pdf?id={paper_id}" if paper_id else None
                review_url = f"https://openreview.net/forum?id={forum_id}" if forum_id else None
                
                # Get reviews (limit to avoid timeout)
                reviews = []
                try:
                    review_notes = or_client.get_notes(forum=forum_id, invitation='~/-/Official_Review')
                    for review in list(review_notes)[:3]:  # Limit to 3 reviews
                        review_dict = review.to_json() if hasattr(review, 'to_json') else dict(review)
                        review_content = review_dict.get('content', {})
                        if isinstance(review_content, dict):
                            summary = review_content.get('summary', {}).get('value', '') if isinstance(review_content.get('summary'), dict) else str(review_content.get('summary', ''))
                            if summary:
                                reviews.append({
                                    'summary': summary[:500],  # Limit review length
                                    'rating': review_content.get('rating', {}).get('value', '') if isinstance(review_content.get('rating'), dict) else str(review_content.get('rating', ''))
                                })
                except:
                    pass
                
                papers.append({
                    'id': paper_id,
                    'title': title,
                    'authors': authors,
                    'abstract': abstract,
                    'venue': note_dict.get('invitation', '').split('/')[0] if '/' in note_dict.get('invitation', '') else '',
                    'year': year,
                    'pdf_url': pdf_url,
                    'review_url': review_url,
                    'reviews': reviews
                })
            except Exception as e:
                continue
        
        return papers
    except Exception as e:
        return []


def extract_numeric_value(value: Any) -> Optional[float]:
    """Extract numeric value from a string or number"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # Try to extract first number from string (e.g., "5: marginally below" -> 5)
        match = re.search(r'(\d+(?:\.\d+)?)', str(value))
        if match:
            return float(match.group(1))
    return None


def clean_nul_bytes(text: str) -> str:
    """Remove NUL bytes from text"""
    if not isinstance(text, str):
        text = str(text)
    return text.replace('\x00', '')


def get_meta_reviews_for_single_paper(paper_id: str, output_csv_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Retrieve meta reviews for a single paper and optionally save to CSV.
    Similar to get_reviews_for_single_submission in the example code.
    
    Args:
        paper_id: OpenReview paper ID
        output_csv_path: Optional path to save CSV file. If None, saves to paper directory.
    
    Returns:
        Dictionary with paper_id, metareviews list, and decision
    """
    try:
        or_client = get_openreview_client()
        if not or_client:
            logger.error("OpenReview client not available")
            return {'paper_id': paper_id, 'metareviews': [], 'decision': ''}
        
        # Get paper note - try to get with details first (like example code)
        submission = None
        replies = []
        
        try:
            # Try to get note with details='replies' (similar to example code)
            submission = or_client.get_note(paper_id, details='replies')
            # Access replies from details (like example: s.details['replies'])
            if hasattr(submission, 'details') and submission.details:
                replies = submission.details.get('replies', [])
            elif hasattr(submission, 'details') and isinstance(submission.details, dict):
                replies = submission.details.get('replies', [])
        except Exception as e:
            logger.warning(f"Could not get note with details for {paper_id}: {str(e)}")
            try:
                # Fallback: get note first, then get all notes from forum
                submission = or_client.get_note(paper_id)
                forum_id = submission.forum if hasattr(submission, 'forum') else paper_id
                # Get all notes from forum (includes submission and all replies)
                all_notes = or_client.get_notes(forum=forum_id)
                # Convert to JSON format and filter to only replies
                for note in all_notes:
                    if hasattr(note, 'to_json'):
                        note_json = note.to_json()
                    else:
                        note_json = dict(note)
                    # Include all notes except the submission itself
                    if note_json.get('id') != paper_id:
                        replies.append(note_json)
            except Exception as e2:
                logger.error(f"Error fetching paper {paper_id}: {str(e2)}")
                return {'paper_id': paper_id, 'metareviews': [], 'decision': ''}
        
        # Get submission ID (might be different from paper_id if paper_id is forum)
        if submission:
            if hasattr(submission, 'id'):
                submission_id = submission.id
            elif hasattr(submission, 'to_json'):
                submission_id = submission.to_json().get('id', paper_id)
            else:
                submission_id = paper_id
        else:
            submission_id = paper_id
        
        # Define fields to extract (same as example)
        fields = ['summary', 'soundness', 'presentation', 'contribution', 'strengths', 'weaknesses', 'questions', 'limitations', 'rating', 'confidence']
        numeric_fields = {'soundness', 'presentation', 'contribution', 'rating', 'confidence'}
        
        # Helper function to link comments recursively
        def link_comments(comment_values, comment_id, accr_values):
            """Recursively link comments to form threaded conversations"""
            for cc in comment_values:
                if cc['reply_id'] == comment_id:
                    accr_values += '\n\nReply:\n' + cc['comment']
                    accr_values = link_comments(comment_values, cc['c_id'], accr_values)
                    break
            return accr_values
        
        # Process all replies
        rebuttal_values = []
        official_values = []
        comment_values = []
        decision = ''
        
        # Convert replies to Note objects (like example: Note.from_json(reply))
        reviews = []
        for reply in replies:
            try:
                if isinstance(reply, dict):
                    reviews.append(openreview.api.Note.from_json(reply))
                elif hasattr(reply, 'to_json'):
                    # Already a Note object, use as is
                    reviews.append(reply)
                else:
                    # Try to convert
                    reviews.append(openreview.api.Note.from_json(reply))
            except Exception as e:
                logger.warning(f"Could not convert reply to Note: {str(e)}")
                # Create a minimal Note-like object
                class NoteLike:
                    def __init__(self, data):
                        self.id = data.get('id', '') if isinstance(data, dict) else getattr(data, 'id', '')
                        self.replyto = data.get('replyto', '') if isinstance(data, dict) else getattr(data, 'replyto', '')
                        if isinstance(data, dict):
                            self.content = data.get('content', {})
                        else:
                            self.content = getattr(data, 'content', {})
                reviews.append(NoteLike(reply))
        
        for r in reviews:
            try:
                # Get content and IDs
                if hasattr(r, 'content'):
                    content = r.content
                else:
                    content = getattr(r, 'content', {})
                
                if hasattr(r, 'id'):
                    reply_id = r.id
                else:
                    reply_id = getattr(r, 'id', '')
                
                if hasattr(r, 'replyto'):
                    replyto = r.replyto
                else:
                    replyto = getattr(r, 'replyto', '')
                
                # Process rebuttals
                if 'rebuttal' in content.keys():
                    rebuttal_text = content['rebuttal'].get('value', '') if isinstance(content['rebuttal'], dict) else str(content.get('rebuttal', ''))
                    rebuttal_values.append({
                        'r_id': reply_id,
                        'reply_id': replyto,
                        'rebuttal': rebuttal_text
                    })
                # Process comments (not decisions, not rebuttals)
                elif 'decision' not in content.keys() and 'comment' in content.keys():
                    comment_text = content['comment'].get('value', '') if isinstance(content['comment'], dict) else str(content.get('comment', ''))
                    comment_values.append({
                        'c_id': reply_id,
                        'reply_id': replyto,
                        'comment': comment_text
                    })
                # Process official reviews (meta reviews with summary field)
                elif 'summary' in content.keys():
                    if replyto == submission_id:
                        values = []
                        for field in fields:
                            field_content = content.get(field, {})
                            if isinstance(field_content, dict):
                                value = field_content.get('value', None)
                            else:
                                value = field_content
                            
                            if field in numeric_fields:
                                value = extract_numeric_value(value)
                            elif value is None:
                                value = 'not_provided'
                            else:
                                value = str(value)
                            
                            # Clean NUL bytes
                            value = clean_nul_bytes(str(value))
                            values.append(value)
                        
                        official_values.append({
                            'id': reply_id,
                            'values': values,
                            'rebuttal': ''
                        })
                # Process decisions
                elif 'decision' in content.keys() and replyto == submission_id:
                    decision_value = content['decision'].get('value', '') if isinstance(content['decision'], dict) else str(content.get('decision', ''))
                    decision = decision_value
            except KeyError as e:
                logger.error(f"Error processing review {getattr(r, 'id', 'unknown')}: {str(e)}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error processing review {getattr(r, 'id', 'unknown')}: {str(e)}")
                logger.error(f"Error type: {type(e).__name__}")
                continue
        
        # Add comments to rebuttals
        for rebut_data in rebuttal_values:
            for comment_data in comment_values:
                if comment_data['reply_id'] == rebut_data['r_id']:
                    accr_values = link_comments(comment_values, comment_data['c_id'], '')
                    rebut_data['rebuttal'] += '\n\nComment:\n' + comment_data['comment'] + accr_values
        
        # Add rebuttals and comments to official reviews
        for official_data in official_values:
            for rebuttal_data in rebuttal_values:
                if rebuttal_data['reply_id'] == official_data['id']:
                    official_data['rebuttal'] += rebuttal_data['rebuttal']
            for comment_data in comment_values:
                if comment_data['reply_id'] == official_data['id']:
                    accr_values = link_comments(comment_values, comment_data['c_id'], '')
                    official_data['rebuttal'] += '\n\nComment:\n' + comment_data['comment'] + accr_values
            official_data['rebuttal'] = clean_nul_bytes(official_data['rebuttal'])
        
        # Add rebuttals directly to submission (standalone rebuttals)
        for rebuttal_data in rebuttal_values:
            if rebuttal_data['reply_id'] == submission_id:
                rebuttal_text = clean_nul_bytes(rebuttal_data['rebuttal'])
                official_values.append({
                    'id': rebuttal_data['r_id'],
                    'values': [None] * len(fields),
                    'rebuttal': rebuttal_text
                })
        
        result = {
            'paper_id': submission_id,
            'metareviews': official_values,
            'decision': decision
        }
        
        # Save to CSV if output path is provided or use default location
        if output_csv_path is None:
            # Use default location in paper directory
            paper_dir = os.path.join(OPENREVIEW_DOCS_DIR, paper_id)
            os.makedirs(paper_dir, exist_ok=True)
            output_csv_path = os.path.join(paper_dir, 'meta_reviews.csv')
        
        # Write to CSV
        try:
            with open(output_csv_path, 'w', encoding='utf-8', newline='') as csvfile:
                fieldnames = ['s_id', 'id', 'summary', 'soundness', 'presentation', 'contribution', 
                             'strengths', 'weaknesses', 'questions', 'limitations', 'rating', 
                             'confidence', 'rebuttal', 'decision']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for official_value in official_values:
                    # Helper to safely get value or empty string
                    def get_value(index):
                        if len(official_value['values']) > index:
                            val = official_value['values'][index]
                            return '' if val is None else str(val)
                        return ''
                    
                    row = {
                        's_id': submission_id,
                        'id': official_value['id'] or '',
                        'summary': get_value(0),
                        'soundness': get_value(1),
                        'presentation': get_value(2),
                        'contribution': get_value(3),
                        'strengths': get_value(4),
                        'weaknesses': get_value(5),
                        'questions': get_value(6),
                        'limitations': get_value(7),
                        'rating': get_value(8),
                        'confidence': get_value(9),
                        'rebuttal': official_value.get('rebuttal', '') or '',
                        'decision': decision or ''
                    }
                    writer.writerow(row)
            
            logger.info(f"Saved meta reviews to {output_csv_path}")
        except Exception as e:
            logger.error(f"Error saving CSV to {output_csv_path}: {str(e)}")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in get_meta_reviews_for_single_paper for {paper_id}: {str(e)}")
        return {'paper_id': paper_id, 'metareviews': [], 'decision': ''}


def create_papers_selection_list(papers: List[Dict[str, Any]], include_none: bool = True) -> List[Dict[str, Any]]:
    """Create a list of papers for user selection, optionally including a 'none' option.
    Removes duplicates based on title, authors, and year (case-insensitive).
    Skips papers without title or authors."""
    papers_list = []
    seen_papers = set()  # Track seen papers by (title_lower, authors_tuple, year)
    
    # Add "none" option first if requested
    if include_none:
        papers_list.append({
            'id': 'none',
            'title': 'None - Skip All Papers',
            'authors': [],
            'abstract': 'Select this option if none of the papers match your query.',
            'venue': '',
            'year': None,
            'pdf_url': None,
            'review_url': None
        })
    
    # Add actual papers, removing duplicates and skipping invalid papers
    for paper in papers:
        # Get title and authors - skip if missing
        title = paper.get('title', '').strip() if paper.get('title') else ''
        authors = paper.get('authors', [])
        
        # Skip if no title or no authors
        if not title or title == 'N/A' or not authors or (isinstance(authors, list) and len(authors) == 0):
            continue
        
        # Normalize title (case-insensitive, strip whitespace)
        title_lower = title.lower().strip()
        
        # Normalize authors (case-insensitive, sorted for consistency)
        if not isinstance(authors, list):
            authors = []
        authors_normalized = tuple(sorted([str(a).strip().lower() for a in authors if a and str(a).strip()]))
        
        # Skip if no valid authors after normalization
        if not authors_normalized:
            continue
        
        # Get year
        year = paper.get('year')
        
        # Create unique key for duplicate detection
        paper_key = (title_lower, authors_normalized, year)
        
        # Skip if duplicate
        if paper_key in seen_papers:
            continue
        
        # Mark as seen
        seen_papers.add(paper_key)
        
        # Add paper to list
        papers_list.append({
            'id': paper.get('paper_id') or paper.get('id', ''),
            'title': title,
            'authors': authors,
            'abstract': paper.get('abstract', '')[:300] + '...' if len(paper.get('abstract', '')) > 300 else paper.get('abstract', ''),
            'venue': paper.get('venue', ''),
            'year': year,
            'pdf_url': paper.get('pdf_url') or (f"https://openreview.net/pdf?id={paper.get('paper_id') or paper.get('id', '')}" if (paper.get('paper_id') or paper.get('id')) else None),
            'review_url': paper.get('review_url') or (f"https://openreview.net/forum?id={paper.get('forum_id') or paper.get('paper_id') or paper.get('id', '')}" if (paper.get('forum_id') or paper.get('paper_id') or paper.get('id')) else None)
        })
    
    return papers_list
