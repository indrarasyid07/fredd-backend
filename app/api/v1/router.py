"""Every /api/v1 feature router, with its prefix and tag, in one place."""

from fastapi import APIRouter

from app.api.v1 import (
    agent,
    audit_logs,
    auth,
    bots,
    dashboard,
    extension_workers,
    form_templates,
    forms,
    invites,
    join_codes,
    members,
    reference_data,
    reports,
    system,
    workspaces,
)

router = APIRouter(prefix="/api/v1")
router.include_router(system.router, tags=["system"])
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(workspaces.router, prefix="/workspace", tags=["workspace"])
router.include_router(members.router, prefix="/members", tags=["members"])
router.include_router(invites.router, prefix="/invites", tags=["invites"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])
router.include_router(bots.router, prefix="/bots", tags=["bots"])
router.include_router(agent.router, prefix="/agent", tags=["agent"])
router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
router.include_router(reference_data.router, prefix="/reference-data", tags=["reference-data"])
router.include_router(forms.router, prefix="/forms", tags=["forms"])
router.include_router(form_templates.router, prefix="/form-templates", tags=["forms"])
router.include_router(join_codes.router, prefix="/forms", tags=["join-codes"])
router.include_router(
    extension_workers.router, prefix="/extension-workers", tags=["extension-workers"]
)
router.include_router(reports.router, prefix="/reports", tags=["reports"])
