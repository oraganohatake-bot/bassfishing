"""Fish – bass entity with staged reaction model.

Reaction pipeline
-----------------
IGNORE  → fish is unaware of the lure, patrolling high-score spots
NOTICE  → fish detected the lure and is watching it
APPROACH→ fish is slowly moving toward the lure to investigate
CHASE   → fish has committed and is closing in fast
BITE    → fish is in striking position; FishingView triggers HIT!
SPOOK   → fish was frightened; retreats then returns to IGNORE
CAUGHT  → fish was landed; managed by FishingView

Key spook triggers
------------------
* Lure speed > SPEED_SPOOK while fish is approaching
* Lure naturalness < NAT_SPOOK while fish is chasing
* Depth mismatch > DEPTH_LIMIT_SPOOK while approaching
* High cell pressure when entering chase

Key "feeding window" mechanic
------------------------------
Fish.update() returns "in_range" when state == CHASE and dist < BITE_DIST.
FishingView accumulates bite_charge based on lure action; at threshold it
sets fish.state = REACT_BITE and shows HIT!.
"""

from __future__ import annotations

import random
import math
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from fish_population import FishIndividual

from constants import (
    UW_SIZE, UW_W, UW_H,
    REACT_IGNORE, REACT_NOTICE, REACT_APPROACH,
    REACT_CHASE, REACT_BITE, REACT_SPOOK, FISH_CAUGHT,
)

# ── Detection & transition distances ──────────────────────────────────
NOTICE_RANGE   = 8.0
APPROACH_RANGE = 5.5
CHASE_RANGE    = 3.5
BITE_DIST      = 1.6

# ── Appeal thresholds for stage transitions ───────────────────────────
NOTICE_APPEAL_MIN   = 0.22
APPROACH_APPEAL_MIN = 0.38
CHASE_APPEAL_MIN    = 0.32

# ── Spook triggers ────────────────────────────────────────────────────
SPEED_SPOOK       = 0.11   # lure faster than this while approach → spook
NAT_SPOOK         = 0.22   # lure naturalness below this while chasing → spook
DEPTH_LIMIT_SPOOK = 2.4    # depth mismatch above this while approaching → ignore
DEPTH_LIMIT_NOTICE= 2.0    # depth mismatch above this → can't even notice
PRESSURE_CHASE    = 8      # cell pressure above this reduces chase probability

# ── Stage timers ──────────────────────────────────────────────────────
NOTICE_TIMEOUT   = 300    # frames before fish gives up in NOTICE
APPROACH_TIMEOUT = 240    # frames before fish retreats from APPROACH
SPOOK_FRAMES     = 200    # frames fish stays spooked

# ── Movement speeds ───────────────────────────────────────────────────
PATROL_SPEED  = 0.030
NOTICE_DRIFT  = 0.018
APPROACH_SPEE = 0.055
CHASE_SPEED   = 0.140
SPOOK_SPEED   = 0.260


class Fish:
    """A single largemouth bass on the underwater map (float cell coords)."""

    def __init__(
        self,
        x: float,
        y: float,
        size_cm: float,
        underwater_map,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._rng = rng or random.Random()
        self.x = x
        self.y = y
        self.size = size_cm
        self._map = underwater_map

        self.activity: float = self._rng.uniform(0.4, 1.0)
        self.state: str = REACT_IGNORE

        # ── Phase 7: 個体識別フィールド ──────────────────────────────
        # 40cm以上の管理個体のみ fish_id が設定される
        self.fish_id: Optional[str] = None

        # Internal timers
        self._stage_timer: int = 0
        self._idle_timer: int = 0
        self._spook_timer: int = 0

        # Patrol / spook targets
        self._patrol_target: tuple = (int(x), int(y))
        self._spook_target: tuple = (int(x), int(y))
        self._pick_patrol_target()

    # ── Public API ─────────────────────────────────────────────────────

    @property
    def preferred_depth(self) -> float:
        """Depth of the cell the fish currently occupies."""
        cx = max(0, min(UW_W - 1, int(self.x)))
        cy = max(0, min(UW_H - 1, int(self.y)))
        return self._map.cell(cx, cy).depth

    def update(self, lure, cell_pressure: int = 0) -> Optional[str]:
        """Update fish AI for one frame.

        Returns
        -------
        "in_range"  fish is in CHASE state and within BITE_DIST
                    (FishingView should accumulate bite charge).
        None        otherwise.
        """
        if self.state in (FISH_CAUGHT, REACT_BITE):
            return None

        if self.state == REACT_SPOOK:
            self._update_spook(lure)
            return None

        # ── No lure: free-roam ──────────────────────────────────────
        if lure is None or not lure.in_water:
            if self.state != REACT_IGNORE:
                self.state = REACT_IGNORE
                self._stage_timer = 0
                self._pick_patrol_target()
            self._patrol()
            return None

        # ── Geometry ────────────────────────────────────────────────
        dx = lure.x - self.x
        dy = lure.y - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        depth_err = abs(lure.depth - self.preferred_depth)

        # ── State machine ────────────────────────────────────────────
        if self.state == REACT_IGNORE:
            self._patrol()
            if (dist < NOTICE_RANGE
                    and depth_err < DEPTH_LIMIT_NOTICE
                    and lure.appeal > NOTICE_APPEAL_MIN
                    and self.activity > 0.20):
                pressure_ok = (
                    cell_pressure < PRESSURE_CHASE
                    or self._rng.random() > (cell_pressure - PRESSURE_CHASE) * 0.08
                )
                if pressure_ok:
                    self.state = REACT_NOTICE
                    self._stage_timer = 0

        elif self.state == REACT_NOTICE:
            self._stage_timer += 1
            # Lose interest
            if dist > NOTICE_RANGE * 1.6 or lure.appeal < NOTICE_APPEAL_MIN * 0.6:
                self.state = REACT_IGNORE
                return None
            # Timeout – fish moves on
            if self._stage_timer > NOTICE_TIMEOUT:
                self.state = REACT_IGNORE
                return None
            # Drift toward lure
            if dist > 0.8:
                self.x += (dx / dist) * NOTICE_DRIFT
                self.y += (dy / dist) * NOTICE_DRIFT
            # Escalate to APPROACH when lure is interesting enough
            if (lure.appeal > APPROACH_APPEAL_MIN
                    and depth_err < DEPTH_LIMIT_NOTICE
                    and (dist < APPROACH_RANGE or lure.action_changed)
                    and self._stage_timer >= 15):
                self.state = REACT_APPROACH
                self._stage_timer = 0

        elif self.state == REACT_APPROACH:
            self._stage_timer += 1
            # Spook: lure too fast
            if lure.speed > SPEED_SPOOK and self.activity < 0.65:
                self._do_spook(lure)
                return None
            # Lose interest: depth mismatch
            if depth_err > DEPTH_LIMIT_SPOOK:
                self.state = REACT_IGNORE
                return None
            # Timeout
            if self._stage_timer > APPROACH_TIMEOUT:
                self.state = REACT_NOTICE
                self._stage_timer = 0
            # Move toward lure
            speed = APPROACH_SPEE * self.activity
            if dist > 0.3:
                self.x += (dx / dist) * speed
                self.y += (dy / dist) * speed
            # Escalate to CHASE
            if dist < CHASE_RANGE and lure.appeal > CHASE_APPEAL_MIN:
                pressure_penalty = max(0, (cell_pressure - PRESSURE_CHASE) * 0.12)
                if self._rng.random() > pressure_penalty:
                    self.state = REACT_CHASE
                    self._stage_timer = 0

        elif self.state == REACT_CHASE:
            self._stage_timer += 1
            # Spook: lure too unnatural
            if lure.naturalness < NAT_SPOOK:
                self._do_spook(lure)
                return None
            # Spook: lure going very fast away
            if lure.speed > SPEED_SPOOK * 1.6:
                self._do_spook(lure)
                return None
            # Move hard toward lure
            if dist > 0.08:
                spd = CHASE_SPEED * self.activity
                self.x += (dx / dist) * spd
                self.y += (dy / dist) * spd
            # Give up if lure is out of range
            if dist > NOTICE_RANGE * 2.0:
                self.state = REACT_IGNORE
                return None
            # Signal bite-range proximity to FishingView
            if dist < BITE_DIST:
                return "in_range"

        self._clamp()
        return None

    def trigger_bite(self) -> None:
        """Called by FishingView when bite charge reaches threshold."""
        self.state = REACT_BITE

    def hook(self) -> None:
        """Called by FishingView when player hooks (SPACE)."""
        self.state = FISH_CAUGHT

    def miss(self) -> None:
        """Called by FishingView on bite timeout (no SPACE in time)."""
        self._do_spook_no_lure()

    def respawn(self, best_positions: list) -> None:
        if best_positions:
            pos = self._rng.choice(best_positions[:5])
            self.x = float(pos[0]) + self._rng.uniform(-1.5, 1.5)
            self.y = float(pos[1]) + self._rng.uniform(-1.5, 1.5)
        self.activity = self._rng.uniform(0.40, 1.0)
        self.state = REACT_IGNORE
        self._stage_timer = 0
        self._idle_timer = 0
        self._clamp()
        self._pick_patrol_target()

    # ── Internal helpers ────────────────────────────────────────────────

    def _patrol(self) -> None:
        self._idle_timer += 1
        if self._idle_timer > self._rng.randint(80, 180):
            self._idle_timer = 0
            self._pick_patrol_target()
        tx, ty = self._patrol_target
        dx, dy = tx - self.x, ty - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0.4:
            self.x += (dx / dist) * PATROL_SPEED
            self.y += (dy / dist) * PATROL_SPEED

    def _do_spook(self, lure) -> None:
        self.state = REACT_SPOOK
        self._spook_timer = SPOOK_FRAMES
        # Spook away from lure
        dx = self.x - lure.x
        dy = self.y - lure.y
        dist = math.sqrt(dx * dx + dy * dy) + 0.01
        nx = self.x + (dx / dist) * 8
        ny = self.y + (dy / dist) * 8
        self._spook_target = (
            max(1, min(UW_W - 2, int(nx))),
            max(1, min(UW_H - 2, int(ny))),
        )

    def _do_spook_no_lure(self) -> None:
        self.state = REACT_SPOOK
        self._spook_timer = SPOOK_FRAMES
        # Pick a random retreat point
        self._spook_target = (
            self._rng.randint(1, UW_W - 2),
            self._rng.randint(1, UW_H - 2),
        )

    def _update_spook(self, lure) -> None:
        self._spook_timer -= 1
        # Sprint toward spook target
        tx, ty = self._spook_target
        dx, dy = tx - self.x, ty - self.y
        dist = math.sqrt(dx * dx + dy * dy) + 0.01
        if dist > 0.5:
            spd = SPOOK_SPEED * self.activity
            self.x += (dx / dist) * spd
            self.y += (dy / dist) * spd
        if self._spook_timer <= 0:
            self.state = REACT_IGNORE
            self._stage_timer = 0
            self._idle_timer = 0
            self._pick_patrol_target()
        self._clamp()

    def _pick_patrol_target(self) -> None:
        best_score = -1.0
        bx, by = int(self.x), int(self.y)
        target = (bx, by)
        for r_dy in range(-7, 8):
            for r_dx in range(-7, 8):
                nx, ny = bx + r_dx, by + r_dy
                if 0 <= nx < UW_W and 0 <= ny < UW_H:
                    s = self._map.full_score(nx, ny)
                    if s > best_score:
                        best_score = s
                        target = (nx, ny)
        self._patrol_target = target

    def _clamp(self) -> None:
        self.x = max(0.0, min(float(UW_W - 1), self.x))
        self.y = max(0.0, min(float(UW_H - 1), self.y))
