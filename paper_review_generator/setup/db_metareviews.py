import openreview
import psycopg
from dotenv import dotenv_values

config = dotenv_values(".env")
client = openreview.api.OpenReviewClient(
    baseurl='https://api2.openreview.net',
    username=config["OPENREVIEW_USERNAME"],
    password=config["OPENREVIEW_PASSWORD"]
)
year = 2023
conference = 'NeurIPS'
venue_id = f'{conference}.cc/{year}/Conference'

venue_group_settings = client.get_group(venue_id).content
submission_invitation = venue_group_settings['submission_id']['value']
submissions = client.get_all_notes(
    invitation=submission_invitation,
    details='directReplies'
)

fields = ['decision', 'comment']

venue_group_settings = client.get_group(venue_id).content
decision_invitation_name = venue_group_settings['decision_name']['value']
for submission in submissions:
    for reply in submission.details['directReplies']:
        if any(invitation.endswith(f'/-/{decision_invitation_name}') for invitation in reply['invitations']):
            with psycopg.connect(config["DB_CONFIG"]) as conn:
                with conn.cursor() as cur:
                    # Get values with proper handling of optional comment field
                    values = []
                    for field in fields:
                        try:
                            value = str(reply['content'][field]['value'])
                        except (KeyError, TypeError):
                            if field == 'comment':  # Make comment optional
                                value = None
                            else:
                                raise KeyError(f"Missing required field: {field}")
                        values.append(value)

                    cur.execute(f"""
                    INSERT INTO metareviews_{year}_{conference} (id, decision, comment)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET decision = EXCLUDED.decision,
                        comment = EXCLUDED.comment;
                    """, 
                    (reply['replyto'], *values))

                    conn.commit()