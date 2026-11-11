import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config import DB_FILE
from games import get_game


SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    draw_target TEXT,
    target_date TEXT,
    game_id TEXT NOT NULL DEFAULT 'power655',
    model TEXT NOT NULL,
    tickets_json TEXT NOT NULL,
    special INTEGER,
    meta_json TEXT
);
CREATE TABLE IF NOT EXISTS game_results (
    game_id TEXT NOT NULL,
    draw_id TEXT NOT NULL,
    date TEXT,
    result_json TEXT NOT NULL,
    special INTEGER,
    PRIMARY KEY (game_id, draw_id)
);
CREATE TABLE IF NOT EXISTS results (
    draw_id TEXT PRIMARY KEY,
    date TEXT,
    main_json TEXT NOT NULL,
    special INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation (
    prediction_id INTEGER,
    draw_id TEXT,
    model TEXT,
    best_hit INTEGER,
    total_hits INTEGER,
    matched_special INTEGER,
    evaluated_at TEXT,
    PRIMARY KEY (prediction_id, draw_id),
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);
"""


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as con:
        con.executescript(SCHEMA)
        columns = {row[1] for row in con.execute("PRAGMA table_info(predictions)")}
        if "game_id" not in columns:
            con.execute(
                "ALTER TABLE predictions ADD COLUMN game_id TEXT NOT NULL DEFAULT 'power655'"
            )
        if "target_date" not in columns:
            con.execute("ALTER TABLE predictions ADD COLUMN target_date TEXT")
        con.execute(
            "INSERT OR IGNORE INTO game_results (game_id, draw_id, date, result_json, special) "
            "SELECT 'power655', draw_id, date, main_json, special FROM results"
        )


def save_prediction(
    model: str,
    tickets: list[list[Any]],
    special: int | None = None,
    draw_target: str | None = None,
    meta: dict | None = None,
    game_id: str = "power655",
    target_date: str | None = None,
) -> int:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        cur = con.execute(
            "INSERT INTO predictions (created_at, draw_target, target_date, game_id, model, tickets_json, special, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                draw_target,
                target_date,
                game_id,
                model,
                json.dumps(tickets),
                special,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def save_result(
    draw_id: str,
    date: str,
    main: Any,
    special: int | None = None,
    game_id: str = "power655",
) -> None:
    init_db()
    payload = main
    legacy_main = main
    legacy_special = special
    game = get_game(game_id)
    if game.kind == "draw" and game.special_max is not None:
        if not isinstance(main, list):
            raise ValueError(f"{game.name}: kết quả phải là danh sách số.")
        if special is None and len(main) == game.main_count + 1:
            legacy_main = main[:game.main_count]
            legacy_special = main[game.main_count]
            payload = main
        elif special is not None and len(main) == game.main_count:
            payload = [*main, special]
        else:
            raise ValueError(f"{game.name}: cần số chính và số đặc biệt.")
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "INSERT OR REPLACE INTO game_results (game_id, draw_id, date, result_json, special) "
            "VALUES (?, ?, ?, ?, ?)",
            (game_id, draw_id, date, json.dumps(payload, ensure_ascii=False), legacy_special),
        )
        if game_id == "power655" and isinstance(legacy_main, list):
            con.execute(
                "INSERT OR REPLACE INTO results (draw_id, date, main_json, special) VALUES (?, ?, ?, ?)",
                (draw_id, date, json.dumps(legacy_main), legacy_special),
            )


def evaluate_pending(draw_id: str, game_id: str = "power655") -> int:
    """Đối chiếu mọi prediction chưa được evaluate với kết quả draw_id."""
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        row = con.execute(
            "SELECT result_json, special FROM game_results WHERE game_id = ? AND draw_id = ?",
            (game_id, draw_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Chưa có kết quả cho draw_id={draw_id}")
        actual = json.loads(row[0])
        actual_special = row[1]
        if isinstance(actual, dict):
            actual_values = {
                value
                for values in actual.values()
                for value in values
            }
        else:
            game = get_game(game_id)
            actual_values = set(actual[:game.main_count])

        preds = con.execute(
            "SELECT id, model, tickets_json, special FROM predictions WHERE game_id = ?",
            (game_id,),
        ).fetchall()
        n = 0
        for pid, model, tickets_json, pred_special in preds:
            exists = con.execute(
                "SELECT 1 FROM evaluation WHERE prediction_id = ? AND draw_id = ?",
                (pid, draw_id),
            ).fetchone()
            if exists:
                continue
            tickets = json.loads(tickets_json)
            hits = [len(set(t) & actual_values) for t in tickets]
            best = max(hits) if hits else 0
            total = sum(hits)
            matched_special = int(pred_special == actual_special) if pred_special is not None else 0

            con.execute(
                "INSERT OR REPLACE INTO evaluation (prediction_id, draw_id, model, best_hit, total_hits, matched_special, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, draw_id, model, best, total, matched_special, datetime.now(timezone.utc).isoformat()),
            )
            n += 1
        return n


def performance_report(game_id: str = "power655") -> None:
    init_db()
    game = get_game(game_id)
    special_column = (
        ", SUM(e.matched_special) AS special_hits"
        if game.special_max is not None
        else ""
    )
    with sqlite3.connect(DB_FILE) as con:
        df = pd.read_sql_query(
            "SELECT e.model, COUNT(*) AS n, AVG(e.best_hit) AS mean_best, "
            f"AVG(e.total_hits) AS mean_total{special_column} "
            "FROM evaluation e JOIN predictions p ON p.id = e.prediction_id "
            "WHERE p.game_id = ? GROUP BY e.model",
            con,
            params=(game_id,),
        )
    print(df.round(4).to_string(index=False))


def get_predictions(
    game_id: str | None = None,
    limit: int = 20,
    prediction_id: int | None = None,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit phải lớn hơn 0.")
    if game_id is not None:
        get_game(game_id)
    init_db()

    filters = []
    params: list[Any] = []
    if game_id is not None:
        filters.append("game_id = ?")
        params.append(game_id)
    if prediction_id is not None:
        filters.append("id = ?")
        params.append(prediction_id)
    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(1 if prediction_id is not None else limit)

    with sqlite3.connect(DB_FILE) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, created_at, draw_target, target_date, game_id, model, tickets_json, special "
            f"FROM predictions {where_clause} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        predictions = []
        for row in rows:
            evaluations = con.execute(
                "SELECT e.draw_id, e.best_hit, e.total_hits, e.matched_special, "
                "r.date, r.result_json "
                "FROM evaluation e LEFT JOIN game_results r "
                "ON r.game_id = ? AND r.draw_id = e.draw_id "
                "WHERE e.prediction_id = ? ORDER BY e.evaluated_at",
                (row["game_id"], row["id"]),
            ).fetchall()
            predictions.append({
                "id": row["id"],
                "created_at": row["created_at"],
                "draw_target": row["draw_target"],
                "target_date": row["target_date"],
                "game_id": row["game_id"],
                "model": row["model"],
                "tickets": json.loads(row["tickets_json"]),
                "special": row["special"],
                "evaluations": [
                    {
                        "draw_id": item["draw_id"],
                        "best_hit": item["best_hit"],
                        "total_hits": item["total_hits"],
                        "matched_special": item["matched_special"],
                        "date": item["date"],
                        "result": json.loads(item["result_json"]) if item["result_json"] else None,
                    }
                    for item in evaluations
                ],
            })
        return predictions


def delete_prediction(prediction_id: int) -> bool:
    deleted, _ = delete_predictions([prediction_id])
    return bool(deleted)


def delete_predictions(prediction_ids: list[int]) -> tuple[list[int], list[int]]:
    prediction_ids = list(dict.fromkeys(prediction_ids))
    if not prediction_ids:
        return [], []

    init_db()
    with sqlite3.connect(DB_FILE) as con:
        placeholders = ", ".join("?" for _ in prediction_ids)
        rows = con.execute(
            f"SELECT id FROM predictions WHERE id IN ({placeholders})",
            prediction_ids,
        ).fetchall()
        deleted_ids = {row[0] for row in rows}
        missing_ids = [item for item in prediction_ids if item not in deleted_ids]
        if not deleted_ids:
            return [], missing_ids

        deleted = [item for item in prediction_ids if item in deleted_ids]
        deleted_placeholders = ", ".join("?" for _ in deleted)
        con.execute(
            f"DELETE FROM evaluation WHERE prediction_id IN ({deleted_placeholders})",
            deleted,
        )
        con.execute(
            f"DELETE FROM predictions WHERE id IN ({deleted_placeholders})",
            deleted,
        )
        return deleted, missing_ids