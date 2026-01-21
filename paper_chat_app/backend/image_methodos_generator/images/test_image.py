import base64
import os
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import asyncio
# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(backend_dir))

from image_methodos_generator.prompt_utils import fix_imamge_size, load_prompt_template
from image_methodos_generator.image_optimizer import criticize_image_with_render_text, edit_image_with_issues, criticize_image_with_logics
from image_methodos_generator.three_layer_generator import generate_layer2_layout, generate_layer3_render, generate_layer1_logic
# Suppress warnings from utils.py about missing prompt templates during import
with redirect_stdout(StringIO()):
    from utils import get_ai_client


ai_client = get_ai_client()

def generate_image(prompt: str, image_path: str):
    result = ai_client.images.generate(
        model="gpt-image-1.5",
        prompt=prompt,
    )

    image_url = result.data[0].url
    b64_json = result.data[0].b64_json
    if not b64_json:
        raise ValueError(f"No b64_json data in API response. Image URL: {image_url}")

    img_bytes = base64.b64decode(b64_json)
    img_bytes = fix_imamge_size(img_bytes, 1536, 1024)

    if img_bytes is None:
        raise ValueError("fix_imamge_size returned None")

    with open(image_path, "wb") as f:
        f.write(img_bytes)
    print(f"Wrote {image_path}")

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)          
    parent_dir = os.path.dirname(base_dir)      

    request_dir = os.path.join(parent_dir, "images", "1768837129")
    # logic_layer = json.load(open(os.path.join(request_dir, "layer1_logic.json"), "r"))
    # layout_layer = json.load(open(os.path.join(request_dir, "layer2_layout.json"), "r"))
    # logic_layer = asyncio.run(generate_layer1_logic(open(os.path.join(request_dir, "interpretation.txt"), "r").read()))
    # with open(os.path.join(request_dir, "layer1_logic_01.json"), "w") as f:
    #     json.dump(logic_layer, f, indent=2, ensure_ascii=False)
    # layout_layer = asyncio.run(generate_layer2_layout(logic_layer))
    # with open(os.path.join(request_dir, "layer2_layout_01.json"), "w") as f:
    #     json.dump(layout_layer, f, indent=2, ensure_ascii=False)
    # render_layer = asyncio.run(generate_layer3_render(logic_layer, layout_layer))
    # with open(os.path.join(request_dir, "layer3_render_01.txt"), "w") as f:
    #     f.write(render_layer)
    # render_text = load_prompt_template(os.path.join(request_dir, "layer3_render_1.txt"))
    # image = generate_image(render_text, os.path.join(request_dir, "methodology_04.png"))
    # print("Image generated")
    # # criticism = asyncio.run(criticize_image_with_prompt(ai_client, request_dir))

    # criticism = asyncio.run(criticize_image_with_render_text(ai_client, request_dir, os.path.join(request_dir, "m_01.png")))
    image_path = os.path.join(request_dir, "m_01.png")
    edited_image = asyncio.run(edit_image_with_issues(ai_client, request_dir, image_path))
    # print("Image edited")
