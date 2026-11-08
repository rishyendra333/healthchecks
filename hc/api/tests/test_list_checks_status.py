from __future__ import annotations

from datetime import timedelta as td

from django.utils.timezone import now

from hc.api.models import Check
from hc.test import BaseTestCase, TestHttpResponse


class ListChecksStatusFilterTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.up = Check.objects.create(
            project=self.project, name="up", status="up", last_ping=now()
        )
        self.down = Check.objects.create(project=self.project, name="down", status="down")
        self.paused = Check.objects.create(
            project=self.project, name="paused", status="paused"
        )
        # Stored status is "up", but the grace period has started
        self.grace = Check.objects.create(
            project=self.project,
            name="grace",
            status="up",
            last_ping=now() - td(days=1, minutes=30),
        )

    def get(self, qs: str, v: int = 3) -> TestHttpResponse:
        return self.client.get(f"/api/v{v}/checks/{qs}", HTTP_X_API_KEY="X" * 32)

    def names(self, r: TestHttpResponse) -> set[str]:
        return {doc["name"] for doc in r.json()["checks"]}

    def test_it_filters_by_status(self) -> None:
        r = self.get("?status=down")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.names(r), {"down"})

    def test_it_accepts_multiple_statuses(self) -> None:
        r = self.get("?status=down&status=paused")
        self.assertEqual(self.names(r), {"down", "paused"})

    def test_it_uses_computed_status(self) -> None:
        r = self.get("?status=grace")
        self.assertEqual(self.names(r), {"grace"})

        r = self.get("?status=up")
        self.assertEqual(self.names(r), {"up"})

    def test_started_in_v1(self) -> None:
        self.up.last_start = now()
        self.up.save()

        r = self.get("?status=started", v=1)
        self.assertEqual(self.names(r), {"up"})

        # In v3, a running check reports its own status
        r = self.get("?status=started", v=3)
        self.assertEqual(self.names(r), set())

    def test_it_combines_with_tags(self) -> None:
        self.down.tags = "foo"
        self.down.save()
        self.paused.tags = "foo"
        self.paused.save()

        r = self.get("?status=down&tag=foo")
        self.assertEqual(self.names(r), {"down"})

    def test_it_rejects_unknown_status(self) -> None:
        r = self.get("?status=bogus")
        self.assertEqual(r.status_code, 400)

    def test_it_works_with_readonly_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        r = self.client.get("/api/v3/checks/?status=down", HTTP_X_API_KEY="R" * 32)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.names(r), {"down"})
