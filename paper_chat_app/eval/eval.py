from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCaseParams, LLMTestCase

import os
os.chdir(os.path.dirname(os.path.abspath(__file__)))


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