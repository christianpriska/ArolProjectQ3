import unittest

from src.analytics.events import compute_machine_speed, filter_events
from src.ingestion.events import ClosureEvent


def event(
    timestamp,
    head="H01",
    count=1,
    accepted=1,
    quality="observed",
    status=0,
):
    return ClosureEvent(
        timestamp=timestamp,
        head_id=head,
        counter=count,
        counter_delta=accepted or 1,
        elapsed_seconds=1.0,
        accepted_closure_count=accepted,
        torque_nm=2.4,
        status_code=status,
        reset_epoch=0,
        event_quality=quality,
        source_file="sample.csv",
    )


class EventAnalyticsTests(unittest.TestCase):
    def test_filter_events_combines_time_head_status_and_quality(self):
        events = [
            event("2026-01-01T10:00:00", head="H01", status=0),
            event("2026-01-01T10:01:00", head="H02", status=9),
            event("2026-01-01T10:02:00", head="H02", quality="gap", accepted=None),
        ]

        filtered = list(
            filter_events(
                events,
                start_time="2026-01-01T10:00:30",
                head_ids=["h02"],
                status_codes=[9],
                event_qualities=["observed"],
                accepted_only=True,
            )
        )

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].timestamp, "2026-01-01T10:01:00")

    def test_machine_speed_uses_all_heads_in_a_complete_window(self):
        events = []
        for minute in range(6):
            timestamp = f"2026-01-01T10:0{minute}:00"
            events.append(event(timestamp, head="H01", count=minute + 1, accepted=50))
            events.append(event(timestamp, head="H02", count=minute + 1, accepted=50))

        points = list(compute_machine_speed(events, window_seconds=300))

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0].closures_in_window, 500)
        self.assertEqual(points[0].pieces_per_hour, 6000.0)

    def test_gap_restarts_the_speed_window(self):
        events = [
            event("2026-01-01T10:00:00", accepted=100),
            event("2026-01-01T10:05:00", accepted=None, quality="gap"),
            event("2026-01-01T10:06:00", accepted=100),
        ]

        self.assertEqual(list(compute_machine_speed(events, window_seconds=300)), [])


if __name__ == "__main__":
    unittest.main()
