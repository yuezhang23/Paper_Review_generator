import os
import logging

# Set up logging
logger = logging.getLogger(__name__)

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
