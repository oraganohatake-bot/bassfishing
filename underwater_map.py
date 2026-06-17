"""32×32 underwater simulation grid with template-driven terrain generation."""

from __future__ import annotations

import random
import math
from typing import List, Tuple

from constants import (
    UW_SIZE,
    TERRAIN_FLAT, TERRAIN_WEED, TERRAIN_COVER, TERRAIN_BREAK, TERRAIN_ROCK,
)


class UnderwaterCell:
    __slots__ = ("depth", "terrain", "weed", "cover", "bait")

    def __init__(self) -> None:
        self.depth: float = 1.0
        self.terrain: int = TERRAIN_FLAT
        self.weed: bool = False
        self.cover: bool = False
        self.bait: int = 0

    @property
    def holding_score(self) -> float:
        """Intrinsic attractiveness of this cell to bass."""
        score = 0.0
        if self.terrain == TERRAIN_ROCK:
            score += 4.5          # rocks are the best structure
        elif self.cover:
            score += 3.0          # wood / brush
        if self.weed:
            score += 2.0
        score += self.bait * 1.5
        return score


class UnderwaterMap:
    """32×32 underwater grid.

    y = 0  : far shore (where casts land).
    y = 31 : near player.
    """

    SIZE = UW_SIZE

    def __init__(self, seed: int = 42, config: dict | None = None) -> None:
        self.cells: List[List[UnderwaterCell]] = [
            [UnderwaterCell() for _ in range(self.SIZE)]
            for _ in range(self.SIZE)
        ]
        self._rng = random.Random(seed)
        cfg = config or {}
        self._apply_depth_profile(cfg.get("depth_profile", "bowl"))
        self._place_weed(
            cfg.get("weed_patches", 3),
            cfg.get("weed_density", 0.55),
        )
        self._place_cover(
            cfg.get("cover_clusters", 2),
            cfg.get("cover_density", 0.55),
        )
        self._place_rocks(
            cfg.get("rock_clusters", 1),
            cfg.get("rock_density", 0.45),
        )
        self._place_breaks(cfg.get("break_lines", 1))
        self._scatter_bait(cfg.get("bait_count", 15))

    # ------------------------------------------------------------------
    # Depth profiles
    # ------------------------------------------------------------------

    def _apply_depth_profile(self, profile: str) -> None:
        S = self.SIZE
        cx, cy = S // 2, S // 2

        if profile == "bowl":
            # Deepest centre, shallows at edges
            for y in range(S):
                for x in range(S):
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                    self.cells[y][x].depth = max(0.5, 3.5 - dist * 0.10)

        elif profile == "flat":
            for y in range(S):
                for x in range(S):
                    self.cells[y][x].depth = 1.5 + self._rng.uniform(-0.2, 0.2)

        elif profile == "flat_shallow":
            for y in range(S):
                for x in range(S):
                    self.cells[y][x].depth = 0.8 + self._rng.uniform(-0.15, 0.15)

        elif profile == "slope":
            # Shallow at far shore (y=0), deepens toward player (y=31)
            for y in range(S):
                for x in range(S):
                    base = 0.6 + (y / S) * 2.8
                    self.cells[y][x].depth = base + self._rng.uniform(-0.2, 0.2)

        elif profile == "shelf":
            # Flat at ≈ 1.2 m, then a sudden 2 m drop at y~= S//2
            shelf_y = S // 2 + self._rng.randint(-3, 3)
            for y in range(S):
                for x in range(S):
                    if y < shelf_y:
                        self.cells[y][x].depth = 1.2 + self._rng.uniform(-0.1, 0.1)
                    else:
                        self.cells[y][x].depth = 3.2 + self._rng.uniform(-0.2, 0.2)

        else:  # fallback
            self._apply_depth_profile("bowl")

    # ------------------------------------------------------------------
    # Structure placement
    # ------------------------------------------------------------------

    def _place_weed(self, n_patches: int, density: float) -> None:
        S = self.SIZE
        for _ in range(n_patches):
            wx = self._rng.randint(2, S - 3)
            wy = self._rng.randint(2, S - 3)
            r = self._rng.randint(2, 4)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < S and 0 <= ny < S:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            if c.terrain == TERRAIN_FLAT:
                                c.weed = True
                                c.terrain = TERRAIN_WEED

    def _place_cover(self, n_clusters: int, density: float) -> None:
        S = self.SIZE
        for _ in range(n_clusters):
            wx = self._rng.randint(2, S - 3)
            wy = self._rng.randint(2, S - 3)
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < S and 0 <= ny < S:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            c.cover = True
                            c.terrain = TERRAIN_COVER

    def _place_rocks(self, n_clusters: int, density: float) -> None:
        S = self.SIZE
        for _ in range(n_clusters):
            wx = self._rng.randint(2, S - 3)
            wy = self._rng.randint(2, S - 3)
            r = self._rng.randint(1, 3)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < S and 0 <= ny < S:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            c.cover = True
                            c.terrain = TERRAIN_ROCK

    def _place_breaks(self, n_breaks: int) -> None:
        S = self.SIZE
        used_rows: set = set()
        for _ in range(n_breaks):
            attempts = 0
            while attempts < 20:
                by = self._rng.randint(S // 5, 4 * S // 5)
                if by not in used_rows:
                    used_rows.add(by)
                    break
                attempts += 1
            else:
                continue

            depth_jump = self._rng.uniform(1.0, 2.0)
            for x in range(S):
                c = self.cells[by][x]
                if c.terrain == TERRAIN_FLAT:
                    c.depth = min(c.depth + depth_jump, 4.5)
                    c.terrain = TERRAIN_BREAK

    def _scatter_bait(self, count: int) -> None:
        S = self.SIZE
        for _ in range(count):
            bx = self._rng.randint(0, S - 1)
            by = self._rng.randint(0, S - 1)
            self.cells[by][bx].bait = self._rng.randint(1, 3)

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    def cell(self, x: int, y: int) -> UnderwaterCell:
        return self.cells[y][x]

    def depth_change(self, x: int, y: int) -> float:
        base = self.cells[y][x].depth
        best = 0.0
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < self.SIZE and 0 <= ny < self.SIZE:
                best = max(best, abs(self.cells[ny][nx].depth - base))
        return best

    def full_score(self, x: int, y: int) -> float:
        return self.cells[y][x].holding_score + self.depth_change(x, y)

    def best_positions(self, n: int = 10) -> List[Tuple[int, int]]:
        scored = [
            (self.full_score(x, y), x, y)
            for y in range(self.SIZE)
            for x in range(self.SIZE)
        ]
        scored.sort(reverse=True)
        return [(x, y) for _, x, y in scored[:n]]
