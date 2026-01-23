from openai import OpenAI
import tiktoken
from shared_utils import get_ai_client
import torch
import json
from tqdm import tqdm
import sys
import argparse
import random

import numpy as np
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams, LLMTestCase


CLIENT = get_ai_client()
TYPOLOGY = set(["clarity", "meaningful_comparison", "motivation", "originality", "replicability", "soundness", "substance", "summary"])
VERBOSE = False


criteria = """Coherence (1-5) - the collective quality of all sentences. We align this dimension with
the DUC quality question of structure and coherence whereby the summary should be
well-structured and well-organized. The summary should not just be a heap of related information, but should build from sentence to sentence to a coherent body of information about a topic."""

coherence_metric = GEval(
    name="Coherence",
    criteria=criteria,
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT, LLMTestCaseParams.EXPECTED_OUTPUT],
)

# Now define your test case, actual_output is your LLM output
test_case = LLMTestCase(input="Hey how's the weather like today?", actual_output="It's alright!")

# Use G-Eval metric
coherence_metric.measure(test_case)
print(coherence_metric.score, coherence_metric.reason)





def count_tokens(system_prompt, gpt_prompt, gpt_output):
    encoding = tiktoken.encoding_for_model("gpt-4o-mini")
    sent = len(encoding.encode(system_prompt, disallowed_special=())) + len(encoding.encode(gpt_prompt, disallowed_special=()))
    received = len(encoding.encode(gpt_output))
    global SENT_TOKENS
    global RECEIVED_TOKENS
    SENT_TOKENS += sent
    RECEIVED_TOKENS += received

    if VERBOSE:
        print(f"SENT: adding {sent}, total {SENT_TOKENS}")
        print(f"Received: adding {received}, total {RECEIVED_TOKENS}")

def Decisiveness(review, acceptance):
    system_prompt = "You are a helpful assistant designed to process and extract information from scientific review."
    gpt_prompt = ("Below is a review to a scientific paper. Your task is to extract information from the review. Output a JSON object that has only "
                  "the key 'acceptance', and pair it with one of three values: 'positive', or 'negative', depending on the recommendation of the "
                  f"review about publishing the paper in a journal/conference.\n\nReview: {review}")
    
    response = CLIENT.chat.completions.create(
        model="gpt-4o-mini",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": gpt_prompt}
            ],
            seed=42,
            temperature=0   
    )
    gpt_output = response.choices[0].message.content
    count_tokens(system_prompt, gpt_prompt, gpt_output)
    gpt_output = json.loads(gpt_output)

    if gpt_output["acceptance"] == "positive":
        review_acceptance = 1
    elif gpt_output["acceptance"] == "negative":
        review_acceptance = -1
    else:
        print(gpt_output["acceptance"])
        return 0
    
    if VERBOSE:
        print("################## EVALUATING DECISIVENESS ##################")
        print(gpt_prompt)
        print(gpt_output)
    
    return acceptance * review_acceptance


def Comprehensiveness(review_annotation, meta_review_annotation):
    review_aspects = set([a[1].replace("_positive", "").replace("_negative", "") for a in review_annotation]) - set(['O'])
    review_aspects_polarity = set([a[1] for a in review_annotation]) - set(['O'])
    meta_review_aspects = set([a[1] for a in meta_review_annotation]) - set(['O'])

    acov = len(review_aspects.intersection(TYPOLOGY)) / len(TYPOLOGY)
    arec = len(review_aspects_polarity.intersection(meta_review_aspects)) / len(meta_review_aspects) if len(meta_review_aspects) != 0 else 1

    if VERBOSE:
        print("################## EVALUATING COMPREHENSIVENESS ##################")
        print(review_aspects)
        print(meta_review_aspects)
    
    return acov, arec

def Justification(review_annotation, review):
    assessments = []
    current_assessment = []
    last_label = review_annotation[0][1]

    for word, label in review_annotation:
        if label == last_label:
            current_assessment.append(word)
        else:
            assessments.append((" ".join(current_assessment), last_label))
            current_assessment = [word]
        last_label = label

    assessments.append((" ".join(current_assessment), last_label))
    assessments = [a[0] for a in assessments if 'negative' in a[1]]

    if len(assessments) == 0: return [-1], None, None

    system_prompt = "You are a helpful assistant designed to process and extract information from scientific review."
    gpt_prompt = ("Below is a review to a scientific paper and a list of negative assessments made by this review. Your task is to output a "
                  "JSON object that contains each assessment as key paired to a supporting statement (from the review) that justifies and explains the reason for the assessment. If an "
                  "assessment isn't justified, pair it with an empty string. For a statement to be considered a valid justification, it must provide in-depth explanation of the assessment. "
                  "Shallow statements should not be considered valid justifications."
                  f"\n\nReview:\n{review}\n\n"
                  f"Assessments:\n{assessments}")
    
    response = CLIENT.chat.completions.create(
        model="gpt-4o-mini",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": gpt_prompt}
            ],
            seed=42,
            temperature=0   
    )

    gpt_output = response.choices[0].message.content
    count_tokens(system_prompt, gpt_prompt, gpt_output)
    try:
        gpt_output = json.loads(gpt_output)
    except:
        print("Failed to load gpt_output")
        print(gpt_output)
        return [0], None, None

    if VERBOSE:
        print("################## EVALUATING JUSTIFICATION ##################")
        print(gpt_prompt)
        print(gpt_output)

    # return len([gpt_output[k] for k in gpt_output.keys() if gpt_output[k] != ""] )/ len(gpt_output), gpt_output
    return [1 if gpt_output[k] != "" else 0 for k in gpt_output.keys()], assessments, gpt_output

def paper_text(paper_dict):
    text = f"TITLE: {paper_dict["metadata"]["title"]}\n\n"
    try:
        for section in paper_dict["metadata"]["sections"]:
            if section["heading"] != None:
                text += section["heading"] + "\n"
            text += section["text"] + "\n\n"
    except:
        return None 
    return text



def Accuracy(paper_text, review, sup_statements):
    system_prompt = "You are a helpful assistant designed to process and extract information from scientific review."
    gpt_prompt = ("Below is a scientific paper and a review of this paper. Your task is to output a "
                  "JSON object that contains one key ('score') paired to a value that indicates how accurate the review summarizes the paper. "
                  "Make sure the length of the review is not taken into consideration on your assessment. "
                  "You should output one of 3 values: 1.0 (if the summary is correct), 0.5 (if the summary is partially correct) or 0.0 (if the summary is incorrect or abscent)"
                  f"\nPaper:\n{paper_text}\n\n"
                  f"Review:\n{review}")
    
    try:
        response = CLIENT.chat.completions.create(
            model="gpt-4o-mini",
            response_format={ "type": "json_object" },
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": gpt_prompt}
                ],
                seed=42,
                temperature=0   
        )

        gpt_output = response.choices[0].message.content
        count_tokens(system_prompt, gpt_prompt, gpt_output)
        gpt_output = json.loads(gpt_output)
        summary_score = float(gpt_output["score"])
    except:
        summary_score = 0


    if sup_statements == None:
        return summary_score, [-1]

    justifications = [v for v in sup_statements.values() if v != ""]

    if VERBOSE:
        print("################## EVALUATING ACCURACY ##################")
        print(gpt_prompt)
        print(gpt_output)

    system_prompt = "You are a helpful assistant designed to process and extract information from scientific review."
    gpt_prompt = ("Below is a review of a scientific paper and a list of statements from the review. Your task is to output a "
                  "JSON object that contains the statements as keys and True or False as the values, signifying if the statement is factually correct "
                  "(i. e. you cannot demonstrate that it is wrong)."
                  f"\n\nReview:\n{review}\n\nStatements:\n{justifications}")
    
    response = CLIENT.chat.completions.create(
        model="gpt-4o-mini",
        response_format={ "type": "json_object" },
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": gpt_prompt}
            ],
            seed=42,
            temperature=0   
    )
    try:
        gpt_output = response.choices[0].message.content
        count_tokens(system_prompt, gpt_prompt, gpt_output)
        gpt_output = json.loads(gpt_output)
    except:
        return summary_score, [0] # Failed to load gpt_output

    # fact_score = len([gpt_output[k] for k in gpt_output.keys() if gpt_output[k]] )/ len(gpt_output)
    fact_score = [1 if gpt_output[k] or (isinstance(gpt_output[k], str) and gpt_output[k].lower() in ["true", "yes", "positive"]) else 0 for k in gpt_output.keys()]

    if VERBOSE:
        print(gpt_prompt)
        print(gpt_output)

    return summary_score, fact_score


def JudgeReview(paper_text, review_text, meta_review_text, acceptance):
    racc = Decisiveness(review_text, acceptance)

    review_annotation = Annotate(review_text)
    meta_review_annotation = Annotate(meta_review_text)
    
    if VERBOSE:
        print("################## ANNOTATIONS ##################")
        print(review_annotation)
        print(meta_review_annotation)

    acov, arec = Comprehensiveness(review_annotation, meta_review_annotation)

    info, assessments, justifications = Justification(review_annotation, review_text)

    if VERBOSE:
        print("################## NEGATIVE ASSESSMENTS X JUSTIFICATIONS ##################")
        print(justifications)

    sacc, acon = Accuracy(paper_text, review_text, justifications)

    return racc, acov, arec, info, sacc, acon, justifications


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review_path", type=str,)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--output_path", type=str,)
    args = parser.parse_args()
    results = []

    # Handle both JSON and JSONL formats
    data_review = []
    with open(args.review_path) as f:
        first_line = f.readline().strip()
        f.seek(0)  # Reset to beginning
        
        if first_line.startswith('['):
            # JSON array format
            data_review = json.load(f)
        else:
            # JSONL format - one JSON object per line
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    data_review.append(json.loads(line))

    n = min(3000, len(data_review))
    idx_map = list(range(n))

    if args.shuffle:
        random.seed(42)
        random.shuffle(idx_map)

    for i in tqdm(range(5)):
        paper = data_review[idx_map[i]]['input']
        meta_review = data_review[idx_map[i]]["metaReview"]
        acceptance = 1 if 'accept' in data_review[idx_map[i]]["acceptance"].lower() else -1
        review = data_review[idx_map[i]]["output"] 
        #for key, val in example['AIScientistReview'].items():
        #    if type(val) is list:
        #        txt = ""
        #        for sentence in val:
        #            txt += sentence + " "
        #        review += f"### {key}:\n{txt}\n\n"
        #    else:
        #        review += f"### {key}:\n{val}\n\n"
        #print(review)
        racc, acov, arec, info, sacc, acon, justifications = JudgeReview(paper, review, meta_review, acceptance)
        acon_mean = float(np.mean(acon)) if isinstance(acon, list) and len(acon) > 0 and acon[0] != -1 else 0.0
        results.append({"racc": racc, "acov": acov, "arec": arec, "info": info, "justifications": justifications, "sacc": sacc, "acon": acon_mean, "acon_list": acon})

        # Write to JSONL for immediate saving (in case of interruption)
        with open(args.output_path, "a") as f:
            json.dump({"racc": racc, "acov": acov, "arec": arec, "info": info, "justifications": justifications, "sacc": sacc, "acon": acon_mean, "acon_list": acon}, f)
            f.write("\n")
    
    racc = sum([r["racc"] for r in results]) / n
    acov = sum([r["acov"] for r in results]) / n
    arec = sum([r["arec"] for r in results]) / n
    # info = sum([r["info"] for r in results]) / n
    sacc = sum([r["sacc"] for r in results]) / n
    acon = sum([r["acon"] for r in results]) / n
            
    print(f"Decisiveness:\n    Recommendation Accuracy: {racc}")
    print(f"Comprehensiveness:\n    Aspect Coverage: {acov}\n    Aspect Recall: {arec}")
    # print(f"Justification:\n    Informativeness: {info}")
    print(f"Accuracy:\n     Aspect-level Constructiveness: {acon}\n    Summary Accuracy: {sacc}")

    # Write final results as JSON array
    with open(args.output_path, "w") as f:
        json.dump(results, f, indent=4)
    
    price = 0.15 * SENT_TOKENS / 1000000 + 0.6 * RECEIVED_TOKENS / 1000000
    print(f"Evaluation cost: {price} dolars")



if __name__ == "__main__":
    main()