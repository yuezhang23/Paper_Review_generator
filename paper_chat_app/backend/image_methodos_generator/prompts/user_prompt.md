GROUND_TRUTH_JSON:
{GROUND_TRUTH_JSON}

STYLE_CONSTRAINTS:
{STYLE_CONSTRAINTS}

TASK:
Compare the infographic image against GROUND_TRUTH_JSON.

Return ONLY JSON with this exact structure:

{{
  "schema_version": "1.0",
  "overall_status": "PASS|FAIL|PASS_WITH_UNCERTAINTY",
  "summary_counts": {{
    "required_nodes": <int>,
    "matched_nodes": <int>,
    "missing_nodes": <int>,
    "extra_nodes": <int>,
    "required_edges": <int>,
    "matched_edges": <int>,
    "missing_edges": <int>,
    "extra_edges": <int>,
    "hard_constraints": <int>,
    "hard_violations": <int>,
    "uncertain_items": <int>
  }},
  "node_checks": [
    {{
      "node_id": "<from ground truth>",
      "required_label": "<exact label from ground truth>",
      "status": "MATCH|MISSING|MISMATCH|UNCERTAIN",
      "observed_label": "<string or null>",
      "notes": "<brief reason, no speculation>"
    }}
  ],
  "edge_checks": [
    {{
      "edge_id": "<compose as from->to (type)>",
      "from": "<node_id>",
      "to": "<node_id>",
      "type": "<arrow|loop|exit|...>",
      "required_label": "<edge label or null>",
      "status": "MATCH|MISSING|MISMATCH|UNCERTAIN",
      "observed": {{
        "connects_correct_nodes": <true|false|null>,
        "observed_label": "<string or null>"
      }},
      "notes": "<brief reason, no speculation>"
    }}
  ],
  "hard_constraint_checks": [
    {{
      "constraint": "<string copied from ground_truth_json.must_not_change>",
      "status": "PASS|FAIL|UNCERTAIN",
      "notes": "<brief reason>"
    }}
  ],
  "uncertainties": [
    {{
      "item_type": "NODE|EDGE|TEXT|LEGEND|OTHER",
      "item_ref": "<node_id or edge_id or description>",
      "reason": "TEXT_ILLEGIBLE|AMBIGUOUS_MAPPING|CROPPED|LOW_RESOLUTION|OVERLAP|OTHER"
    }}
  ],
  "patch_instructions": [
    {{
      "priority": "P0|P1|P2",
      "action_type": "ADD|REMOVE|EDIT|MOVE|RELABEL|REWIRE",
      "target": "<node_id/edge_id or description>",
      "instruction": "<imperative edit instruction for image editor>",
      "acceptance_test": "<how to verify it’s fixed>"
    }}
  ]
}}

Important:
1) You MUST enumerate all required nodes from ground truth in node_checks, in the same order as ground_truth_json.nodes.
2) You MUST enumerate all required edges from ground truth in edge_checks, in the same order as ground_truth_json.edges.
3) If you see extra nodes/edges not in ground truth, include them by adding additional entries at the end with status = "EXTRA" is NOT allowed; instead count them in summary_counts and describe them in notes fields of a dedicated uncertainties item_type="OTHER".
4) If any hard_constraint_checks status is FAIL, overall_status must be FAIL unless the failure is purely due to unreadable content, in which case it may be PASS_WITH_UNCERTAINTY.
5) Do NOT output anything except the JSON object.
