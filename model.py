import random
import itertools
import numpy as np
import pandas as pd
from config import N_MAIN, MAX_NUMBER


def _to_main_set(row) -> set[int]:
    return {int(row[f"m{i+1}"]) for i in range(N_MAIN)}


def score_pairs(numbers: list[int], pair_score: dict[tuple[int, int], float]) -> float:
    """Tổng log-lift (đã làm trơn) của 15 cặp trong bộ 6 số."""
    s = 0.0
    for a, b in itertools.combinations(sorted(numbers), 2):
        s += pair_score.get((a, b), 0.0)
    return s


def build_pair_score(pair_df: pd.DataFrame, alpha: float = 5.0) -> dict[tuple[int, int], float]:
    """
    Làm trơn: log((count + alpha*prior) / (expected + alpha*prior))
    Với prior = 1.0 (mức trung bình), tránh log(0).
    """
    d = {}
    for _, r in pair_df.iterrows():
        num = r["count"] + alpha
        den = r["expected"] + alpha
        d[(int(r["a"]), int(r["b"]))] = float(np.log(num / den))
    return d


# ---------------- Model A: tần suất đơn ----------------
def model_A_candidates(freq: pd.Series, n_tickets: int, rng: random.Random) -> list[list[int]]:
    top = freq.sort_values(ascending=False).head(20).index.tolist()
    out = []
    seen = set()
    while len(out) < n_tickets:
        cand = tuple(sorted(rng.sample(top, N_MAIN)))
        if cand not in seen:
            seen.add(cand)
            out.append(list(cand))
    return out


# ---------------- Model B: cặp + tần suất ----------------
def _weighted_choice(weights: dict[int, float], k: int, rng: random.Random) -> list[int]:
    nums = list(weights.keys())
    w = np.array([weights[n] for n in nums], dtype=float)
    w = np.clip(w, 1e-9, None)
    w /= w.sum()
    return sorted(rng.choices(nums, weights=w, k=k))


def model_B_candidates(
    freq: pd.Series,
    pair_score: dict[tuple[int, int], float],
    n_tickets: int,
    rng: random.Random,
) -> list[list[int]]:
    # Trọng số chọn số: kết hợp tần suất và "độ mạnh cặp" trung bình với các số khác
    pair_strength = {n: 0.0 for n in range(1, MAX_NUMBER + 1)}
    for (a, b), v in pair_score.items():
        pair_strength[a] += v
        pair_strength[b] += v
    weights = {}
    for n in range(1, MAX_NUMBER + 1):
        weights[n] = max(0.1, freq.get(n, 0)) * (1.0 + 0.05 * pair_strength[n])

    out = []
    seen = set()
    trials = 0
    while len(out) < n_tickets and trials < n_tickets * 200:
        trials += 1
        cand = tuple(_weighted_choice(weights, N_MAIN, rng))
        if len(cand) < N_MAIN or cand in seen:
            continue
        seen.add(cand)
        out.append(list(cand))
    # Bù nếu chưa đủ
    while len(out) < n_tickets:
        cand = tuple(sorted(rng.sample(range(1, MAX_NUMBER + 1), N_MAIN)))
        if cand not in seen:
            seen.add(cand)
            out.append(list(cand))
    return out


# ---------------- Model C: cặp + đa dạng ----------------
def model_C_candidates(
    freq: pd.Series,
    pair_score: dict[tuple[int, int], float],
    n_tickets: int,
    rng: random.Random,
    pool_size: int = 3000,
    max_overlap: int = 4,
) -> list[list[int]]:
    """
    Sinh pool lớn các bộ có điểm cặp cao, sau đó chọn n_tickets bộ đa dạng:
    bộ mới không được trùng > max_overlap số với mọi bộ đã chọn.
    """
    # Sinh pool bằng beam-ish: lấy 30 số có tần suất cao + ngẫu nhiên
    top = freq.sort_values(ascending=False).head(30).index.tolist()
    pool = []
    seen = set()
    while len(pool) < pool_size:
        if rng.random() < 0.7:
            cand = tuple(sorted(rng.sample(top, N_MAIN)))
        else:
            cand = tuple(sorted(rng.sample(range(1, MAX_NUMBER + 1), N_MAIN)))
        if cand in seen:
            continue
        seen.add(cand)
        sc = score_pairs(list(cand), pair_score)
        pool.append((sc, cand))
    pool.sort(reverse=True)

    selected: list[tuple[int, ...]] = []
    for sc, cand in pool:
        if len(selected) >= n_tickets:
            break
        if all(len(set(cand) & set(s)) <= max_overlap for s in selected):
            selected.append(cand)
    # Nếu chưa đủ do ràng buộc quá chặt, nới lỏng
    if len(selected) < n_tickets:
        for sc, cand in pool:
            if len(selected) >= n_tickets:
                break
            if cand not in selected:
                selected.append(cand)
    return [list(c) for c in selected[:n_tickets]]


def model_random_candidates(n_tickets: int, rng: random.Random) -> list[list[int]]:
    out = []
    seen = set()
    while len(out) < n_tickets:
        cand = tuple(sorted(rng.sample(range(1, MAX_NUMBER + 1), N_MAIN)))
        if cand not in seen:
            seen.add(cand)
            out.append(list(cand))
    return out