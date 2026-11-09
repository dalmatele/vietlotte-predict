from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATA_URL = "https://raw.githubusercontent.com/vietvudanh/vietlott-data/main/data/power655.jsonl"
DATA_FILE = DATA_DIR / "power655.jsonl"

DB_FILE = DATA_DIR / "tracker.sqlite"

N_MAIN = 6          # số chính
MAX_NUMBER = 55     # 1..55
SPECIAL_SEP = True  # phân tích số đặc biệt riêng