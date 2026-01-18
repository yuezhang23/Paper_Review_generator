# Prompt Templates

This directory contains all prompt templates used by the paper analysis chat application.

## Files

### Static Prompts (loaded at module initialization)

- **paper_analysis_system_prompt.md**: Main system prompt for the paper analysis assistant. Defines the assistant's role, capabilities, and behavior guidelines.

- **paper_summary_template.md**: Template for structured paper summaries. Used when users request a summary/analysis of a paper. Includes sections for Summary, Strengths, Weaknesses, Innovations, Contributions, Limitations, and Rating Score.

### Dynamic Prompts (loaded and formatted at runtime)

- **query_clarity_check_template.md**: Template for checking if a user query is clear enough to answer. Uses placeholders:
  - `{context_note}`: Information about whether paper context is available
  - `{query}`: The user's query string

- **paper_query_verification_template.md**: Template for verifying if a query is about an academic paper. Uses placeholders:
  - `{query}`: The user's query string

## Usage

Prompts are loaded using the `load_prompt_template()` function in `main.py`. Static prompts are loaded at module initialization, while dynamic prompts are loaded and formatted when needed.

## Format

- All templates are in Markdown format
- The first line (if it's a markdown header `# Title`) is automatically removed when loading
- Dynamic templates use Python string formatting placeholders: `{variable_name}`
- Templates should be written in clear, natural language with proper formatting

## Editing

When editing prompts:
1. Keep the structure and formatting consistent
2. Test changes to ensure they work correctly
3. Update this README if adding new templates
4. Ensure dynamic templates have correct placeholder names
