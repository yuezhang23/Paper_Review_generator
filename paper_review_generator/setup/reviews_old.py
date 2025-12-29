import openreview
import psycopg
from dotenv import dotenv_values
import logging
import re

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_numeric_value(value):
    """Extract numeric value from text like '2 fair' or '3 good'."""
    if isinstance(value, (int, float)):
        return str(value)
    # Try to find a number at the start of the string
    match = re.match(r'^\s*(\d+)', str(value))
    if match:
        return match.group(1)
    return str(value)

def check_for_nul_bytes(values, fields):
    """Check which field contains NUL bytes and return the field name."""
    for i, value in enumerate(values):
        if isinstance(value, str) and '\x00' in value:
            return fields[i]
    return None

def clean_nul_bytes(value):
    """Remove NUL bytes from string values."""
    if isinstance(value, str):
        return value.replace('\x00', '')
    return value



config = dotenv_values(".env")

client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username=config["OPENREVIEW_USERNAME"],
    password=config["OPENREVIEW_PASSWORD"]
)

venue_id = 'NeurIPS.cc/2024/Conference'

# First get all valid submission IDs from metareviews table
with psycopg.connect(config["DB_CONFIG"]) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM metareviews_2024_NeurIPS")
        valid_submission_ids = {row[0] for row in cur.fetchall()}

venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
submissions = client.get_all_notes(invitation=f'{venue_id}/-/{submission_name}', details='replies')

review_name = venue_group.content['review_name']['value']
fields = ['summary', 'soundness', 'presentation', 'contribution', 'strengths', 'weaknesses', 'questions', 'limitations', 'rating', 'confidence']
numeric_fields = {'soundness', 'presentation', 'contribution', 'rating', 'confidence'}

with psycopg.connect(config["DB_CONFIG"]) as conn:
    with conn.cursor() as cur:
        for s in submissions:
            # Only process submissions that have metareviews
            if s.id not in valid_submission_ids:
                logger.info(f"Skipping submission {s.id} as it has no metareview")
                continue
                
            reviews=[openreview.api.Note.from_json(reply) for reply in s.details['replies'] if f'{venue_id}/{submission_name}{s.number}/-/{review_name}' in reply['invitations']]
            for r in reviews:
                try:
                    # Try to get all required fields
                    values = []
                    for field in fields:
                        try:
                            value = r.content[field]['value']
                            # For numeric fields, extract the numeric part but keep as string
                            if field in numeric_fields:
                                value = extract_numeric_value(value)
                            elif value == None:
                                value = str('not_provided')
                            else:
                                value = str(value)
                            # Clean NUL bytes from all string values
                            value = clean_nul_bytes(value)

                        except (KeyError, TypeError):
                            if field == 'limitations':  # Make limitations optional
                                value = str('not_provided')
                            else:
                                logger.warning(f"Missing field '{field}' in review {r.replyto}, skipping this review")
                                raise KeyError(f"Missing field: {field}")
                        values.append(value)
                    
                    cur.execute("""
                        INSERT INTO reviews_2024_NeurIPS (id, summary, soundness, presentation, contribution, strengths, weaknesses, questions, limitations, rating, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (r.replyto, *values)    
                    )
                    conn.commit()
                except KeyError as e:
                    logger.error(f"Error processing review {r.replyto}: {str(e)}")
                    continue  
                except Exception as e:
                    nul_field = check_for_nul_bytes(values, fields)
                    if nul_field:
                        logger.error(f"NUL bytes found in field '{nul_field}'")
                    logger.error(f"Unexpected error processing review {r.replyto}: {str(e)}")
                    logger.error(f"Error type: {type(e).__name__}")
                    continue  
