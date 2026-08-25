"""G0.4: Recalibración de OBSTACLE_OCCUPANCY_BLOCKED contra dataset de F1.3.

- Usa ttc_gt_s * speed_mps para estimar profundidad real.
- Define "celda ocupada" como profundidad <= umbral (5, 10, 15 m).
- Recalibra la ocupancia: occ_corregida = clip((divergence / 8) * k, 0, 1).
- ROC para encontrar factor k óptimo por índice de Youden.
- Reporta AUC y umbrales recomendados.

Uso:
    python experiments/analyze_occupancy.py runs/ttc/*.jsonl
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


def recalibrate_occupancy(records, depth_threshold_m=10.0):
    """Calibra ocupancia contra profundidad real.

    Define "celda ocupada" como z = ttc_gt_s * speed_mps <= depth_threshold_m.
    Usa ROC para encontrar el factor k óptimo tal que occ = clip(divergence * k, 0, 1).
    """
    # Filtrar registros con confianza y datos válidos.
    valid_records = [
        r for r in records
        if r.get("confidence", 0.0) > 0.0 and r.get("ttc_gt_s") is not None
        and r.get("speed_mps", 0.0) > 0.01 and r.get("divergence", 0.0) >= 0.0
    ]

    if not valid_records:
        print(f"Sin registros válidos para profundidad {depth_threshold_m}m")
        return None

    # Crear evento binario basado en profundidad.
    depths = np.array([r["ttc_gt_s"] * r["speed_mps"] for r in valid_records])
    y_true = (depths <= depth_threshold_m).astype(int)

    if y_true.sum() == 0 or y_true.sum() == len(y_true):
        print(f"  profundidad {depth_threshold_m}m: sin variación de clase.")
        return None

    # Probar diferentes factores k: desde 0.01 hasta 10.0.
    k_values = np.logspace(-2, 1, 50)  # 0.01 a 10.0
    divergences = np.array([r["divergence"] for r in valid_records])

    best_auc = -1.0
    best_k = 0.125  # default conservador
    best_youden_idx = -1

    for k in k_values:
        # Escalar divergencia a ocupancia.
        occupancies = np.clip(divergences * k / 8.0, 0.0, 1.0)

        # Construir curva ROC usando ocupancia como score.
        thresholds = np.unique(occupancies)
        tprs, fprs = [], []

        for thr in thresholds:
            pred = occupancies >= thr
            tp = np.sum(pred & (y_true == 1))
            fp = np.sum(pred & (y_true == 0))
            fn = np.sum(~pred & (y_true == 1))
            tn = np.sum(~pred & (y_true == 0))
            tpr = tp / (tp + fn) if (tp + fn) else 0.0
            fpr = fp / (fp + tn) if (fp + tn) else 0.0
            tprs.append(tpr)
            fprs.append(fpr)

        # Calcular AUC.
        order = np.argsort(fprs)
        trapz = getattr(np, "trapezoid", None) or np.trapz
        auc = trapz(np.array(tprs)[order], np.array(fprs)[order])

        # Actualizar si es mejor.
        if auc > best_auc:
            best_auc = auc
            best_k = k
            # Encontrar índice de Youden en el mejor k.
            youden = np.array(tprs) - np.array(fprs)
            best_youden_idx = int(np.argmax(youden))

    # Con el mejor k, recalcular el umbral de ocupancia óptimo.
    occupancies_best = np.clip(divergences * best_k / 8.0, 0.0, 1.0)
    thresholds_best = np.unique(occupancies_best)
    tprs_best, fprs_best = [], []

    for thr in thresholds_best:
        pred = occupancies_best >= thr
        tp = np.sum(pred & (y_true == 1))
        fp = np.sum(pred & (y_true == 0))
        fn = np.sum(~pred & (y_true == 1))
        tn = np.sum(~pred & (y_true == 0))
        tpr = tp / (tp + fn) if (tp + fn) else 0.0
        fpr = fp / (fp + tn) if (fp + tn) else 0.0
        tprs_best.append(tpr)
        fprs_best.append(fpr)

    youden_best = np.array(tprs_best) - np.array(fprs_best)
    best_idx = int(np.argmax(youden_best))
    best_occ_threshold = thresholds_best[best_idx] if best_idx < len(thresholds_best) else 0.35

    return {
        "depth_threshold_m": depth_threshold_m,
        "n_samples": len(valid_records),
        "positive_ratio": y_true.sum() / len(y_true),
        "best_k": best_k,
        "best_occ_threshold": best_occ_threshold,
        "best_auc": best_auc,
    }


def false_positive_analysis(records):
    """Mide la tasa de falsos positivos del criterio OR (occupancy >= 0.35 OR ttc_s <= 2.5).

    Usa profundidad real (ttc_gt_s * speed_mps) como ground truth de ocupancia.
    """
    valid_records = [
        r for r in records
        if r.get("confidence", 0.0) > 0.0 and r.get("ttc_gt_s") is not None
        and r.get("speed_mps", 0.0) > 0.01
    ]

    if not valid_records:
        print("Sin registros válidos para análisis de falsos positivos.")
        return

    # Ground truth: celda ocupada si profundidad <= 10 m.
    depths = np.array([r["ttc_gt_s"] * r["speed_mps"] for r in valid_records])
    y_true = (depths <= 10.0).astype(int)

    # Predicciones con umbral provisional (0.35 ocupancia, 2.5s TTC).
    occupancies = np.array([r["occupancy"] for r in valid_records])
    ttcs = np.array([r.get("ttc_est_s", float("inf")) for r in valid_records])

    # Criterio OR: bloqueado si occupancy >= 0.35 OR ttc <= 2.5.
    y_pred = (occupancies >= 0.35) | (ttcs <= 2.5)

    # Metricas.
    tp = np.sum(y_pred & (y_true == 1))
    fp = np.sum(y_pred & (y_true == 0))
    fn = np.sum(~y_pred & (y_true == 1))
    tn = np.sum(~y_pred & (y_true == 0))

    sensitivity = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    fnr = fn / (fn + tp) if (fn + tp) else 0.0

    print(f"\nAnálisis de falsos positivos (umbral profundidad 10m):")
    print(f"  N={len(valid_records)}  positivos={y_true.sum()}")
    print(f"  Sensibilidad (TPR)={sensitivity:.2%}  Especificidad={specificity:.2%}")
    print(f"  Precisión={precision:.2%}  FPR={fpr:.2%}  FNR={fnr:.2%}")


def main():
    patterns = sys.argv[1:] or ["runs/ttc/*.jsonl"]
    records = load_records(patterns)
    if not records:
        print(f"Sin registros para {patterns}. Correr antes collect_ttc_dataset.py.")
        return

    print(f"Cargados {len(records)} registros de {patterns}\n")

    # Recalibrar para diferentes umbrales de profundidad.
    print("Recalibración de OBSTACLE_OCCUPANCY_BLOCKED (usa np.gradient corregido):")
    print("(Busca factor k óptimo para occ = clip((divergence / 8) * k, 0, 1))\n")

    results = []
    for depth_m in [5.0, 10.0, 15.0]:
        result = recalibrate_occupancy(records, depth_threshold_m=depth_m)
        if result:
            results.append(result)
            print(
                f"  Profundidad {depth_m}m: "
                f"k={result['best_k']:.3f}  "
                f"occ_threshold={result['best_occ_threshold']:.3f}  "
                f"AUC={result['best_auc']:.3f}  "
                f"positivos={result['positive_ratio']:.1%}"
            )

    # Recomendación: usar el mejor k (promediado entre umbrales si es estable).
    if results:
        k_values = [r["best_k"] for r in results]
        k_mean = np.mean(k_values)
        k_std = np.std(k_values)
        print(f"\n  Recomendación: k={k_mean:.3f} ± {k_std:.3f}")
        print(f"  Fijar DIVERGENCE_TO_OCCUPANCY_SCALE = {k_mean:.3f} en src/perception/flow_ttc.py:280")

    # Análisis de tasa de falsos positivos con umbrales actuales.
    false_positive_analysis(records)

    print(f"\n✓ Recalibración completa. Actualizar .env y CHANGELOG.md con los valores recomendados.")


if __name__ == "__main__":
    main()
