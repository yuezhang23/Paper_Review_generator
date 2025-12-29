import openreview
import psycopg
from dotenv import dotenv_values
import logging
import re
import json
import os
from review_utilities import extract_numeric_value, check_for_nul_bytes, clean_nul_bytes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for docker
config = dotenv_values(".env")


client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username=config["OPENREVIEW_USERNAME"],
    password=config["OPENREVIEW_PASSWORD"]
)

year = 2023
conference = 'NeurIPS'
venue_id = f'{conference}.cc/{year}/Conference'
venue_group = client.get_group(venue_id)
submission_name = venue_group.content['submission_name']['value']
submissions = client.get_all_notes(invitation=f'{venue_id}/-/{submission_name}', details='replies')

# review_name = venue_group.content['review_name']['value']
fields = ['summary', 'soundness', 'presentation', 'contribution', 'strengths', 'weaknesses', 'questions', 'limitations', 'rating', 'confidence']
# extra_fields = ['rebuttal', 'comment']
numeric_fields = {'soundness', 'presentation', 'contribution', 'rating', 'confidence'}

def get_reviews_for_single_submission(s):
    # dfs to link comments
    def link_comments(comment_values, id, accr_values):
        for cc in comment_values:
            if cc['reply_id'] == id:
                accr_values += '\n\nReply:\n' + cc['comment']
                accr_values = link_comments(comment_values, cc['c_id'], accr_values)
                break
        return accr_values
    
    rebuttal_values = []
    official_values = []    
    comment_values = []
    decision = ''   
    reviews=[openreview.api.Note.from_json(reply) for reply in s.details['replies']]            
    for r in reviews:
        try:
            # Try to get all required fields
            if 'rebuttal' in r.content.keys():
                rebuttal_values.append({'r_id' : r.id, 'reply_id' : r.replyto, 'rebuttal' : r.content['rebuttal']['value']})
            elif 'decision' not in r.content.keys() and 'comment' in r.content.keys():
                comment_values.append({'c_id' : r.id, 'reply_id' : r.replyto, 'comment' : r.content['comment']['value']})                   
            elif 'summary' in r.content.keys():
                values = []
                if r.replyto == s.id:
                    for field in fields:
                        value = r.content[field]['value']
                        if field in numeric_fields:
                            value = extract_numeric_value(value)
                        elif value is None:
                            value = 'not_provided'
                        else:
                            value = str(value)
                        # Clean NUL bytes from all string values
                        value = clean_nul_bytes(value)               
                        values.append(value)
                official_values.append({'id' : r.id, 'values' : values, 'rebuttal' : ''})
            # Skip reviews that have a 'decision' field (these are not actual reviews)
            else:
                if (r.replyto == s.id):
                    decision = r.content['decision']['value']                     
        except KeyError as e:
            logger.error(f"Error processing review {r.replyto}: {str(e)}")
            continue  
        except Exception as e:
            logger.error(f"Unexpected error processing review {r.replyto}: {str(e)}")
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
                # Clean NUL bytes from rebuttal text
        for comment_data in comment_values: 
            if comment_data['reply_id'] == official_data['id']:
                accr_values = link_comments(comment_values, comment_data['c_id'], '')
                official_data['rebuttal'] += '\n\nComment:\n' + comment_data['comment'] + accr_values
        official_data['rebuttal'] = clean_nul_bytes(official_data['rebuttal'])   

    # Add rebuttals directly to submission
    for rebuttal_data in rebuttal_values:
        if rebuttal_data['reply_id'] == s.id:
            rebuttal_text = clean_nul_bytes(rebuttal_data['rebuttal']) 
            official_values.append({'id' : rebuttal_data['r_id'], 'values' : [None] * len(fields), 'rebuttal' : rebuttal_text})
    return {'s_id' : s.id, 'metareviews': official_values, 'decision' : decision}

def get_reviews(submissions, valid_submission_ids={}):
    export_reviews = []
    for s in submissions:
        if valid_submission_ids and s.id not in valid_submission_ids:
            logger.info(f"Skipping submission {s.id} as it has no metareview")
            continue
        export_reviews.append(get_reviews_for_single_submission(s))
    return export_reviews

def dump_to_database(export_reviews):
    with psycopg.connect(config["DB_CONFIG"]) as conn:
        with conn.cursor() as cur:
            for sub in export_reviews:
                for i, official_value in enumerate(sub['metareviews']):
                    try:
                        cur.execute(f"""
                        INSERT INTO reviews_{year}_{conference} (s_id, id, summary, soundness, presentation, contribution, strengths, weaknesses, questions, limitations, rating, confidence, rebuttal, decision)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (sub['s_id'], official_value['id'], *official_value['values'], official_value['rebuttal'], sub['decision'])) 
                        conn.commit()
                    except Exception as e:
                        logger.error(f"Error inserting {sub['s_id']}: {str(e)}")
                        continue


# First get all valid submission IDs from metareviews table
valid_submission_ids = {}
with psycopg.connect(config["DB_CONFIG"]) as conn:
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM metareviews_{year}_{conference}")
        valid_submission_ids = {row[0] for row in cur.fetchall()}

export_reviews = get_reviews(submissions, valid_submission_ids)
dump_to_database(export_reviews)