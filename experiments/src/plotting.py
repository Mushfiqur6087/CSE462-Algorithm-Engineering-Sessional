from __future__ import annotations

from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd


def _prepare(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def plot_grouped_bar(df: pd.DataFrame, x: str, y: str, hue: str, title: str, output_path: Path) -> None:
    output_path = _prepare(output_path)
    pivot = df.pivot_table(index=x, columns=hue, values=y, aggfunc="mean")
    ax = pivot.plot(kind="bar", figsize=(9, 5), width=0.8)
    ax.set_title(title)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def plot_line(df: pd.DataFrame, x: str, y: str, hue: str, title: str, output_path: Path) -> None:
    output_path = _prepare(output_path)
    fig, ax = plt.subplots(figsize=(9, 5))
    for label, group in df.groupby(hue):
        group = group.sort_values(x)
        ax.plot(group[x], group[y], marker="o", label=str(label))
    ax.set_title(title)
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(alpha=0.25)
    ax.legend()
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()


def plot_history(df: pd.DataFrame, x: str, y: str, variant: str, title: str, output_path: Path) -> None:
    output_path = _prepare(output_path)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(df[x], df[y], marker="o")
    ax.set_title(f"{title} ({variant})")
    ax.set_xlabel(x)
    ax.set_ylabel(y)
    ax.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(output_path, dpi=180)
    plt.close()
