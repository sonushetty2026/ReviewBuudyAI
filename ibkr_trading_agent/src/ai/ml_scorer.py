"""
ML Signal Scorer — Gradient Boosting classifier that learns which
ORB setups are most likely to win.

Features (8 total):
  vwap_dist_pct   : % distance of entry price above/below VWAP
  rs_score        : relative strength vs SPY (positive = stock stronger)
  volume_ratio    : current bar volume / historical average
  spread_bps      : bid-ask spread in basis points
  atr_pct         : ATR as % of entry price (proxy for volatility)
  or_range_pct    : Opening Range size as % of price (large = high-volatility day)
  time_sin        : cyclical sine encoding of time of day
  time_cos        : cyclical cosine encoding of time of day

Training:
  - Activated after MIN_SAMPLES (20) completed trades
  - Retrained from scratch after each new trade (fast: <200ms for <500 samples)
  - Model persisted to disk so learning accumulates across sessions

Before 20 trades: returns neutral score (0.5, active=False)
After  20 trades: returns calibrated win probability (active=True)
"""

from __future__ import annotations

import logging
import math
import os
import pickle
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MIN_SAMPLES = 20  # trades needed before ML scoring activates

FEATURE_NAMES = [
    "vwap_dist_pct",
    "rs_score",
    "volume_ratio",
    "spread_bps",
    "atr_pct",
    "or_range_pct",
    "time_sin",
    "time_cos",
]


@dataclass
class MLScore:
    win_probability: float     # 0.0–1.0 predicted P(win)
    n_samples: int             # training set size
    active: bool               # False = not enough data yet, score is neutral
    top_feature: str = ""      # highest-importance feature (for logging)


class MLScorer:
    """
    Gradient Boosting classifier trained on every completed trade.

    Usage
    -----
    scorer = MLScorer(model_path="data/ml_model.pkl")
    score  = scorer.score(features)        # before entry
    scorer.update(features, was_winner)    # after position closes
    """

    def __init__(self, model_path: str):
        self._path = model_path
        self._model = None
        self._X: list[list[float]] = []
        self._y: list[int] = []           # 1 = winner, 0 = loser
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, features: dict) -> MLScore:
        """Score a candidate trade signal."""
        n = len(self._y)
        if self._model is None or n < MIN_SAMPLES:
            return MLScore(win_probability=0.5, n_samples=n, active=False)

        x = self._extract(features)
        try:
            import numpy as np
            prob = float(self._model.predict_proba(np.array([x]))[0][1])
            top = self._top_feature()
        except Exception as exc:
            logger.warning("ML score prediction failed: %s", exc)
            return MLScore(win_probability=0.5, n_samples=n, active=False)

        return MLScore(
            win_probability=round(prob, 4),
            n_samples=n,
            active=True,
            top_feature=top,
        )

    def update(self, features: dict, was_winner: bool) -> None:
        """
        Record a closed trade result and retrain the model.
        Should be called once after every position closes.
        """
        x = self._extract(features)
        self._X.append(x)
        self._y.append(1 if was_winner else 0)

        n = len(self._y)
        logger.debug("ML training set: %d samples", n)

        if n >= MIN_SAMPLES:
            self._train()

    @property
    def n_samples(self) -> int:
        return len(self._y)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extract(self, f: dict) -> list[float]:
        """Convert a feature dict to the fixed-length feature vector."""
        hour = int(f.get("hour", 10))
        minute = int(f.get("minute", 0))
        # Normalise time to [0, 1] across the 6.5-hour US trading day
        t_norm = (hour * 60 + minute) / (6.5 * 60)
        return [
            float(f.get("vwap_dist_pct", 0.0)),
            float(f.get("rs_score", 0.0)),
            float(f.get("volume_ratio", 1.0)),
            float(f.get("spread_bps", 0.0)),
            float(f.get("atr_pct", 0.0)),
            float(f.get("or_range_pct", 0.0)),
            math.sin(2 * math.pi * t_norm),
            math.cos(2 * math.pi * t_norm),
        ]

    def _train(self) -> None:
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            import numpy as np
        except ImportError:
            logger.warning(
                "scikit-learn not installed — ML scoring disabled. "
                "Fix: pip install scikit-learn"
            )
            return

        try:
            X = np.array(self._X, dtype=float)
            y = np.array(self._y, dtype=int)

            self._model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=3,
                learning_rate=0.1,
                subsample=0.8,
                random_state=42,
            )
            self._model.fit(X, y)
            self._save()

            win_rate = y.mean()
            logger.info(
                "ML model retrained on %d trades  win_rate=%.0f%%  top=%s",
                len(y), win_rate * 100, self._top_feature(),
            )
        except Exception as exc:
            logger.error("ML training failed: %s", exc)

    def _top_feature(self) -> str:
        if self._model is None or not hasattr(self._model, "feature_importances_"):
            return ""
        idx = int(self._model.feature_importances_.argmax())
        return FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else ""

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "wb") as f:
                pickle.dump(
                    {"model": self._model, "X": self._X, "y": self._y}, f
                )
        except Exception as exc:
            logger.error("ML model save failed: %s", exc)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "rb") as f:
                data = pickle.load(f)
            self._model = data.get("model")
            self._X = data.get("X", [])
            self._y = data.get("y", [])
            logger.info(
                "ML model loaded from disk: %d training samples", len(self._y)
            )
        except Exception as exc:
            logger.warning("ML model load failed (starting fresh): %s", exc)
