"""
Template library endpoints — /api/v1/templates
════════════════════════════════════════════════════════════════════════════════
Provides a read-only catalogue of pre-built agents and workflows that users
can discover and clone into their own account.

Endpoints
─────────
GET  /api/v1/templates/agents
     ?category=Sales&sort=popularity&q=lead
     Returns {items, categories, total}

GET  /api/v1/templates/workflows
     ?category=Sales&sort=popularity&q=pipeline
     Returns {items, categories, total}

GET  /api/v1/templates/agents/{template_id}
     Returns a single agent template

GET  /api/v1/templates/workflows/{template_id}
     Returns a single workflow template

POST /api/v1/templates/agents/{template_id}/clone
     Creates a real Agent from the template for the current user
     Returns: BackendAgent (same shape as /api/v1/agents)

POST /api/v1/templates/workflows/{template_id}/clone
     Creates a real Workflow from the template for the current user
     Returns: BackendWorkflow (same shape as /api/v1/workflows)
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_found
from app.models.db_session import get_db
from app.models.schemas import AgentCreate, WorkflowCreate
from app.services import agent_service, workflow_service

router = APIRouter(prefix="/templates", tags=["templates"])

_STUB_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

# ── Data loading ──────────────────────────────────────────────────────────────

_TEMPLATES_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "templates"


def _load_json(filename: str) -> List[Dict[str, Any]]:
    path = _TEMPLATES_DIR / filename
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _get_agent_templates() -> List[Dict[str, Any]]:
    return _load_json("agents.json")


def _get_workflow_templates() -> List[Dict[str, Any]]:
    return _load_json("workflows.json")


def _find_template(templates: List[Dict], template_id: str) -> Optional[Dict[str, Any]]:
    return next((t for t in templates if t["id"] == template_id), None)


# ── Sort helpers ──────────────────────────────────────────────────────────────

def _sort_key(item: Dict, sort: str) -> Any:
    if sort == "popularity":
        return -(item.get("popularity", 0))
    if sort == "rating":
        return -(item.get("rating", 0))
    if sort == "name":
        return item.get("name", "").lower()
    return 0  # default — no sort


# ── Pydantic-free response models (dicts returned directly) ───────────────────
# FastAPI serialises plain dicts fine; no need for extra Pydantic classes here.


# ══════════════════════════════════════════════════════════════════════════════
# Agent template endpoints
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/agents",
    summary="List agent templates",
    response_model=None,
)
async def list_agent_templates(
    category: Optional[str] = Query(default=None, description="Filter by category"),
    sort: str = Query(default="popularity", description="Sort by: popularity | rating | name"),
    q: Optional[str] = Query(default=None, description="Search query"),
) -> Dict[str, Any]:
    templates = _get_agent_templates()

    # Filter
    if category and category.lower() != "all":
        templates = [t for t in templates if t.get("category", "").lower() == category.lower()]
    if q:
        q_lower = q.lower()
        templates = [
            t for t in templates
            if q_lower in t.get("name", "").lower()
            or q_lower in t.get("description", "").lower()
            or any(q_lower in tag.lower() for tag in t.get("tags", []))
        ]

    # Sort
    templates = sorted(templates, key=lambda t: _sort_key(t, sort))

    # Collect distinct categories from the original set
    all_templates = _get_agent_templates()
    categories = sorted({t.get("category", "Uncategorized") for t in all_templates})

    return {
        "total": len(templates),
        "items": templates,
        "categories": ["All"] + categories,
    }


@router.get(
    "/agents/{template_id}",
    summary="Get single agent template",
    response_model=None,
)
async def get_agent_template(template_id: str) -> Dict[str, Any]:
    template = _find_template(_get_agent_templates(), template_id)
    if not template:
        raise not_found("Agent template")
    return template


@router.post(
    "/agents/{template_id}/clone",
    status_code=status.HTTP_201_CREATED,
    summary="Clone agent template into user account",
    response_model=None,
)
async def clone_agent_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    template = _find_template(_get_agent_templates(), template_id)
    if not template:
        raise not_found("Agent template")

    # Validate required fields with the existing schema
    try:
        payload = AgentCreate(
            name=f"{template['name']} (Copy)",
            role=template.get("role", "analyst"),
            system_prompt=template["system_prompt"],
            model=template.get("model", "claude-sonnet-4-6"),
            tools=template.get("tools", []),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TEMPLATE_INVALID", "message": str(exc)},
        )

    agent = await agent_service.create_agent(db, _STUB_USER_ID, payload)

    return {
        "id": str(agent.id),
        "user_id": str(agent.user_id),
        "name": agent.name,
        "role": agent.role,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "status": agent.status,
        "tools": agent.tools,
        "created_at": agent.created_at.isoformat(),
        "cloned_from": template_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Workflow template endpoints
# ══════════════════════════════════════════════════════════════════════════════


@router.get(
    "/workflows",
    summary="List workflow templates",
    response_model=None,
)
async def list_workflow_templates(
    category: Optional[str] = Query(default=None),
    sort: str = Query(default="popularity"),
    q: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    templates = _get_workflow_templates()

    if category and category.lower() != "all":
        templates = [t for t in templates if t.get("category", "").lower() == category.lower()]
    if q:
        q_lower = q.lower()
        templates = [
            t for t in templates
            if q_lower in t.get("name", "").lower()
            or q_lower in t.get("description", "").lower()
            or any(q_lower in tag.lower() for tag in t.get("tags", []))
        ]

    templates = sorted(templates, key=lambda t: _sort_key(t, sort))

    all_templates = _get_workflow_templates()
    categories = sorted({t.get("category", "Uncategorized") for t in all_templates})

    return {
        "total": len(templates),
        "items": templates,
        "categories": ["All"] + categories,
    }


@router.get(
    "/workflows/{template_id}",
    summary="Get single workflow template",
    response_model=None,
)
async def get_workflow_template(template_id: str) -> Dict[str, Any]:
    template = _find_template(_get_workflow_templates(), template_id)
    if not template:
        raise not_found("Workflow template")
    return template


@router.post(
    "/workflows/{template_id}/clone",
    status_code=status.HTTP_201_CREATED,
    summary="Clone workflow template into user account",
    response_model=None,
)
async def clone_workflow_template(
    template_id: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    template = _find_template(_get_workflow_templates(), template_id)
    if not template:
        raise not_found("Workflow template")

    dag_config = template.get("dag_config", {})
    # Strip agent_template_id hints — callers must wire real agent IDs themselves
    if "nodes" in dag_config:
        cleaned_nodes = [
            {k: v for k, v in node.items() if k != "agent_template_id"}
            for node in dag_config["nodes"]
        ]
        dag_config = {**dag_config, "nodes": cleaned_nodes}

    try:
        payload = WorkflowCreate(
            name=f"{template['name']} (Copy)",
            dag_config=dag_config,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "TEMPLATE_INVALID", "message": str(exc)},
        )

    workflow = await workflow_service.create_workflow(db, _STUB_USER_ID, payload)

    return {
        "id": str(workflow.id),
        "user_id": str(workflow.user_id),
        "name": workflow.name,
        "dag_config": workflow.dag_config,
        "is_active": workflow.is_active,
        "created_at": workflow.created_at.isoformat(),
        "cloned_from": template_id,
    }
