import itertools
import numpy as np
import pandas as pd
from scipy.stats import binomtest
from statsmodels.stats.multitest import multipletests  # nếu chưa cài: pip install statsmodels

from config import N_MAIN, MAX_NUMBER


# -------- Tần suất --------
def freq_main(df: pd.DataFrame) -> pd.Series:
    cols = [f"m{i+1}" for i in range(N_MAIN)]
    values = df[cols].values.ravel()
    s = pd.Series(values).value_counts().reindex(range(1, MAX_NUMBER + 1), fill_value=0)
    s.index.name = "number"
    s.name = "count_main"
    return s.sort_values(ascending=False)


def freq_special(df: pd.DataFrame) -> pd.Series:
    s = df["special"].value_counts().reindex(range(1, MAX_NUMBER + 1), fill_value=0)
    s.index.name = "number"
    s.name = "count_special"
    return s.sort_values(ascending=False)


# -------- Đồng xuất hiện cặp --------
def pair_counts(df: pd.DataFrame) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    cols = [f"m{i+1}" for i in range(N_MAIN)]
    for row in df[cols].itertuples(index=False):
        nums = sorted(int(x) for x in row)
        for a, b in itertools.combinations(nums, 2):
            counts[(a, b)] = counts.get((a, b), 0) + 1
    return counts


def triple_counts(df: pd.DataFrame) -> dict[tuple[int, int, int], int]:
    counts: dict[tuple[int, int, int], int] = {}
    cols = [f"m{i+1}" for i in range(N_MAIN)]
    for row in df[cols].itertuples(index=False):
        nums = sorted(int(x) for x in row)
        for t in itertools.combinations(nums, 3):
            counts[t] = counts.get(t, 0) + 1
    return counts


def pair_stats(df: pd.DataFrame) -> pd.DataFrame:
    """
    Trả về DataFrame cho 1485 cặp: pair, count, expected, lift, p_raw, q_fdr.
    Expected = N * P(2 số cùng trong 6 số chính) = N * (6/55)*(5/54) = N/99
    """
    n = len(df)
    p_pair = (N_MAIN / MAX_NUMBER) * ((N_MAIN - 1) / (MAX_NUMBER - 1))
    expected = n * p_pair
    counts = pair_counts(df)

    rows = []
    for a, b in itertools.combinations(range(1, MAX_NUMBER + 1), 2):
        c = counts.get((a, b), 0)
        rows.append({"a": a, "b": b, "count": c})
    out = pd.DataFrame(rows)
    out["expected"] = expected
    out["lift"] = out["count"] / expected
    # Binomial test 2 phía với p_pair
    out["p_raw"] = out["count"].apply(
        lambda k: binomtest(int(k), n=n, p=p_pair, alternative="two-sided").pvalue
    )
    out["q_fdr"] = multipletests(out["p_raw"], method="fdr_bh")[1]
    out = out.sort_values("count", ascending=False).reset_index(drop=True)
    return out


def triple_stats(df: pd.DataFrame, min_count: int = 2) -> pd.DataFrame:
    """
    Với 26k bộ ba, chỉ tính stats cho các bộ có count >= min_count để đỡ nặng.
    Expected = N * (6/55)*(5/54)*(4/53) = N * 20 / (55*54*53 / 6?) — tính trực tiếp:
    P(3 số cố định cùng trong 6 số chính) = C(52,3)/C(55,6) = 20 / C(55,3)
    """
    n = len(df)
    from math import comb
    p_triple = comb(52, 3) / comb(55, 6)  # tương đương 20 / C(55,3)
    expected = n * p_triple

    counts = triple_counts(df)
    rows = []
    for t, c in counts.items():
        if c < min_count:
            continue
        rows.append({"triple": t, "count": c})
    if not rows:
        return pd.DataFrame(columns=["triple", "count", "expected", "lift", "p_raw", "q_fdr"])
    out = pd.DataFrame(rows)
    out["expected"] = expected
    out["lift"] = out["count"] / expected
    out["p_raw"] = out["count"].apply(
        lambda k: binomtest(int(k), n=n, p=p_triple, alternative="two-sided").pvalue
    )
    out["q_fdr"] = multipletests(out["p_raw"], method="fdr_bh")[1]
    out = out.sort_values("count", ascending=False).reset_index(drop=True)
    return out


def special_main_cross(df: pd.DataFrame, top: int = 20) -> pd.DataFrame:
    """
    Đếm các cặp (số chính i, số đặc biệt j) cùng xuất hiện trong cùng kỳ.
    Mỗi kỳ có 6 cặp như vậy. Mức kỳ vọng = N * (6/55)*(1/55).
    """
    n = len(df)
    expected = n * (N_MAIN / MAX_NUMBER) * (1 / MAX_NUMBER)
    counts: dict[tuple[int, int], int] = {}
    cols = [f"m{i+1}" for i in range(N_MAIN)]
    for row in df.itertuples(index=False):
        special = int(getattr(row, "special"))
        for i in range(N_MAIN):
            main = int(getattr(row, f"m{i+1}"))
            counts[(main, special)] = counts.get((main, special), 0) + 1
    rows = [{"main": k[0], "special": k[1], "count": v} for k, v in counts.items()]
    out = pd.DataFrame(rows).sort_values("count", ascending=False).head(top).reset_index(drop=True)
    out["expected"] = expected
    out["lift"] = out["count"] / expected
    return out