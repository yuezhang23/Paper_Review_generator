"""
Methodology Utilities - Query templates for extracting methodology content from papers
Contains section-anchor queries for finding method zones and detail-seeking queries for
extracting detailed methodology information.
"""

# Section-anchor queries: Used to identify "method zone" candidates
# These queries target sections that typically contain methodology information
SECTION_ANCHOR_QUERIES = [
    "What is the methodology or approach used in this paper?",
    "How does the method work step by step?",
    "What is the experimental setup or implementation details?",
    "Describe the algorithm or model architecture",
    "What are the key components and how do they interact?",
    "How is the system designed and what are its main modules?",
    "What preprocessing or data processing steps are performed?",
    "What training procedures or optimization methods are used?",
    "How are experiments conducted and what is the evaluation protocol?",
    "What are the technical details of the proposed approach?"
]

# Detail-seeking queries: Used to extract detailed methodology information
# These queries go deeper into specific aspects of the methodology
DETAIL_SEEKING_QUERIES = [
    "What are the specific steps of the algorithm or method?",
    "What are the mathematical formulations or equations used?",
    "What are the hyperparameters and configuration details?",
    "How are the data processed before feeding into the model?",
    "What loss functions or objectives are optimized?",
    "What neural network architectures or model structures are used?",
    "How are features extracted or transformed?",
    "What evaluation metrics are used and how are they calculated?",
    "What are the specific implementation details and code structure?",
    "How is the method initialized and what are the training procedures?",
    "What are the batch processing and optimization strategies?",
    "How are results computed and what post-processing is applied?",
    "What are the data augmentation or regularization techniques used?",
    "How are different components integrated together?",
    "What are the computational requirements and efficiency considerations?"
]
