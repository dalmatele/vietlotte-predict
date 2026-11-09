import json
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import game_data
import main
import tracker
from games import get_game
from game_data import add_manual_record, load_records, normalize_record


class GameDataTests(unittest.TestCase):
    def test_upstream_record_shapes(self):
        samples = {
            "power655": {"id": "1", "result": [1, 2, 3, 4, 5, 6, 7]},
            "power645": {"id": "1", "result": [1, 2, 3, 4, 5, 6]},
            "power535": {"id": "1", "result": [1, 2, 3, 4, 5, 5]},
            "keno": {"id": "1", "result": list(range(1, 21))},
            "3d": {"id": "1", "result": {"Giải Đặc biệt": ["015", "3"]}},
            "3d_pro": {"id": "1", "result": {"Giải Đặc biệt": ["003"]}},
        }
        for code, sample in samples.items():
            with self.subTest(game=code):
                record = normalize_record(get_game(code), sample)
                self.assertIsNotNone(record)
                if code == "3d":
                    self.assertEqual(record["result"]["Giải Đặc biệt"], ["015", "003"])

    def test_manual_records_are_separated_by_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(game_data, "DATA_DIR", Path(temporary)):
                add_manual_record("power645", "001", [1, 2, 3, 4, 5, 6])
                add_manual_record("keno", "001", list(range(1, 21)))
                self.assertEqual(len(load_records("power645")), 1)
                self.assertEqual(len(load_records("keno")), 1)
                self.assertEqual(len(load_records("power655")), 0)


class TrackerTests(unittest.TestCase):
    def test_existing_tracker_database_migrates_to_game_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        draw_target TEXT,
                        model TEXT NOT NULL,
                        tickets_json TEXT NOT NULL,
                        special INTEGER,
                        meta_json TEXT
                    );
                    CREATE TABLE results (
                        draw_id TEXT PRIMARY KEY,
                        date TEXT,
                        main_json TEXT NOT NULL,
                        special INTEGER NOT NULL
                    );
                    CREATE TABLE evaluation (
                        prediction_id INTEGER,
                        draw_id TEXT,
                        model TEXT,
                        best_hit INTEGER,
                        total_hits INTEGER,
                        matched_special INTEGER,
                        evaluated_at TEXT,
                        PRIMARY KEY (prediction_id, draw_id)
                    );
                    INSERT INTO results VALUES ('001', '', '[1,2,3,4,5,6]', 7);
                    """
                )
            with patch.object(tracker, "DB_FILE", database):
                tracker.init_db()
                with sqlite3.connect(database) as connection:
                    prediction_columns = {
                        row[1] for row in connection.execute("PRAGMA table_info(predictions)")
                    }
                    migrated_result = connection.execute(
                        "SELECT result_json FROM game_results WHERE game_id = 'power655' AND draw_id = '001'"
                    ).fetchone()
                self.assertIn("game_id", prediction_columns)
                self.assertIn("target_date", prediction_columns)
                self.assertEqual(migrated_result, ("[1,2,3,4,5,6]",))

    def test_game_results_evaluate_only_matching_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with patch.object(tracker, "DB_FILE", database):
                tracker.init_db()
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[1, 2, 3, 4, 5, 6]],
                    special=7,
                    game_id="power655",
                    target_date="2026-11-12",
                )
                tracker.save_result("001", "", [1, 2, 3, 4, 5, 6], 7)
                self.assertEqual(tracker.evaluate_pending("001", "power655"), 1)
                with sqlite3.connect(database) as connection:
                    row = connection.execute(
                        "SELECT best_hit, matched_special FROM evaluation WHERE prediction_id = ?",
                        (prediction_id,),
                    ).fetchone()
                self.assertEqual(row, (6, 1))
                tracker.performance_report("power655")
                history = tracker.get_predictions(prediction_id=prediction_id)
                self.assertEqual(history[0]["tickets"], [[1, 2, 3, 4, 5, 6]])
                self.assertEqual(history[0]["target_date"], "2026-11-12")
                self.assertEqual(history[0]["evaluations"][0]["result"], [1, 2, 3, 4, 5, 6, 7])
                self.assertEqual(tracker.get_predictions(game_id="keno"), [])
                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(game="power655", limit=20, id=prediction_id)
                    )
                self.assertIn("Ngày dự đoán cho kỳ: 2026-11-12", output.getvalue())

    def test_digit_game_evaluation(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with patch.object(tracker, "DB_FILE", database):
                tracker.init_db()
                tracker.save_prediction(
                    model="test",
                    tickets=[["015"]],
                    game_id="3d",
                )
                tracker.save_result(
                    "001",
                    "",
                    {"Giải Đặc biệt": ["015", "123"]},
                    game_id="3d",
                )
                self.assertEqual(tracker.evaluate_pending("001", "3d"), 1)

    def test_non_power655_cli_workflows(self):
        examples = {
            "power645": ("1,2,3,4,5,6", None, None),
            "power535": ("1,2,3,4,5", 5, None),
            "keno": (",".join(str(number) for number in range(1, 21)), None, None),
            "3d": (None, None, '{"Giải Đặc biệt":["015","123"]}'),
            "3d_pro": (None, None, '{"Giải Đặc biệt":["015","123"]}'),
        }
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", Path(temporary) / "data"),
                patch.object(tracker, "DB_FILE", database),
            ):
                for code, (numbers, special, result_json) in examples.items():
                    game = get_game(code)
                    result = (
                        json.loads(result_json)
                        if result_json
                        else [int(value) for value in numbers.split(",")]
                    )
                    if special is not None:
                        result.append(special)
                    add_manual_record(code, "sample", result)
                    main._predict_other_game(
                        SimpleNamespace(
                            game=code,
                            refresh=False,
                            tickets=1,
                            pick_count=2,
                            seed=7,
                            special=None,
                            draw_target=None,
                            draw_date=None,
                        )
                    )
                    main._backtest_other_game(
                        SimpleNamespace(
                            game=code,
                            refresh=False,
                            start_idx=0,
                            tickets=1,
                            pick_count=2,
                            seed=7,
                        )
                    )
                    main.cmd_record_result(
                        SimpleNamespace(
                            game=code,
                            draw_id="actual",
                            date="",
                            numbers=numbers,
                            result_json=result_json,
                            special=special,
                        )
                    )
                    tracker.performance_report(code)


if __name__ == "__main__":
    unittest.main()
