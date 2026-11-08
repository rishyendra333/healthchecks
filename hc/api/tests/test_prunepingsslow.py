from __future__ import annotations

from unittest.mock import Mock, patch

from hc.api.management.commands.prunepingsslow import Command
from hc.api.models import Check, Ping
from hc.test import BaseTestCase


class PrunePingsSlowTestCase(BaseTestCase):
    @patch("hc.api.models.remove_objects", autospec=True)
    def test_it_works(self, remove_objects: Mock) -> None:
        check = Check.objects.create(project=self.project, n_pings=101)
        Ping.objects.create(owner=check, n=1)
        Command(stdout=Mock()).handle()

        # The ping should have been deleted
        self.assertFalse(Ping.objects.exists())

    @patch("hc.api.models.remove_objects", autospec=True)
    def test_it_deletes_in_batches(self, remove_objects: Mock) -> None:
        self.profile.ping_log_limit = 2
        self.profile.save()

        check = Check.objects.create(project=self.project, n_pings=107)
        for n in range(1, 108):
            Ping.objects.create(owner=check, n=n)

        Command(stdout=Mock()).handle(batch_size=10)

        # Only the two most recent pings should remain
        remaining = list(Ping.objects.values_list("n", flat=True).order_by("n"))
        self.assertEqual(remaining, [106, 107])

    def test_batched_delete_leaves_other_checks_alone(self) -> None:
        from hc.api.management.commands.prunepingsslow import delete_pings_batched

        a = Check.objects.create(project=self.project, n_pings=5)
        b = Check.objects.create(project=self.project, n_pings=5)
        for n in range(1, 6):
            Ping.objects.create(owner=a, n=n)
            Ping.objects.create(owner=b, n=n)

        deleted = delete_pings_batched(a, threshold=3, batch_size=2)
        self.assertEqual(deleted, 3)
        self.assertEqual(Ping.objects.filter(owner=a).count(), 2)
        self.assertEqual(Ping.objects.filter(owner=b).count(), 5)

    def test_batched_delete_with_exact_multiple(self) -> None:
        from hc.api.management.commands.prunepingsslow import delete_pings_batched

        check = Check.objects.create(project=self.project, n_pings=4)
        for n in range(1, 5):
            Ping.objects.create(owner=check, n=n)

        # 4 rows in batches of 2: two full batches, then an empty one
        deleted = delete_pings_batched(check, threshold=4, batch_size=2)
        self.assertEqual(deleted, 4)
        self.assertFalse(Ping.objects.exists())
