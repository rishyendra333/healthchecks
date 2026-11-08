from __future__ import annotations

from datetime import timedelta as td

from django.utils.timezone import now

from hc.api.models import Check, Flip
from hc.test import BaseTestCase


class BulkPauseTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.a = Check.objects.create(project=self.project, status="up", tags="foo")
        self.b = Check.objects.create(project=self.project, status="up", tags="foo bar")
        self.c = Check.objects.create(project=self.project, status="up", tags="baz")
        self.url = "/api/v3/checks/bulk/pause"

    def post(self, data: dict[str, object], api_key: str = "X" * 32):  # type: ignore
        return self.csrf_client.post(
            self.url, data, content_type="application/json", HTTP_X_API_KEY=api_key
        )

    def test_it_pauses_by_codes(self) -> None:
        r = self.post({"checks": [str(self.a.code), str(self.b.code)]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Access-Control-Allow-Origin"], "*")

        doc = r.json()
        self.assertEqual(doc["n_changed"], 2)
        self.assertEqual(len(doc["checks"]), 2)
        self.assertEqual(doc["checks"][0]["status"], "paused")

        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "paused")
        self.c.refresh_from_db()
        self.assertEqual(self.c.status, "up")

        # It should create one flip per paused check, already processed
        self.assertEqual(Flip.objects.count(), 2)
        self.assertFalse(Flip.objects.filter(processed=None).exists())

    def test_it_pauses_by_tag(self) -> None:
        r = self.post({"tag": "foo"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["n_changed"], 2)

        self.c.refresh_from_db()
        self.assertEqual(self.c.status, "up")

    def test_tag_filter_is_exact(self) -> None:
        Check.objects.create(project=self.project, status="up", tags="foobar")
        r = self.post({"tag": "foo"})
        self.assertEqual(r.json()["n_changed"], 2)

    def test_it_skips_already_paused(self) -> None:
        self.a.status = "paused"
        self.a.save()

        r = self.post({"checks": [str(self.a.code), str(self.b.code)]})
        self.assertEqual(r.json()["n_changed"], 1)
        self.assertEqual(Flip.objects.count(), 1)

    def test_it_clears_alert_after(self) -> None:
        self.a.alert_after = now() + td(hours=1)
        self.a.last_start = now()
        self.a.save()

        self.post({"checks": [str(self.a.code)]})
        self.a.refresh_from_db()
        self.assertIsNone(self.a.alert_after)
        self.assertIsNone(self.a.last_start)

    def test_it_requires_checks_or_tag(self) -> None:
        r = self.post({})
        self.assertEqual(r.status_code, 400)
        self.assertIn("checks or tag is required", r.json()["error"])

    def test_it_validates_uuids(self) -> None:
        r = self.post({"checks": ["not-a-uuid"]})
        self.assertEqual(r.status_code, 400)

    def test_it_validates_checks_type(self) -> None:
        r = self.post({"checks": "foo"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "json validation error: checks is not an array")

    def test_it_rejects_readonly_key(self) -> None:
        self.project.api_key_readonly = "R" * 32
        self.project.save()

        r = self.post({"tag": "foo"}, api_key="R" * 32)
        self.assertEqual(r.status_code, 401)

    def test_it_rejects_get(self) -> None:
        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 405)


class BulkResumeTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()

        self.a = Check.objects.create(project=self.project, status="paused", tags="foo")
        self.b = Check.objects.create(project=self.project, status="up", tags="foo")
        self.url = "/api/v3/checks/bulk/resume"

    def test_it_works(self) -> None:
        r = self.csrf_client.post(
            self.url,
            {"tag": "foo"},
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["n_changed"], 1)

        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "new")
        self.assertIsNone(self.a.last_ping)

        self.b.refresh_from_db()
        self.assertEqual(self.b.status, "up")

        flip = Flip.objects.get()
        self.assertEqual(flip.new_status, "new")
        self.assertTrue(flip.processed)
