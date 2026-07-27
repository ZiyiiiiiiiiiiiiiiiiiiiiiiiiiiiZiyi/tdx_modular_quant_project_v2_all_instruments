"""Numerical helpers for bounded causal diagnostics."""
from __future__ import annotations

import numpy as np


def ols(y, x, *, ridge: float = 0.0):
    yv = np.asarray(y, dtype=float).reshape(-1)
    xv = np.asarray(x, dtype=float)
    if xv.ndim == 1:
        xv = xv.reshape(-1, 1)
    valid = np.isfinite(yv) & np.isfinite(xv).all(axis=1)
    yv, xv = yv[valid], xv[valid]
    if len(yv) <= xv.shape[1]:
        raise ValueError("insufficient observations for regression")
    gram = xv.T @ xv
    penalty = np.eye(xv.shape[1]) * max(float(ridge), 0.0)
    beta = np.linalg.pinv(gram + penalty) @ xv.T @ yv
    residual = yv - xv @ beta
    dof = max(len(yv) - xv.shape[1], 1)
    sigma2 = float(residual @ residual / dof)
    covariance = sigma2 * np.linalg.pinv(gram + penalty)
    return beta, residual, covariance, valid


def normal_ci(point: float, standard_error: float, *, z: float = 1.6448536269514722):
    return point - z * standard_error, point + z * standard_error
