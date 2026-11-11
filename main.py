import argparse
import json
import random
from datetime import date
from pathlib import Path

import pandas as pd

from data_loader import load_draws, validate
from analysis import (
    freq_main, freq_special, pair_stats, triple_stats, special_main_cross
)
from model import (
    build_pair_score, model_A_candidates, model_B_candidates,
    model_C_candidates, model_D_candidates, model_random_candidates,
)
from backtest import walk_forward, summarize
from charts import plot_freq_main, plot_freq_special, plot_pair_heatmap
from tracker import (
    init_db, save_prediction, save_result, evaluate_pending, performance_report,
    get_predictions, delete_predictions,
)
from updater import update as updater_update, get_latest_local
from games import get_game, game_choices
from game_data import (
    add_manual_record, analyze_records, load_records, normalize_result,
    update_from_github,
)


def cmd_update(args):
    """Cập nhật dữ liệu cho game được chọn."""
    game = get_game(args.game)
    records = load_records(args.game)
    if records:
        latest = records[-1]
        print(f"Bản ghi mới nhất {game.name}: kỳ {latest['id']} ({latest['date']})")
    n = update_from_github(args.game)
    if not n and args.try_vietlott:
        if args.game != "power655":
            print("Hiện chỉ hỗ trợ fallback vietlott.vn trực tiếp cho Power 6/55.")
        else:
            latest = get_latest_local()
            if latest:
                print(f"Bản ghi mới nhất hiện có: kỳ {latest.get('id')} ({latest.get('date')})")
            n = updater_update(use_vietlott=True)
    print(f"Tổng cộng thêm {n} kỳ.")


def cmd_add_manual(args):
    """Nhập tay một kỳ quay với cấu trúc theo game."""
    game = get_game(args.game)
    if args.result_json:
        result = json.loads(args.result_json)
    elif game.kind == "digits":
        raise ValueError(f"{game.name} cần truyền --result-json.")
    else:
        values = args.numbers
        if not values:
            raise ValueError("Cần truyền --numbers hoặc --main.")
        result = [int(value.strip()) for value in values.split(",")]
        if game.kind == "draw" and game.special_max is not None:
            if args.special is not None:
                result.append(args.special)
            elif len(result) == game.main_count:
                raise ValueError(f"{game.name} cần có số đặc biệt qua --special.")
    add_manual_record(args.game, args.draw_id, result, args.date or "")


def cmd_analyze(args):
    if args.game != "power655":
        game = get_game(args.game)
        if args.refresh:
            update_from_github(args.game)
        records = load_records(args.game)
        if not records:
            raise RuntimeError(f"Chưa có dữ liệu {game.name}. Chạy `python main.py update --game {args.game}`.")
        counts, extra = analyze_records(args.game)
        print(f"{game.name}: {len(records)} kỳ, từ kỳ {records[0]['id']} đến {records[-1]['id']}")
        if game.kind == "digits":
            print("\nTop 20 dãy 3 chữ số theo số lần xuất hiện:")
            print(pd.Series(counts).sort_values(ascending=False).head(20).to_string())
            print("\nTần suất chữ số theo vị trí:")
            for position in range(1, 4):
                print(f"Vị trí {position}: {dict((digit, extra[(position, digit)]) for digit in range(10))}")
        else:
            print("\nTần suất số xuất hiện:")
            print(pd.Series(counts).sort_values(ascending=False).to_string())
            if extra:
                print("\nTần suất số đặc biệt:")
                print(pd.Series(extra).sort_values(ascending=False).to_string())
        return
    if args.refresh:
        update_from_github(args.game)
    df = load_draws()
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
    if args.game != "power655":
        _backtest_other_game(args)
        return
    if args.refresh:
        update_from_github(args.game)
    df = load_draws()
    validate(df)
    print(f"Backtest trên {len(df)} kỳ, từ kỳ index {args.start_idx}.")
    res = walk_forward(
        df, start_idx=args.start_idx, n_tickets=args.tickets,
        seed=args.seed, models=("A", "B", "C", "R", "D"),
    )
    summary = summarize(res)
    print("\n== Kết quả backtest ==")
    print(summary.to_string(index=False))


def cmd_predict(args):
    if args.draw_date:
        try:
            parsed_date = date.fromisoformat(args.draw_date)
        except ValueError as exc:
            raise ValueError("--draw-date phải có định dạng YYYY-MM-DD.") from exc
        if parsed_date.isoformat() != args.draw_date:
            raise ValueError("--draw-date phải có định dạng YYYY-MM-DD.")
    if args.game != "power655":
        _predict_other_game(args)
        return
    requested_models = _selected_prediction_models(args, get_game(args.game))
    if args.refresh:
        update_from_github(args.game)
    df = load_draws()
    validate(df)
    if args.special is not None and not 1 <= args.special <= 55:
        raise ValueError("Số đặc biệt Power 6/55 phải nằm trong khoảng 1..55.")
    f = freq_main(df) if any(model in {"A", "B", "C"} for model in requested_models) else None
    score = None
    if any(model in {"B", "C"} for model in requested_models):
        score = build_pair_score(pair_stats(df), alpha=5.0)
    rng = random.Random(args.seed)

    model_generators = {
        "A": lambda: model_A_candidates(f, args.tickets, rng),
        "B": lambda: model_B_candidates(f, score, args.tickets, rng),
        "C": lambda: model_C_candidates(f, score, args.tickets, rng),
        "R": lambda: model_random_candidates(args.tickets, rng),
        "D": lambda: model_D_candidates(
            draws=[
                [int(value) for value in row]
                for row in df[[f"m{index + 1}" for index in range(6)]].itertuples(
                    index=False, name=None
                )
            ],
            number_pool=range(1, 56),
            picks_per_ticket=6,
            n_tickets=args.tickets,
            rng=random.Random(args.seed + 1),
            exclude_numbers=[args.special] if args.special is not None else (),
        ),
    }
    models = {
        model_name: model_generators[model_name]()
        for model_name in requested_models
    }
    if args.special is not None and any(
        args.special in ticket
        for tickets in models.values()
        for ticket in tickets
    ):
        raise ValueError("Số đặc biệt không được trùng với số chính của vé.")

    for m, tickets in models.items():
        print(f"\n--- Model {m} ---")
        for t in tickets:
            line = f"  {sorted(t)}"
            if args.special is not None:
                line += f" + số đặc biệt {args.special}"
            print(line)
        pid = save_prediction(
            model=m, tickets=tickets, special=args.special,
            draw_target=args.draw_target,
            meta={"n_train": len(df), "seed": args.seed, "tickets": args.tickets},
            game_id=args.game,
            target_date=args.draw_date,
        )
        print(f"  saved prediction_id={pid}")


def cmd_record_result(args):
    game = get_game(args.game)
    if args.result_json:
        result = json.loads(args.result_json)
    elif game.kind == "digits":
        raise ValueError(f"{game.name} cần truyền --result-json.")
    else:
        values = args.numbers
        if not values:
            raise ValueError("Cần truyền --numbers hoặc --main.")
        result = [int(value.strip()) for value in values.split(",")]
        if game.kind == "draw" and game.special_max is not None and args.special is not None:
            result.append(args.special)
    result = normalize_result(game, result)
    special = result[-1] if game.kind == "draw" and game.special_max is not None else None
    stored_result = result[:game.main_count] if special is not None else result
    save_result(
        draw_id=args.draw_id,
        date=args.date,
        main=stored_result,
        special=special,
        game_id=args.game,
    )
    print(f"Đã lưu kết quả {args.draw_id} ({game.name})")
    n = evaluate_pending(args.draw_id, args.game)
    print(f"Đã evaluate {n} predictions với kết quả {args.draw_id}")


def cmd_perf(args):
    performance_report(args.game)


def cmd_predictions(args):
    predictions = get_predictions(
        game_id=args.game,
        limit=args.limit,
        prediction_id=args.id,
    )
    if not predictions:
        print("Chưa có dự đoán phù hợp.")
        return

    if getattr(args, "list", False):
        print("ID | Kỳ mục tiêu | Game | Model | Số trúng cao nhất")
        for prediction in predictions:
            game = get_game(prediction["game_id"])
            evaluation_matches, _ = _select_prediction_target(
                prediction,
                prediction["evaluations"],
                id_key="draw_id",
            )
            if evaluation_matches:
                jsonl_matches = []
                hit_counts = [
                    f"{evaluation['draw_id']}:{evaluation['best_hit']}"
                    for evaluation in evaluation_matches
                ]
                target_matches = evaluation_matches
            else:
                jsonl_matches, _ = _prediction_results_from_jsonl(prediction, game)
                hit_counts = []
                for result in jsonl_matches:
                    ticket_hits = [
                        len(set(ticket) & result["main_numbers"])
                        for ticket in prediction["tickets"]
                    ]
                    if ticket_hits:
                        hit_counts.append(f"{result['id']}:{max(ticket_hits)}")
                target_matches = jsonl_matches
            hit_summary = ", ".join(hit_counts) if hit_counts else "-"
            target_label = _prediction_target_label(prediction, target_matches)
            print(
                f"#{prediction['id']} | "
                f"{target_label} | "
                f"{game.name} | {prediction['model']} | {hit_summary}"
            )
        return

    for prediction in predictions:
        game = get_game(prediction["game_id"])
        evaluation_matches, _ = _select_prediction_target(
            prediction,
            prediction["evaluations"],
            id_key="draw_id",
        )
        jsonl_matches = (
            []
            if evaluation_matches
            else _prediction_results_from_jsonl(prediction, game)[0]
        )
        target_matches = evaluation_matches or jsonl_matches
        print(
            f"\nDự đoán #{prediction['id']} | {game.name} | "
            f"{prediction['created_at']} | model {prediction['model']}"
        )
        print(f"Kỳ mục tiêu: {_prediction_target_label(prediction, target_matches)}")
        for index, ticket in enumerate(prediction["tickets"], start=1):
            line = f"  Vé {index}: {ticket}"
            if prediction["special"] is not None:
                line += f" + số đặc biệt {prediction['special']}"
            print(line)
        if prediction["evaluations"]:
            for evaluation in prediction["evaluations"]:
                date_suffix = f" ({evaluation['date']})" if evaluation["date"] else ""
                outcome = (
                    f"  Kết quả kỳ {evaluation['draw_id']}"
                    f"{date_suffix}: "
                    f"trúng nhiều nhất {evaluation['best_hit']}, "
                    f"tổng số trùng {evaluation['total_hits']}"
                )
                if game.special_max is not None:
                    outcome += (
                        f", số đặc biệt "
                        f"{'trúng' if evaluation['matched_special'] else 'không trúng'}"
                    )
                print(outcome)
                if evaluation["result"] is not None:
                    print(f"  Kết quả thực tế: {evaluation['result']}")
            continue

        matches, match_source = _prediction_results_from_jsonl(prediction, game)
        if not matches:
            print("  Chưa tìm thấy kết quả đối chiếu trong database hoặc JSONL.")
            continue
        for result in matches:
            print(f"  Đối chiếu từ JSONL ({match_source}): kỳ {result['id']} ({result['date']})")
            print(f"  Kết quả thực tế: {result['result']}")
            per_ticket_hits = [
                len(set(ticket) & result["main_numbers"])
                for ticket in prediction["tickets"]
            ]
            if per_ticket_hits:
                print(
                    f"  Trúng nhiều nhất {max(per_ticket_hits)}, "
                    f"tổng số trùng {sum(per_ticket_hits)}"
                )
                for index, hit_count in enumerate(per_ticket_hits, start=1):
                    print(f"  Vé {index}: {hit_count} số trùng")
            if game.special_max is not None and prediction["special"] is not None:
                matched_special = prediction["special"] == result["special"]
                print(
                    f"  Số đặc biệt dự đoán: {prediction['special']} — "
                    f"{'trúng' if matched_special else 'không trúng'}"
                )


def cmd_delete_prediction(args):
    deleted, missing = delete_predictions(args.ids)
    if deleted:
        deleted_labels = ", ".join(f"#{prediction_id}" for prediction_id in deleted)
        print(f"Đã xóa dự đoán {deleted_labels} và các dữ liệu đối chiếu của chúng.")
    if missing:
        missing_labels = ", ".join(f"#{prediction_id}" for prediction_id in missing)
        print(f"Không tìm thấy dự đoán {missing_labels}; các ID này không bị xóa.")


def _selected_prediction_models(args, game):
    if game.code == "power655":
        available = {"A", "B", "C", "D", "R"}
        defaults = ("A", "B", "C", "R", "D")
    elif game.kind == "digits":
        available = {"frequency-random"}
        defaults = ("frequency-random",)
    else:
        available = {"frequency-random", "D"}
        defaults = ("frequency-random", "D")

    requested_models = getattr(args, "models", None)
    requested = tuple(requested_models) if requested_models else defaults
    unsupported = [model for model in requested if model not in available]
    if unsupported:
        choices = ", ".join(sorted(available))
        raise ValueError(
            f"Model {', '.join(unsupported)} không hỗ trợ cho {game.name}. "
            f"Các model có thể chọn: {choices}."
        )
    if len(set(requested)) != len(requested):
        raise ValueError("Không nhập lặp lại cùng một model.")
    return requested


def _prediction_results_from_jsonl(prediction, game):
    records = load_records(prediction["game_id"])
    matches, source = _select_prediction_target(prediction, records)

    enriched_matches = []
    for record in matches:
        result = record["result"]
        if game.kind == "digits":
            main_numbers = {
                code
                for values in result.values()
                for code in values
            }
            special = None
        else:
            main_numbers = set(result[:game.main_count])
            special = (
                result[game.main_count]
                if game.special_max is not None
                else None
            )
        enriched_matches.append({
            **record,
            "main_numbers": main_numbers,
            "special": special,
        })
    return enriched_matches, source


def _select_prediction_target(prediction, candidates, id_key="id"):
    target_id = prediction["draw_target"]
    target_date = prediction["target_date"]
    if target_id:
        normalized_target = str(target_id).lstrip("#")
        matches = [
            item
            for item in candidates
            if str(item[id_key]).lstrip("#") == normalized_target
        ]
        if matches:
            return matches, "mã kỳ mục tiêu"

    if target_date:
        matches = [
            item for item in candidates
            if item.get("date") == target_date
        ]
        if matches:
            return matches, f"ngày mục tiêu {target_date}"
        anchor_text = target_date
        anchor_label = f"ngày mục tiêu {target_date}"
        direction = "future"
    else:
        created_at = prediction.get("created_at") or ""
        if not created_at:
            return [], ""
        anchor_text = created_at[:10]
        anchor_label = f"ngày dự đoán {anchor_text}"
        direction = "past"

    try:
        anchor_date = date.fromisoformat(anchor_text)
    except ValueError:
        return [], ""

    dated_candidates = []
    for item in candidates:
        try:
            item_date = date.fromisoformat(item.get("date", "")[:10])
        except ValueError:
            continue
        if direction == "past" and item_date <= anchor_date:
            dated_candidates.append((item_date, item))
        elif direction == "future" and item_date > anchor_date:
            dated_candidates.append((item_date, item))
    if not dated_candidates:
        return [], ""

    nearest_date = (
        max(item_date for item_date, _ in dated_candidates)
        if direction == "past"
        else min(item_date for item_date, _ in dated_candidates)
    )
    matches = [
        item
        for item_date, item in dated_candidates
        if item_date == nearest_date
    ]
    if direction == "past":
        source = f"kỳ gần nhất trước {anchor_label} ({nearest_date.isoformat()})"
    else:
        source = f"kỳ tiếp theo gần nhất sau {anchor_label} ({nearest_date.isoformat()})"
    return matches, source


def _prediction_target_label(prediction, matches):
    if matches:
        return ", ".join(
            f"{item.get('draw_id', item.get('id'))} ({item.get('date') or 'chưa rõ ngày'})"
            for item in matches
        )
    if prediction["draw_target"]:
        return str(prediction["draw_target"])
    if prediction["target_date"]:
        return prediction["target_date"]
    return "chưa xác định"


def _predict_other_game(args):
    game = get_game(args.game)
    requested_models = _selected_prediction_models(args, game)
    if args.refresh:
        update_from_github(args.game)
    records = load_records(args.game)
    if not records:
        raise RuntimeError(f"Chưa có dữ liệu {game.name}. Chạy `python main.py update --game {args.game}`.")
    rng = random.Random(args.seed)
    predicted_special = args.special
    if game.special_max is not None:
        if predicted_special is None:
            predicted_special = rng.randint(1, game.special_max)
        if not 1 <= predicted_special <= game.special_max:
            raise ValueError(f"Số đặc biệt của {game.name} phải trong khoảng 1..{game.special_max}.")
    if "frequency-random" in requested_models:
        counts, _ = analyze_records(args.game)
        if game.kind == "digits":
            if args.tickets > 1000:
                raise ValueError("Max 3D tối đa 1000 dãy 3 chữ số khác nhau.")
            codes = [f"{number:03d}" for number in range(1000)]
            weights = [max(1, counts.get(code, 0)) for code in codes]
            tickets = []
            seen = set()
            while len(tickets) < args.tickets:
                candidate = rng.choices(codes, weights=weights, k=1)[0]
                if candidate not in seen:
                    seen.add(candidate)
                    tickets.append([candidate])
        else:
            pick_count = args.pick_count if game.kind == "keno" else game.main_count
            if not 1 <= pick_count <= game.max_number:
                raise ValueError(f"--pick-count phải trong khoảng 1..{game.max_number}.")
            numbers = list(range(1, game.max_number + 1))
            weights = [max(1, counts.get(number, 0)) for number in numbers]
            tickets = []
            seen = set()
            while len(tickets) < args.tickets:
                candidate = tuple(sorted(rng.choices(numbers, weights=weights, k=pick_count)))
                if len(set(candidate)) != len(candidate) or candidate in seen:
                    continue
                seen.add(candidate)
                tickets.append(list(candidate))
        print("\n--- Model frequency-random ---")
        for ticket in tickets:
            line = f"  {ticket}"
            if predicted_special is not None:
                line += f" + số đặc biệt {predicted_special}"
            print(line)
        prediction_id = save_prediction(
            model="frequency-random",
            tickets=tickets,
            special=predicted_special,
            draw_target=args.draw_target,
            meta={"seed": args.seed, "tickets": args.tickets},
            game_id=args.game,
            target_date=args.draw_date,
        )
        print(f"Đã lưu prediction_id={prediction_id} ({game.name}).")
    if "D" in requested_models:
        if game.kind == "digits":
            raise ValueError(f"Model D hiện chưa hỗ trợ cho {game.name}.")
        draws = [record["result"][:game.main_count] for record in records]
        relational_tickets = model_D_candidates(
            draws=draws,
            number_pool=range(1, game.max_number + 1),
            picks_per_ticket=args.pick_count if game.kind == "keno" else game.main_count,
            n_tickets=args.tickets,
            rng=random.Random(args.seed + 1),
        )
        print("\n--- Model D: quan hệ kế tiếp ---")
        for ticket in relational_tickets:
            line = f"  {ticket}"
            if predicted_special is not None:
                line += f" + số đặc biệt {predicted_special}"
            print(line)
        prediction_id = save_prediction(
            model="D",
            tickets=relational_tickets,
            special=predicted_special,
            draw_target=args.draw_target,
            meta={"seed": args.seed, "tickets": args.tickets},
            game_id=args.game,
            target_date=args.draw_date,
        )
        print(f"Đã lưu prediction_id={prediction_id} ({game.name}, model D).")


def _backtest_other_game(args):
    game = get_game(args.game)
    if args.refresh:
        update_from_github(args.game)
    records = load_records(args.game)
    if args.start_idx >= len(records):
        raise ValueError(f"--start-idx phải nhỏ hơn số kỳ dữ liệu ({len(records)}).")
    rng = random.Random(args.seed)
    best_hits = []
    total_hits = []
    for record in records[args.start_idx:]:
        if game.kind == "digits":
            actual = {
                code
                for values in record["result"].values()
                for code in values
            }
            tickets = [[f"{rng.randrange(1000):03d}"] for _ in range(args.tickets)]
        else:
            actual_values = record["result"][:game.main_count]
            actual = set(actual_values)
            pick_count = args.pick_count if game.kind == "keno" else game.main_count
            tickets = [
                rng.sample(range(1, game.max_number + 1), pick_count)
                for _ in range(args.tickets)
            ]
        hits = [len(set(ticket) & actual) for ticket in tickets]
        best_hits.append(max(hits))
        total_hits.append(sum(hits))
    print(f"Backtest ngẫu nhiên {game.name}: {len(best_hits)} kỳ, {args.tickets} vé/kỳ.")
    print(f"Trung bình số khớp tốt nhất: {sum(best_hits) / len(best_hits):.4f}")
    print(f"Trung bình tổng số khớp mỗi kỳ: {sum(total_hits) / len(total_hits):.4f}")


def build_parser():
    p = argparse.ArgumentParser(description="Vietlott multi-game research tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="Phân tích dữ liệu game")
    a.add_argument("--game", choices=game_choices(), default="power655")
    a.add_argument("--refresh", action="store_true", help="Đồng bộ thêm các kỳ mới từ GitHub")
    a.add_argument("--out", default=None, help="Thư mục lưu biểu đồ")
    a.set_defaults(func=cmd_analyze)

    b = sub.add_parser("backtest", help="Backtest model (ngẫu nhiên cho game ngoài Power 6/55)")
    b.add_argument("--game", choices=game_choices(), default="power655")
    b.add_argument("--refresh", action="store_true")
    b.add_argument("--start-idx", type=int, default=500)
    b.add_argument("--tickets", type=int, default=10)
    b.add_argument("--pick-count", type=int, default=10, help="Số lựa chọn mỗi vé Keno")
    b.add_argument("--seed", type=int, default=42)
    b.set_defaults(func=cmd_backtest)

    c = sub.add_parser("predict", help="Sinh bộ số cho kỳ tiếp theo và lưu prediction")
    c.add_argument("--game", choices=game_choices(), default="power655")
    c.add_argument("--refresh", action="store_true")
    c.add_argument("--tickets", type=int, default=10)
    c.add_argument("--pick-count", type=int, default=10, help="Số lựa chọn mỗi vé Keno")
    c.add_argument("--special", type=int, default=None, help="Chọn số đặc biệt (nếu muốn)")
    c.add_argument(
        "--models",
        "--model",
        nargs="+",
        choices=("A", "B", "C", "D", "R", "frequency-random"),
        help="Chọn model (vd: --models D; mặc định dùng các model khả dụng)",
    )
    c.add_argument("--draw-target", default=None, help="Mã kỳ dự đoán (vd #01422)")
    c.add_argument("--draw-date", default=None, help="Ngày kỳ dự đoán, định dạng YYYY-MM-DD")
    c.add_argument("--seed", type=int, default=42)
    c.set_defaults(func=cmd_predict)

    d = sub.add_parser("record-result", help="Ghi kết quả kỳ quay thực và evaluate predictions")
    d.add_argument("--game", choices=game_choices(), default="power655")
    d.add_argument("--draw-id", required=True)
    d.add_argument("--date", default="")
    d.add_argument("--numbers", "--main", dest="numbers", help="Danh sách số, cách nhau dấu phẩy")
    d.add_argument("--result-json", help="Kết quả dạng JSON; dùng cho Max 3D/Max 3D Pro")
    d.add_argument("--special", type=int, help="Số đặc biệt nếu game có")
    d.set_defaults(func=cmd_record_result)

    e = sub.add_parser("perf", help="Xem hiệu suất các model đã paper-track")
    e.add_argument("--game", choices=game_choices(), default="power655")
    e.set_defaults(func=cmd_perf)

    h = sub.add_parser("predictions", help="Xem lại các vé đã dự đoán và kết quả đối chiếu")
    h.add_argument("--game", choices=game_choices(), default=None, help="Lọc theo game")
    h.add_argument("--id", type=int, default=None, help="Chỉ xem một prediction ID")
    h.add_argument("--limit", type=int, default=20, help="Số dự đoán gần nhất (mặc định 20)")
    h.add_argument(
        "--list",
        action="store_true",
        help="Liệt kê ID, ngày quay, game, model và số trúng cao nhất",
    )
    h.set_defaults(func=cmd_predictions)

    remove = sub.add_parser(
        "delete-prediction",
        help="Xóa một hoặc nhiều dự đoán đã lưu và các lần đối chiếu của chúng",
    )
    remove.add_argument(
        "--id",
        "--ids",
        dest="ids",
        type=int,
        nargs="+",
        required=True,
        help="Một hoặc nhiều prediction ID cần xóa",
    )
    remove.set_defaults(func=cmd_delete_prediction)
        
    u = sub.add_parser("update", help="Cập nhật dữ liệu từ GitHub/vietlott.vn")
    u.add_argument("--game", choices=game_choices(), default="power655")
    u.add_argument("--try-vietlott", action="store_true",
                   help="Nếu GitHub không có gì mới, thử cào vietlott.vn")
    u.set_defaults(func=cmd_update)

    m = sub.add_parser("add-manual", help="Nhập tay một kỳ quay")
    m.add_argument("--game", choices=game_choices(), default="power655")
    m.add_argument("--draw-id", required=True, help="Mã kỳ, vd #01422")
    m.add_argument("--numbers", "--main", dest="numbers", help="Danh sách số, cách nhau dấu phẩy")
    m.add_argument("--result-json", help="Kết quả dạng JSON; dùng cho Max 3D/Max 3D Pro")
    m.add_argument("--special", type=int, help="Số đặc biệt nếu game có")
    m.add_argument("--date", default="", help="Ngày quay YYYY-MM-DD (tùy chọn)")
    m.set_defaults(func=cmd_add_manual)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    init_db()
    args.func(args)