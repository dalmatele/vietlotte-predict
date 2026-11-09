import argparse
import json
import random
from pathlib import Path

import pandas as pd

from data_loader import load_draws, validate, explode_main
from analysis import (
    freq_main, freq_special, pair_stats, triple_stats, special_main_cross
)
from model import (
    build_pair_score, model_A_candidates, model_B_candidates,
    model_C_candidates, model_random_candidates,
)
from backtest import walk_forward, summarize
from charts import plot_freq_main, plot_freq_special, plot_pair_heatmap
from tracker import init_db, save_prediction, save_result, evaluate_pending, performance_report
from updater import update as updater_update, add_manual, get_latest_local


def cmd_update(args):
    """Cập nhật dữ liệu từ nguồn online hoặc vietlott.vn."""
    latest = get_latest_local()
    if latest:
        print(f"Bản ghi mới nhất hiện có: kỳ {latest.get('id')} ({latest.get('date')})")
    n = updater_update(use_vietlott=args.try_vietlott)
    print(f"Tổng cộng thêm {n} kỳ.")


def cmd_add_manual(args):
    """Nhập tay một kỳ quay."""
    main = [int(x) for x in args.main.split(",")]
    add_manual(
        draw_id=args.draw_id,
        main=main,
        special=args.special,
        date_str=args.date or "",
    )


def cmd_analyze(args):
    df = load_draws(force_download=args.refresh)
    validate(df)
    print(f"Loaded {len(df)} kỳ. Kỳ đầu: {df.iloc[0]['draw_id']} ({df.iloc[0]['date']}), "
          f"kỳ cuối: {df.iloc[-1]['draw_id']} ({df.iloc[-1]['date']})")

    f_main = freq_main(df)
    f_special = freq_special(df)
    print("\nTop 12 số chính:")
    print(f_main.head(12).to_string())
    print("\nTop 12 số đặc biệt:")
    print(f_special.head(12).to_string())

    ps = pair_stats(df)
    print(f"\nSố cặp vượt FDR 5%: {(ps['q_fdr'] < 0.05).sum()} / {len(ps)}")
    print(ps.head(10).to_string(index=False))

    ts = triple_stats(df, min_count=3)
    if not ts.empty:
        print(f"\nSố bộ ba vượt FDR 5%: {(ts['q_fdr'] < 0.05).sum()} / {len(ts)}")
        print(ts.head(10).to_string(index=False))

    print("\nGiao nhau số chính × số đặc biệt (top 15):")
    print(special_main_cross(df, top=15).to_string(index=False))

    out_dir = Path(args.out) if args.out else Path(".")
    plot_freq_main(f_main, str(out_dir / "freq_main.png"))
    plot_freq_special(f_special, str(out_dir / "freq_special.png"))
    plot_pair_heatmap(ps, str(out_dir / "pair_heatmap.png"))
    print(f"\nĐã lưu biểu đồ vào {out_dir.resolve()}")


def cmd_backtest(args):
    df = load_draws(force_download=args.refresh)
    validate(df)
    print(f"Backtest trên {len(df)} kỳ, từ kỳ index {args.start_idx}.")
    res = walk_forward(
        df, start_idx=args.start_idx, n_tickets=args.tickets,
        seed=args.seed, models=("A", "B", "C", "R"),
    )
    summary = summarize(res)
    print("\n== Kết quả backtest ==")
    print(summary.to_string(index=False))


def cmd_predict(args):
    df = load_draws(force_download=args.refresh)
    validate(df)
    f = freq_main(df)
    ps = pair_stats(df)
    score = build_pair_score(ps, alpha=5.0)
    rng = random.Random(args.seed)

    models = {
        "A": model_A_candidates(f, args.tickets, rng),
        "B": model_B_candidates(f, score, args.tickets, rng),
        "C": model_C_candidates(f, score, args.tickets, rng),
        "R": model_random_candidates(args.tickets, rng),
    }

    for m, tickets in models.items():
        print(f"\n--- Model {m} ---")
        for t in tickets:
            print(" ", sorted(t))
        pid = save_prediction(
            model=m, tickets=tickets, special=args.special,
            draw_target=args.draw_target,
            meta={"n_train": len(df), "seed": args.seed, "tickets": args.tickets},
        )
        print(f"  saved prediction_id={pid}")


def cmd_record_result(args):
    draw_id = args.draw_id
    main = [int(x) for x in args.main.split(",")]
    save_result(draw_id=draw_id, date=args.date, main=main, special=args.special)
    print(f"Đã lưu kết quả {draw_id}")
    n = evaluate_pending(draw_id)
    print(f"Đã evaluate {n} predictions với kết quả {draw_id}")


def cmd_perf(args):
    performance_report()


def build_parser():
    p = argparse.ArgumentParser(description="Vietlott Power 6/55 Research Tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Phân tích tần suất, cặp, bộ ba, xuất biểu đồ")
    a.add_argument("--refresh", action="store_true", help="Tải lại dữ liệu từ GitHub")
    a.add_argument("--out", default=None, help="Thư mục lưu biểu đồ")
    a.set_defaults(func=cmd_analyze)

    b = sub.add_parser("backtest", help="Walk-forward backtest A/B/C/random")
    b.add_argument("--refresh", action="store_true")
    b.add_argument("--start-idx", type=int, default=500)
    b.add_argument("--tickets", type=int, default=10)
    b.add_argument("--seed", type=int, default=42)
    b.set_defaults(func=cmd_backtest)

    c = sub.add_parser("predict", help="Sinh bộ số cho kỳ tiếp theo và lưu prediction")
    c.add_argument("--refresh", action="store_true")
    c.add_argument("--tickets", type=int, default=10)
    c.add_argument("--special", type=int, default=None, help="Chọn số đặc biệt (nếu muốn)")
    c.add_argument("--draw-target", default=None, help="Mã kỳ dự đoán (vd #01422)")
    c.add_argument("--seed", type=int, default=42)
    c.set_defaults(func=cmd_predict)

    d = sub.add_parser("record-result", help="Ghi kết quả kỳ quay thực và evaluate predictions")
    d.add_argument("--draw-id", required=True)
    d.add_argument("--date", default="")
    d.add_argument("--main", required=True, help="6 số chính, cách nhau dấu phẩy, vd 1,5,12,20,33,44")
    d.add_argument("--special", type=int, required=True)
    d.set_defaults(func=cmd_record_result)

    e = sub.add_parser("perf", help="Xem hiệu suất các model đã paper-track")
    e.set_defaults(func=cmd_perf)
        
    u = sub.add_parser("update", help="Cập nhật dữ liệu từ GitHub/vietlott.vn")
    u.add_argument("--try-vietlott", action="store_true",
                   help="Nếu GitHub không có gì mới, thử cào vietlott.vn")
    u.set_defaults(func=cmd_update)

    m = sub.add_parser("add-manual", help="Nhập tay một kỳ quay")
    m.add_argument("--draw-id", required=True, help="Mã kỳ, vd #01422")
    m.add_argument("--main", required=True, help="6 số chính, vd 5,19,20,26,44,53")
    m.add_argument("--special", type=int, required=True, help="Số đặc biệt")
    m.add_argument("--date", default="", help="Ngày quay YYYY-MM-DD (tùy chọn)")
    m.set_defaults(func=cmd_add_manual)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    init_db()
    args.func(args)