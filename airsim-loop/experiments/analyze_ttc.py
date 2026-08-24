"""F1.3: analiza el dataset de collect_ttc_dataset.py.

- Dispersion ttc_est vs ttc_gt, correlacion y error relativo.
- Error estratificado por velocidad y por |yaw_rate| (valida la derotacion).
- ROC del evento binario "colision dentro de tau segundos", para elegir
  TTC_EVASION_THRESHOLD / TTC_SAFE_THRESHOLD con evidencia.

Uso:
    python experiments/analyze_ttc.py runs/ttc/*.jsonl
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np


def load_records(patterns):
    records = []
    for pattern in patterns:
        for path in glob.glob(pattern):
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
    return records


def correlation_and_error(records):
    pairs = [(r["ttc_est_s"], r["ttc_gt_s"]) for r in records if r.get("ttc_est_s") is not None and r.get("confidence", 0) > 0.15]
    if not pairs:
        print("Sin pares (ttc_est, ttc_gt) con confianza suficiente.")
        return
    est = np.array([p[0] for p in pairs])
    gt = np.array([p[1] for p in pairs])
    corr = np.corrcoef(est, gt)[0, 1] if len(pairs) > 1 else float("nan")
    rel_err = np.abs(est - gt) / np.maximum(gt, 1e-3)
    print(f"N={len(pairs)}  correlacion(ttc_est, ttc_gt)={corr:.3f}  error_relativo_mediano={np.median(rel_err):.2%}")


def stratified_by_yaw_rate(records):
    print("\nError relativo estratificado por |yaw_rate| (valida la derotacion, F1.2):")
    bins = [(0.0, 0.05), (0.05, 0.2), (0.2, 1.0), (1.0, float("inf"))]
    for lo, hi in bins:
        subset = [
            r for r in records
            if r.get("ttc_est_s") is not None and lo <= abs(r.get("yaw_rate_rad_s", 0.0)) < hi and r.get("confidence", 0) > 0.15
        ]
        if not subset:
            continue
        est = np.array([r["ttc_est_s"] for r in subset])
        gt = np.array([r["ttc_gt_s"] for r in subset])
        rel_err = np.abs(est - gt) / np.maximum(gt, 1e-3)
        print(f"  |yaw_rate| in [{lo:.2f}, {hi:.2f}) rad/s: N={len(subset)}  error_relativo_mediano={np.median(rel_err):.2%}")


def roc_for_threshold(records, tau_values=(1.0, 2.0, 3.0)):
    print("\nROC del evento 'colision dentro de tau s' (usa ttc_gt como proxy de colision real):")
    for tau in tau_values:
        y_true = np.array([1 if r["ttc_gt_s"] <= tau else 0 for r in records if r.get("ttc_est_s") is not None])
        scores = np.array([-r["ttc_est_s"] for r in records if r.get("ttc_est_s") is not None])  # TTC bajo = score alto de riesgo
        if y_true.sum() == 0 or y_true.sum() == len(y_true):
            print(f"  tau={tau}s: sin variacion de clase, no se puede calcular AUC.")
            continue
        thresholds = np.unique(scores)
        tprs, fprs = [], []
        for thr in thresholds:
            pred = scores >= thr
            tp = np.sum(pred & (y_true == 1))
            fp = np.sum(pred & (y_true == 0))
            fn = np.sum(~pred & (y_true == 1))
            tn = np.sum(~pred & (y_true == 0))
            tprs.append(tp / (tp + fn) if (tp + fn) else 0.0)
            fprs.append(fp / (fp + tn) if (fp + tn) else 0.0)
        order = np.argsort(fprs)
        auc = np.trapz(np.array(tprs)[order], np.array(fprs)[order])
        # Indice de Youden: umbral que maximiza TPR - FPR.
        youden = np.array(tprs) - np.array(fprs)
        best_idx = int(np.argmax(youden))
        best_ttc_threshold = -thresholds[best_idx]
        print(f"  tau={tau}s: AUC={auc:.3f}  umbral_TTC_optimo(Youden)={best_ttc_threshold:.2f}s")


def main():
    patterns = sys.argv[1:] or ["runs/ttc/*.jsonl"]
    records = load_records(patterns)
    if not records:
        print(f"Sin registros para {patterns}. Correr antes collect_ttc_dataset.py.")
        return
    print(f"Cargados {len(records)} registros de {patterns}")
    correlation_and_error(records)
    stratified_by_yaw_rate(records)
    roc_for_threshold(records)


if __name__ == "__main__":
    main()
