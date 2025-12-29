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
#config = dotenv_values(".env")
# for local
config = dotenv_values("../../.env")


client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username=config["OPENREVIEW_USERNAME"],
    password=config["OPENREVIEW_PASSWORD"]
)

year = 2024
conference = 'ICLR'
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
                accr_values.append(cc)
                link_comments(comment_values, cc['c_id'], accr_values)
                break
    
    rebuttal_values = []
    official_values = []    
    comment_values = []
    decision = ''   
    reviews=[openreview.api.Note.from_json(reply) for reply in s.details['replies']]            
    for r in reviews:
        try:
            # Try to get all required fields
            if 'rebuttal' in r.content.keys():
                r.content['rebuttal']['value'] = clean_nul_bytes(r.content['rebuttal']['value'])
                rebuttal_values.append({'r_id' : r.id, 'rebuttal' : {'reply_id' : r.replyto, 'value' : r.content['rebuttal']['value'], 'comments' : []}})
            elif 'decision' not in r.content.keys() and 'comment' in r.content.keys():
                r.content['comment']['value'] = clean_nul_bytes(r.content['comment']['value'])
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
                official_values.append({'id' : r.id, 'reply_id' : r.replyto, 'values' : values, 'rebuttal' : []})
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
        accr_values = []
        for comment_data in comment_values:
            if comment_data['reply_id'] == rebut_data['r_id']: 
                accr_values.append(comment_data)
                link_comments(comment_values, comment_data['c_id'], accr_values)
        rebut_data['rebuttal']['comments'] = accr_values

    # Add rebuttals and comments to official reviews
    for official_data in official_values:
        for rebuttal_data in rebuttal_values:
            if rebuttal_data['rebuttal']['reply_id'] == official_data['id']:
                official_data['rebuttal'].append(rebuttal_data)
        for comment_data in comment_values: 
            if comment_data['reply_id'] == official_data['id']:
                # accr_values.extend(link_comments(comment_values, comment_data['c_id'], []))
                accr_values = [comment_data]
                link_comments(comment_values, comment_data['c_id'], accr_values)
                rebuttal_s = {'r_id' : comment_data['c_id'], 'rebuttal' : {'reply_id' : comment_data['reply_id'], 'value' : None, 'comments' : accr_values}}
                official_data['rebuttal'].append(rebuttal_s)


    # Add rebuttals directly to submission
    for rebuttal_data in rebuttal_values:
        if rebuttal_data['rebuttal']['reply_id'] == s.id:
            official_values.append({'id' : rebuttal_data['r_id'], 'values' : [None] * len(fields), 'rebuttal' : [rebuttal_data]})
    return {'s_id' : s.id, 'metareviews': official_values, 'decision' : decision}

def get_reviews(submissions, valid_submission_ids={}):
    export_reviews = []
    for s in submissions:
        if valid_submission_ids and s.id not in valid_submission_ids:
            logger.info(f"Skipping submission {s.id} as it has no metareview")
            continue
        export_reviews.append(get_reviews_for_single_submission(s))
    return export_reviews

# Dump export_reviews to JSON file
def dump_to_json(export_reviews):
    # Create output directory if it doesn't exist
    output_dir = "./dump_data"
    os.makedirs(output_dir, exist_ok=True)

    # Save export_reviews to JSON file
    output_file = os.path.join(output_dir, f"reviews_{year}_{conference}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(export_reviews, f, indent=2, ensure_ascii=False)

    logger.info(f"Exported {len(export_reviews)} reviews to {output_file}")


export_reviews = get_reviews(submissions, {})
dump_to_json(export_reviews)