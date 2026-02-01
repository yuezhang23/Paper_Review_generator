import base64
import os
import time
import traceback
import logging
import httpx
from fastapi import HTTPException, APIRouter
from .image_method_generator import (
    ImageGenerationRequest,
    resolve_pdf_and_index,
    retrieve_methodology_chunks,
    combine_and_validate_chunks,
    generate_interpretation,
    save_interpretation_and_create_request_dir,
    generate_whiteboard_prompt,
    generate_image,
    is_image_model,
)
from utils import get_ai_client, get_ai_builder_base_url, file_storage, ensure_file_info_from_main_backend

router = APIRouter(prefix="/api", tags=["image-generation"])
logger = logging.getLogger(__name__)


def _get_image_graph():
    """Lazy-load LangGraph image agent (uses gateway config, calls LiteLLM for images)."""
    from orchestrator_backup.config import load_gateway_config
    from orchestrator_backup.graph import build_image_agent_graph
    cfg_path = os.getenv("MCP_GATEWAY_CONFIG_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "orchestrator_backup",
        "mcp_gateway_config.yaml",
    )
    cfg = load_gateway_config(cfg_path)
    return build_image_agent_graph(cfg)


def _resolve_file_ids_to_pdf_path(file_ids: list) -> str | None:
    """Resolve first file_id to pdf_path from file_storage (for gateway proxy)."""
    for fid in (file_ids or []):
        if fid in file_storage:
            info = file_storage[fid]
            path = info.get("pdf_path")
            if path and os.path.exists(path):
                return path
    return None


async def _proxy_to_gateway_agent(request: ImageGenerationRequest) -> dict:
    """Proxy image generation to orchestrator gateway LangGraph agent. Only when running on main backend (8000)."""
    # When MAIN_BACKEND_URL is set, we're the gateway (8010) - run locally, don't proxy to self
    if os.getenv("MAIN_BACKEND_URL"):
        return None
    use_gateway = os.getenv("USE_GATEWAY_ORCHESTRATOR", "").lower() in ("true", "1", "yes")
    if not use_gateway:
        return None

    token = (
        os.getenv("AI_BUILDER_TOKEN")
        or os.getenv("MCP_GATEWAY_TOKEN")
        or os.getenv("LITELLM_PROXY_KEY")
    )
    if not token:
        logger.warning(
            "USE_GATEWAY_ORCHESTRATOR set but no AI_BUILDER_TOKEN, MCP_GATEWAY_TOKEN, or LITELLM_PROXY_KEY"
        )
        return None

    base = get_ai_builder_base_url()
    gateway_base = base.replace("/backend/v1", "").rstrip("/")
    url = f"{gateway_base}/backend/v1/agents/methodology/summary-image"

    # Resolve file_ids -> pdf_path (gateway process has empty file_storage)
    body = request.model_dump(exclude_none=True)
    if request.file_ids and not body.get("pdf_path"):
        pdf_path = _resolve_file_ids_to_pdf_path(request.file_ids)
        if pdf_path:
            body["pdf_path"] = pdf_path
            body.pop("file_ids", None)  # Gateway can't resolve file_ids; use pdf_path only
        else:
            logger.warning("Could not resolve file_ids to pdf_path, gateway may fail")

    async with httpx.AsyncClient(timeout=900.0) as client:
        r = await client.post(
            url,
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text or "Gateway agent error")
        data = r.json()
        return {
            "image_url": data.get("image_url"),
            "image_bytes": None,
            "revised_prompt": data.get("revised_prompt"),
            "methodology_steps": data.get("methodology_steps"),
        }


@router.post("/generate-summary-image")
async def generate_summary_image(request: ImageGenerationRequest):
    function_start_time = time.time()
    try:
        # When on gateway (8010), fetch file info from main backend (8000) for file_ids
        if request.file_ids:
            await ensure_file_info_from_main_backend(request.file_ids)
        
        # When using gateway orchestrator (and we're on main backend), proxy to LangGraph agent
        proxy_result = await _proxy_to_gateway_agent(request)
        if proxy_result is not None:
            logger.info(f"generate_summary_image proxied to gateway, elapsed: {time.time() - function_start_time:.2f}s")
            return proxy_result

        # When on gateway (8010), use LangGraph so step 7 calls LiteLLM directly (not gateway /images/generations)
        # LangGraph decides image model via config.resolve_model(..., "image")
        if os.getenv("MAIN_BACKEND_URL"):
            try:
                image_graph = _get_image_graph()
            except RuntimeError as e:
                if "Missing API key" in str(e):
                    raise HTTPException(
                        status_code=503,
                        detail="Image pipeline unavailable: set LITELLM_PROXY_KEY (or provider API key) and retry.",
                    ) from e
                raise
            req_dict = request.model_dump(exclude_none=True)
            state = {"request": req_dict, "model": request.model}
            out = await image_graph.ainvoke(state)
            image_bytes_b64 = out.get("image_bytes_b64") or ""
            total_elapsed_time = time.time() - function_start_time
            logger.info(f"generate_summary_image (LangGraph) total execution time: {total_elapsed_time:.2f} seconds")
            return {
                "image_url": out.get("image_url"),
                "image_bytes_b64": image_bytes_b64,
                "revised_prompt": out.get("whiteboard_prompt"),
                "methodology_steps": out.get("interpretation_preview"),
            }

        # Direct pipeline (standalone, no gateway)
        # Step 1: Resolve PDF path and build/load RAG index
        pdf_path, index, cache_key = await resolve_pdf_and_index(request)
        
        # Step 2: Retrieve methodology chunks (with parallelized queries)
        method_zone_chunks, detail_chunks = await retrieve_methodology_chunks(cache_key, index)
        
        # Step 3: Combine and validate chunks
        retrieved_content = combine_and_validate_chunks(method_zone_chunks, detail_chunks)
        
        # Step 4: Generate step-by-step interpretation using AI (with parallelized calls)
        ai_client = get_ai_client()
        text_model = getattr(request, "model", None)
        interpretation_preview = await generate_interpretation(ai_client, retrieved_content, model=text_model)
        
        # Step 5: Save interpretation and create request directory
        request_dir, interpretation_path = save_interpretation_and_create_request_dir(interpretation_preview)
        
        # Step 6: Generate whiteboard diagram prompt (ai_client from gateway/standalone)
        whiteboard_prompt = await generate_whiteboard_prompt(
            interpretation_path, request_dir, ai_client=ai_client, model=text_model
        )
        
        # Step 7: Generate and save image (use request.model only if it is an image model; else use default)
        # vision_model for ranking: use text model if request has one, else generate_image uses DEFAULT_VISION_MODEL
        request_model = getattr(request, "model", None)
        image_model = request_model if is_image_model(request_model) else None
        vision_model = request_model if (request_model and not is_image_model(request_model)) else None
        image_bytes, image_url = await generate_image(
            ai_client,
            whiteboard_prompt,
            request_dir,
            criticize_image=True,
            model=image_model,
            vision_model=vision_model,
        )
        
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time: {total_elapsed_time:.2f} seconds")
        image_bytes_b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else ""
        return {
            "image_url": image_url,
            "image_bytes_b64": image_bytes_b64,
            "revised_prompt": whiteboard_prompt,
            "methodology_steps": interpretation_preview,
        }

    except HTTPException:
        total_elapsed_time = time.time() - function_start_time
        logger.info(f"generate_summary_image total execution time (HTTPException): {total_elapsed_time:.2f} seconds")
        raise
    except Exception as e:
        total_elapsed_time = time.time() - function_start_time
        logger.error(f"Error generating image: {str(e)}\n{traceback.format_exc()}")
        logger.info(f"generate_summary_image total execution time (Exception): {total_elapsed_time:.2f} seconds")
        raise HTTPException(
            status_code=500,
            detail=f"Error generating image: {str(e)}"
        )
