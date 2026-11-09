import json
import sqlite3
from datetime import datetime, timezone

import pandas as pd

from config import DB_FILE, N_MAIN


SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    draw_target TEXT,
    model TEXT NOT NULL,
    tickets_json TEXT NOT NULL,
    special INTEGER,
    meta_json TEXT
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


def save_prediction(
    model: str,
    tickets: list[list[int]],
    special: int | None = None,
    draw_target: str | None = None,
    meta: dict | None = None,
) -> int:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        cur = con.execute(
            "INSERT INTO predictions (created_at, draw_target, model, tickets_json, special, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                draw_target,
                model,
                json.dumps(tickets),
                special,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def save_result(draw_id: str, date: str, main: list[int], special: int) -> None:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        con.execute(
            "INSERT OR REPLACE INTO results (draw_id, date, main_json, special) VALUES (?, ?, ?, ?)",
            (draw_id, date, json.dumps(main), special),
        )


def evaluate_pending(draw_id: str) -> int:
    """Đối chiếu mọi prediction chưa được evaluate với kết quả draw_id."""
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        row = con.execute(
            "SELECT main_json, special FROM results WHERE draw_id = ?", (draw_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Chưa có kết quả cho draw_id={draw_id}")
        actual_main = set(json.loads(row[0]))
        actual_special = int(row[1])

        preds = con.execute("SELECT id, model, tickets_json FROM predictions").fetchall()
        n = 0
        for pid, model, tickets_json in preds:
            exists = con.execute(
                "SELECT 1 FROM evaluation WHERE prediction_id = ? AND draw_id = ?",
                (pid, draw_id),
            ).fetchone()
            if exists:
                continue
            tickets = json.loads(tickets_json)
            hits = [len(set(t) & actual_main) for t in tickets]
            best = max(hits) if hits else 0
            total = sum(hits)
            matched_special = int(best == N_MAIN)  # chỉ tính khi trúng cả 6 chính
            # Hoặc chỉ cần 1 vé có chứa số đặc biệt:
            # matched_special = int(any(True for _ in [1])) — cần đối chiếu vé với special riêng
            # Ở đây ta kiểm tra đơn giản: prediction.special có khớp actual_special không
            pred_special = con.execute(
                "SELECT special FROM predictions WHERE id = ?", (pid,)
            ).fetchone()[0]
            matched_special = int(pred_special == actual_special) if pred_special else 0

            con.execute(
                "INSERT OR REPLACE INTO evaluation (prediction_id, draw_id, model, best_hit, total_hits, matched_special, evaluated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, draw_id, model, best, total, matched_special, datetime.now(timezone.utc).isoformat()),
            )
            n += 1
        return n


def performance_report() -> None:
    init_db()
    with sqlite3.connect(DB_FILE) as con:
        df = pd.read_sql_query(
            "SELECT model, COUNT(*) AS n, AVG(best_hit) AS mean_best, "
            "AVG(total_hits) AS mean_total, SUM(matched_special) AS special_hits "
            "FROM evaluation GROUP BY model",
            con,
        )
    print(df.round(4).to_string(index=False))