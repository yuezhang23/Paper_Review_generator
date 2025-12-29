# Paper Review Generator

A comprehensive project for paper review generation with OpenReview integration and MCP server support.

## Project Structure

```
.
├── openreview_mcp/          # OpenReview MCP server implementation
│   ├── openreview_mcp.py    # Main MCP server script
│   ├── test_openreview_search.py
│   ├── requirements_openreview.txt
│   └── OPENREVIEW_MCP_README.md
│
├── docs/                    # Documentation
│   ├── README.md           # Original README (if exists)
│   └── deployment-prompt.md
│
├── scripts/                 # Utility scripts
│   ├── create_github_repo.py
│   └── setup_github.sh
│
├── paper_review_generator/  # Main paper review generator
│   └── setup/              # Database and review utilities
│
├── pj_1/                    # Project 1: Web scraper
├── pj_3/                    # Project 3: Search redirect bookmarklet
└── pj_4/                    # Project 4: HTML project
```

## Components

### OpenReview MCP Server
Located in `openreview_mcp/`, this provides Model Context Protocol (MCP) integration with OpenReview API for accessing paper submissions, reviews, and profiles.

### Paper Review Generator
Main application in `paper_review_generator/` for generating paper reviews from OpenReview data.

### Projects
Various sub-projects (pj_1, pj_3, pj_4) for different functionalities.

## Getting Started

See individual component READMEs for setup instructions:
- [OpenReview MCP Server](openreview_mcp/OPENREVIEW_MCP_README.md)
- [Deployment Guide](docs/deployment-prompt.md)

## Requirements

- Python 3.9+
- See `openreview_mcp/requirements_openreview.txt` for OpenReview MCP dependencies
- See individual project folders for project-specific requirements

