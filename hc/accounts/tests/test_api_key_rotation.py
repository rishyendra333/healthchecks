from __future__ import annotations

from datetime import timedelta as td

from django.utils.timezone import now

from hc.accounts.models import Project
from hc.test import BaseTestCase


class ApiKeyRotationTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.old_key = self.project.set_api_key()
        self.project.save()
        self.url = f"/projects/{self.project.code}/settings/"

    def test_rotation_keeps_old_key_valid(self) -> None:
        new_key = self.project.rotate_api_key()
        self.project.save()

        found = Project.objects.for_api_key(new_key, accept_rw=True, accept_ro=False)
        self.assertEqual(found, self.project)

        found = Project.objects.for_api_key(self.old_key, accept_rw=True, accept_ro=False)
        self.assertEqual(found, self.project)

    def test_old_key_expires(self) -> None:
        self.project.rotate_api_key(grace=td(hours=1))
        self.project.api_key_previous_expires = now() - td(seconds=1)
        self.project.save()

        found = Project.objects.for_api_key(self.old_key, accept_rw=True, accept_ro=False)
        self.assertIsNone(found)

    def test_rotating_legacy_key(self) -> None:
        self.project.api_key = "X" * 32
        self.project.save()

        self.project.rotate_api_key()
        self.project.save()

        found = Project.objects.for_api_key("X" * 32, accept_rw=True, accept_ro=False)
        self.assertEqual(found, self.project)

    def test_previous_key_is_not_readonly_key(self) -> None:
        self.project.rotate_api_key()
        self.project.save()

        found = Project.objects.for_api_key(self.old_key, accept_rw=False, accept_ro=True)
        self.assertIsNone(found)

    def test_view_rotates_key(self) -> None:
        self.client.login(username="alice@example.org", password="password")
        r = self.client.post(self.url, {"create_key": "api_key"})
        self.assertContains(r, "The previous API key keeps working until")

        self.project.refresh_from_db()
        self.assertTrue(self.project.api_key_previous)
        assert self.project.api_key_previous_expires
        self.assertTrue(self.project.api_key_previous_expires > now())

    def test_view_create_without_existing_key(self) -> None:
        self.project.api_key = ""
        self.project.save()

        self.client.login(username="alice@example.org", password="password")
        r = self.client.post(self.url, {"create_key": "api_key"})
        self.assertNotContains(r, "The previous API key keeps working until")
