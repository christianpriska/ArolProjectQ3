import csv
import tempfile
import unittest
from pathlib import Path

from src.ingestion.pipeline import run_ingestion


class IngestionPipelineTests(unittest.TestCase):
    def test_pipeline_ingests_csv_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "data"
            data_dir.mkdir()
            database_path = root / "events.db"
            csv_path = data_dir / "sample.csv"

            heads = [f"H{number:02d}" for number in range(1, 37)]
            header = ["timestamp"]
            header += [f"{head} Count" for head in heads]
            header += [f"{head} AppTorque" for head in heads]
            header += [f"{head} Status" for head in heads]

            with csv_path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(header)
                for second, h01_count in enumerate((0, 1, 2)):
                    counts = [h01_count] + [0] * 35
                    torques = [2.4] + [0] * 35
                    statuses = [0] * 36
                    writer.writerow(
                        [f"2026-01-01T10:00:0{second}"]
                        + counts
                        + torques
                        + statuses
                    )

            first = run_ingestion(data_dir=data_dir, database_path=database_path)
            second = run_ingestion(data_dir=data_dir, database_path=database_path)

            self.assertEqual(first.files_processed, 1)
            self.assertEqual(first.events_detected, 2)
            self.assertEqual(first.events_inserted, 2)
            self.assertEqual(first.accepted_closures, 2)
            self.assertEqual(second.events_detected, 2)
            self.assertEqual(second.events_inserted, 0)


if __name__ == "__main__":
    unittest.main()
