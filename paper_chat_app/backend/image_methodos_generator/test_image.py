import base64
import os
import sys
from pathlib import Path
from openai import OpenAI
# Add parent directory to path to import utils
sys.path.insert(0, str(Path(__file__).parent.parent))
from utils import get_ai_client


ai_client = get_ai_client()
prompt = """
Create a highly detailed academic infographic illustrating the ProTeGi (Prompt Optimization with Textual Gradients) methodology workflow diagram in a single-page landscape canvas (wide format, 16:9 aspect ratio). Use a clean, professional visual style with sans-serif fonts (e.g., Arial or Helvetica), subtle drop shadows on boxes, high contrast for readability, and a colorful yet restrained palette: light backgrounds in soft grays/whites, vibrant accents per node types. Ensure precise spatial layout: primary top-to-bottom flow on the left, branching horizontally into Step 2 sub-process in the center, feeding into a large clockwise iterative loop on the right, exiting at bottom center. Do not invent steps, alter numbers, or change connections—strictly follow the specified nodes, edges, labels, and must-not-change rules.

STYLE:
Vivid academic infographic. Clean white background. Professional but colorful. Crisp vector-like shapes. High readability. Consistent typography. No clutter. Use clear arrows with arrowheads.
professional drawing with hand-drawn style
vivd elements with doodle icons

**Title Placement:** Centered at the top in large bold font (72pt, dark navy blue): "ProTeGi (Prompt Optimization with Textual Gradients)". Subtitle below in smaller italic (36pt): "Iterative prompt refinement using textual gradients and bandit selection".

**Regions and Layout Structure:**
- **R1_Initialization (top_left, 20% width x 10% height):** Contains only S1 box.
- **R2_Expansion_Main (center_left, stacked below R1, 20% width x 8% height):** Contains only S2 box.
- **R3_Expansion_Substeps (center, horizontal row spanning 40% width x 8% height, directly right of R2):** Contains S2a, S2b, S2c, S2d in left-to-right sequence, equally spaced.
- **R4_Iteration_Loop (right, 30% width x 50% height, forming a prominent clockwise loop):** Contains S3 (top), S4 (bottom-right), L1 (center of loop).
- **R5_Finalization (bottom_center, spanning 30% width x 10% height):** Contains only S5 box.
Leave 5-10% margins around edges, ample white space between regions for arrows.

**Node Boxes (rounded rectangles, 2pt stroke, semi-transparent fills matching color groups, icons integrated top-left in each box):**
Use exact labels and key_components as bullet points inside each box (small font, 14pt). Color-encode by type:
- setup_final: blue-green gradient (light blue #AED6F1 for setup S1, dark green #27AE60 for final S5).
- meta_prompt: vibrant magenta #E91E63 (S2b).
- optimizer_action: warm orange #F39C12 (S2, S2c, S2d).
- scorer_action: cool purple #9B59B6 (S2a, S3).
- update_loop_control: bold red #E74C3C for loop control L1, teal #17A589 for update S4.

- **S1 (setup, light blue):** "Step 1: Initialization with Starting Prompt" bullets: "p₀", "human-written initial prompt". Icon: ✍️.
- **S2 (optimizer_action, warm orange):** "Step 2: Expansion via Textual Gradient Descent" bullets: "minibatch", "textual gradients", "prompt editing", "paraphrasing".
- **S2a (scorer_action, cool purple):** "2a. Identify Errors" bullets: "minibatch=64", "error identification".
- **S2b (meta_prompt, vibrant magenta):** "2b. Generate Textual Gradients" bullets: "LLM critiques", "g".
- **S2c (optimizer_action, warm orange):** "2c. Edit the Prompt" bullets: "p'", "gradient-based editing".
- **S2d (optimizer_action, warm orange):** "2d. Diversify with Paraphrasing" bullets: "p''", "semantic variations".
- **S3 (scorer_action, cool purple):** "Step 3: Selection using Bandit Optimization" bullets: "UCB Bandits", "best arm identification", "top b=4 prompts". Icon: 🎰.
- **S4 (update, teal):** "Step 4: Iteration and Beam Update" bullets: "beam update", "r=6 iterations". Icon: 🔍.
- **S5 (final, dark green):** "Step 5: Final Prompt Selection" bullets: "highest F1 score", "test data evaluation". Icon: 🏆.
- **L1 (loop_control, bold red, curved banner shape wrapping the loop):** "Iteration Loop (r=6)" bullets: "Expansion → Selection → Beam Update".

**Arrows and Connections (thick 3pt arrows, curved where specified, with exact labels in bold white text on black background bubbles):**
- S1 → S2: straight downward, label "initial beam = {p₀}".
- S2 → S2a: straight rightward.
- S2a → S2b: straight rightward.
- S2b → S2c: straight rightward.
- S2c → S2d: straight rightward.
- S2 → S3: straight diagonal up-right, label "candidate pool".
- S3 → S4: straight downward, label "top b=4 prompts".
- S4 → L1: straight leftward.
- L1 → S2: prominent clockwise loop segment (large curved arrow encircling R4 region, bold dashed line for loop path), label "repeat r=6 times".
- L1 → S5: downward exit straight to bottom center, label "after r=6".

**Legend (bottom-left corner, compact grid, 10pt font, small icons):**
- p₀: "Initial human-written prompt" ✍️
- beam: "Set of top candidate prompts (width b=4)" 🔍
- textual gradients: "Natural language critiques of prompt flaws" 📈
- minibatch: "Random subset of training data (size=64)"
- UCB Bandits: "Upper Confidence Bound algorithm for bandit optimization" 🎰
- F1 score: "Performance metric for prompt evaluation" 🏆

**Callouts (curved leader lines with yellow note bubbles, 12pt font):**
- Attach to S2a: "Evaluates on a random minibatch of 64 examples."
- Attach to S3: "UCB Bandit selects the best 4 prompts (arms) to form the new beam."
- Attach to L1: "The Expansion -> Selection -> Update cycle repeats 6 times."

**Accuracy Rules (enforce strictly):**
- Numbers unchanged: minibatch=64, b=4, r=6, F1 score, UCB Bandits.
- No extra steps/nodes/arrows; exact topology only.
- Clockwise loop must visually dominate right side, with clear entry/exit.
- All text legible, no overlaps; use subscript for p₀/p'/p'' (p₀, p', p'').
- Professional polish: subtle gradients, consistent icon scaling (24x24px), anti-aliased edges.
"""

result = ai_client.images.generate(
    model="gpt-image-1.5",
    prompt=prompt,
    size="1536x1024"  
)

image_url = result.data[0].url
img_bytes = base64.b64decode(result.data[0].b64_json)

images_dir = "images"
os.makedirs(images_dir, exist_ok=True)
image_path = os.path.join(images_dir, "opro_7panel_4.png")
with open(image_path, "wb") as f:
    f.write(img_bytes)
print("Wrote: opro_7panel_4.png")
