import json
import io
import random
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import game_data
import main
import pandas as pd
import tracker
from backtest import walk_forward
from games import get_game
from game_data import add_manual_record, load_records, normalize_record
from model import model_D_candidates


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


class RelationalModelTests(unittest.TestCase):
    def test_model_d_anchors_at_most_frequent_and_uses_pair_probability(self):
        draws = [[1, 2] for _ in range(9)] + [[1, 3]]
        tickets = [
            model_D_candidates(
                draws=draws,
                number_pool=range(1, 5),
                picks_per_ticket=2,
                n_tickets=1,
                rng=random.Random(seed),
            )[0]
            for seed in range(500)
        ]
        self.assertTrue(all(1 in ticket for ticket in tickets))
        self.assertTrue(all(len(ticket) == len(set(ticket)) == 2 for ticket in tickets))
        self.assertGreater(sum(2 in ticket for ticket in tickets), 400)

    def test_model_d_is_available_to_power655_backtest(self):
        frame = pd.DataFrame(
            [
                [1, 2, 3, 4, 5, 6],
                [1, 2, 3, 4, 5, 7],
                [1, 2, 3, 4, 6, 8],
            ],
            columns=[f"m{index}" for index in range(1, 7)],
        )
        results = walk_forward(
            frame,
            start_idx=2,
            n_tickets=1,
            seed=42,
            models=("D",),
        )
        self.assertIn("D", results)
        self.assertEqual(len(results["D"]["best_max"]), 1)

    def test_power655_predict_keeps_existing_models_and_adds_d(self):
        frame = pd.DataFrame(
            [
                [number + offset for number in range(1, 7)]
                for offset in range(10)
            ],
            columns=[f"m{index}" for index in range(1, 7)],
        )
        frequency = pd.Series(
            {number: 20 - number for number in range(1, 56)}
        ).sort_values(ascending=False)
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tracker, "DB_FILE", Path(temporary) / "tracker.sqlite"):
                with (
                    patch.object(main, "load_draws", return_value=frame),
                    patch.object(main, "validate"),
                    patch.object(main, "freq_main", return_value=frequency),
                    patch.object(main, "pair_stats", return_value=pd.DataFrame()),
                ):
                    main.cmd_predict(
                        SimpleNamespace(
                            game="power655",
                            refresh=False,
                            tickets=1,
                            seed=42,
                            special=None,
                            draw_target=None,
                            draw_date=None,
                        )
                    )
                predictions = tracker.get_predictions(game_id="power655", limit=10)
        self.assertEqual(
            {prediction["model"] for prediction in predictions},
            {"A", "B", "C", "R", "D"},
        )

    def test_power655_can_generate_only_model_d(self):
        frame = pd.DataFrame(
            [[number + offset for number in range(1, 7)] for offset in range(10)],
            columns=[f"m{index}" for index in range(1, 7)],
        )
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(tracker, "DB_FILE", Path(temporary) / "tracker.sqlite"):
                with (
                    patch.object(main, "load_draws", return_value=frame),
                    patch.object(main, "validate"),
                    patch.object(main, "freq_main", side_effect=AssertionError("not needed")),
                    patch.object(main, "pair_stats", side_effect=AssertionError("not needed")),
                ):
                    main.cmd_predict(
                        SimpleNamespace(
                            game="power655",
                            refresh=False,
                            tickets=1,
                            seed=42,
                            special=None,
                            models=["D"],
                            draw_target=None,
                            draw_date=None,
                        )
                    )
                predictions = tracker.get_predictions(game_id="power655", limit=10)
        self.assertEqual([prediction["model"] for prediction in predictions], ["D"])

    def test_manual_records_are_separated_by_game(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(game_data, "DATA_DIR", Path(temporary)):
                add_manual_record("power645", "001", [1, 2, 3, 4, 5, 6])
                add_manual_record("keno", "001", list(range(1, 21)))
                self.assertEqual(len(load_records("power645")), 1)
                self.assertEqual(len(load_records("keno")), 1)
                self.assertEqual(len(load_records("power655")), 0)


class TrackerTests(unittest.TestCase):
    def test_predictions_list_shows_model_and_database_hit_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with patch.object(tracker, "DB_FILE", database):
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[1, 2, 3, 4, 5, 6]],
                    game_id="power645",
                    target_date="2026-11-15",
                )
                tracker.save_result(
                    "draw-15",
                    "2026-11-15",
                    [1, 2, 7, 8, 9, 10],
                    game_id="power645",
                )
                tracker.evaluate_pending("draw-15", "power645")
                with sqlite3.connect(database) as connection:
                    connection.execute(
                        "UPDATE predictions SET created_at = ? WHERE id = ?",
                        ("2026-11-11T10:20:30+00:00", prediction_id),
                    )

                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(
                            game=None,
                            limit=20,
                            id=None,
                            list=True,
                        )
                    )

        text = output.getvalue()
        self.assertIn(
            f"#{prediction_id} | draw-15 (2026-11-15) | Power 6/45 | test | draw-15:2",
            text,
        )
        self.assertNotIn("Vé 1", text)

    def test_predictions_list_shows_jsonl_hit_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", data_dir),
                patch.object(tracker, "DB_FILE", database),
            ):
                add_manual_record(
                    "power645",
                    "draw-15",
                    [1, 2, 7, 8, 9, 10],
                    "2026-11-15",
                )
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[1, 2, 3, 4, 5, 6]],
                    game_id="power645",
                    target_date="2026-11-15",
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(
                            game=None,
                            limit=20,
                            id=None,
                            list=True,
                        )
                    )

        self.assertIn(
            f"#{prediction_id} | draw-15 (2026-11-15) | Power 6/45 | test | draw-15:2",
            output.getvalue(),
        )

    def test_delete_prediction_removes_its_evaluations_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with patch.object(tracker, "DB_FILE", database):
                tracker.init_db()
                to_delete = tracker.save_prediction(
                    model="delete-me",
                    tickets=[[1, 2, 3, 4, 5, 6]],
                    game_id="power655",
                )
                to_keep = tracker.save_prediction(
                    model="keep-me",
                    tickets=[[7, 8, 9, 10, 11, 12]],
                    game_id="power655",
                )
                tracker.save_result("001", "", [1, 2, 3, 4, 5, 6], 7)
                tracker.evaluate_pending("001", "power655")

                self.assertTrue(tracker.delete_prediction(to_delete))
                self.assertFalse(tracker.delete_prediction(to_delete))

                with sqlite3.connect(database) as connection:
                    predictions = connection.execute(
                        "SELECT id FROM predictions ORDER BY id"
                    ).fetchall()
                    evaluations = connection.execute(
                        "SELECT prediction_id FROM evaluation ORDER BY prediction_id"
                    ).fetchall()
                    results = connection.execute(
                        "SELECT draw_id FROM game_results"
                    ).fetchall()

        self.assertEqual(predictions, [(to_keep,)])
        self.assertEqual(evaluations, [(to_keep,)])
        self.assertEqual(results, [("001",)])

    def test_delete_predictions_accepts_multiple_ids_and_reports_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "tracker.sqlite"
            with patch.object(tracker, "DB_FILE", database):
                first = tracker.save_prediction(
                    model="first",
                    tickets=[[1, 2, 3, 4, 5, 6]],
                    game_id="power655",
                )
                second = tracker.save_prediction(
                    model="second",
                    tickets=[[7, 8, 9, 10, 11, 12]],
                    game_id="power655",
                )
                tracker.save_prediction(
                    model="keep",
                    tickets=[[13, 14, 15, 16, 17, 18]],
                    game_id="power655",
                )
                tracker.save_result("001", "", [1, 2, 3, 4, 5, 6], 7)
                tracker.evaluate_pending("001", "power655")

                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_delete_prediction(
                        SimpleNamespace(ids=[first, second, 999])
                    )

                with sqlite3.connect(database) as connection:
                    prediction_ids = connection.execute(
                        "SELECT id FROM predictions ORDER BY id"
                    ).fetchall()
                    evaluations = connection.execute(
                        "SELECT prediction_id FROM evaluation ORDER BY prediction_id"
                    ).fetchall()
                    results = connection.execute(
                        "SELECT draw_id FROM game_results"
                    ).fetchall()

        self.assertEqual(prediction_ids, [(3,)])
        self.assertEqual(evaluations, [(3,)])
        self.assertEqual(results, [("001",)])
        self.assertIn(f"Đã xóa dự đoán #{first}, #{second}", output.getvalue())
        self.assertIn("Không tìm thấy dự đoán #999", output.getvalue())

    def test_predictions_compare_target_date_with_jsonl_without_recording_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", data_dir),
                patch.object(tracker, "DB_FILE", database),
            ):
                add_manual_record(
                    "power645",
                    "001",
                    [1, 2, 3, 4, 5, 6],
                    "2026-11-11",
                )
                add_manual_record(
                    "power645",
                    "002",
                    [5, 6, 7, 8, 9, 10],
                    "2026-11-13",
                )
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[1, 5, 20, 21, 22, 23]],
                    game_id="power645",
                    target_date="2026-11-13",
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(game="power645", limit=20, id=prediction_id)
                    )

        text = output.getvalue()
        self.assertIn("Đối chiếu từ JSONL (ngày mục tiêu 2026-11-13)", text)
        self.assertIn("Kết quả thực tế: [5, 6, 7, 8, 9, 10]", text)
        self.assertIn("Vé 1: 1 số trùng", text)

    def test_predictions_infer_nearest_past_draw_when_target_date_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", data_dir),
                patch.object(tracker, "DB_FILE", database),
            ):
                add_manual_record("power645", "old", [1, 2, 3, 4, 5, 6], "2026-11-09")
                add_manual_record("power645", "same-day", [1, 2, 3, 4, 5, 6], "2026-11-10")
                add_manual_record("power645", "next", [6, 7, 8, 9, 10, 11], "2026-11-12")
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[6, 7, 8, 9, 10, 11]],
                    game_id="power645",
                )
                with sqlite3.connect(database) as connection:
                    connection.execute(
                        "UPDATE predictions SET created_at = ? WHERE id = ?",
                        ("2026-11-10T12:00:00+00:00", prediction_id),
                    )
                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(game="power645", limit=20, id=prediction_id)
                    )

        text = output.getvalue()
        self.assertIn(
            "kỳ gần nhất trước ngày dự đoán 2026-11-10 (2026-11-10)",
            text,
        )
        self.assertIn("Kỳ mục tiêu: same-day (2026-11-10)", text)
        self.assertIn("Kết quả thực tế: [1, 2, 3, 4, 5, 6]", text)
        self.assertNotIn("Kết quả thực tế: [6, 7, 8, 9, 10, 11]", text)

    def test_target_date_without_exact_result_uses_nearest_future_draw(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", data_dir),
                patch.object(tracker, "DB_FILE", database),
            ):
                add_manual_record("power645", "old", [1, 2, 3, 4, 5, 6], "2026-11-11")
                add_manual_record("power645", "nearest", [6, 7, 8, 9, 10, 11], "2026-11-13")
                add_manual_record("power645", "future", [11, 12, 13, 14, 15, 16], "2026-11-17")
                prediction_id = tracker.save_prediction(
                    model="test",
                    tickets=[[6, 7, 8, 9, 10, 11]],
                    game_id="power645",
                    target_date="2026-11-15",
                )
                output = io.StringIO()
                with redirect_stdout(output):
                    main.cmd_predictions(
                        SimpleNamespace(game="power645", limit=20, id=prediction_id)
                    )

        text = output.getvalue()
        self.assertIn(
            "kỳ tiếp theo gần nhất sau ngày mục tiêu 2026-11-15 (2026-11-17)",
            text,
        )
        self.assertIn("Kết quả thực tế: [11, 12, 13, 14, 15, 16]", text)

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
            data_dir = Path(temporary) / "data"
            database = Path(temporary) / "tracker.sqlite"
            with (
                patch.object(game_data, "DATA_DIR", data_dir),
                patch.object(tracker, "DB_FILE", database),
            ):
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
                self.assertIn("Kỳ mục tiêu: 2026-11-12", output.getvalue())

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
                            models=None,
                            draw_target=None,
                            draw_date=None,
                        )
                    )
                    prediction_history = tracker.get_predictions(game_id=code, limit=10)
                    expected_models = (
                        {"frequency-random"}
                        if game.kind == "digits"
                        else {"frequency-random", "D"}
                    )
                    self.assertEqual(
                        {item["model"] for item in prediction_history},
                        expected_models,
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
