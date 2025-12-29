#!/usr/bin/env python3
"""
OpenReview MCP Server
A Model Context Protocol server that wraps the OpenReview Python SDK.
"""

import os
from pathlib import Path
from typing import Optional, Dict, List, Any
from fastmcp import FastMCP
import openreview

# Try to load from .env file if available
try:
    from dotenv import load_dotenv
    # Look for .env in current directory or parent directories
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, will rely on environment variables

# Initialize the MCP server
mcp = FastMCP("OpenReview MCP Server")

# Global client instance (will be initialized on first use)
_client: Optional[openreview.api.OpenReviewClient] = None


def get_client() -> openreview.api.OpenReviewClient:
    """Get or create the OpenReview client instance."""
    global _client
    if _client is None:
        baseurl = os.getenv("OPENREVIEW_BASEURL", "https://api2.openreview.net")
        username = os.getenv("OPENREVIEW_USERNAME")
        password = os.getenv("OPENREVIEW_PASSWORD")
        
        if not username or not password:
            raise ValueError(
                "OpenReview credentials not found. Please set OPENREVIEW_USERNAME "
                "and OPENREVIEW_PASSWORD environment variables."
            )
        
        _client = openreview.api.OpenReviewClient(
            baseurl=baseurl,
            username=username,
            password=password
        )
    return _client


@mcp.tool()
def get_profile(email: str) -> Dict[str, Any]:
    """
    Retrieve OpenReview profile information for a given email address.
    
    Args:
        email: The email address of the user whose profile to retrieve
        
    Returns:
        A dictionary containing the user's profile information
    """
    try:
        client = get_client()
        profile = client.get_profile(email)
        return profile.to_json() if hasattr(profile, 'to_json') else dict(profile)
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@mcp.tool()
def search_notes(
    content: Optional[str] = None,
    title: Optional[str] = None,
    venue: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Search for notes (papers/submissions) in OpenReview.
    
    Args:
        content: Search term to match in paper content
        title: Search term to match in paper title
        venue: Venue ID to filter by (e.g., 'ICLR.cc/2025/Conference')
        limit: Maximum number of results to return (default: 10)
        
    Returns:
        A dictionary containing search results
    """
    try:
        client = get_client()
        results = []
        
        # If venue is specified, use get_all_notes approach
        if venue:
            try:
                # Get venue group to find submission name
                venue_group = client.get_group(venue)
                submission_name = venue_group.content['submission_name']['value']
                invitation = f'{venue}/-/{submission_name}'
                
                # Get all notes for this venue
                all_notes = client.get_all_notes(invitation=invitation, details='replies')
                
                # Filter by title and/or content if specified
                filtered_notes = []
                for note in all_notes:
                    try:
                        # Access title from note content
                        if hasattr(note, 'content') and isinstance(note.content, dict):
                            note_title = note.content.get('title', {}).get('value', '') if isinstance(note.content.get('title'), dict) else str(note.content.get('title', ''))
                            note_content = str(note.content.get('abstract', {}).get('value', '')) if isinstance(note.content.get('abstract'), dict) else str(note.content.get('abstract', ''))
                        else:
                            note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                            content_dict = note_dict.get('content', {})
                            note_title = content_dict.get('title', {}).get('value', '') if isinstance(content_dict.get('title'), dict) else str(content_dict.get('title', ''))
                            note_content = str(content_dict.get('abstract', {}).get('value', '')) if isinstance(content_dict.get('abstract'), dict) else str(content_dict.get('abstract', ''))
                        
                        # Check filters
                        title_match = not title or title.lower() in note_title.lower()
                        content_match = not content or content.lower() in note_content.lower()
                        
                        if title_match and content_match:
                            filtered_notes.append(note)
                    except:
                        continue
                
                # Limit results
                notes = filtered_notes[:limit]
                
            except Exception as e:
                return {"error": f"Error searching venue {venue}: {str(e)}", "type": type(e).__name__}
        else:
            # Use search_notes for general search (without venue filter)
            query_parts = []
            if content:
                query_parts.append(f'content:"{content}"')
            if title:
                query_parts.append(f'title:"{title}"')
            
            query = ' AND '.join(query_parts) if query_parts else '*'
            
            try:
                notes = client.search_notes(term=query)
            except:
                # Fallback if term parameter doesn't work
                notes = client.search_notes(content=query) if hasattr(client, 'search_notes') else []
        
        # Convert notes to dictionaries
        for note in notes:
            try:
                note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                results.append(note_dict)
            except:
                continue
        
        return {
            "count": len(results),
            "results": results[:limit]
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@mcp.tool()
def get_note(note_id: str) -> Dict[str, Any]:
    """
    Retrieve a specific note (paper/submission) by its ID.
    
    Args:
        note_id: The OpenReview note ID (e.g., '~Author1/Submission1')
        
    Returns:
        A dictionary containing the note information
    """
    try:
        client = get_client()
        note = client.get_note(note_id)
        return note.to_json() if hasattr(note, 'to_json') else dict(note)
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@mcp.tool()
def get_reviews(note_id: str) -> Dict[str, Any]:
    """
    Retrieve all reviews for a specific note (paper/submission).
    
    Args:
        note_id: The OpenReview note ID to get reviews for
        
    Returns:
        A dictionary containing review information
    """
    try:
        client = get_client()
        reviews = client.get_notes(forum=note_id, invitation='~/-/Official_Review')
        
        results = []
        for review in reviews:
            review_dict = review.to_json() if hasattr(review, 'to_json') else dict(review)
            results.append(review_dict)
        
        return {
            "note_id": note_id,
            "count": len(results),
            "reviews": results
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@mcp.tool()
def get_group(group_id: str) -> Dict[str, Any]:
    """
    Retrieve information about an OpenReview group.
    
    Args:
        group_id: The OpenReview group ID (e.g., 'ICLR.cc/2024/Conference')
        
    Returns:
        A dictionary containing group information
    """
    try:
        client = get_client()
        group = client.get_group(group_id)
        return group.to_json() if hasattr(group, 'to_json') else dict(group)
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@mcp.tool()
def get_invitations(
    group_id: Optional[str] = None,
    invitation_id: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Retrieve invitations from OpenReview.
    
    Args:
        group_id: Filter invitations by group ID
        invitation_id: Get a specific invitation by ID
        limit: Maximum number of results to return (default: 10)
        
    Returns:
        A dictionary containing invitation information
    """
    try:
        client = get_client()
        
        if invitation_id:
            invitation = client.get_invitation(invitation_id)
            return invitation.to_json() if hasattr(invitation, 'to_json') else dict(invitation)
        
        invitations = client.get_invitations(group=group_id, limit=limit)
        
        results = []
        for invitation in invitations:
            inv_dict = invitation.to_json() if hasattr(invitation, 'to_json') else dict(invitation)
            results.append(inv_dict)
        
        return {
            "count": len(results),
            "invitations": results
        }
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


if __name__ == "__main__":
    mcp.run()

