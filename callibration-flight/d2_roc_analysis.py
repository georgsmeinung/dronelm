"""D2 — Análisis ROC para calibración de OCCUPANCY_BLOCKED_THRESHOLD.

Carga el NPZ capturado con d2_occupancy_capture.py, define ground truth
binario por gt_depth_centro, barre thresholds sobre occ_centro y encuentra
threshold* = argmax(TPR - FPR) (índice de Youden).

Uso:
    python d2_roc_analysis.py d2_dataset/d2_dataset_20260910_130726.npz
    python d2_roc_analysis.py d2_dataset/d2_dataset_20260910_130726.npz --gt-dist 5.0
"""
import argparse
import sys
from pathlib import Path

import numpy as np

# ── GT: distancia a partir de la cual consideramos "obstáculo presente" ──────
DEFAULT_GT_DIST_M = 5.0   # frames con gt_depth_centro < este valor → positivo


def load_npz(path: str) -> dict:
    data = np.load(path, allow_pickle=True)
    return {k: data[k] for k in data.files}


def roc_sweep(scores: np.ndarray, labels: np.ndarray, n_thresholds: int = 500):
    """Devuelve (thresholds, tpr, fpr, youden_j)."""
    t_min, t_max = scores.min(), scores.max()
    thresholds = np.linspace(t_min, t_max, n_thresholds)

    n_pos = labels.sum()
    n_neg = len(labels) - n_pos

    tpr_list, fpr_list = [], []
    for t in thresholds:
        pred = scores >= t
        tp = (pred & labels).sum()
        fp = (pred & ~labels).sum()
        tpr_list.append(tp / n_pos if n_pos > 0 else 0.0)
        fpr_list.append(fp / n_neg if n_neg > 0 else 0.0)

    tpr = np.array(tpr_list)
    fpr = np.array(fpr_list)
    youden = tpr - fpr
    return thresholds, tpr, fpr, youden


def main():
    p = argparse.ArgumentParser()
    p.add_argument("npz", help="Ruta al archivo .npz del dataset D2")
    p.add_argument("--gt-dist", type=float, default=DEFAULT_GT_DIST_M,
                   help=f"Distancia GT (m) para label positivo (default {DEFAULT_GT_DIST_M})")
    p.add_argument("--current-threshold", type=float, default=0.35,
                   help="Threshold actual en obstacle_field.py (default 0.35)")
    args = p.parse_args()

    npz_path = Path(args.npz)
    if not npz_path.exists():
        sys.exit(f"No se encuentra: {npz_path}")

    d = load_npz(str(npz_path))

    gt_depth  = d["gt_depth_centro"]
    occ       = d["occ_centro"]
    dist_wall = d["dist_to_wall_m"]
    conf      = d["conf_centro"]
    speed     = d["approach_speed_mps"]

    n_total = len(occ)
    labels  = gt_depth < args.gt_dist   # True = obstáculo presente
    n_pos   = int(labels.sum())
    n_neg   = n_total - n_pos

    print(f"\n── Dataset: {npz_path.name} ──")
    print(f"  Frames totales : {n_total}")
    print(f"  GT threshold   : gt_depth_centro < {args.gt_dist} m")
    print(f"  Positivos (GT) : {n_pos}  ({100*n_pos/n_total:.1f}%)")
    print(f"  Negativos (GT) : {n_neg}  ({100*n_neg/n_total:.1f}%)")
    print(f"  occ_centro     : min={occ.min():.4f}  max={occ.max():.4f}  "
          f"mean={occ.mean():.4f}  p95={np.percentile(occ,95):.4f}")
    print(f"  conf_centro    : min={conf.min():.3f}  max={conf.max():.3f}  "
          f"mean={conf.mean():.3f}")

    # ── ROC ──────────────────────────────────────────────────────────────────
    thresholds, tpr, fpr, youden = roc_sweep(occ, labels)

    best_idx    = int(np.argmax(youden))
    best_thresh = float(thresholds[best_idx])
    best_tpr    = float(tpr[best_idx])
    best_fpr    = float(fpr[best_idx])
    best_j      = float(youden[best_idx])

    # AUC (trapezoidal, eje fpr)
    order = np.argsort(fpr)
    auc   = float(np.trapz(tpr[order], fpr[order]))

    print(f"\n── Curva ROC ──")
    print(f"  AUC                  : {auc:.4f}")
    print(f"  Threshold óptimo     : {best_thresh:.4f}  (Youden J = {best_j:.4f})")
    print(f"  TPR @ óptimo         : {best_tpr:.3f}")
    print(f"  FPR @ óptimo         : {best_fpr:.3f}")

    # ── Comparación con threshold actual ────────────────────────────────────
    cur_t   = args.current_threshold
    cur_tpr = float(tpr[np.argmin(np.abs(thresholds - cur_t))])
    cur_fpr = float(fpr[np.argmin(np.abs(thresholds - cur_t))])
    cur_j   = cur_tpr - cur_fpr

    print(f"\n── Threshold actual ({cur_t}) ──")
    print(f"  TPR : {cur_tpr:.3f}")
    print(f"  FPR : {cur_fpr:.3f}")
    print(f"  J   : {cur_j:.4f}")

    # ── Recomendación ────────────────────────────────────────────────────────
    diff = abs(best_thresh - cur_t)
    print(f"\n── Recomendación ──")
    if diff > 0.05:
        print(f"  ✗ El threshold actual ({cur_t}) difiere en {diff:.3f} del óptimo.")
        print(f"  → Actualizar OCCUPANCY_BLOCKED_THRESHOLD = {best_thresh:.4f}")
        print(f"    en obstacle_field.py y config/.env")
    else:
        print(f"  ✓ El threshold actual ({cur_t}) está dentro de ±0.05 del óptimo.")
        print(f"    No se requiere cambio.")

    # ── Tabla de puntos clave ────────────────────────────────────────────────
    print(f"\n── Puntos clave de la curva (threshold → TPR, FPR, J) ──")
    key_thresholds = [0.005, 0.01, 0.02, 0.03, 0.05, 0.10, best_thresh, cur_t]
    key_thresholds = sorted(set(key_thresholds))
    print(f"  {'Threshold':>10}  {'TPR':>6}  {'FPR':>6}  {'J':>7}")
    print(f"  {'-'*36}")
    for kt in key_thresholds:
        idx = int(np.argmin(np.abs(thresholds - kt)))
        marker = " ← ÓPTIMO" if abs(kt - best_thresh) < 1e-6 else (
                 " ← ACTUAL"  if abs(kt - cur_t)      < 1e-6 else "")
        print(f"  {kt:>10.4f}  {tpr[idx]:>6.3f}  {fpr[idx]:>6.3f}  {youden[idx]:>7.4f}{marker}")

    # ── Guardar curva ROC como CSV para el informe ────────────────────────────
    out_csv = npz_path.parent / (npz_path.stem + "_roc.csv")
    rows = np.column_stack([thresholds, tpr, fpr, youden])
    np.savetxt(out_csv, rows, delimiter=",",
               header="threshold,tpr,fpr,youden_j", comments="")
    print(f"\n  Curva guardada en: {out_csv}")

    # ── Intento de plot (matplotlib opcional) ─────────────────────────────────
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))

        ax = axes[0]
        ax.plot(fpr[np.argsort(fpr)], tpr[np.argsort(fpr)], "b-", lw=2,
                label=f"ROC (AUC={auc:.3f})")
        ax.scatter([best_fpr], [best_tpr], color="red", zorder=5,
                   label=f"Óptimo t={best_thresh:.4f}")
        ax.scatter([cur_fpr], [cur_tpr], color="orange", zorder=5, marker="s",
                   label=f"Actual t={cur_t}")
        ax.plot([0, 1], [0, 1], "k--", lw=0.8)
        ax.set_xlabel("FPR"); ax.set_ylabel("TPR")
        ax.set_title("Curva ROC — occ_centro vs gt_depth_centro")
        ax.legend(); ax.grid(True, alpha=0.3)

        ax2 = axes[1]
        ax2.plot(thresholds, youden, "g-", lw=2, label="Youden J")
        ax2.axvline(best_thresh, color="red", ls="--",
                    label=f"Óptimo = {best_thresh:.4f}")
        ax2.axvline(cur_t, color="orange", ls="--",
                    label=f"Actual = {cur_t}")
        ax2.set_xlabel("Threshold"); ax2.set_ylabel("J = TPR − FPR")
        ax2.set_title("Índice de Youden por threshold")
        ax2.legend(); ax2.grid(True, alpha=0.3)

        out_png = npz_path.parent / (npz_path.stem + "_roc.png")
        fig.tight_layout()
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
        print(f"  Gráfico guardado en: {out_png}")
    except ImportError:
        print("  (matplotlib no disponible — solo CSV)")


if __name__ == "__main__":
    main()
