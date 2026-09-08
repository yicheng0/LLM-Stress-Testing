from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.auth import AuthUser, current_user
from backend.app.core.repository import Repository
from backend.app.core.vendor_billing import pricing_rule
from backend.app.core.vendor_endpoint_security import validate_vendor_endpoint
from backend.app.models.database import VendorTemplate
from backend.app.models.schemas import VendorTemplateCreate, VendorTemplateListOut, VendorTemplateOut, VendorTemplateUpdate

router = APIRouter(prefix="/api/vendor-templates", tags=["vendor-templates"])


def get_repository() -> Repository:
    from backend.app.main import repository

    return repository


def _config(template: VendorTemplate) -> dict:
    try:
        value = json.loads(template.config_json)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _out(template: VendorTemplate) -> VendorTemplateOut:
    config = _config(template)
    rule = pricing_rule(str(config.get("pricing_rule_id") or "")) or {}
    config["pricing_verified"] = bool(rule.get("verified"))
    config["pricing_source"] = rule.get("source")
    config["pricing_source_version"] = rule.get("source_version")
    return VendorTemplateOut(
        id=template.id,
        owner_username=template.owner_username,
        owner_role=template.owner_role,
        version=template.version,
        enabled=template.enabled,
        created_at=template.created_at,
        updated_at=template.updated_at,
        config=config,
    )


def _validate(payload: VendorTemplateCreate | VendorTemplateUpdate) -> None:
    rule = pricing_rule(payload.pricing_rule_id)
    if not rule:
        raise HTTPException(status_code=400, detail="价格规则不存在")
    if rule.get("protocol") != payload.api_protocol:
        raise HTTPException(status_code=400, detail="价格规则与 API 协议不匹配")
    try:
        validate_vendor_endpoint(payload.base_url, reference=False)
        validate_vendor_endpoint(payload.reference_base_url, reference=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=VendorTemplateListOut)
async def list_templates(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    enabled: bool | None = None,
    supplier_name: str | None = None,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> VendorTemplateListOut:
    total, rows = repository.list_vendor_templates(page, page_size, user, enabled, supplier_name)
    return VendorTemplateListOut(total=total, page=page, page_size=page_size, items=[_out(row) for row in rows])


@router.post("", response_model=VendorTemplateOut)
async def create_template(
    payload: VendorTemplateCreate,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> VendorTemplateOut:
    _validate(payload)
    return _out(repository.create_vendor_template(payload, user))


@router.get("/{template_id}", response_model=VendorTemplateOut)
async def get_template(
    template_id: str,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> VendorTemplateOut:
    template = repository.get_vendor_template(template_id, user)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _out(template)


@router.put("/{template_id}", response_model=VendorTemplateOut)
async def update_template(
    template_id: str,
    payload: VendorTemplateUpdate,
    user: AuthUser = Depends(current_user),
    repository: Repository = Depends(get_repository),
) -> VendorTemplateOut:
    _validate(payload)
    template = repository.update_vendor_template(template_id, payload, user)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _out(template)


async def _set_enabled(template_id: str, enabled: bool, user: AuthUser, repository: Repository) -> VendorTemplateOut:
    template = repository.set_vendor_template_enabled(template_id, enabled, user)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")
    return _out(template)


@router.post("/{template_id}/enable", response_model=VendorTemplateOut)
async def enable_template(template_id: str, user: AuthUser = Depends(current_user), repository: Repository = Depends(get_repository)) -> VendorTemplateOut:
    return await _set_enabled(template_id, True, user, repository)


@router.post("/{template_id}/disable", response_model=VendorTemplateOut)
async def disable_template(template_id: str, user: AuthUser = Depends(current_user), repository: Repository = Depends(get_repository)) -> VendorTemplateOut:
    return await _set_enabled(template_id, False, user, repository)
