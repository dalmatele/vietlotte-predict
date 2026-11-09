import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

from config import DATA_DIR
from games import Game, get_game

GITHUB_DATA_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data"


def _result_values(record: dict[str, Any]) -> Any:
    return record.get("result") or record.get("value") or record.get("numbers")


def normalize_result(game: Game, result: Any) -> Any:
    if game.kind == "digits":
        if not isinstance(result, dict) or not result:
            raise ValueError(f"{game.name}: result phải là object gồm các hạng giải.")
        normalized = {}
        for prize, values in result.items():
            if not isinstance(values, list) or not values:
                raise ValueError(f"{game.name}: hạng giải {prize!r} phải có danh sách số.")
            codes = []
            for value in values:
                code = str(value).strip()
                if code.isdigit() and len(code) < 3:
                    code = code.zfill(3)
                if len(code) != 3 or not code.isdigit():
                    raise ValueError(f"{game.name}: số giải phải gồm đúng 3 chữ số: {value!r}.")
                codes.append(code)
            normalized[str(prize)] = codes
        return normalized

    if not isinstance(result, list):
        raise ValueError(f"{game.name}: result phải là danh sách số.")
    numbers = [int(value) for value in result]
    if game.kind == "keno":
        if len(numbers) != game.main_count:
            raise ValueError(f"Keno cần đúng {game.main_count} số mỗi kỳ.")
        if len(set(numbers)) != len(numbers):
            raise ValueError("Các số Keno trong cùng kỳ không được trùng.")
        if not all(1 <= n <= game.max_number for n in numbers):
            raise ValueError(f"Số Keno phải trong khoảng 1..{game.max_number}.")
        return numbers

    expected = game.main_count + (1 if game.special_max is not None else 0)
    if len(numbers) != expected:
        raise ValueError(f"{game.name} cần {expected} số trong result.")
    main, special = numbers[: game.main_count], numbers[game.main_count :]
    if len(set(main)) != len(main):
        raise ValueError(f"{game.name}: các số chính không được trùng.")
    if not all(1 <= n <= game.max_number for n in main):
        raise ValueError(f"{game.name}: số chính phải trong khoảng 1..{game.max_number}.")
    if special:
        if not 1 <= special[0] <= (game.special_max or game.max_number):
            raise ValueError(f"{game.name}: số đặc biệt nằm ngoài miền hợp lệ.")
        if game.code == "power655" and special[0] in main:
            raise ValueError(f"{game.name}: số đặc biệt không được trùng số chính.")
    return numbers


def normalize_record(game: Game, raw: dict[str, Any]) -> dict[str, Any] | None:
    result = _result_values(raw)
    if result is None and raw.get("main") is not None:
        result = raw["main"]
        if raw.get("special") is not None:
            result = [*result, raw["special"]]
    if result is None:
        return None
    try:
        normalized = normalize_result(game, result)
    except (TypeError, ValueError):
        return None
    draw_id = raw.get("id") or raw.get("draw_id") or raw.get("ky") or ""
    if not draw_id:
        return None
    return {
        "id": str(draw_id),
        "date": str(raw.get("date") or raw.get("ngay") or ""),
        "result": normalized,
    }


def records_path(game_code: str) -> Path:
    return DATA_DIR / get_game(game_code).data_file


def load_records(game_code: str) -> list[dict[str, Any]]:
    game = get_game(game_code)
    path = records_path(game_code)
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                record = normalize_record(game, raw)
                if record is not None:
                    records.append(record)
    records.sort(key=lambda row: (row["date"] or "", row["id"]))
    return records


def _append_records(game_code: str, records: list[dict[str, Any]]) -> int:
    if not records:
        return 0
    path = records_path(game_code)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as destination:
        for record in records:
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    return len(records)


def update_from_github(game_code: str) -> int:
    game = get_game(game_code)
    path = records_path(game_code)
    url = f"{GITHUB_DATA_URL}/{path.name}"
    print(f"Đang tải dữ liệu {game.name} từ {url} ...")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    existing_ids = {row["id"] for row in load_records(game_code)}
    incoming = []
    for line in tqdm(response.text.splitlines(), desc="Lọc kỳ mới"):
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        record = normalize_record(game, raw)
        if record and record["id"] not in existing_ids:
            incoming.append(record)
            existing_ids.add(record["id"])
    added = _append_records(game_code, incoming)
    print(f"Đã thêm {added} kỳ mới.")
    return added


def add_manual_record(
    game_code: str,
    draw_id: str,
    result: Any,
    date_str: str = "",
) -> bool:
    game = get_game(game_code)
    record = {
        "id": draw_id,
        "date": date_str or date.today().isoformat(),
        "result": normalize_result(game, result),
    }
    if any(row["id"] == draw_id for row in load_records(game_code)):
        print(f"Kỳ {draw_id} đã tồn tại trong {game.name}, không thêm.")
        return False
    _append_records(game_code, [record])
    print(f"Đã thêm kỳ {draw_id} vào dữ liệu {game.name}.")
    return True


def analyze_records(game_code: str) -> tuple[Counter, Counter]:
    game = get_game(game_code)
    records = load_records(game_code)
    if game.kind == "digits":
        frequencies = Counter()
        positions = Counter()
        for row in records:
            for values in row["result"].values():
                for code in values:
                    frequencies[code] += 1
                    for position, digit in enumerate(code, start=1):
                        positions[(position, digit)] += 1
        return frequencies, positions

    frequencies = Counter()
    specials = Counter()
    for row in records:
        values = row["result"]
        if game.kind == "draw" and game.special_max is not None:
            frequencies.update(values[: game.main_count])
            specials.update(values[game.main_count :])
        else:
            frequencies.update(values)
    return frequencies, specials
