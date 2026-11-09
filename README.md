# Vietlott Lottery Research Tool

Công cụ Python để cập nhật, phân tích dữ liệu, sinh vé tham khảo, backtest và
theo dõi kết quả Vietlott. Dữ liệu được tách riêng theo game. Kết quả quá khứ
không dự đoán hay đảm bảo kết quả xổ số tương lai; tool chưa tính tiền thưởng.

## Các game hỗ trợ

| Tên game | Giá trị `--game` | Dạng kết quả |
|---|---|---|
| Power 6/55 | `power655` (mặc định) | 6 số chính và 1 số đặc biệt |
| Power 6/45 | `power645` | 6 số chính |
| Power 5/35 | `power535` | 5 số chính và 1 số đặc biệt |
| Keno | `keno` | 20 số được quay mỗi kỳ |
| Max 3D | `3d` | Các dãy 3 chữ số theo hạng giải |
| Max 3D Pro | `3d_pro` | Các dãy 3 chữ số theo hạng giải |

Các lệnh hỗ trợ `--game`; nếu bỏ qua, tool dùng `power655`. Dữ liệu từ các
game được lưu thành file riêng, không dùng chung bản ghi.

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
python main.py update --game power645
python main.py update --game keno
```

Các mã game khác là `power535`, `3d` và `3d_pro`. Nguồn GitHub dùng file
`data/<game>.jsonl` trong `vietvudanh/vietlott-data`.

Nếu GitHub không có dữ liệu mới, có thể thử lấy kết quả mới nhất từ
vietlott.vn:

```bash
python main.py update --try-vietlott
```

Fallback cào trực tiếp hiện chỉ hỗ trợ Power 6/55; trang Vietlott có thể chặn
truy cập tự động. Nếu cần, cài thêm `cloudscraper` và `beautifulsoup4`. Có thể
nhập kỳ quay thủ công cho mọi game:

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

Định dạng nhập tay theo từng game:

```bash
# Power 6/45: chỉ nhập 6 số chính, không có --special
python main.py add-manual --game power645 --draw-id "00001" \
  --numbers "1,5,12,20,33,44"

# Power 5/35: 5 số chính và số đặc biệt
python main.py add-manual --game power535 --draw-id "00001" \
  --numbers "7,9,10,16,19" --special 9

# Keno: nhập đủ 20 số được quay
python main.py add-manual --game keno --draw-id "#0110271" \
  --numbers "3,8,10,11,16,20,26,29,31,32,33,43,44,47,55,57,60,75,79,80"

# Max 3D / Max 3D Pro: giữ số 0 ở đầu bằng chuỗi 3 ký tự
python main.py add-manual --game 3d --draw-id "00001" \
  --result-json '{"Giải Đặc biệt":["015","517"],"Giải Nhất":["334","279"]}'
```

Với Max 3D/Max 3D Pro, truyền kết quả dạng JSON object gồm tên hạng giải và
danh sách các số trúng (mỗi số đúng 3 chữ số). `--date` tùy chọn; nếu bỏ qua,
tool dùng ngày hiện tại. Mã kỳ đã tồn tại trong cùng game sẽ không được thêm
lại. Đối với Power 5/35, số đặc biệt được quay từ miền riêng nên có thể trùng
giá trị với một số chính.

### Phân tích dữ liệu

```bash
python main.py analyze
python main.py analyze --game power645
python main.py analyze --game 3d_pro
```

Power 6/55 in thống kê tần suất, cặp/bộ ba và tạo các biểu đồ
`freq_main.png`, `freq_special.png`, `pair_heatmap.png`. Các game khác in tần
suất theo cấu trúc dữ liệu game; Max 3D/Max 3D Pro thống kê dãy 3 chữ số và
tần suất từng chữ số theo vị trí. Có thể chỉ định thư mục biểu đồ cho Power
6/55:

```bash
mkdir -p output
python main.py analyze --out output
```

### Backtest

```bash
python main.py backtest
```

Power 6/55 chạy walk-forward với các model A/B/C/ngẫu nhiên. Các game khác
hiện dùng model ngẫu nhiên làm đường cơ sở:

```bash
python main.py backtest --start-idx 500 --tickets 10 --seed 42
python main.py backtest --game keno --start-idx 500 --tickets 10 --pick-count 10
```

`--start-idx` là chỉ số dòng trong dữ liệu đã sắp theo thời gian, bắt đầu từ 0.
`--pick-count` áp dụng cho Keno. Thêm `--refresh` để đồng bộ thêm các kỳ mới từ
GitHub trước khi chạy.

### Sinh bộ số tham khảo

```bash
python main.py predict
python main.py predict --game power645
python main.py predict --game keno --pick-count 10
python main.py predict --game 3d_pro
```

Power 6/55 dùng các model A, B, C và ngẫu nhiên (R). Các game khác sinh vé
tham khảo theo tần suất dữ liệu đã thấy, lưu bằng model `frequency-random`.
Với Keno có thể chọn số lượng số trong mỗi vé bằng `--pick-count`. Tất cả dự
đoán được ghi vào SQLite cùng mã game.

```bash
python main.py predict --tickets 10 --seed 42
python main.py predict --tickets 5 --draw-target "#01422"
```

`--special` và `--draw-target` là tùy chọn với Power 6/55; Power 5/35 cũng
nhận `--special` (nếu bỏ qua, tool chọn ngẫu nhiên một số đặc biệt). Seed cố
định giúp tái tạo cùng chuỗi kết quả khi dữ liệu và tham số không đổi. Nếu
chỉ định `--special` cho Power 6/55, số đó không được trùng số chính trong bất
kỳ vé nào được sinh ra.

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

Chọn `--game` tương ứng. Power 6/45 và Keno không dùng `--special`; Keno nhập
20 số qua `--numbers`. Với Max 3D/Max 3D Pro, dùng `--result-json` như ví dụ:

```bash
python main.py record-result --game 3d --draw-id "00001" \
  --result-json '{"Giải Đặc biệt":["015","517"],"Giải Nhất":["334","279"]}'
```

Xem báo cáo hiệu suất đã paper-track:

```bash
python main.py perf
python main.py perf --game power645
```

## Dữ liệu và tệp được tạo

- Dữ liệu được lấy từ GitHub theo game và lưu tại `data/<game>.jsonl`;
  `update`/`--refresh` chỉ nối các kỳ chưa có, không ghi đè dữ liệu thủ công.
- Dự đoán, kết quả và đánh giá được lưu tại `data/tracker.sqlite`.
- Biểu đồ Power 6/55 lưu ở thư mục làm việc hiện tại hoặc thư mục truyền qua
  `analyze --out`.

## Cấu trúc chính

- `main.py`: CLI cho các game, các lệnh `analyze`, `backtest`, `predict`,
  `record-result`, `perf`, `update`, `add-manual`.
- `games.py`: định nghĩa mã game và cấu trúc kết quả.
- `game_data.py`: tải dữ liệu GitHub, kiểm tra schema, nhập tay và thống kê chung.
- `updater.py`: fallback trực tiếp Vietlott cho Power 6/55.
- `data_loader.py`: đọc và kiểm tra dữ liệu Power 6/55.
- `analysis.py`: thống kê tần suất, cặp, bộ ba và giao nhau số.
- `model.py`: các model sinh vé.
- `backtest.py`: walk-forward backtest và tổng hợp kết quả.
- `tracker.py`: lưu và đánh giá dự đoán bằng SQLite.
- `charts.py`: xuất biểu đồ.

Chạy kiểm tra tự động:

```bash
python -m unittest discover -s tests -v
```
