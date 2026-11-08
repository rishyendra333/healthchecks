from __future__ import annotations

import logging
import time
from argparse import ArgumentParser
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from hc.api.models import Check, Ping

logger = logging.getLogger(__name__)


def delete_pings_batched(check: Check, threshold: int, batch_size: int) -> int:
    """Delete the check's pings with n <= threshold, batch_size rows at a time.

    A single DELETE of a few million rows holds row locks for a long time and
    produces one huge transaction. Deleting in small batches keeps each
    transaction short, so concurrent pings to the same check don't wait on
    the prune.

    Return the total number of deleted rows.
    """

    if connection.vendor == "mysql":
        # MySQL does not support LIMIT in IN (subquery). Fall back to the
        # ORM, which deletes everything in one statement.
        deleted, _ = Ping.objects.filter(owner_id=check.id, n__lte=threshold).delete()
        return deleted

    # The table name comes from model metadata, not from user input.
    # All values are passed as query parameters.
    table = connection.ops.quote_name(Ping._meta.db_table)
    sql = f"""
        DELETE FROM {table} WHERE id IN (
            SELECT id FROM {table}
            WHERE owner_id = %s AND n <= %s
            ORDER BY n
            LIMIT %s
        )
    """

    total = 0
    while True:
        with connection.cursor() as cursor:
            cursor.execute(sql, [check.id, threshold, batch_size])
            deleted = cursor.rowcount

        total += deleted
        if deleted < batch_size:
            return total


class Command(BaseCommand):
    help = "Sequentially prune all checks in the database."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--batch-size",
            type=int,
            default=0,
            help="Delete pings in batches of this size (default: no batching)",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.0,
            help="Seconds to sleep between checks, to reduce database load",
        )

    def handle(self, batch_size: int = 0, sleep: float = 0.0, **options: Any) -> str:
        # Delete operations are sometimes slow, increase timeout
        settings.S3_TIMEOUT = 60

        for check in Check.objects.filter(n_pings__gt=100).order_by("code").iterator():
            # Pruning of all checks is a potentially long operations, and some
            # checks may get removed while the operation is running.
            # To reduce the chance of hitting DoesNotExist exceptions,
            # before pruning each check make sure it still exists:
            if not Check.objects.filter(id=check.id).exists():
                continue

            self.stdout.write(f"Pruning: {check.code}")
            try:
                if batch_size > 0:
                    # Remove the bulk of old pings in small batches first.
                    # check.prune() then handles object storage, notifications
                    # and flips, and finds no pings left to delete.
                    threshold = check.n_pings - check.project.owner_profile.ping_log_limit
                    deleted = delete_pings_batched(check, threshold, batch_size)
                    self.stdout.write(f"  deleted {deleted} pings in batches")

                check.prune(wait=True)
            except Exception:
                logger.exception("Exception in Check.prune()")

            if sleep:
                time.sleep(sleep)

        return "Done!"
