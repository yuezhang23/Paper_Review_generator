# Paper Query Verification Template

Analyze the following user query and determine if it is asking about an academic paper or research paper.

User query: "{query}"

Respond in JSON format with two fields:
1. "is_about_paper": boolean - true if the query is asking about a specific paper, searching for papers, or discussing paper content. false if it's a general question, coding question, or not related to academic papers.
2. "rephrased_query": string - if is_about_paper is true, provide a rephrased version that better captures the intention for searching academic papers (extract paper titles, authors, topics, or key terms). If is_about_paper is false, return the original query unchanged.

Examples:
- "What is machine learning?" -> {"is_about_paper": false, "rephrased_query": "What is machine learning?"}
- "Tell me about the Transformer paper" -> {"is_about_paper": true, "rephrased_query": "Transformer attention is all you need"}
- "Summarize the paper by Vaswani et al." -> {"is_about_paper": true, "rephrased_query": "Vaswani attention transformer"}
- "How do I implement a neural network?" -> {"is_about_paper": false, "rephrased_query": "How do I implement a neural network?"}

Respond only with valid JSON, no additional text.
