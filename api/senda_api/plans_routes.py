"""`/api/plans*`: the plans a browser saved, kept in Postgres under its cookie label.

A plan is made again on the server from the request, together with the fire card at the same pass, so the saved
record shows the fire as it was when the plan was made. There is no sending of a plan.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from . import fires_routes, plan
from .chat.store import stamp
from .client import carry, client_of
from .contracts import FireDetail, FirePlan, Out, ok
from .errors import ApiError, SafeJSONResponse, clean
from .models import Plan

router = APIRouter(prefix="/api/plans", tags=["api"])

MAX_PLANS = 100
PLAN_ID = Annotated[int, Path(ge=1, le=2**62)]


class NewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fire_id: str = Field(min_length=1, max_length=64)
    title: str = Field(default="", max_length=200)
    request: plan.PlanRequest = Field(description="The plan is made again from this, on the server.")


class PlanListItem(Out):
    id: int
    title: str
    fire_id: str
    near: str = Field(description="Name of the place nearest to the fire.")
    crews: int
    hours: int
    created_at: str


class PlanRecord(Out):
    """A saved plan, with the fire as it was when the plan was made."""

    id: int
    title: str
    fire_id: str
    created_at: str
    request: plan.PlanRequest
    plan: FirePlan
    fire: FireDetail


def _record(row: Plan) -> dict:
    return {"id": row.id, "title": row.title, "fire_id": row.fire_id, "created_at": stamp(row.created_at),
            "request": row.request, **row.response}


def _item(row: Plan) -> dict:
    place = row.response["fire"]["summary"].get("nearest_place") or {}
    return {"id": row.id, "title": row.title, "fire_id": row.fire_id, "near": place.get("name", ""),
            "crews": row.request["crews"], "hours": row.request["hours"], "created_at": stamp(row.created_at)}


@router.get("", responses=ok(list[PlanListItem]))
def list_plans(request: Request, response: Response):
    client = client_of(request, response)
    with request.app.state.db.session() as s:
        rows = s.scalars(select(Plan).where(Plan.client_id == client).order_by(Plan.created_at.desc()))
        return [_item(r) for r in rows]


@router.post("", status_code=201, responses={201: {"model": PlanRecord}})
def save_plan(request: Request, response: Response, body: NewPlan):
    client = client_of(request, response)
    db = request.app.state.db
    with db.session() as s:
        if (s.scalar(select(func.count()).select_from(Plan).where(Plan.client_id == client)) or 0) >= MAX_PLANS:
            raise ApiError(409, "conflict", f"At most {MAX_PLANS} saved plans: delete one first")
    made = clean(fires_routes.fire_plan(request, body.fire_id, body.request))
    card = clean(fires_routes.fire_card(request, body.fire_id, made["pass_index"]))
    with db.session() as s:
        row = Plan(client_id=client, fire_id=body.fire_id, title=body.title,
                   request=body.request.model_dump(mode="json", by_alias=True),
                   response={"plan": made, "fire": card})
        s.add(row)
        s.flush()
        s.refresh(row)
        return carry(response, SafeJSONResponse(_record(row), status_code=201))


@router.get("/{plan_id}", responses=ok(PlanRecord))
def get_plan(request: Request, response: Response, plan_id: PLAN_ID):
    client = client_of(request, response)
    with request.app.state.db.session() as s:
        row = s.scalar(select(Plan).where(Plan.id == plan_id, Plan.client_id == client))
        if row is None:
            raise ApiError(404, "not_found", "No such plan")
        return _record(row)


@router.delete("/{plan_id}", status_code=204)
def delete_plan(request: Request, response: Response, plan_id: PLAN_ID):
    client = client_of(request, response)
    with request.app.state.db.session() as s:
        if s.execute(delete(Plan).where(Plan.id == plan_id, Plan.client_id == client)).rowcount == 0:
            raise ApiError(404, "not_found", "No such plan")
    return carry(response, Response(status_code=204))
