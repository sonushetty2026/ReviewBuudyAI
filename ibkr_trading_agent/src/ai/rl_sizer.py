"""
RL Position Sizer — tabular Q-learning agent for adaptive position sizing.

This is "recursive learning": after every trade, the agent receives a
reward (the realised R-multiple) and updates its policy so future sizing
decisions in similar market conditions improve.

State space (3 × 3 × 3 = 27 discrete states):
  win_rate_bucket   0 = poor   (<40%)     1 = neutral (40–60%)   2 = good (>60%)
  drawdown_bucket   0 = fine   (<1% acct) 1 = caution (1–3%)     2 = danger (>3%)
  volatility_bucket 0 = low    (ATR<0.5%) 1 = medium  (0.5–1.5%) 2 = high  (>1.5%)

Action space (5 discrete multipliers):
  [0.50, 0.75, 1.00, 1.25, 1.50]

Reward:
  realised R-multiple of the completed trade
  (e.g. +1.5 if we made 1.5× risk, -1.0 if stopped out)

Q-update (TD-0):
  Q(s,a) ← Q(s,a) + α · [r + γ · max_a' Q(s', a') − Q(s, a)]

Exploration:
  Epsilon-greedy policy; epsilon decays from 0.20 → 0.05 over time.
  After ~200 trades the agent is almost entirely in exploit mode.

Persistence:
  Q-table saved as JSON after every update so learning survives restarts.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

ACTIONS: list[float] = [0.50, 0.75, 1.00, 1.25, 1.50]
N_ACTIONS = len(ACTIONS)

StateKey = tuple[int, int, int]


@dataclass(frozen=True)
class RLState:
    win_rate_bucket: int    # 0 | 1 | 2
    drawdown_bucket: int    # 0 | 1 | 2
    volatility_bucket: int  # 0 | 1 | 2

    def key(self) -> StateKey:
        return (self.win_rate_bucket, self.drawdown_bucket, self.volatility_bucket)


class RLSizer:
    """
    Tabular Q-learning agent for position-size selection.

    Usage
    -----
    sizer = RLSizer(q_table_path="data/rl_qtable.json")

    # Before each trade:
    mult = sizer.choose_multiplier(win_rate, drawdown_pct, avg_atr_pct)

    # After trade closes:
    sizer.update(r_multiple, new_win_rate, new_drawdown_pct, new_avg_atr_pct)
    """

    def __init__(
        self,
        q_table_path: str,
        learning_rate: float = 0.10,
        discount: float = 0.90,
        epsilon_start: float = 0.20,
        epsilon_min: float = 0.05,
        epsilon_decay: float = 0.995,
    ):
        self._path = q_table_path
        self._lr = learning_rate
        self._gamma = discount
        self._epsilon = epsilon_start
        self._epsilon_min = epsilon_min
        self._epsilon_decay = epsilon_decay

        self._q: dict[StateKey, list[float]] = {}
        self._last_state: Optional[RLState] = None
        self._last_action_idx: Optional[int] = None
        self._n_updates: int = 0

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def choose_multiplier(
        self,
        win_rate: float,
        drawdown_pct: float,
        avg_atr_pct: float,
    ) -> float:
        """
        Select a position-size multiplier using epsilon-greedy policy.

        Parameters
        ----------
        win_rate      : fraction of trades won this session (0–1)
        drawdown_pct  : |daily_loss| / account_size (0–1)
        avg_atr_pct   : average ATR / price of watchlist symbols (0–1)
        """
        state = self._discretize(win_rate, drawdown_pct, avg_atr_pct)
        self._last_state = state
        key = state.key()

        if key not in self._q:
            self._q[key] = [0.0] * N_ACTIONS

        # Epsilon-greedy
        if random.random() < self._epsilon:
            action_idx = random.randint(0, N_ACTIONS - 1)
            mode = "explore"
        else:
            action_idx = int(max(range(N_ACTIONS), key=lambda i: self._q[key][i]))
            mode = "exploit"

        self._last_action_idx = action_idx
        mult = ACTIONS[action_idx]

        logger.debug(
            "RL sizer: state=%s  action=%.2fx [%s]  ε=%.3f  q=%s",
            key, mult, mode, self._epsilon,
            [round(v, 3) for v in self._q[key]],
        )
        return mult

    def update(
        self,
        reward: float,
        next_win_rate: float,
        next_drawdown_pct: float,
        next_avg_atr_pct: float,
    ) -> None:
        """
        TD-0 update after a trade closes.

        Parameters
        ----------
        reward            : realised R-multiple (+ve winner, -ve loser)
        next_win_rate     : updated win rate after the trade
        next_drawdown_pct : updated drawdown fraction after the trade
        next_avg_atr_pct  : current average ATR%
        """
        if self._last_state is None or self._last_action_idx is None:
            logger.debug("RL update skipped — no prior action recorded")
            return

        s_key = self._last_state.key()
        a = self._last_action_idx

        next_state = self._discretize(next_win_rate, next_drawdown_pct, next_avg_atr_pct)
        ns_key = next_state.key()
        if ns_key not in self._q:
            self._q[ns_key] = [0.0] * N_ACTIONS

        # Bellman update
        best_next = max(self._q[ns_key])
        td_error = reward + self._gamma * best_next - self._q[s_key][a]
        self._q[s_key][a] += self._lr * td_error

        # Decay exploration rate
        self._epsilon = max(self._epsilon_min, self._epsilon * self._epsilon_decay)
        self._n_updates += 1

        logger.info(
            "RL update #%d: state=%s  action=%.2fx  reward=%.3fR  "
            "td_error=%.4f  new_Q=%.4f  ε=%.4f",
            self._n_updates, s_key, ACTIONS[a], reward,
            td_error, self._q[s_key][a], self._epsilon,
        )

        self._save()

    def get_stats(self) -> dict:
        return {
            "rl_states_explored": len(self._q),
            "rl_total_updates": self._n_updates,
            "rl_epsilon": round(self._epsilon, 4),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _discretize(
        self, win_rate: float, drawdown_pct: float, atr_pct: float
    ) -> RLState:
        # Win rate bucket
        if win_rate < 0.40:
            wr = 0
        elif win_rate < 0.60:
            wr = 1
        else:
            wr = 2

        # Drawdown bucket (fraction of account lost today)
        if drawdown_pct < 0.01:
            dd = 0
        elif drawdown_pct < 0.03:
            dd = 1
        else:
            dd = 2

        # Volatility bucket (ATR as fraction of price)
        if atr_pct < 0.005:
            vol = 0
        elif atr_pct < 0.015:
            vol = 1
        else:
            vol = 2

        return RLState(wr, dd, vol)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            serialisable = {str(k): v for k, v in self._q.items()}
            payload = {
                "q": serialisable,
                "epsilon": self._epsilon,
                "n_updates": self._n_updates,
            }
            with open(self._path, "w") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("RL Q-table save failed: %s", exc)

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            raw_q: dict = data.get("q", {})
            # Keys are stored as str(tuple); eval them back
            self._q = {}
            for k, v in raw_q.items():
                try:
                    key: StateKey = tuple(eval(k))  # noqa: S307
                    self._q[key] = v
                except Exception:
                    pass
            self._epsilon = float(data.get("epsilon", self._epsilon))
            self._n_updates = int(data.get("n_updates", 0))
            logger.info(
                "RL Q-table loaded: %d states  %d updates  ε=%.4f",
                len(self._q), self._n_updates, self._epsilon,
            )
        except Exception as exc:
            logger.warning("RL Q-table load failed (starting fresh): %s", exc)
