import random
import itertools
from math import comb
from typing import Sequence

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


def model_D_candidates(
    draws: Sequence[Sequence[int]],
    number_pool: Sequence[int],
    picks_per_ticket: int,
    n_tickets: int,
    rng: random.Random,
    smoothing: float = 1.0,
    exclude_numbers: Sequence[int] = (),
) -> list[list[int]]:
    """Generate tickets from the most frequent anchor and conditional co-occurrence.

    The next number is sampled using its smoothed probability of appearing in
    the same draw as the number most recently selected.
    """
    if smoothing <= 0:
        raise ValueError("smoothing must be greater than zero.")
    if n_tickets < 0:
        raise ValueError("n_tickets must not be negative.")

    excluded = set(exclude_numbers)
    numbers = list(dict.fromkeys(int(number) for number in number_pool if number not in excluded))
    if not 1 <= picks_per_ticket <= len(numbers):
        raise ValueError("picks_per_ticket must be within the available number pool.")
    if n_tickets > comb(len(numbers), picks_per_ticket):
        raise ValueError("Requested ticket count exceeds the number of unique combinations.")
    if n_tickets == 0:
        return []

    allowed = set(numbers)
    marginal_counts = {number: 0 for number in numbers}
    pair_counts: dict[tuple[int, int], int] = {}
    valid_draw_count = 0

    for draw in draws:
        values = sorted({int(number) for number in draw if int(number) in allowed})
        if not values:
            continue
        valid_draw_count += 1
        for number in values:
            marginal_counts[number] += 1
        for pair in itertools.combinations(values, 2):
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

    if not valid_draw_count:
        raise ValueError("At least one draw must contain a number from number_pool.")

    highest_count = max(marginal_counts.values())
    anchors = [number for number, count in marginal_counts.items() if count == highest_count]
    if highest_count == 0:
        anchors = numbers

    tickets: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    while len(tickets) < n_tickets:
        selected = [rng.choice(anchors)]
        while len(selected) < picks_per_ticket:
            previous = selected[-1]
            remaining = [number for number in numbers if number not in selected]
            previous_count = marginal_counts[previous]
            weights = []
            for candidate in remaining:
                pair = tuple(sorted((previous, candidate)))
                prior_probability = (marginal_counts[candidate] + 1) / (
                    valid_draw_count + len(numbers)
                )
                cooccurrence = pair_counts.get(pair, 0)
                conditional_probability = (
                    (cooccurrence + smoothing * prior_probability)
                    / (previous_count + smoothing)
                    if previous_count + smoothing
                    else 0.0
                )
                weights.append(conditional_probability)
            if not any(weights):
                weights = [max(1, marginal_counts[number]) for number in remaining]
            selected.append(rng.choices(remaining, weights=weights, k=1)[0])

        ticket = tuple(sorted(selected))
        if ticket not in seen:
            seen.add(ticket)
            tickets.append(list(ticket))
    return tickets