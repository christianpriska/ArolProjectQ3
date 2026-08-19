import csv
import tempfile
import unittest
from pathlib import Path

from src.ingestion.events import ClosureExtractor


def row(timestamp, count, torque="2.4", status="0"):
    return {
        "timestamp": timestamp,
        "H01 Count": str(count),
        "H01 AppTorque": torque,
        "H01 Status": status,
    }


class ClosureExtractorTests(unittest.TestCase):
    def make_extractor(self, **overrides):
        options = {
            "head_ids": ["H01"],
            "max_contiguous_gap_seconds": 2,
            "max_closures_per_head_second": 5,
        }
        options.update(overrides)
        return ClosureExtractor(**options)

    def test_observed_and_aggregated_increments(self):
        extractor = self.make_extractor()

        events = list(
            extractor.iter_rows(
                [
                    row("2026-01-01T10:00:00", 100),
                    row("2026-01-01T10:00:01", 101),
                    row("2026-01-01T10:00:02", 105),
                ],
                source_file="sample.csv",
            )
        )

        self.assertEqual([event.counter_delta for event in events], [1, 4])
        self.assertEqual([event.accepted_closure_count for event in events], [1, 4])
        self.assertEqual([event.event_quality for event in events], ["observed", "aggregated"])

    def test_increment_after_gap_is_not_accepted_as_precise_closures(self):
        extractor = self.make_extractor()

        events = list(
            extractor.iter_rows(
                [
                    row("2026-01-01T10:00:00", 100),
                    row("2026-01-01T12:00:00", 500),
                ],
                source_file="sample.csv",
            )
        )

        self.assertEqual(events[0].counter_delta, 400)
        self.assertEqual(events[0].elapsed_seconds, 7200)
        self.assertIsNone(events[0].accepted_closure_count)
        self.assertEqual(events[0].event_quality, "gap")
        self.assertEqual(len(extractor.gaps), 1)
        self.assertEqual(extractor.gaps[0].duration_seconds, 7200)

    def test_implausible_increment_is_marked_anomalous(self):
        extractor = self.make_extractor(max_closures_per_head_second=2)

        events = list(
            extractor.iter_rows(
                [
                    row("2026-01-01T10:00:00", 100),
                    row("2026-01-01T10:00:01", 110),
                ],
                source_file="sample.csv",
            )
        )

        self.assertEqual(events[0].counter_delta, 10)
        self.assertIsNone(events[0].accepted_closure_count)
        self.assertEqual(events[0].event_quality, "anomalous")

    def test_reset_is_detected_before_event_extraction(self):
        extractor = self.make_extractor()

        events = list(
            extractor.iter_rows(
                [
                    row("2026-01-01T10:00:00", 100),
                    row("2026-01-01T10:00:01", 101),
                    row("2026-01-01T10:00:02", 0),
                    row("2026-01-01T10:00:03", 1),
                ],
                source_file="sample.csv",
            )
        )

        self.assertEqual([event.counter for event in events], [101, 1])
        self.assertEqual([event.reset_epoch for event in events], [0, 1])
        self.assertEqual(extractor.reset_counts["H01"], 1)

    def test_short_reset_does_not_remove_repeated_counter(self):
        extractor = self.make_extractor()

        events = list(
            extractor.iter_rows(
                [
                    row("2026-01-01T10:00:00", 100),
                    row("2026-01-01T10:00:01", 101),
                    row("2026-01-01T10:00:02", 100),
                    row("2026-01-01T10:00:03", 101),
                ],
                source_file="sample.csv",
            )
        )

        self.assertEqual([event.counter for event in events], [101, 101])
        self.assertEqual([event.reset_epoch for event in events], [0, 1])

    def test_state_is_preserved_across_files(self):
        extractor = self.make_extractor()

        first_events = list(
            extractor.iter_rows(
                [row("2026-01-01T10:00:00", 100)],
                source_file="first.csv",
            )
        )
        second_events = list(
            extractor.iter_rows(
                [row("2026-01-01T10:00:01", 101)],
                source_file="second.csv",
            )
        )

        self.assertEqual(first_events, [])
        self.assertEqual(len(second_events), 1)
        self.assertEqual(second_events[0].source_file, "second.csv")
        self.assertEqual(second_events[0].event_quality, "observed")

    def test_trailing_zero_padding_is_removed_without_resetting_state(self):
        extractor = self.make_extractor()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(
                    ["timestamp", "H01 Count", "H01 AppTorque", "H01 Status"]
                )
                writer.writerow(["2026-01-01T10:00:00", 100, 2.4, 0])
                writer.writerow(["2026-01-01T10:00:01", 101, 2.4, 0])
                writer.writerow(["2026-01-01T10:00:02", 0, 0, 0])

            events = list(extractor.iter_file(path))

        self.assertEqual(len(events), 1)
        self.assertEqual(extractor.state["H01"].counter, 101)
        self.assertEqual(extractor.reset_counts["H01"], 0)
        self.assertEqual(extractor.padding_rows["sample.csv"], 1)


if __name__ == "__main__":
    unittest.main()
