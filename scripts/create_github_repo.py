#!/usr/bin/env python3
"""
Script to create a GitHub repository using the GitHub API.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load .env file
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded .env from: {env_path}")

# Get GitHub PAT
github_pat = os.getenv("PAT") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

if not github_pat:
    print("Error: GitHub Personal Access Token not found in .env file")
    print("Please set PAT or GITHUB_PERSONAL_ACCESS_TOKEN in your .env file")
    sys.exit(1)

# Repository details
repo_name = "AI_Paper_Reviewer"
repo_description = "An intelligent paper review system with OpenReview MCP integration"

# GitHub API endpoint
url = "https://api.github.com/user/repos"

# Headers
headers = {
    "Authorization": f"Bearer {github_pat}",
    "Accept": "application/vnd.github.v3+json",
    "X-GitHub-Api-Version": "2022-11-28"
}

# Repository data
data = {
    "name": repo_name,
    "description": repo_description,
    "private": False,
    "auto_init": False  # Don't initialize with README since we have files
}

print(f"Creating repository '{repo_name}' on GitHub...")
print(f"Description: {repo_description}")

try:
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 201:
        repo_info = response.json()
        repo_url = repo_info.get("html_url", "")
        clone_url = repo_info.get("clone_url", "")
        
        print(f"\n✅ Success! Repository created:")
        print(f"   URL: {repo_url}")
        print(f"   Clone URL: {clone_url}")
        print(f"\nNext steps:")
        print(f"   1. git remote add origin {clone_url}")
        print(f"   2. git add .")
        print(f"   3. git commit -m 'Initial commit'")
        print(f"   4. git push -u origin main")
        
    elif response.status_code == 401:
        print(f"\n❌ Authentication failed. Please check your GitHub Personal Access Token.")
        print(f"   Make sure your token has the 'repo' scope enabled.")
        print(f"   Create a new token at: https://github.com/settings/tokens/new")
        
    elif response.status_code == 403:
        print(f"\n❌ Permission denied. Your token may not have the required scopes.")
        print(f"   Required scope: 'repo' (Full control of private repositories)")
        print(f"   Check your token scopes at: https://github.com/settings/tokens")
        print(f"\nResponse: {response.text}")
        
    elif response.status_code == 422:
        error_data = response.json()
        if "already exists" in str(error_data).lower():
            print(f"\n⚠️  Repository '{repo_name}' already exists on GitHub.")
            print(f"   You can push to it directly or choose a different name.")
        else:
            print(f"\n❌ Validation error: {error_data}")
            
    else:
        print(f"\n❌ Error creating repository:")
        print(f"   Status code: {response.status_code}")
        print(f"   Response: {response.text}")
        
except requests.exceptions.RequestException as e:
    print(f"\n❌ Network error: {e}")
    sys.exit(1)

