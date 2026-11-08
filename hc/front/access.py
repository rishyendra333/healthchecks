"""Access checks for objects that belong to a project.

Every view that loads a check, an integration or a project by its code goes
through one of the functions here. Each one returns the object and a flag that
says whether the current user can modify it:

* superusers and the project's owner always have read-write access,
* team members have read-write access unless their role is read-only,
* everybody else gets a 404, so we don't reveal that the object exists.

Pass ``need="write"`` to get a 403 (PermissionDenied) for read-only members
instead of the flag.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest

from hc.accounts.models import Member, Project
from hc.api.models import Channel, Check

Need = Literal["read", "write"]


def _resolve_rw(request: HttpRequest, project: Project, need: Need) -> bool:
    """Return True if the user has read-write access to the project.

    Raise Http404 if the user has no access at all, and PermissionDenied if
    write access is needed but the user only has read access.
    """

    assert request.user.is_authenticated

    if request.user.is_superuser or request.user.id == project.owner_id:
        return True

    membership = Member.objects.filter(project=project, user=request.user).first()
    if membership is None:
        raise Http404()

    if need == "write" and not membership.is_rw:
        raise PermissionDenied

    return membership.is_rw


def check_for_user(
    request: HttpRequest,
    code: UUID,
    *,
    need: Need = "read",
    preload_owner_profile: bool = False,
) -> tuple[Check, bool]:
    """Return the check and the rw flag, if the current user has access.

    If `preload_owner_profile` is `True`, the returned check's
    project.owner.profile will be already loaded. This helps avoid extra SQL queries
    if the caller later looks up the project owner's check_limit or ping_log_limit.
    """

    q = Check.objects.select_related("project")
    if preload_owner_profile:
        q = q.select_related("project__owner__profile")

    try:
        check = q.get(code=code)
    except Check.DoesNotExist:
        raise Http404()

    return check, _resolve_rw(request, check.project, need)


def channel_for_user(
    request: HttpRequest, code: UUID, *, need: Need = "read"
) -> tuple[Channel, bool]:
    """Return the channel and the rw flag, if the current user has access."""

    try:
        channel = Channel.objects.select_related("project").get(code=code)
    except Channel.DoesNotExist:
        raise Http404()

    return channel, _resolve_rw(request, channel.project, need)


def project_for_user(
    request: HttpRequest, code: UUID, *, need: Need = "read"
) -> tuple[Project, bool]:
    """Return the project and the rw flag, if the current user has access."""

    try:
        project = Project.objects.get(code=code)
    except Project.DoesNotExist:
        raise Http404()

    return project, _resolve_rw(request, project, need)
