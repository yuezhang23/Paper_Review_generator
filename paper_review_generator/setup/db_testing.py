import pandas as pd
import psycopg
import csv
from psycopg.rows import dict_row
import os
import logging
import random
from dotenv import dotenv_values

ratingScores = {
    1: "Very Strong Reject: For instance, a paper with incorrect statements, improper (e.g., offensive) language, unaddressed ethical considerations, incorrect results and/or flawed methodology (e.g., training using a test set).",
    2: "Strong Reject: For instance, a paper with major technical flaws, and/or poor evaluation, limited impact, poor reproducibility and mostly unaddressed ethical considerations.",
    3: "reject, not good enough",
    4: "Borderline reject: Technically solid paper where reasons to reject, e.g., limited evaluation, outweigh reasons to accept, e.g., good evaluation. Please use sparingly.",
    5: "marginally below the acceptance threshold",
    6: "marginally above the acceptance threshold",
    7: "Accept: Technically solid paper, with high impact on at least one sub-area, or moderate-to-high impact on more than one areas, with good-to-excellent evaluation, resources, reproducibility, and no unaddressed ethical considerations.",
    8: "accept, good paper",
    9: "Very Strong Accept: Technically flawless paper with groundbreaking impact on at least one area of AI/ML and excellent impact on multiple areas of AI/ML, with flawless evaluation, resources, and reproducibility, and no unaddressed ethical considerations.",
    10: "strong accept, should be highlighted at the conference"
}

confidenceScores = {
    1: "Your assessment is an educated guess. The submission is not in your area or the submission was difficult to understand. Math/other details were not carefully checked.",
    2: "You are willing to defend your assessment, but it is quite likely that you did not understand the central parts of the submission or that you are unfamiliar with some pieces of related work. Math/other details were not carefully checked.",
    3: "You are fairly confident in your assessment. It is possible that you did not understand some parts of the submission or that you are unfamiliar with some pieces of related work. Math/other details were not carefully checked.",
    4: "You are confident in your assessment, but not absolutely certain. It is unlikely, but not impossible, that you did not understand some parts of the submission or that you are unfamiliar with some pieces of related work.",
    5: "You are absolutely certain about your assessment. You are very familiar with the related work and checked the math/other details carefully."
}

miscScores = {
    1: "poor",
    2: "fair",
    3: "good",
    4: "excellent"
}

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# for docker
config = dotenv_values(".env")

fields = ['summary', 'soundness', 'presentation', 'contribution', 'strengths', 'weaknesses', 'limitations', 'rating', 'confidence', 'rebuttal']

def toString_no_rebuttal(review):
    ret = "REVIEW \n"
    for field in fields[:-1]:
        if review[field] is not None:
            ret += field.capitalize() + ":" + "\n"
            ret += str(review[field])
            if isinstance(review[field], int):
                if (field == "rating"):
                    ret += ": " + ratingScores[review[field]]
                elif (field == "confidence"):
                    ret += ": " + confidenceScores[review[field]]
                else:
                    ret += ": " + miscScores[review[field]]
            ret += "\n\n"
    return ret


def toString(review):
    ret = "REVIEW \n"
    for field in fields:
        if review[field] is not None:
            ret += field.capitalize() + ":" + "\n"
            ret += str(review[field])
            if isinstance(review[field], int):
                if (field == "rating"):
                    ret += ": " + ratingScores[review[field]]
                elif (field == "confidence"):
                    ret += ": " + confidenceScores[review[field]]
                else:
                    ret += ": " + miscScores[review[field]]
            ret += "\n\n"
    return ret

year = 2023
conference = 'NeurIPS'
ratio = 0.0
def get_train_examples():
    # Get test data (100 accept + 100 reject)
    test_exs = []
    with psycopg.connect(os.getenv("DB_CONFIG"), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Get test data
            cur.execute(f"""(SELECT id, decision FROM metareviews_{year}_{conference} WHERE LOWER(decision) LIKE '%reject%' ORDER BY RANDOM()) 
                        UNION ALL 
                        (SELECT id, decision FROM metareviews_{year}_{conference} WHERE LOWER(decision) LIKE '%accept%' ORDER BY RANDOM())""")
            test_metareviews = cur.fetchall()
            
            for metareview in test_metareviews:
                id = metareview["id"]
                decision = metareview["decision"]
                promptText = ""

                cur.execute(f"SELECT * FROM reviews_{year}_{conference} WHERE s_id = %s", [id])
                allReviews = cur.fetchall()

                rebuttal_reviews = [r for r in allReviews if r['rebuttal'] is not None]
                sample_rebuttal_reviews = random.sample(rebuttal_reviews, int(len(rebuttal_reviews) * ratio))
                           
                # Build prompt text
                for review in allReviews:
                    if review in sample_rebuttal_reviews:
                        promptText += toString(review)
                    else:
                        promptText += toString_no_rebuttal(review)
                test_exs.append({'id': id, 'text': promptText, 'label': 1 if "accept" in decision.lower() else 0})

    # Save test data
    header = ['id', 'text', 'label']
    with open(f'./data/reviews_{ratio}_rebuttal_{year}_{conference}.csv', 'w', newline='', encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=header, delimiter=";")
        writer.writeheader()  
        writer.writerows(test_exs)

    return test_exs


get_train_examples()