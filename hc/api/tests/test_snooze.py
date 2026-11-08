from __future__ import annotations

from datetime import timedelta as td

from django.utils.timezone import now

from hc.api.management.commands.sendalerts import Command
from hc.api.models import Channel, Check, Flip
from hc.test import BaseTestCase


class SnoozeApiTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check.objects.create(project=self.project, status="up")
        self.url = f"/api/v3/checks/{self.check.code}"

    def post(self, data: dict[str, object]):  # type: ignore
        return self.csrf_client.post(
            self.url, data, content_type="application/json", HTTP_X_API_KEY="X" * 32
        )

    def test_it_snoozes(self) -> None:
        r = self.post({"snooze": 3600})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()["snoozed_until"])

        self.check.refresh_from_db()
        assert self.check.snoozed_until
        self.assertTrue(self.check.is_snoozed())
        delta = self.check.snoozed_until - now()
        self.assertTrue(td(minutes=59) < delta <= td(hours=1))

    def test_zero_cancels_snooze(self) -> None:
        self.check.snoozed_until = now() + td(hours=1)
        self.check.save()

        r = self.post({"snooze": 0})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["snoozed_until"])

        self.check.refresh_from_db()
        self.assertIsNone(self.check.snoozed_until)

    def test_it_rejects_too_long_snooze(self) -> None:
        r = self.post({"snooze": 604801})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "json validation error: snooze is too large")

    def test_it_rejects_negative_snooze(self) -> None:
        r = self.post({"snooze": -1})
        self.assertEqual(r.status_code, 400)

    def test_expired_snooze_is_not_reported(self) -> None:
        self.check.snoozed_until = now() - td(minutes=1)
        self.check.save()

        r = self.client.get(self.url, HTTP_X_API_KEY="X" * 32)
        self.assertIsNone(r.json()["snoozed_until"])


class SnoozeAlertsTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.check = Check(project=self.project, status="up")
        self.check.last_ping = now() - td(days=2)
        self.check.alert_after = self.check.last_ping + td(days=1, hours=1)
        self.check.save()

        self.channel = Channel.objects.create(project=self.project, kind="email")
        self.channel.value = "alice@example.org"
        self.channel.save()
        self.channel.checks.add(self.check)

    def test_sendalerts_skips_snoozed_check(self) -> None:
        self.check.snoozed_until = now() + td(hours=1)
        self.check.save()

        result = Command().handle_going_down()
        self.assertTrue(result)

        # It should not create a flip while the check is snoozed
        self.assertFalse(Flip.objects.exists())
        self.check.refresh_from_db()
        self.assertEqual(self.check.status, "up")

    def test_sendalerts_handles_expired_snooze(self) -> None:
        self.check.snoozed_until = now() - td(minutes=5)
        self.check.save()

        Command().handle_going_down()
        flip = Flip.objects.get()
        self.assertEqual(flip.new_status, "down")

    def test_select_channels_respects_snooze(self) -> None:
        self.check.snoozed_until = now() + td(hours=1)
        self.check.save()

        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        self.assertEqual(flip.select_channels(), [])

    def test_select_channels_after_snooze(self) -> None:
        self.check.snoozed_until = now() - td(hours=1)
        self.check.save()

        flip = Flip(owner=self.check, created=now(), old_status="up", new_status="down")
        self.assertEqual(flip.select_channels(), [self.channel])
