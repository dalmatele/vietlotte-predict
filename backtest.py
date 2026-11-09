import random
import numpy as np
import pandas as pd
from tqdm import tqdm

from analysis import freq_main, pair_stats
from model import (
    build_pair_score,
    model_A_candidates,
    model_B_candidates,
    model_C_candidates,
    model_random_candidates,
)
from config import N_MAIN


def _matches(ticket: list[int], actual: set[int]) -> int:
    return len(set(ticket) & actual)


def walk_forward(
    df: pd.DataFrame,
    start_idx: int = 500,
    n_tickets: int = 10,
    seed: int = 42,
    models: tuple[str, ...] = ("A", "B", "C", "R"),
) -> dict[str, dict]:
    """
    Với mỗi kỳ i từ start_idx..len(df)-1:
      - Dùng df[:i] để tính freq + pair_stats
      - Sinh n_tickets vé cho mỗi model
      - Đối chiếu với kết quả df.iloc[i]
    Trả về dict model -> metrics
    """
    rng = random.Random(seed)
    results = {m: {"best_max": [], "hits": [], "total_hits": [], "distinct": []} for m in models}

    # cache stats mỗi khi refit (refit mỗi 50 kỳ để đỡ chậm)
    refit_every = 50
    cached = {}

    for i in tqdm(range(start_idx, len(df)), desc="Backtest"):
        if i == start_idx or (i - start_idx) % refit_every == 0:
            train = df.iloc[:i]
            f = freq_main(train)
            ps = pair_stats(train)
            score = build_pair_score(ps, alpha=5.0)
            cached = {"freq": f, "pair_score": score}

        f = cached["freq"]
        score = cached["pair_score"]

        actual = {int(df.iloc[i][f"m{j+1}"]) for j in range(N_MAIN)}

        for m in models:
            if m == "A":
                tickets = model_A_candidates(f, n_tickets, rng)
            elif m == "B":
                tickets = model_B_candidates(f, score, n_tickets, rng)
            elif m == "C":
                tickets = model_C_candidates(f, score, n_tickets, rng)
            else:
                tickets = model_random_candidates(n_tickets, rng)

            hits = [_matches(t, actual) for t in tickets]
            results[m]["hits"].append(hits)
            results[m]["best_max"].append(max(hits))
            results[m]["total_hits"].append(sum(hits))
            all_nums = set()
            for t in tickets:
                all_nums.update(t)
            results[m]["distinct"].append(len(all_nums))

    return results


def summarize(results: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for m, r in results.items():
        best = np.array(r["best_max"])
        hits = np.array([h for row in r["hits"] for h in row])
        total = np.array(r["total_hits"])
        distinct = np.array(r["distinct"])
        rows.append({
            "model": m,
            "mean_best_hit": best.mean(),
            "mean_total_hits": total.mean(),
            "tickets_ge2": (hits >= 2).mean(),
            "tickets_ge3": (hits >= 3).mean(),
            "tickets_ge4": (hits >= 4).mean(),
            "mean_distinct_numbers": distinct.mean(),
            "n_draws": len(best),
            "n_tickets": len(hits) // len(best) if len(best) else 0,
        })
    return pd.DataFrame(rows).round(4)