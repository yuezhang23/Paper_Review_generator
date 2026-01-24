import base64
import io
import json
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Tuple
from typing import Dict, Any
from PIL import Image, ImageDraw
import logging
logger = logging.getLogger(__name__)


import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils import get_ai_client


ai_client = get_ai_client()


# ----------------------------
# Data model for issues
# ----------------------------
@dataclass
class BoxIssue:
    """
    Box coordinates are in FULL-IMAGE pixel coordinates:
      (x1, y1) top-left, (x2, y2) bottom-right
      [x_min, y_min, x_max, y_max]
    """
    id: str
    x1: int
    y1: int
    x2: int
    y2: int
    prompt: str  # patch-specific edit instruction


# ----------------------------
# Mask generators
# ----------------------------
def make_box_mask_rgba(size: Tuple[int, int], box: Tuple[int, int, int, int]) -> Image.Image:
    w, h = size
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))  # fully opaque
    draw = ImageDraw.Draw(mask)
    x1, y1, x2, y2 = box
    
    # Clamp box coordinates to mask bounds to prevent out-of-bounds drawing
    x1 = max(0, min(x1, w))
    y1 = max(0, min(y1, h))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))
    
    # Only draw if box is valid
    if x2 > x1 and y2 > y1:
        draw.rectangle([x1, y1, x2, y2], fill=(0, 0, 0, 0))  
    return mask


def make_polygon_mask_rgba(size: Tuple[int, int], polygon_xy: List[Tuple[int, int]]) -> Image.Image:
    """
    Pixel-level (polygon) mask:
      - OPAQUE outside polygon (protected)
      - TRANSPARENT inside polygon (editable)
    """
    w, h = size
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    draw = ImageDraw.Draw(mask)
    draw.polygon(polygon_xy, fill=(0, 0, 0, 0))
    return mask


# ----------------------------
# Patch crop / paste helpers
# ----------------------------
def clamp_box(box: Tuple[int, int, int, int], w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    x1 = max(0, min(x1, w - 1))
    y1 = max(0, min(y1, h - 1))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))
    if x2 <= x1: x2 = min(w, x1 + 1)
    if y2 <= y1: y2 = min(h, y1 + 1)
    return x1, y1, x2, y2
    

def expand_box(box: Tuple[int, int, int, int], pad: int, w: int, h: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return clamp_box((x1 - pad, y1 - pad, x2 + pad, y2 + pad), w, h)


def crop_patch(img: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    return img.crop(box)


def crop_mask(mask: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    return mask.crop(box)


def paste_patch(base: Image.Image, patch: Image.Image, box: Tuple[int, int, int, int]) -> Image.Image:
    """
    Paste patch back into base at box (x1,y1,x2,y2).
    Patch should be same size as the crop.

    CRITICAL: This function must preserve the full base image and only replace
    the patch region. If the result only shows the patch, there's a bug here.
    """
    # Ensure both images are RGBA for proper handling
    out = base.copy().convert("RGBA")
    patch_rgba = patch.convert("RGBA")
    
    # Get paste coordinates
    x1, y1 = box[0], box[1]
    expected_w = box[2] - box[0]
    expected_h = box[3] - box[1]
    
    # Verify patch size matches expected crop size
    if patch_rgba.size != (expected_w, expected_h):
        print(f"Warning: Patch size {patch_rgba.size} doesn't match expected {(expected_w, expected_h)}. Resizing.")
        patch_rgba = patch_rgba.resize((expected_w, expected_h), Image.Resampling.LANCZOS)
    

    out.paste(patch_rgba, (x1, y1), patch_rgba if patch_rgba.mode == "RGBA" else None)
    
    return out


# ----------------------------
# OpenAI image edit call (masked inpainting)
# ----------------------------
def openai_inpaint_patch(
    base_img: Image.Image,
    patch_img: Image.Image,
    patch_mask: Image.Image,
    prompt: str,
    size: Optional[str] = None,
) -> Image.Image:
    """
    Calls the OpenAI Images API edit with model gpt-image-1.5.
    - patch_mask must be RGBA with transparency defining editable region.

    Docs: image generation / images API reference :contentReference[oaicite:2]{index=2}
    """
    # Ensure RGBA + PNG for alpha mask semantics
    patch_img_rgba = patch_img.convert("RGBA")
    patch_mask_rgba = patch_mask.convert("RGBA")

    # Use temporary files to ensure correct mimetype detection
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file, \
         tempfile.NamedTemporaryFile(suffix=".png", delete=False) as mask_file:
        patch_img_rgba.save(img_file.name, format="PNG")
        patch_mask_rgba.save(mask_file.name, format="PNG")
        
        img_path = img_file.name
        mask_path = mask_file.name

    try:
        # size: if you omit, it uses input image size; you can also set e.g. "1024x1024"
        # NOTE: Keep patch sizes reasonable; very tiny patches can behave oddly.
        with open(img_path, "rb") as img_f, open(mask_path, "rb") as mask_f:
            resp = ai_client.images.edit(
                model="gpt-image-1.5",
                image=img_f,
                mask=mask_f,
                prompt=prompt,
                # size=size,  # optionally force a target; usually best to keep same as patch
            )
    finally:
        # Clean up temporary files
        try:
            os.unlink(img_path)
            os.unlink(mask_path)
        except OSError:
            pass

    # Response contains base64 image in resp.data[0].b64_json (common for Images API)
    b64 = resp.data[0].b64_json
    edited_bytes = base64.b64decode(b64)
    return Image.open(io.BytesIO(edited_bytes)).convert("RGBA")


# ----------------------------
# Local refinement loop (box-level)
# ----------------------------
def refine_with_local_inpainting(
    base_img: Image.Image,
    issues: List[BoxIssue],
    pad: int = 32,
    max_passes: int = 1,
) -> Image.Image:

    img = base_img.convert("RGBA")
    W, H = img.size

    for _ in range(max_passes):
        for issue in issues:
            # First clamp the original issue box to image bounds
            issue_box = clamp_box((issue.x1, issue.y1, issue.x2, issue.y2), W, H)
            
            # Expand to get patch box (this will be clamped by expand_box)
            # NOTE: We expand from the clamped issue_box, which is correct because
            # we want context around the visible part of the issue
            patch_box = expand_box(issue_box, pad=pad, w=W, h=H)

            # Crop patch
            patch = crop_patch(img, patch_box)
            patch_w, patch_h = patch.size

            # Build a patch-local mask: transparent only in the issue area (within the patch)
            # Convert full-image issue_box to patch-local coordinates
            # CRITICAL: Compute the intersection of issue_box with patch_box in patch-local coords
            # This handles cases where patch_box was clamped at edges
            px1 = max(0, issue_box[0] - patch_box[0])
            py1 = max(0, issue_box[1] - patch_box[1])
            px2 = min(patch_w, issue_box[2] - patch_box[0])
            py2 = min(patch_h, issue_box[3] - patch_box[1])
            
            # Ensure valid box dimensions (at least 1x1 pixel)
            if px2 <= px1:
                px2 = min(patch_w, px1 + 1)
            if py2 <= py1:
                py2 = min(patch_h, py1 + 1)
            
            # Final bounds check - ensure coordinates are within patch
            px1 = max(0, min(px1, patch_w - 1))
            py1 = max(0, min(py1, patch_h - 1))
            px2 = max(px1 + 1, min(px2, patch_w))
            py2 = max(py1 + 1, min(py2, patch_h))

            patch_mask = make_box_mask_rgba(patch.size, (px1, py1, px2, py2))

            # Strongly anchor surrounding context in the prompt to reduce drift
            # (Your diagrams benefit from very explicit "keep everything else identical" constraints.)
            patch_prompt = (
                "You are editing a small cropped patch of an academic infographic diagram.\n\n"
                "STRICT RULES:\n"
                "- Only change pixels inside the transparent mask region.\n"
                "- Keep all text outside the mask unchanged.\n"
                "- Do not introduce new elements.\n\n"
                f"PATCH EDIT INSTRUCTION:\n{issue.prompt}\n"
            )

            edited_patch = openai_inpaint_patch(
                base_img=base_img,
                patch_img=patch,
                patch_mask=patch_mask,
                prompt=patch_prompt,
            )
            
            # Verify the edited patch size matches the original patch
            if edited_patch.size != patch.size:
                print(f"Warning: Edited patch size {edited_patch.size} != original patch size {patch.size}")
                # Resize to match if needed
                edited_patch = edited_patch.resize(patch.size, Image.Resampling.LANCZOS)

            # Paste back - this should preserve the full image with the edited region
            img = paste_patch(img, edited_patch, patch_box)
            
            # Verify the image size is still correct after pasting
            if img.size != (W, H):
                print(f"ERROR: Image size changed from {(W, H)} to {img.size} after pasting patch!")
                # This should never happen - if it does, there's a serious bug
                raise ValueError(f"Image size mismatch: expected {(W, H)}, got {img.size}")
            return img
    # # Final validation: ensure output size matches input
    # if img.size != (W, H):
    #     print(f"ERROR: Final image size {img.size} doesn't match input size {(W, H)}!")
    #     raise ValueError(f"Output image size mismatch: expected {(W, H)}, got {img.size}")
    
    # return img


# ----------------------------
# Example usage
# ----------------------------
import os
import asyncio
from image_optimizer import criticize_image_with_render_text

if __name__ == "__main__":
    # Load your base image
    request_dir = os.path.join(os.path.dirname(__file__), "images", "1768957244")
    image_path = os.path.join(request_dir, "m.png")
    base = Image.open(image_path).convert("RGBA")

    # criticism = asyncio.run(criticize_image_with_render_text(ai_client, request_dir, image_path))
    with open(os.path.join(request_dir, "issues.json"), "r") as f:
        criticism = json.load(f)

    new_issues = []
    for issue in criticism:
        box = issue["bbox"]
        prompt = issue["patch_instruction"]
        new_issues.append(BoxIssue(
            id=issue["issue_type"],
            x1=box[0],
            y1=box[1],
            x2=box[2],
            y2=box[3],
            prompt=prompt
        ))

    out = refine_with_local_inpainting(base, new_issues, pad=145, max_passes=1)
    out.save(os.path.join(request_dir, "refined.png"))
    print("Saved refined.png")




def draw_issue_on_image(request_dir: str, image_path: str, issues: Dict[str, Any]):
    from PIL import Image, ImageDraw

    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0,0,0,0))
    draw = ImageDraw.Draw(overlay)

    for issue in issues:
        box = issue["bbox"]
        draw.rectangle(
            [box[0], box[1], box[2], box[3]],
            outline=(255,0,0,255),
            width=4
        )
        draw.text((box[0], box[1]-20), issue["id"], fill=(255,0,0,255))
    Image.alpha_composite(img, overlay).save(os.path.join(request_dir, "diagnostic.png"))



async def criticize_image_with_location(ai_client, request_dir: str, image_path: str, overflow_check: bool = False, missing_step_check: bool = False):
    # Find layer3_render.txt file (could be layer3_render.txt or layer3_render_1.txt)
    layer3_render_path = None
    possible_names = ["layer3_render.txt", "layer3_render_01.txt", "layer_3_render.txt"]
    for name in possible_names:
        path = os.path.join(request_dir, name)
        print(path)
        if os.path.exists(path):
            layer3_render_path = path
            break
    
    if not layer3_render_path:
        raise Exception(
            status_code=404,
            detail=f"Layer3 render file not found in {request_dir}. Looked for: {possible_names}"
        )
    
    # load the ground truth render blueprint
    with open(layer3_render_path, 'r', encoding='utf-8') as f:
        ground_truth_render_blueprint = f.read()

    # critize the image with the ground_truth, return the a list of issues
    system_prompt = """You are an expert at analyzing academic infographic images and extracting all visible text content with high accuracy."""

    img = Image.open(image_path)
    W, H = img.size

    user_prompt = f"""You are analyzing an academic infographic image based on the RENDER_BLUEPRINT.

    RENDER_BLUEPRINT:
    {ground_truth_render_blueprint}

    TASK:
    1. Identify all violations of the RENDER_BLUEPRINT.
    2. For each violation, localize it with a tight bounding box.

    COORDINATE SYSTEM:
    - Image resolution: {W} × {H} pixels
    - Origin (0,0) is top-left
    - x increases to the right, y increases downward

    OUTPUT FORMAT:
    [
        {{
            "id": "string",
            "issue_type": "missing_text | wrong_label | layout_error | arrow_error | legend_error | other",
            "description": "what is wrong",
            "patch_instruction": "exact instruction for image editor",
            "bbox": [
                "x1": int,
                "y1": int,
                "x2": int,
                "y2": int
            ]
        }},
    ]
    MUST START WITH A OPENING BRACKET.
    MUST END WITH A CLOSING BRACKET.
    """
    attemps = 3
    for attempt in range(attemps):
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
            image_format = "png"
            
            messages = [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/{image_format};base64,{base64_image}"
                            }
                        }
                    ]
                }
            ]
            
            # Run in thread pool for async execution
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="gemini-3-flash-preview",
                messages=messages,
                temperature=0.2,
                response_format={"type": "text"}
            )       
            result_content = response.choices[0].message.content

            if result_content is None or result_content.strip() == "":
                logger.error(f"No content returned from the model")
                continue

            if overflow_check or missing_step_check:
                return result_content

            try:
                if result_content.startswith("```json"):
                    result_content = result_content[7:  -3]
                if result_content.endswith("```"):
                    result_content = result_content[3 : -3]
                result_content = result_content.strip()
                try:    
                    extracted_text = json.loads(result_content)
                    return extracted_text
                except json.JSONDecodeError as e:
                    if attempt < attemps:
                        logger.error(f"JSON decode error: {str(e)}, retrying...")
                        continue
                    raise e
            except Exception as e:
                if attempt < attemps:
                    logger.error(f"Error criticizing image: {str(e)}, retrying...")
                    continue
                raise e
        except Exception as e:
            if attempt < attemps:
                logger.error(f"Error criticizing image: {str(e)}, retrying...")
                continue
            raise e

