#!/usr/bin/env python3
"""
Web scraper to extract paper information from CVPR HTML pages.
Extracts paper titles, authors, and links, then outputs to JSON.
"""

import json
import re
from bs4 import BeautifulSoup
from typing import List, Dict
import sys


def extract_papers_from_html(html_content: str) -> List[Dict]:
    """
    Extract paper information from HTML content.
    
    Args:
        html_content: HTML string to parse
        
    Returns:
        List of dictionaries containing paper information
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    papers = []
    
    # Find all dt elements with class "ptitle" which contain paper titles
    paper_elements = soup.find_all('dt', class_='ptitle')
    
    for paper_elem in paper_elements:
        paper_info = {}
        
        # Extract title and link
        title_link = paper_elem.find('a')
        if title_link:
            paper_info['title'] = title_link.get_text(strip=True)
            paper_info['link'] = title_link.get('href', '')
        
        # Extract authors from the following dd element
        authors = []
        # Find the next dd sibling that contains author forms
        next_dd = paper_elem.find_next_sibling('dd')
        if next_dd:
            # Find all author forms
            author_forms = next_dd.find_all('form', class_='authsearch')
            for form in author_forms:
                # Extract author name from the hidden input or the link text
                hidden_input = form.find('input', {'name': 'query_author'})
                if hidden_input:
                    author_name = hidden_input.get('value', '').strip()
                    if author_name:
                        authors.append(author_name)
                else:
                    # Fallback: get author name from link text
                    author_link = form.find('a')
                    if author_link:
                        author_name = author_link.get_text(strip=True)
                        if author_name:
                            authors.append(author_name)
        
        # Remove trailing commas from author names
        authors = [author.rstrip(',') for author in authors if author]
        
        paper_info['authors'] = authors
        paper_info['num_authors'] = len(authors)
        
        if paper_info.get('title'):  # Only add if we have a title
            papers.append(paper_info)
    
    return papers


def scrape_from_file(html_file_path: str) -> List[Dict]:
    """
    Read HTML from a file and extract paper information.
    
    Args:
        html_file_path: Path to HTML file
        
    Returns:
        List of dictionaries containing paper information
    """
    with open(html_file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()
    return extract_papers_from_html(html_content)


def scrape_from_url(url: str) -> List[Dict]:
    """
    Fetch HTML from a URL and extract paper information.
    
    Args:
        url: URL to fetch HTML from
        
    Returns:
        List of dictionaries containing paper information
    """
    try:
        import requests
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return extract_papers_from_html(response.text)
    except ImportError:
        print("Error: requests library is required for URL scraping. Install it with: pip install requests")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching URL: {e}")
        sys.exit(1)


def save_to_json(data: List[Dict], output_file: str):
    """
    Save extracted data to a JSON file.
    
    Args:
        data: List of paper dictionaries
        output_file: Path to output JSON file
    """
    output_data = {
        'total_papers': len(data),
        'papers': data
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Successfully saved {len(data)} papers to {output_file}")


def main():
    """
    Main function to run the scraper.
    Can be used with command line arguments or with the provided HTML string.
    """
    
    url = 'https://openaccess.thecvf.com/CVPR2024?day=all'
    
    # Extract papers from the example HTML
    papers = scrape_from_url(url)

    
    # Save to JSON
    output_file = 'papers_output.json'
    save_to_json(papers, output_file)
    
    # Print summary
    print(f"\nExtracted {len(papers)} paper(s):")
    for i, paper in enumerate(papers, 1):
        print(f"\n{i}. {paper['title']}")
        print(f"   Authors: {', '.join(paper['authors'])}")
        print(f"   Link: {paper['link']}")


if __name__ == '__main__':
    main()

