import openreview
import psycopg
from dotenv import dotenv_values
import logging
import re

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for docker
# config = dotenv_values(".env")
# for local
config = dotenv_values("../../.env")

client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username=config["OPENREVIEW_USERNAME"],
    password=config["OPENREVIEW_PASSWORD"]
)

year = 2024
venue_id = f'NeurIPS.cc/{year}/Conference'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
submissions = client.get_all_notes(invitation=f'{venue_id}/-/{submission_name}',details='replies')
review_name = venue_group.content['review_name']['value']


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



# def get_review_jasons(submission):
#     # reply_type = "Official_Review" #also: "Meta_Review","Official_Comment", "Decision", "Rebuttal" etc.
#     field_counts= []
#     for s in submissions:
#         reviews=[openreview.api.Note.from_json(reply) for reply in s.details['replies']]   
#         for i, r in enumerate(reviews):
#             if ('decision' in r.content.keys()):
#                 print(f"{r.id} from decision: {r.replyto}\n")
#                 print(r.content['decision']['value'])
#             elif ('comment' in r.content.keys()):
#                 print(f"{r.id} from comment: {r.replyto}\n")
#                 print(r.content['comment']['value'])
#             elif ('rebuttal' in r.content.keys()):
#                 print(f"{r.id} from rebuttal: {r.replyto}\n")
#                 print(r.content['rebuttal']['value'])
#             else:
#                 print(f"{r.id} from official_review to {r.replyto}\n")

