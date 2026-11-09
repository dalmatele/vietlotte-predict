# Vietlott Power 6/55 Research Tool

Công cụ Python để phân tích dữ liệu Power 6/55, chạy backtest các cách chọn số,
sinh bộ số tham khảo và theo dõi kết quả qua SQLite. Đây là công cụ nghiên cứu
dữ liệu; kết quả quá khứ không dự đoán hay đảm bảo kết quả xổ số tương lai.

## Yêu cầu

- Python 3.10 trở lên
- Kết nối Internet lần đầu chạy để tải dữ liệu

## Cài đặt

Mở terminal tại thư mục project:

```bash
cd /duong-dan/toi/vietlotte
```

Tạo và kích hoạt môi trường ảo:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Trên Windows PowerShell, dùng:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Cài các thư viện cần thiết:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Chạy công cụ

Các lệnh được chạy từ thư mục project. Xem trợ giúp:

```bash
python main.py --help
python main.py analyze --help
```

### Cập nhật dữ liệu

Tải dữ liệu mới từ GitHub và chỉ nối các kỳ chưa có vào file local:

```bash
python main.py update
```

Nếu GitHub không có dữ liệu mới, có thể thử lấy kết quả mới nhất từ
vietlott.vn:

```bash
python main.py update --try-vietlott
```

Nguồn vietlott.vn có thể chặn truy cập tự động. Nếu cần, cài thêm
`cloudscraper` và `beautifulsoup4`; nếu việc cập nhật online không thành công,
có thể nhập kỳ quay thủ công:

```bash
python main.py add-manual \
  --draw-id "#01422" \
  --main "5,19,20,26,44,53" \
  --special 12 \
  --date "2026-11-09"
```

Trong Power 6/55, mỗi kỳ quay có 6 số chính và 1 số đặc biệt. `--special` là
số đặc biệt thứ 7, được dùng để xét giải Jackpot 2 (khớp 5 số chính và số đặc
biệt); đây không phải số chính thứ 7. Ví dụ trên, `5,19,20,26,44,53` là 6 số
chính và `12` là số đặc biệt.

Ngày `--date` là tùy chọn; nếu bỏ qua, chương trình dùng ngày hiện tại. Các kỳ
đã có cùng mã sẽ không được thêm lại. Lệnh `update` cập nhật file dữ liệu
`data/power655.jsonl`; các lệnh phân tích và dự đoán sẽ sử dụng file này.

### Phân tích dữ liệu

```bash
python main.py analyze
```

Lệnh in tần suất số chính/số đặc biệt, thống kê cặp và bộ ba, đồng thời tạo
các biểu đồ `freq_main.png`, `freq_special.png` và `pair_heatmap.png` trong
thư mục hiện tại. Có thể chỉ định thư mục đầu ra đã tồn tại:

```bash
mkdir -p output
python main.py analyze --out output
```

### Backtest

```bash
python main.py backtest
```

Mặc định backtest từ kỳ có chỉ số 500, mỗi model sinh 10 vé và dùng seed 42.
Có thể thay đổi các tham số:

```bash
python main.py backtest --start-idx 500 --tickets 10 --seed 42
```

`--start-idx` là chỉ số dòng trong dữ liệu đã sắp theo thời gian, bắt đầu từ 0.
Thêm `--refresh` để tải lại file dữ liệu từ nguồn GitHub trước khi chạy. Khác
với lệnh `update`, thao tác này thay file local bằng dữ liệu tải về, nên các kỳ
chỉ được nhập thủ công có thể bị mất.

### Sinh bộ số tham khảo

```bash
python main.py predict
```

Lệnh tạo vé từ các model A, B, C và ngẫu nhiên (R), rồi lưu dự đoán vào cơ sở
dữ liệu theo dõi. Tùy chọn:

```bash
python main.py predict --tickets 10 --seed 42
python main.py predict --tickets 5 --special 12 --draw-target "#01422"
```

`--special` và `--draw-target` là tùy chọn. Seed cố định giúp tái tạo cùng
chuỗi kết quả khi dữ liệu và tham số không đổi.

### Ghi kết quả thực tế và đối chiếu

Sau khi có kết quả quay, ghi mã kỳ, ngày, sáu số chính và số đặc biệt:

```bash
python main.py record-result \
  --draw-id "#01422" \
  --date "2026-11-09" \
  --main "1,5,12,20,33,44" \
  --special 7
```

Lệnh sẽ lưu kết quả và đối chiếu các dự đoán chưa được đánh giá với mã kỳ đó.
Thay ví dụ trên bằng kết quả chính xác của kỳ quay.

Xem báo cáo hiệu suất đã paper-track:

```bash
python main.py perf
```

## Dữ liệu và tệp được tạo

- Dữ liệu đầu vào được tải tự động từ nguồn GitHub đã cấu hình trong
  `config.py` và lưu tại `data/power655.jsonl`.
- Dùng `python main.py update` để nối dữ liệu mới mà không ghi đè các kỳ đã có.
- Dùng `--refresh` với `analyze`, `backtest` hoặc `predict` để tải lại và thay
  thế file dữ liệu local bằng bản từ GitHub; dùng `update` để chỉ nối kỳ mới.
- Dự đoán, kết quả và đánh giá được lưu tại `data/tracker.sqlite`.
- Các biểu đồ được lưu ở thư mục làm việc hiện tại, hoặc thư mục truyền qua
  `analyze --out`.

## Cấu trúc chính

- `main.py`: CLI và các lệnh `analyze`, `backtest`, `predict`,
  `record-result`, `perf`, `update`, `add-manual`.
- `updater.py`: cập nhật dữ liệu từ nguồn online hoặc nhập kỳ quay thủ công.
- `data_loader.py`: tải, đọc và kiểm tra dữ liệu.
- `analysis.py`: thống kê tần suất, cặp, bộ ba và giao nhau số.
- `model.py`: các model sinh vé.
- `backtest.py`: walk-forward backtest và tổng hợp kết quả.
- `tracker.py`: lưu và đánh giá dự đoán bằng SQLite.
- `charts.py`: xuất biểu đồ.
