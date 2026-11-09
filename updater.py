"""
Module cập nhật dữ liệu Power 6/55.

Chiến lược:
1. Ưu tiên kéo từ nguồn mở vietvudanh/vietlott-data (NDJSON, cập nhật hàng ngày)
2. Fallback: cào trực tiếp vietlott.vn (có thể bị Cloudflare chặn)
3. Luôn có thể nhập tay qua CLI

Nguyên tắc: không ghi đè dữ liệu cũ, chỉ append bản ghi mới (theo draw_id).
"""

import json
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import requests
from tqdm import tqdm

from config import DATA_URL, DATA_FILE, N_MAIN, MAX_NUMBER


# ============================================================
# 1. Đọc / ghi file local
# ============================================================

def _read_existing_ids() -> set[str]:
    """Đọc tất cả draw_id đã có trong file local."""
    if not DATA_FILE.exists():
        return set()
    ids = set()
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                did = rec.get("id") or rec.get("draw_id") or ""
                if did:
                    ids.add(str(did))
            except json.JSONDecodeError:
                continue
    return ids


def _append_records(records: list[dict]) -> int:
    """Ghi nối các bản ghi mới vào file local. Trả về số bản ghi đã ghi."""
    if not records:
        return 0
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(records)


def _normalize_record(raw: dict) -> Optional[dict]:
    """
    Chuẩn hóa một bản ghi về cấu trúc thống nhất:
      {"id": "...", "date": "YYYY-MM-DD", "result": [m1..m6, special]}
    Chấp nhận nhiều biến thể key từ các nguồn khác nhau.
    """
    try:
        # Lấy mảng số
        numbers = (
            raw.get("result")
            or raw.get("value")
            or raw.get("numbers")
            or raw.get("main")
        )
        if numbers is None:
            return None

        # Nếu là dict có main/special riêng
        if isinstance(numbers, dict):
            main = numbers.get("main") or numbers.get("numbers")
            special = numbers.get("special") or numbers.get("bonus")
            if main and special is not None:
                nums = [int(x) for x in main] + [int(special)]
            else:
                return None
        else:
            nums = [int(x) for x in numbers]

        if len(nums) != N_MAIN + 1:
            return None
        if not all(1 <= n <= MAX_NUMBER for n in nums):
            return None

        did = str(raw.get("id") or raw.get("draw_id") or raw.get("ky") or "")
        date_raw = raw.get("date") or raw.get("ngay") or ""

        # Chuẩn hóa ngày về YYYY-MM-DD nếu có thể
        date_norm = ""
        if date_raw:
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    date_norm = datetime.strptime(str(date_raw), fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
            if not date_norm:
                date_norm = str(date_raw)

        return {"id": did, "date": date_norm, "result": nums}
    except Exception:
        return None


# ============================================================
# 2. Nguồn 1: GitHub vietvudanh/vietlott-data (NDJSON)
# ============================================================

def fetch_from_github() -> list[dict]:
    """
    Kéo toàn bộ file NDJSON từ GitHub, lọc ra bản ghi chưa có local.
    """
    print(f"[1/2] Đang kéo dữ liệu từ GitHub: {DATA_URL}")
    try:
        r = requests.get(DATA_URL, timeout=60)
        r.raise_for_status()
    except Exception as e:
        print(f"  Lỗi kéo GitHub: {e}")
        return []

    existing = _read_existing_ids()
    new_records = []
    lines = r.text.strip().split("\n")
    for line in tqdm(lines, desc="  Lọc bản ghi mới"):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        norm = _normalize_record(raw)
        if norm is None:
            continue
        did = norm["id"]
        if did and did in existing:
            continue
        new_records.append(norm)

    print(f"  Tìm thấy {len(new_records)} bản ghi mới.")
    return new_records


# ============================================================
# 3. Nguồn 2: Cào trực tiếp vietlott.vn (fallback)
# ============================================================

VIETLOTT_URL = "https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/655.html"


def fetch_from_vietlott_html() -> list[dict]:
    """
    Cào trang kết quả mới nhất từ vietlott.vn.
    Lưu ý: trang này dùng Cloudflare, requests thường có thể bị chặn.
    Nếu cần, cài cloudscraper: pip install cloudscraper
    """
    print(f"[2/2] Thử cào trực tiếp vietlott.vn ...")
    try:
        import cloudscraper  # type: ignore
        scraper = cloudscraper.create_scraper()
    except ImportError:
        scraper = requests.Session()
        scraper.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36"
        })

    try:
        resp = scraper.get(VIETLOTT_URL, timeout=30)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print(f"  Lỗi cào vietlott.vn: {e}")
        print("  Gợi ý: pip install cloudscraper, hoặc dùng nhập tay.")
        return []

    # Parse DOM — cấu trúc theo tài liệu Vietlott Source Notes [citation:3]
    # div.chitietketqua_title h5 > b[0] = draw_id, b[1] = date
    # div.day_so_ket_qua_v2 span.bong_tron (active = special)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        container = soup.select_one("div.chitietketqua")
        if not container:
            print("  Không tìm thấy div.chitietketqua — có thể bị Cloudflare.")
            return []

        h5 = container.select_one("div.chitietketqua_title h5")
        b_tags = h5.find_all("b") if h5 else []
        draw_id = b_tags[0].get_text(strip=True).lstrip("#") if len(b_tags) > 0 else ""
        date_raw = b_tags[1].get_text(strip=True) if len(b_tags) > 1 else ""

        ball_div = container.select_one("div.day_so_ket_qua_v2")
        if not ball_div:
            print("  Không tìm thấy div.day_so_ket_qua_v2.")
            return []

        balls = ball_div.find_all("span", class_="bong_tron")
        main, special = [], None
        for b in balls:
            val = b.get_text(strip=True)
            if not val.isdigit():
                continue
            n = int(val)
            if "active" in b.get("class", []):
                special = n
            else:
                main.append(n)

        if len(main) != N_MAIN or special is None:
            print(f"  Parse không đủ: main={main}, special={special}")
            return []

        rec = {
            "id": draw_id,
            "date": _normalize_date(date_raw),
            "result": main + [special],
        }
        existing = _read_existing_ids()
        if draw_id in existing:
            print(f"  Kỳ {draw_id} đã có, bỏ qua.")
            return []
        print(f"  Lấy được kỳ {draw_id}: {rec['result']}")
        return [rec]
    except ImportError:
        print("  Thiếu beautifulsoup4. Cài: pip install beautifulsoup4")
        return []
    except Exception as e:
        print(f"  Lỗi parse HTML: {e}")
        return []


def _normalize_date(s: str) -> str:
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


# ============================================================
# 4. Nhập tay
# ============================================================

def add_manual(draw_id: str, main: list[int], special: int, date_str: str = "") -> bool:
    """Thêm một kỳ quay bằng tay. Trả về True nếu thêm mới."""
    if len(main) != N_MAIN:
        raise ValueError(f"Cần đúng {N_MAIN} số chính, nhận {len(main)}")
    if not all(1 <= n <= MAX_NUMBER for n in main + [special]):
        raise ValueError(f"Số phải trong 1..{MAX_NUMBER}")
    if len(set(main)) != N_MAIN:
        raise ValueError("Các số chính không được trùng nhau")

    existing = _read_existing_ids()
    if draw_id in existing:
        print(f"Kỳ {draw_id} đã tồn tại, không thêm.")
        return False

    rec = {
        "id": draw_id,
        "date": date_str or date.today().isoformat(),
        "result": sorted(main) + [special],
    }
    _append_records([rec])
    print(f"Đã thêm kỳ {draw_id}: {rec['result']}")
    return True


# ============================================================
# 5. Hàm tổng hợp
# ============================================================

def update(use_vietlott: bool = False) -> int:
    """
    Cập nhật dữ liệu. Trả về tổng số bản ghi mới đã thêm.
    - use_vietlott=False: chỉ dùng GitHub (nhanh, ổn định)
    - use_vietlott=True: thử GitHub trước, nếu không có gì mới thì thử vietlott.vn
    """
    new = fetch_from_github()
    if not new and use_vietlott:
        new = fetch_from_vietlott_html()

    if new:
        n = _append_records(new)
        print(f"Đã thêm {n} bản ghi mới vào {DATA_FILE}")
        return n
    print("Không có bản ghi mới nào.")
    return 0


def get_latest_local() -> Optional[dict]:
    """Đọc bản ghi cuối cùng trong file local (nếu có)."""
    if not DATA_FILE.exists():
        return None
    last = None
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except json.JSONDecodeError:
                    continue
    return last