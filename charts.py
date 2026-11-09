import matplotlib.pyplot as plt
import pandas as pd
from config import MAX_NUMBER


def plot_freq_main(freq: pd.Series, out_path: str = "freq_main.png") -> None:
    s = freq.reindex(range(1, MAX_NUMBER + 1), fill_value=0)
    plt.figure(figsize=(14, 4))
    plt.bar(s.index, s.values, color="#3b7dd8")
    plt.axhline(s.mean(), color="red", linestyle="--", label=f"mean={s.mean():.1f}")
    plt.title("Tần suất 55 số chính – Power 6/55")
    plt.xlabel("Số")
    plt.ylabel("Số lần xuất hiện")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    plt.close()


def plot_freq_special(freq: pd.Series, out_path: str = "freq_special.png") -> None:
    s = freq.reindex(range(1, MAX_NUMBER + 1), fill_value=0)
    plt.figure(figsize=(14, 4))
    plt.bar(s.index, s.values, color="#e08a1e")
    plt.axhline(s.mean(), color="red", linestyle="--", label=f"mean={s.mean():.1f}")
    plt.title("Tần suất số đặc biệt – Power 6/55")
    plt.xlabel("Số")
    plt.ylabel("Số lần")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    plt.close()


def plot_pair_heatmap(pair_df: pd.DataFrame, out_path: str = "pair_heatmap.png") -> None:
    import numpy as np
    mat = np.zeros((MAX_NUMBER, MAX_NUMBER))
    for _, r in pair_df.iterrows():
        a, b = int(r["a"]) - 1, int(r["b"]) - 1
        mat[a, b] = mat[b, a] = r["count"]
    plt.figure(figsize=(9, 8))
    plt.imshow(mat, cmap="viridis")
    plt.colorbar(label="Số lần đồng xuất hiện")
    plt.title("Ma trận đồng xuất hiện 55×55 (số chính)")
    plt.xlabel("Số")
    plt.ylabel("Số")
    plt.tight_layout()
    plt.savefig(out_path, dpi=140)
    plt.close()