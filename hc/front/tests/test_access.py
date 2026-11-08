from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory

from hc.accounts.models import Member
from hc.api.models import Channel, Check
from hc.front.access import channel_for_user, check_for_user, project_for_user
from hc.test import BaseTestCase


class AccessTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check.objects.create(project=self.project)
        self.channel = Channel.objects.create(project=self.project, kind="email")

    def request_for(self, user):  # type: ignore
        request = RequestFactory().get("/")
        request.user = user
        return request

    def test_owner_has_rw(self) -> None:
        request = self.request_for(self.alice)
        check, rw = check_for_user(request, self.check.code, need="write")
        self.assertEqual(check, self.check)
        self.assertTrue(rw)

    def test_member_has_rw(self) -> None:
        request = self.request_for(self.bob)
        channel, rw = channel_for_user(request, self.channel.code)
        self.assertEqual(channel, self.channel)
        self.assertTrue(rw)

    def test_readonly_member_reads(self) -> None:
        self.bobs_membership.role = Member.Role.READONLY
        self.bobs_membership.save()

        request = self.request_for(self.bob)
        project, rw = project_for_user(request, self.project.code)
        self.assertEqual(project, self.project)
        self.assertFalse(rw)

    def test_readonly_member_cannot_write(self) -> None:
        self.bobs_membership.role = Member.Role.READONLY
        self.bobs_membership.save()

        request = self.request_for(self.bob)
        with self.assertRaises(PermissionDenied):
            check_for_user(request, self.check.code, need="write")

    def test_outsider_gets_404(self) -> None:
        request = self.request_for(self.charlie)
        with self.assertRaises(Http404):
            project_for_user(request, self.project.code)

    def test_superuser_has_rw(self) -> None:
        self.charlie.is_superuser = True
        self.charlie.save()

        request = self.request_for(self.charlie)
        _, rw = check_for_user(request, self.check.code, need="write")
        self.assertTrue(rw)
