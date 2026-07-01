"""Underwater simulation grid (UW_W × UW_H) with template-driven terrain.

Exploration v2: 釣りビューを横へ広げたため、従来の正方(32×32)から
幅(UW_W) × 奥行き(UW_H) の矩形グリッドへ拡張。cells[y][x] で y=奥行き, x=幅。
"""

from __future__ import annotations

import random
import math
from typing import List, Tuple

from constants import (
    UW_W, UW_H, FISHING_VIEW_WIDTH_SCALE,
    TERRAIN_FLAT, TERRAIN_WEED, TERRAIN_COVER, TERRAIN_BREAK, TERRAIN_ROCK,
    DIR_NONE,
)
from structure_objects import cell_params as _cell_params


def _scale_count(n: int) -> int:
    """Exploration v2: フィールドを横 1.5x に広げた分、構造物/ベイトの数も
    面積比 (= FISHING_VIEW_WIDTH_SCALE) で増やして密度を据え置く。
    0 は「その地形を置かない」意図なので 0 のまま。"""
    if n <= 0:
        return 0
    return int(math.floor(n * FISHING_VIEW_WIDTH_SCALE + 0.5))


class UnderwaterCell:
    __slots__ = (
        "depth", "terrain", "weed", "cover", "bait", "log_id",
        # Phase A: 地形システム土台 — structure_objects / fishing_terrain から参照
        "blocking", "snag_weight", "weak_dir",
    )

    def __init__(self) -> None:
        self.depth: float = 1.0
        self.terrain: int = TERRAIN_FLAT
        self.weed: bool = False
        self.cover: bool = False
        self.bait: int = 0
        self.log_id: int = -1    # TERRAIN_COVER クラスター ID (-1 = 未所属)
        # Phase A: 根がかり / ライン干渉用パラメータ (_apply_snag_params で設定)
        self.blocking:    bool  = False
        self.snag_weight: float = 0.0
        self.weak_dir:    int   = DIR_NONE

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
    """UW_W × UW_H underwater grid.

    y = 0      : far shore (where casts land).
    y = UW_H-1 : near player.
    x は 0..UW_W-1 (横; 探索で左右に広い)。
    """

    W = UW_W          # 幅 (x)
    H = UW_H          # 奥行き (y)

    def __init__(self, seed: int = 42, config: dict | None = None) -> None:
        self.cells: List[List[UnderwaterCell]] = [
            [UnderwaterCell() for _ in range(self.W)]
            for _ in range(self.H)
        ]
        self._rng = random.Random(seed)
        cfg = config or {}
        self._apply_depth_profile(cfg.get("depth_profile", "bowl"))
        # Exploration v2: カウント系は面積補正 (_scale_count) して密度を維持。
        # density 系 (fill 比率) はそのまま。
        self._place_weed(
            _scale_count(cfg.get("weed_patches", 3)),
            cfg.get("weed_density", 0.55),
        )
        self._place_cover(
            _scale_count(cfg.get("cover_clusters", 2)),
            cfg.get("cover_density", 0.55),
        )
        self._place_rocks(
            _scale_count(cfg.get("rock_clusters", 1)),
            cfg.get("rock_density", 0.45),
        )
        self._place_breaks(cfg.get("break_lines", 1))
        self._scatter_bait(_scale_count(cfg.get("bait_count", 15)))
        # Phase A: 全セルの根がかり/ブロックパラメータを terrain から一括設定
        self._apply_snag_params()

    # ------------------------------------------------------------------
    # Depth profiles
    # ------------------------------------------------------------------

    def _apply_depth_profile(self, profile: str) -> None:
        W, H = self.W, self.H
        cx, cy = W // 2, H // 2

        if profile == "bowl":
            # Deepest centre, shallows at edges
            for y in range(H):
                for x in range(W):
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
                    self.cells[y][x].depth = max(0.5, 3.5 - dist * 0.10)

        elif profile == "flat":
            for y in range(H):
                for x in range(W):
                    self.cells[y][x].depth = 1.5 + self._rng.uniform(-0.2, 0.2)

        elif profile == "flat_shallow":
            for y in range(H):
                for x in range(W):
                    self.cells[y][x].depth = 0.8 + self._rng.uniform(-0.15, 0.15)

        elif profile == "slope":
            # Shallow at far shore (y=0), deepens toward player (y=H-1)
            for y in range(H):
                for x in range(W):
                    base = 0.6 + (y / H) * 2.8
                    self.cells[y][x].depth = base + self._rng.uniform(-0.2, 0.2)

        elif profile == "shelf":
            # Flat at ≈ 1.2 m, then a sudden 2 m drop at y ≈ H//2
            shelf_y = H // 2 + self._rng.randint(-3, 3)
            for y in range(H):
                for x in range(W):
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
        W, H = self.W, self.H
        for _ in range(n_patches):
            wx = self._rng.randint(2, W - 3)
            wy = self._rng.randint(2, H - 3)
            r = self._rng.randint(2, 4)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            if c.terrain == TERRAIN_FLAT:
                                c.weed = True
                                c.terrain = TERRAIN_WEED

    def _place_cover(self, n_clusters: int, density: float) -> None:
        W, H = self.W, self.H
        for cluster_id in range(n_clusters):
            wx = self._rng.randint(2, W - 3)
            wy = self._rng.randint(2, H - 3)
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            c.cover = True
                            c.terrain = TERRAIN_COVER
                            c.log_id = cluster_id

    def _place_rocks(self, n_clusters: int, density: float) -> None:
        W, H = self.W, self.H
        for _ in range(n_clusters):
            wx = self._rng.randint(2, W - 3)
            wy = self._rng.randint(2, H - 3)
            r = self._rng.randint(1, 3)
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    nx, ny = wx + dx, wy + dy
                    if 0 <= nx < W and 0 <= ny < H:
                        if self._rng.random() < density:
                            c = self.cells[ny][nx]
                            c.cover = True
                            c.terrain = TERRAIN_ROCK

    def _place_breaks(self, n_breaks: int) -> None:
        W, H = self.W, self.H
        used_rows: set = set()
        for _ in range(n_breaks):
            attempts = 0
            while attempts < 20:
                by = self._rng.randint(H // 5, 4 * H // 5)
                if by not in used_rows:
                    used_rows.add(by)
                    break
                attempts += 1
            else:
                continue

            depth_jump = self._rng.uniform(1.0, 2.0)
            for x in range(W):
                c = self.cells[by][x]
                if c.terrain == TERRAIN_FLAT:
                    c.depth = min(c.depth + depth_jump, 4.5)
                    c.terrain = TERRAIN_BREAK

    def _scatter_bait(self, count: int) -> None:
        W, H = self.W, self.H
        for _ in range(count):
            bx = self._rng.randint(0, W - 1)
            by = self._rng.randint(0, H - 1)
            self.cells[by][bx].bait = self._rng.randint(1, 3)

    def _apply_snag_params(self) -> None:
        """Phase A: terrain フラグから blocking / snag_weight / weak_dir を一括設定。

        配置系メソッド (_place_cover 等) が完了した後に呼ぶ。
        structure_objects.cell_params() が単一の正規化ロジックを持つ。
        """
        for row in self.cells:
            for cell in row:
                p = _cell_params(cell.terrain, cell.cover, cell.weed)
                cell.blocking    = p.blocking
                cell.snag_weight = p.snag_weight
                cell.weak_dir    = p.weak_dir

    # ------------------------------------------------------------------
    # Public queries
    # ------------------------------------------------------------------

    def cell(self, x: int, y: int) -> UnderwaterCell:
        return self.cells[y][x]

    def depth_change(self, x: int, y: int) -> float:
        base = self.cells[y][x].depth
        best = 0.0
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < self.W and 0 <= ny < self.H:
                best = max(best, abs(self.cells[ny][nx].depth - base))
        return best

    def full_score(self, x: int, y: int) -> float:
        return self.cells[y][x].holding_score + self.depth_change(x, y)

    def best_positions(self, n: int = 10) -> List[Tuple[int, int]]:
        scored = [
            (self.full_score(x, y), x, y)
            for y in range(self.H)
            for x in range(self.W)
        ]
        scored.sort(reverse=True)
        return [(x, y) for _, x, y in scored[:n]]
