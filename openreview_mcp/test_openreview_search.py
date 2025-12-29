#!/usr/bin/env python3
"""
Test script to search for papers from ICLR 2025 with "generative" in the title.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import openreview

# Load .env file
env_path = Path(__file__).parent / ".env"
if not env_path.exists():
    env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded .env from: {env_path}")
else:
    print("Warning: .env file not found. Using environment variables.")

# Get credentials
username = os.getenv("OPENREVIEW_USERNAME")
password = os.getenv("OPENREVIEW_PASSWORD")
baseurl = os.getenv("OPENREVIEW_BASEURL", "https://api2.openreview.net")

if not username or not password:
    print("Error: OPENREVIEW_USERNAME and OPENREVIEW_PASSWORD must be set in .env or environment variables")
    sys.exit(1)

print(f"Connecting to OpenReview at {baseurl}...")

try:
    # Initialize client
    client = openreview.api.OpenReviewClient(
        baseurl=baseurl,
        username=username,
        password=password
    )
    print("✓ Successfully authenticated with OpenReview")
    
    # Search for papers from ICLR 2025 with "generative" in title
    print("\nSearching for papers from ICLR 2025 with 'generative' in title...")
    
    # ICLR 2025 venue ID
    venue_id = "ICLR.cc/2025/Conference"
    
    print(f"Venue: {venue_id}")
    
    # Get venue group to find submission name
    try:
        venue_group = client.get_group(venue_id)
        submission_name = venue_group.content['submission_name']['value']
        invitation = f'{venue_id}/-/{submission_name}'
        print(f"Submission name: {submission_name}")
        print(f"Invitation: {invitation}")
        
        # Get all notes for ICLR 2025 submissions (without limit parameter)
        all_notes = client.get_all_notes(invitation=invitation, details='replies')
        print(f"Retrieved {len(all_notes)} total submissions from ICLR 2025")
        
        # Filter for papers with "generative" in title
        generative_notes = []
        for note in all_notes:
            try:
                # Access title from note content
                if hasattr(note, 'content') and isinstance(note.content, dict):
                    title_obj = note.content.get('title', {})
                    title = title_obj.get('value', '') if isinstance(title_obj, dict) else str(title_obj) if title_obj else ''
                else:
                    # Fallback to to_json
                    note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
                    content = note_dict.get('content', {})
                    title_obj = content.get('title', {})
                    title = title_obj.get('value', '') if isinstance(title_obj, dict) else str(title_obj) if title_obj else ''
                
                if title and 'generative' in title.lower():
                    generative_notes.append(note)
            except Exception as e:
                # Skip notes that can't be processed
                continue
        
        notes = generative_notes[:10]
        print(f"Found {len(notes)} paper(s) with 'generative' in title:\n")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        notes = []
    
    # Display results
    for i, note in enumerate(notes, 1):
        note_dict = note.to_json() if hasattr(note, 'to_json') else dict(note)
        # Handle different content structures
        content = note_dict.get('content', {})
        if isinstance(content, dict):
            title_obj = content.get('title', {})
            title = title_obj.get('value', '') if isinstance(title_obj, dict) else str(title_obj) if title_obj else 'N/A'
            authors_obj = content.get('authors', {})
            authors = authors_obj.get('value', []) if isinstance(authors_obj, dict) else (authors_obj if isinstance(authors_obj, list) else [])
        else:
            title = str(content.get('title', 'N/A')) if hasattr(content, 'get') else 'N/A'
            authors = content.get('authors', []) if hasattr(content, 'get') else []
        
        note_id = note_dict.get('id', 'N/A')
        forum = note_dict.get('forum', 'N/A')
        
        print(f"{i}. {title}")
        if authors:
            authors_str = ', '.join(authors[:3]) if isinstance(authors, list) else str(authors)
            print(f"   Authors: {authors_str}{'...' if isinstance(authors, list) and len(authors) > 3 else ''}")
        print(f"   Note ID: {note_id}")
        print(f"   Forum: {forum}")
        print()
    
    # Pick a random one if we have results
    if len(notes) > 0:
        import random
        random_note = random.choice(notes)
        random_note_dict = random_note.to_json() if hasattr(random_note, 'to_json') else dict(random_note)
        
        print("=" * 80)
        print("RANDOM SELECTED PAPER:")
        print("=" * 80)
        
        # Handle content structure
        content = random_note_dict.get('content', {})
        if isinstance(content, dict):
            title_obj = content.get('title', {})
            title = title_obj.get('value', '') if isinstance(title_obj, dict) else str(title_obj) if title_obj else 'N/A'
            authors_obj = content.get('authors', {})
            authors = authors_obj.get('value', []) if isinstance(authors_obj, dict) else (authors_obj if isinstance(authors_obj, list) else [])
            abstract_obj = content.get('abstract', {})
            abstract = abstract_obj.get('value', '') if isinstance(abstract_obj, dict) else str(abstract_obj) if abstract_obj else 'N/A'
        else:
            title = str(content.get('title', 'N/A')) if hasattr(content, 'get') else 'N/A'
            authors = content.get('authors', []) if hasattr(content, 'get') else []
            abstract = str(content.get('abstract', 'N/A')) if hasattr(content, 'get') else 'N/A'
        
        print(f"Title: {title}")
        if authors:
            authors_str = ', '.join(authors) if isinstance(authors, list) else str(authors)
            print(f"Authors: {authors_str}")
        print(f"Note ID: {random_note_dict.get('id', 'N/A')}")
        if abstract and abstract != 'N/A':
            print(f"Abstract: {abstract[:200]}...")
        print(f"Full content available at: https://openreview.net/forum?id={random_note_dict.get('forum', 'N/A')}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
