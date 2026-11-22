from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import WorkspaceContext, current_user, get_repo, workspace_access
from app.repository import DuplicateError, Repository
from app.schemas import MemberAdd, MemberRoleUpdate, WorkspaceCreate

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


def _ws_out(w: dict) -> dict:
    return {"id": str(w["id"]), "name": w["name"], "slug": w["slug"], "role": w["role"], "is_demo": w["is_demo"]}


@router.get("")
def list_workspaces(user: dict = Depends(current_user), repo: Repository = Depends(get_repo)):
    return [_ws_out(w) for w in repo.list_workspaces_for_user(user["id"])]


@router.post("", status_code=201)
def create_workspace(body: WorkspaceCreate, user: dict = Depends(current_user), repo: Repository = Depends(get_repo)):
    ws = repo.create_workspace(user["id"], body.name)
    repo.audit(ws["id"], user["id"], "workspace.create", "workspace", str(ws["id"]))
    return _ws_out(ws)


@router.get("/{workspace_id}")
def get_workspace(ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    m = repo.get_membership(ctx.workspace_id, ctx.user["id"])
    return {"id": str(ctx.workspace_id), "name": m["name"], "slug": m["slug"], "role": ctx.role, "is_demo": ctx.is_demo}


@router.get("/{workspace_id}/members")
def list_members(ctx: WorkspaceContext = Depends(workspace_access("viewer")), repo: Repository = Depends(get_repo)):
    return [{"user_id": str(m["user_id"]), "email": m["email"], "display_name": m["display_name"], "role": m["role"]}
            for m in repo.list_members(ctx.workspace_id)]


@router.post("/{workspace_id}/members", status_code=201)
def add_member(body: MemberAdd, ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    if body.role == "owner" and ctx.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can grant the owner role")
    try:
        member = repo.add_member_by_email(ctx.workspace_id, body.email, body.role)
    except DuplicateError:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member") from None
    if member is None:
        # Invitation emails are not implemented; the user must sign up first.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with that email. Ask them to sign up first.")
    repo.audit(ctx.workspace_id, ctx.user["id"], "member.add", "user", str(member["user_id"]), {"role": body.role})
    return {"user_id": str(member["user_id"]), "email": member["email"], "role": member["role"]}


@router.patch("/{workspace_id}/members/{user_id}")
def change_role(user_id: uuid.UUID, body: MemberRoleUpdate,
                ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    target = repo.get_membership(ctx.workspace_id, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if (body.role == "owner" or target["role"] == "owner") and ctx.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can change owner roles")
    if target["role"] == "owner" and body.role != "owner" and repo.count_owners(ctx.workspace_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A workspace must keep at least one owner")
    repo.change_member_role(ctx.workspace_id, user_id, body.role)
    repo.audit(ctx.workspace_id, ctx.user["id"], "member.role_change", "user", str(user_id), {"role": body.role})
    return {"user_id": str(user_id), "role": body.role}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(user_id: uuid.UUID, ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    target = repo.get_membership(ctx.workspace_id, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if target["role"] == "owner" and (ctx.role != "owner" or repo.count_owners(ctx.workspace_id) <= 1):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the last owner or an owner without being owner")
    repo.remove_member(ctx.workspace_id, user_id)
    repo.audit(ctx.workspace_id, ctx.user["id"], "member.remove", "user", str(user_id))


@router.get("/{workspace_id}/audit-logs")
def audit_logs(ctx: WorkspaceContext = Depends(workspace_access("admin")), repo: Repository = Depends(get_repo)):
    return [{"id": str(a["id"]), "action": a["action"], "resource_type": a["resource_type"], "resource_id": a["resource_id"],
             "actor": a["actor_email"], "created_at": a["created_at"].isoformat()} for a in repo.list_audit(ctx.workspace_id)]
