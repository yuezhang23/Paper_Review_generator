# Query Clarity Check Template

Analyze the following user query about an academic paper and determine if it is clear and specific enough to provide a good answer.

Context: {context_note}

User query: "{query}"

Respond in JSON format with two fields:
1. "is_clear": boolean - true if the query is specific, clear, and has enough context to provide a good answer. false if the query is vague, ambiguous, lacks necessary details, or could be interpreted in multiple ways.
2. "clarification_question": string or null - if is_clear is false, provide a helpful, specific clarifying question to ask the user. If is_clear is true, set this to null.

Consider these scenarios as unclear:
- Vague questions like "tell me about it", "what about this", "explain"
- Questions without specifying which paper (if multiple papers might be involved)
- Questions without specifying what aspect they want to know about (methodology, results, contributions, etc.)
- Ambiguous questions that could have multiple interpretations

Examples:
- "What is the main contribution?" (no paper specified) -> {{"is_clear": false, "clarification_question": "Which paper are you asking about? Please specify the paper title or provide more context."}}
- "Summarize the Transformer paper" -> {{"is_clear": true, "clarification_question": null}}
- "Tell me about it" -> {{"is_clear": false, "clarification_question": "What specific aspect of the paper would you like to know about? For example: methodology, experimental results, key contributions, limitations, or comparisons with other works."}}
- "What are the experimental results in the Transformer paper?" -> {{"is_clear": true, "clarification_question": null}}
- "Compare them" -> {{"is_clear": false, "clarification_question": "Which papers would you like me to compare? Please specify the papers you're interested in."}}

Respond only with valid JSON, no additional text.
