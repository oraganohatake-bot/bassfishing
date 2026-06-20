"""LureCatalog – Phase 6: six lure types with parameters.

Each LureSpec defines physical / behavioural parameters used by
FishingView to compute lure_match and adjust bite-charge rate.

Lure index → key binding
  0 Minnow     → 1
  1 Crankbait  → 2
  2 Spinnerbait→ 3
  3 Worm       → 4
  4 Jig        → 5
  5 Topwater   → 6
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from constants import (
    ACTION_IDLE, ACTION_RETRIEVE, ACTION_STOP,
    ACTION_TWITCH, ACTION_LIFT, ACTION_FALL,
)
import tuning as TU


@dataclass
class LureSpec:
    name: str
    # ── Physical ────────────────────────────────────────────────────────
    running_depth: float   # typical running depth (m) – display only
    appeal: float          # 0–1  base appeal modifier
    naturalness: float     # 0–1  base naturalness modifier
    vibration: float       # 0–1  vibration / wobble intensity
    splash_power: float    # 0–1  entry-splash effect (topwater only)
    snag_risk: float       # 0–1  probability of snagging on structure
    # ── Behaviour ───────────────────────────────────────────────────────
    best_actions: List[str]      # ACTION_* constants that suit this lure
    best_conditions: List[str]   # see _CONDITION_KEYS below
    best_terrain: List[str]      # "shallow","weed","cover","break","rock","deep"
    # ── UI ──────────────────────────────────────────────────────────────
    color: tuple           # RGB display colour
    description: str
    # ── Phase 9: Fish Learning ──────────────────────────────────────────
    lure_category: str = "hard_bait"
    # Categories: hard_bait | soft_bait | topwater | vibration | bottom_contact
    # ── Beta v0.96: 適正スラックレンジ (m) ──────────────────────────────
    # このルアーが最も食う / 最も掛かる slack_m の帯。None ならカテゴリ既定。
    optimal_slack_range: Tuple[float, float] = None


# ── カテゴリ別 既定適正スラックレンジ (m) ────────────────────────────────
# hard_bait  : テンション維持 → アクション → バイト (張って使う)
# vibration  : 張りつつ波動を出す (やや幅)
# soft_bait  : テンション抜き → フォール → バイト (弛ませて食わせる)
# bottom_contact: しゃくる → slack発生 → フォール → バイト
# topwater   : 水面で張る (ほぼ張ったまま)
OPTIMAL_SLACK_BY_CATEGORY: dict = {
    "hard_bait":      (0.0, 0.3),
    "vibration":      (0.0, 0.4),
    "soft_bait":      (0.4, 1.2),
    "bottom_contact": (0.3, 1.0),
    "topwater":       (0.0, 0.2),
}


# ── Condition key reference ──────────────────────────────────────────────
# "morning"      : 04:00–08:00 game time
# "evening"      : 17:00–21:00 game time
# "cloudy"       : weather == Cloudy
# "rain"         : weather == Rain or Heavy Rain
# "clear"        : weather == Sunny
# "wind"         : wind_speed > 4 m/s
# "low_activity" : env.activity_modifier < 0.65  (cold / hot / pressured)
# "pressure"     : lure spot pressure >= 5 (fish pressure grid)

LURE_CATALOG: List[LureSpec] = [
    LureSpec(
        name="Minnow",
        running_depth=0.5,
        appeal=0.65,
        naturalness=0.75,
        vibration=0.40,
        splash_power=0.20,
        snag_risk=0.10,
        best_actions=[ACTION_TWITCH, ACTION_STOP],
        best_conditions=["morning", "evening", "clear"],
        best_terrain=["shallow"],
        color=(255, 120,  50),
        description="Shallow jerkbait. Best with twitch-and-stop.",
        lure_category="hard_bait",
    ),
    LureSpec(
        name="Crankbait",
        running_depth=2.0,
        appeal=0.70,
        naturalness=0.60,
        vibration=0.85,
        splash_power=0.10,
        snag_risk=0.20,
        best_actions=[ACTION_RETRIEVE],
        best_conditions=["clear", "morning"],
        best_terrain=["break", "rock"],
        color=(255, 200,  30),
        description="Medium-depth crank. Steady retrieve over structure.",
        lure_category="hard_bait",
    ),
    LureSpec(
        name="Spinnerbait",
        running_depth=1.0,
        appeal=0.65,
        naturalness=0.55,
        vibration=0.90,
        splash_power=0.30,
        snag_risk=0.15,
        best_actions=[ACTION_RETRIEVE, ACTION_LIFT],
        best_conditions=["wind", "cloudy", "rain"],
        best_terrain=["weed", "cover"],
        color=( 80, 230,  80),
        description="Blade bait. Shines in wind, stained water, weed.",
        lure_category="vibration",
    ),
    LureSpec(
        name="Worm",
        running_depth=2.5,
        appeal=0.55,
        naturalness=0.90,
        vibration=0.20,
        splash_power=0.05,
        snag_risk=0.20,
        best_actions=[ACTION_STOP, ACTION_FALL, ACTION_TWITCH],
        best_conditions=["low_activity", "pressure"],
        best_terrain=["cover", "weed"],
        color=(180,  80, 220),
        description="Soft plastic. Works on pressured, finicky fish.",
        lure_category="soft_bait",
    ),
    LureSpec(
        name="Jig",
        running_depth=3.5,
        appeal=0.60,
        naturalness=0.80,
        vibration=0.30,
        splash_power=0.05,
        snag_risk=0.45,
        best_actions=[ACTION_FALL, ACTION_STOP],
        best_conditions=["low_activity", "pressure"],
        best_terrain=["rock", "cover"],
        color=( 60, 150, 220),
        description="Heavy jig. Bottom-contact; targets big bass on structure.",
        lure_category="bottom_contact",
    ),
    LureSpec(
        name="Topwater",
        running_depth=0.0,
        appeal=0.80,
        naturalness=0.70,
        vibration=0.50,
        splash_power=0.95,
        snag_risk=0.05,
        best_actions=[ACTION_TWITCH, ACTION_STOP, ACTION_IDLE],
        best_conditions=["morning", "evening", "cloudy", "rain"],
        best_terrain=["shallow"],
        color=(255,  55, 140),
        description="Surface popper. Explosive at dawn/dusk or overcast.",
        lure_category="topwater",
    ),
]

LURE_NAMES: List[str] = [s.name for s in LURE_CATALOG]


def get_spec(name: str) -> LureSpec:
    """Return the LureSpec for *name*, falling back to Minnow."""
    for s in LURE_CATALOG:
        if s.name == name:
            return s
    return LURE_CATALOG[0]


def get_spec_by_idx(idx: int) -> LureSpec:
    return LURE_CATALOG[idx % len(LURE_CATALOG)]


def optimal_slack_range(spec: LureSpec) -> Tuple[float, float]:
    """*spec* の適正スラックレンジ (m)。未指定ならカテゴリ既定を返す。"""
    if spec.optimal_slack_range is not None:
        return spec.optimal_slack_range
    return OPTIMAL_SLACK_BY_CATEGORY.get(spec.lure_category, (0.0, 0.3))


def slack_modifier(slack: float, rng: Tuple[float, float]) -> float:
    """現在の *slack* (m) が適正レンジ *rng* にどれだけ合っているか。

    レンジ内      → SLACK_BITE_OPTIMAL (1.0)
    NEAR_TOL以内 → SLACK_BITE_NEAR    (0.7)
    大きく外れる  → SLACK_BITE_FAR     (0.3)
    """
    lo, hi = rng
    if lo <= slack <= hi:
        return TU.SLACK_BITE_OPTIMAL
    dist = (lo - slack) if slack < lo else (slack - hi)
    if dist <= TU.SLACK_NEAR_TOL:
        return TU.SLACK_BITE_NEAR
    return TU.SLACK_BITE_FAR
