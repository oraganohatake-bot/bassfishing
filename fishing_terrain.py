"""fishing_terrain.py – 地形クエリ層 + InfluenceGrid。

根がかり判定・カーソル危険度・ライン経路チェックを提供する。
FishingView / fight_system がこのモジュールの関数を呼び出すことで
地形依存ロジックを一箇所に集約する。

Phase A: TerrainCell / FishingTerrain / build_fishing_terrain() を追加。
         既存の check_snag / cursor_danger / get_line_path は変更なし。
Phase 1（根がかりシステム）から FishingView が呼び出す予定。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List, Optional, Tuple

from structure_objects import cell_params

if TYPE_CHECKING:
    from underwater_map import UnderwaterCell, UnderwaterMap


# ── TerrainCell: セルごとの地形データ ───────────────────────────────

@dataclass
class TerrainCell:
    """釣りビュー1セルの地形データ。

    Phase A では depth_m / slope だけ生成する。
    その他フィールドは Phase C (StructureObject → influence) で埋まる。

    Attributes
    ----------
    depth_m       : このセルの実水深 [m]
    base_depth_m  : プロファイル由来の基本水深 (ストラクチャー補正前)
    depth_delta_m : ストラクチャーによる水深変化 [m] (Phase C で使用)
    slope         : 隣接セルとの水深差の最大値を正規化 (0.0–1.0)
    cover         : カバー密度 0.0–1.0 (Phase C)
    shade         : 影響度 0.0–1.0 (Phase C)
    snag          : 根がかりリスク 0.0–1.0 (Phase C)
    vegetation    : 水草密度 0.0–1.0 (Phase C)
    hardness      : 底質硬さ 0.0–1.0 (Phase C)
    ambush        : アンブッシュスコア 0.0–1.0 (Phase C)
    bottom_type   : "mud" | "sand" | "gravel" | "rock" | "weed"
    """
    depth_m:      float = 1.0
    base_depth_m: float = 1.0
    depth_delta_m:float = 0.0
    slope:        float = 0.0
    cover:        float = 0.0
    shade:        float = 0.0
    snag:         float = 0.0
    vegetation:   float = 0.0
    hardness:     float = 0.0
    ambush:       float = 0.0
    bottom_type:  str   = "mud"


# ── FishingTerrain: スポット全体の地形グリッド ──────────────────────

@dataclass
class FishingTerrain:
    """スポット固有の釣りビュー地形データ。

    Attributes
    ----------
    spot_id      : "spot_01" 〜 "spot_10"
    grid_cols    : グリッド列数 (X軸: 左右)
    grid_rows    : グリッド行数 (Y軸: 奥=0, 手前=max)
    view_width_m : ビューの横幅 [m]
    view_depth_m : ビューの縦幅 [m]
    cells        : cells[row][col] = TerrainCell
    hotspots     : 高スコアセル候補 [(col, row), ...]
    structures   : StructureObject リスト (Phase D で描画)
    """
    spot_id:      str
    grid_cols:    int
    grid_rows:    int
    view_width_m: float
    view_depth_m: float
    cells:        List[List[TerrainCell]] = field(default_factory=list)
    hotspots:     List[Tuple[int, int]]  = field(default_factory=list)
    structures:   List                   = field(default_factory=list)

    def cell(self, col: int, row: int) -> TerrainCell:
        """境界クランプ付きセルアクセス。"""
        r = max(0, min(self.grid_rows - 1, row))
        c = max(0, min(self.grid_cols - 1, col))
        return self.cells[r][c]


# ── depth_profile 別の水深生成 ────────────────────────────────────

def _profile_depth(
    row: int, col: int,
    grid_rows: int, grid_cols: int,
    base: float, max_d: float,
    profile: str,
    seed: int = 0,
) -> float:
    """row/col に応じた水深を返す。

    row=0 が最奥 (深い)、row=grid_rows-1 が最手前 (浅い)。
    col は横方向のノイズ/ブレイクライン揺らぎに使う。
    """
    t = row / max(1, grid_rows - 1)
    far_t = 1.0 - t   # far_t=1.0 が最奥

    depth_span = max_d - base

    # 横方向の自然な揺らぎ (全プロファイル共通)
    col_noise = (
        math.sin(col * 0.41 + seed * 2.3) * 0.06
        + math.sin(col * 0.17 + seed * 5.1) * 0.04
    )

    if profile == "shallow_flat":
        base_d = base + depth_span * far_t * 0.7
        # 浅場は軽い横揺らぎ
        return max(base * 0.5, base_d + depth_span * col_noise * 0.35)

    elif profile == "normal_slope":
        base_d = base + depth_span * far_t
        # 奥ほど揺らぎ幅が大きくなる (ハンプ/深みっぽい)
        return max(base * 0.5, base_d + depth_span * far_t * col_noise * 0.55)

    elif profile == "steep_break":
        # ブレイクラインを col ごとにずらして直線帯を防ぐ
        phase = (col * 0.35 + seed * 1.618)
        col_hash = (col * 7 + seed * 13) % 11
        break_far_t = (
            0.50
            + math.sin(phase) * 0.10
            + (col_hash / 11.0 - 0.5) * 0.08
        )
        break_far_t = max(0.30, min(0.70, break_far_t))

        if far_t < break_far_t:
            ratio = far_t / break_far_t
            return base + depth_span * ratio * 0.28
        else:
            break_start = base + depth_span * 0.14
            k = (far_t - break_far_t) / max(0.01, 1.0 - break_far_t)
            base_d = break_start + (max_d - break_start) * k
            return max(base * 0.5, base_d + depth_span * col_noise * 0.25)

    elif profile == "deep_edge":
        base_d = base + depth_span * (far_t ** 0.7)
        # 左右どちらかが少し深い (斜め落ち)
        diagonal_bias = (col / max(1, grid_cols - 1) - 0.5) * depth_span * 0.15
        return max(base * 0.5, base_d + diagonal_bias + depth_span * col_noise * 0.20)

    return base + depth_span * far_t


# ── 局所的な水深変化 (scour hole / rock hump) ─────────────────────────

def _apply_ellipse_depth_delta(
    cells: List[List[TerrainCell]],
    grid_rows: int, grid_cols: int,
    center_col: int, center_row: int,
    radius_col: int, radius_row: int,
    delta_m: float,
) -> None:
    """楕円形の局所的な水深変化をセルに加算する (scour hole / rock hump)。"""
    r0 = max(0, center_row - radius_row)
    r1 = min(grid_rows, center_row + radius_row + 1)
    c0 = max(0, center_col - radius_col)
    c1 = min(grid_cols, center_col + radius_col + 1)
    for r in range(r0, r1):
        for c in range(c0, c1):
            dr = (r - center_row) / max(1, radius_row)
            dc = (c - center_col) / max(1, radius_col)
            dist = math.sqrt(dr * dr + dc * dc)
            if dist <= 1.0:
                weight = (1.0 - dist) ** 2
                cells[r][c].depth_m = max(0.2, cells[r][c].depth_m + delta_m * weight)


# ── slope 計算 ───────────────────────────────────────────────────────

def _compute_slopes(cells: List[List[TerrainCell]], grid_rows: int, grid_cols: int) -> None:
    """全セルの slope フィールドをインプレース更新する。"""
    max_diff = 0.0
    raw: List[List[float]] = []

    for r in range(grid_rows):
        row_vals = []
        for c in range(grid_cols):
            d = cells[r][c].depth_m
            neighbors = []
            if r > 0:               neighbors.append(cells[r-1][c].depth_m)
            if r < grid_rows - 1:   neighbors.append(cells[r+1][c].depth_m)
            if c > 0:               neighbors.append(cells[r][c-1].depth_m)
            if c < grid_cols - 1:   neighbors.append(cells[r][c+1].depth_m)
            diff = max(abs(d - n) for n in neighbors) if neighbors else 0.0
            row_vals.append(diff)
            if diff > max_diff:
                max_diff = diff
        raw.append(row_vals)

    scale = max_diff if max_diff > 0.0 else 1.0
    for r in range(grid_rows):
        for c in range(grid_cols):
            cells[r][c].slope = raw[r][c] / scale


# ── ビルダー ─────────────────────────────────────────────────────────

def build_fishing_terrain(spot_id: str) -> FishingTerrain:
    """spot_id から FishingTerrain を生成して返す。"""
    from fishing_spots import get_fishing_spot

    spot = get_fishing_spot(spot_id)

    rows = spot.grid_rows
    cols = spot.grid_cols
    seed = hash(spot_id) & 0xFFFF

    cells: List[List[TerrainCell]] = []
    for r in range(rows):
        row: List[TerrainCell] = []
        for c in range(cols):
            d = _profile_depth(
                r, c, rows, cols,
                spot.base_depth_m, spot.max_depth_m,
                spot.depth_profile, seed,
            )
            tc = TerrainCell(depth_m=d, base_depth_m=d)
            row.append(tc)
        cells.append(row)

    # 局所的な深み/盛り上がり (scour holes / rock humps)
    rng_local = random.Random(seed)
    # scour hole 1〜2個: 楕円形に少し深くなる
    num_scour = 1 + (seed % 2)
    for _ in range(num_scour):
        fc = rng_local.randint(cols // 5, cols * 4 // 5)
        fr = rng_local.randint(rows // 5, rows * 2 // 3)
        delta = -(0.30 + rng_local.random() * 0.30)
        _apply_ellipse_depth_delta(cells, rows, cols, fc, fr, 3, 2, delta)
    # rock hump 1個: 局所的に少し浅くなる盛り上がり
    hc = (seed * 7 % (cols // 2)) + cols // 4
    hr = rows // 4 + (seed * 3 % (rows // 3))
    _apply_ellipse_depth_delta(cells, rows, cols, hc, hr, 2, 2, 0.35)

    _compute_slopes(cells, rows, cols)

    return FishingTerrain(
        spot_id=spot_id,
        grid_cols=cols,
        grid_rows=rows,
        view_width_m=spot.view_width_m,
        view_depth_m=spot.view_depth_m,
        cells=cells,
        hotspots=[],
        structures=list(spot.structures),
    )


# ── ルアー別 根がかり耐性 (1.0 に近いほど引っかかりにくい) ───────────
# lure_catalog.py の各 LureSpec.name と対応させる。
SNAG_RESIST: dict[str, float] = {
    "Minnow":      0.45,   # トレブルフック 2本 — そこそこ引っかかる
    "Crankbait":   0.70,   # リップが障害物を回避しやすい
    "Spinnerbait": 0.75,   # ワイヤーアームがガードになる
    "Worm":        0.20,   # ウエイトフックが引っかかりやすい
    "Jig":         0.35,   # ガード付きでも構造上引っかかりやすい
    "Topwater":    0.95,   # 水面系なので底ストラクチャーにほぼ触れない
}
_DEFAULT_SNAG_RESIST = 0.50


# ── 根がかり判定 ────────────────────────────────────────────────────
def check_snag(
    cell: "UnderwaterCell",
    lure_name: str,
    rng: Optional[random.Random] = None,
    spot_snag_rating: float = 0.5,
) -> bool:
    """ルアーがセルで根がかるか確率判定する。

    Parameters
    ----------
    cell             : 現在のルアー位置の UnderwaterCell
    lure_name        : ルアー名 (SNAG_RESIST のキー)
    rng              : 再現性のある乱数源。None なら random モジュールを使用
    spot_snag_rating : SpotMeta.snag_rating (0–1)。スポット難易度補正

    Returns
    -------
    True = 根がかり発生
    """
    params = cell_params(cell.terrain, cell.cover, cell.weed)
    if params.snag_weight <= 0.0:
        return False

    resist = SNAG_RESIST.get(lure_name, _DEFAULT_SNAG_RESIST)
    # spot_snag_rating: 0.0 で 20% 減衰、1.0 で 20% 増幅 (線形補間)
    spot_mult = 0.80 + 0.40 * spot_snag_rating
    effective = params.snag_weight * (1.0 - resist) * spot_mult
    roll = rng.random() if rng else random.random()
    return roll < effective


# ── カーソル危険度 ───────────────────────────────────────────────────
def cursor_danger(cell: "UnderwaterCell") -> str:
    """セルのキャスト危険度を分類する。

    FishingView がカーソルの色選択に使用する（Phase 1 で描画に反映）。

    Returns
    -------
    "block" : 着水ブロック (blocking=True) — 赤点滅
    "snag"  : 根がかりリスク高 (snag_weight >= 0.50) — オレンジ点滅
    "light" : 根がかりリスク低 (snag_weight > 0) — 黄色
    "clear" : 安全 — 通常色
    """
    params = cell_params(cell.terrain, cell.cover, cell.weed)
    if params.blocking:
        return "block"
    if params.snag_weight >= 0.50:
        return "snag"
    if params.snag_weight > 0.0:
        return "light"
    return "clear"


# ── ライン経路 (Bresenham) ───────────────────────────────────────────
def get_line_path(
    sx: int, sy: int,
    ex: int, ey: int,
) -> List[Tuple[int, int]]:
    """Bresenham アルゴリズムでグリッド経路を返す。

    キャスト着水点 (sx, sy) からルアー現在位置 (ex, ey) までの
    経路上の全セル座標を始点・終点込みで返す。

    Parameters
    ----------
    sx, sy : 開始セル (キャスト着水点)
    ex, ey : 終了セル (ルアー現在位置)

    Returns
    -------
    List of (x, y) tuples representing the path
    """
    cells: List[Tuple[int, int]] = []
    dx = abs(ex - sx)
    dy = abs(ey - sy)
    x, y = sx, sy
    step_x = 1 if ex > sx else -1
    step_y = 1 if ey > sy else -1

    if dx >= dy:
        err = dx // 2
        while x != ex:
            cells.append((x, y))
            err -= dy
            if err < 0:
                y += step_y
                err += dx
            x += step_x
    else:
        err = dy // 2
        while y != ey:
            cells.append((x, y))
            err -= dx
            if err < 0:
                x += step_x
                err += dy
            y += step_y
    cells.append((ex, ey))
    return cells


# ── ライン干渉チェック ───────────────────────────────────────────────
def check_line_interference(
    path: List[Tuple[int, int]],
    uw_map: "UnderwaterMap",
    threshold: float = 0.30,
) -> Optional[Tuple[int, int]]:
    """ライン経路上で最初に干渉するセル座標を返す。

    始点（キャスト着水点）と終点（ルアー位置）を除いた中間セルを検査する。
    snag_weight >= threshold のセルに触れたらその座標を返す。

    Parameters
    ----------
    path      : get_line_path() の戻り値
    uw_map    : UnderwaterMap インスタンス
    threshold : ライン干渉と判定する snag_weight の下限値

    Returns
    -------
    (x, y) of first interfering cell, or None
    """
    if len(path) <= 2:
        return None
    W, H = uw_map.W, uw_map.H
    for cx, cy in path[1:-1]:
        if not (0 <= cx < W and 0 <= cy < H):
            continue
        cell = uw_map.cell(cx, cy)
        params = cell_params(cell.terrain, cell.cover, cell.weed)
        if params.snag_weight >= threshold:
            return (cx, cy)
    return None
