from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.doc_converter import CurlConvertError, convert_curl_to_openapi
from backend.app.models.schemas import CurlConvertOut, CurlConvertRequest

router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.post("/convert-curl", response_model=CurlConvertOut)
async def convert_curl(payload: CurlConvertRequest) -> CurlConvertOut:
    try:
        converted = convert_curl_to_openapi(
            curl=payload.curl,
            base_url=payload.base_url,
            title=payload.title,
        )
    except CurlConvertError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CurlConvertOut(
        protocol=converted.protocol,  # type: ignore[arg-type]
        method=converted.method,
        endpoint=converted.endpoint,
        model=converted.model,
        sanitized_curl=converted.sanitized_curl,
        openapi_yaml=converted.openapi_yaml,
        recognized_params=converted.recognized_params,
        unknown_params=converted.unknown_params,
        warnings=converted.warnings,
    )
