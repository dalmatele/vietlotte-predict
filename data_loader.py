import json
import requests
import pandas as pd
from tqdm import tqdm
from config import DATA_URL, DATA_FILE, N_MAIN, MAX_NUMBER


def download_data(force: bool = False) -> None:
    """Tải file power655.jsonl nếu chưa có hoặc force=True."""
    if DATA_FILE.exists() and not force:
        return
    print(f"Đang tải dữ liệu từ {DATA_URL} ...")
    r = requests.get(DATA_URL, timeout=60)
    r.raise_for_status()
    DATA_FILE.write_bytes(r.content)
    print(f"Đã lưu {len(r.content)} bytes vào {DATA_FILE}")


def _parse_record(rec: dict) -> dict | None:
    """
    Dataset vietvudanh có cấu trúc gần như:
      {"id": "...", "date": "2017-08-01", "result": [1,2,3,4,5,6,7]}
    Một số bản có key 'value' hoặc list trực tiếp. Ta cố gắng linh hoạt.
    """
    try:
        result = rec.get("result") or rec.get("value") or rec.get("numbers")
        if result is None:
            return None
        nums = [int(x) for x in result]
        if len(nums) != N_MAIN + 1:
            return None
        draw_id = rec.get("id") or rec.get("draw_id") or rec.get("kỳ") or ""
        date = rec.get("date") or rec.get("ngay") or ""
        main = nums[:N_MAIN]
        special = nums[N_MAIN]
        return {"draw_id": draw_id, "date": date, "main": main, "special": special}
    except Exception:
        return None


def load_draws(force_download: bool = False) -> pd.DataFrame:
    """
    Trả về DataFrame:
      draw_id, date, m1..m6, special
    Sắp xếp theo thứ tự thời gian tăng dần (theo vị trí trong file nếu date thiếu).
    """
    download_data(force=force_download)

    rows = []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in tqdm(f, desc="Đọc jsonl"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            parsed = _parse_record(rec)
            if parsed:
                rows.append(parsed)

    if not rows:
        raise RuntimeError("Không parse được bản ghi nào. Kiểm tra cấu trúc JSONL.")

    df = pd.DataFrame(rows)
    # Thử sắp theo date nếu parse được, không thì giữ nguyên thứ tự file
    df["_date_parsed"] = pd.to_datetime(df["date"], errors="coerce")
    if df["_date_parsed"].notna().any():
        df = df.sort_values("_date_parsed", kind="stable").reset_index(drop=True)
    df = df.drop(columns=["_date_parsed"])

    # Tách cột m1..m6
    mains = pd.DataFrame(df["main"].tolist(), columns=[f"m{i+1}" for i in range(N_MAIN)])
    df = pd.concat([df.drop(columns=["main"]), mains], axis=1)
    return df


def explode_main(df: pd.DataFrame) -> pd.DataFrame:
    """Trả về long-format: mỗi dòng là 1 số chính trong 1 kỳ."""
    long = df.melt(
        id_vars=["draw_id", "date"],
        value_vars=[f"m{i+1}" for i in range(N_MAIN)],
        value_name="number",
    )
    long["number"] = long["number"].astype(int)
    return long


def validate(df: pd.DataFrame) -> None:
    """Kiểm tra nhanh tính hợp lệ cơ bản."""
    for i in range(N_MAIN):
        col = f"m{i+1}"
        assert df[col].between(1, MAX_NUMBER).all(), f"{col} ngoài 1..{MAX_NUMBER}"
    assert df["special"].between(1, MAX_NUMBER).all()
    # Mỗi kỳ 6 số chính phải phân biệt
    def distinct(row):
        return len(set(row)) == N_MAIN
    mains = df[[f"m{i+1}" for i in range(N_MAIN)]].values
    assert all(distinct(r) for r in mains), "Có kỳ trùng số chính"