"""POST /api/vision/fen: turn a board image into a FEN for the editor and analysis board."""

from __future__ import annotations

import asyncio
import time
from email import policy
from email.parser import BytesParser

from fastapi import APIRouter, HTTPException, Request

from .accounts import Viewer
from .coach_limits import QuotaCharge, limit_reached
from .monitoring import log_event
from .vision import (
    ALLOWED_MEDIA_TYPES,
    MAX_IMAGE_BYTES,
    VisionResult,
    VisionUnavailable,
    estimate_vision_cost,
    read_board_image,
    sniff_media_type,
)

router = APIRouter(prefix="/api/vision")


def _multipart_image(content_type: str, body: bytes) -> bytes:
    """Pull the first file part out of a multipart/form-data body.

    python-multipart is not a dependency, so parse with the standard library email parser.
    """
    message = BytesParser(policy=policy.HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise HTTPException(400, "Could not read the upload. Send the image as form field 'image'.")
    fallback: bytes | None = None
    for part in message.iter_parts():
        payload = part.get_payload(decode=True) or b""
        if part.get_param("name", header="content-disposition") == "image":
            return payload
        if part.get_filename() and fallback is None:
            fallback = payload
    if fallback is None:
        raise HTTPException(400, "No image found in the upload. Send it as form field 'image'.")
    return fallback


@router.post("/fen", response_model=VisionResult)
async def image_to_fen(request: Request, user_id: Viewer) -> VisionResult:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_IMAGE_BYTES + 64_000:
        raise HTTPException(413, "The image is larger than 5 MB.")
    body = await request.body()
    content_type = request.headers.get("content-type", "")
    image = _multipart_image(content_type, body) if content_type.startswith("multipart/") else body
    if not image:
        raise HTTPException(400, "The upload is empty.")
    if len(image) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "The image is larger than 5 MB.")
    media_type = sniff_media_type(image)
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(415, "Use a PNG, JPEG or WebP image.")

    charge = QuotaCharge(request, user_id, "vision")
    if not await asyncio.to_thread(charge.take):
        raise limit_reached(charge.scope)

    started = time.perf_counter()
    try:
        result = await read_board_image(image, media_type)
    except VisionUnavailable as exc:
        await asyncio.to_thread(charge.refund)
        raise HTTPException(503, "Board recognition needs OPENROUTER_API_KEY on the server.") from exc
    except TimeoutError as exc:
        await asyncio.to_thread(charge.refund)
        log_event("vision_fen_failed", {"error": "timeout", "bytes": len(image)})
        raise HTTPException(504, "Reading the board took too long. Try a tighter crop.") from exc
    except ValueError as exc:
        # The model did answer, and any photo can trigger this. It stays counted, or uploading
        # non-boards would be unlimited.
        log_event("vision_fen_failed", {"error": str(exc)[:300], "bytes": len(image)})
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        await asyncio.to_thread(charge.refund)
        reason = f"{type(exc).__name__}: {exc}"[:300]
        log_event("vision_fen_failed", {"error": reason, "bytes": len(image)})
        raise HTTPException(502, "The vision model could not read this image.") from exc

    log_event(
        "vision_fen",
        {
            "model": result.model,
            "media_type": media_type,
            "bytes": len(image),
            "valid": result.valid,
            "attempts": result.attempts,
            "confidence": result.confidence,
            "orientation": result.orientation,
            "warnings": len(result.warnings),
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "usage": {
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "estimated_cost_usd": estimate_vision_cost(result.input_tokens, result.output_tokens),
            },
        },
    )
    return result
