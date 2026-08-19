import tempfile
import unittest
from pathlib import Path

from src.ingestion.events import ClosureEvent
from src.storage.database import (
    create_connection,
    create_tables,
    insert_events,
    query_events,
)


def sample_event(timestamp="2026-01-01T10:00:00", head="H01"):
    return ClosureEvent(
        timestamp=timestamp,
        head_id=head,
        counter=101,
        counter_delta=1,
        elapsed_seconds=1.0,
        accepted_closure_count=1,
        torque_nm=2.4,
        status_code=0,
        reset_epoch=0,
        event_quality="observed",
        source_file="sample.csv",
    )


class DatabaseTests(unittest.TestCase):
    def test_insert_is_idempotent_and_queryable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            with create_connection(path) as connection:
                create_tables(connection)
                event = sample_event()

                self.assertEqual(insert_events(connection, [event]), 1)
                self.assertEqual(insert_events(connection, [event]), 0)

                rows = query_events(connection, head_id="h01")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["counter_delta"], 1)
                self.assertEqual(rows[0]["event_quality"], "observed")

    def test_query_events_filters_time_and_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.db"
            with create_connection(path) as connection:
                create_tables(connection)
                insert_events(
                    connection,
                    [
                        sample_event("2026-01-01T10:00:00", "H01"),
                        sample_event("2026-01-01T11:00:00", "H02"),
                    ],
                )

                rows = query_events(
                    connection,
                    start_time="2026-01-01T10:30:00",
                    event_quality="observed",
                )
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["head_id"], "H02")


if __name__ == "__main__":
    unittest.main()
