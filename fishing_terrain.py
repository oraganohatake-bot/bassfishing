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
    depth_m       : このセルの実水深 [m] (= base_depth_m + depth_delta_m, 最低 0.2m)
    base_depth_m  : プロファイル由来の基本水深 (ストラクチャー補正前)
    depth_delta_m : ストラクチャー/局所地形による水深変化 [m]。
                    符号仕様: depth_delta_m > 0 → 深くなる (えぐれ/洗掘/ポケット)
                              depth_delta_m < 0 → 浅くなる (盛り上がり/ハンプ)
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
    hotspots     : StructureObject 由来の付き場候補 [dict, ...]
                   (kind / x / y / score / preferred_lures / risk / source)
    structures   : StructureObject リスト (Phase D で描画)
    min_depth_m  : グリッド内の最小水深 [m] (ストラクチャー補正後)
    max_depth_m  : グリッド内の最大水深 [m] (ストラクチャー補正後)
    """
    spot_id:      str
    grid_cols:    int
    grid_rows:    int
    view_width_m: float
    view_depth_m: float
    cells:        List[List[TerrainCell]] = field(default_factory=list)
    hotspots:     List[dict]              = field(default_factory=list)
    structures:   List                    = field(default_factory=list)
    min_depth_m:  float                   = 0.2
    max_depth_m:  float                   = 1.0

    def cell(self, col: int, row: int) -> TerrainCell:
        """境界クランプ付きセルアクセス。"""
        r = max(0, min(self.grid_rows - 1, row))
        c = max(0, min(self.grid_cols - 1, col))
        return self.cells[r][c]


# ── depth_profile 別の水深生成 ────────────────────────────────────

def _smoothstep(edge0: float, edge1: float, x: float) -> float:
    """edge0→edge1 の間を 0.0→1.0 になめらかに補間する。"""
    if edge1 == edge0:
        return 0.0 if x < edge0 else 1.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


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
        # 曲がった駆け上がり/落ち込み。
        # ブレイクライン「自体」を暗くせず、ラインを境に奥側を深くする。
        # 溝(細い深い帯)を作らないため smoothstep で面として移行させる。
        phase = (col * 0.35 + seed * 1.618)
        col_hash = (col * 7 + seed * 13) % 11
        break_far_t = (
            0.50
            + math.sin(phase) * 0.10
            + (col_hash / 11.0 - 0.5) * 0.08
        )
        break_far_t = max(0.30, min(0.70, break_far_t))

        shallow_depth = base + depth_span * 0.20   # 手前の浅いフラット
        deep_depth    = max_d                       # 奥の深い側
        transition_width = 0.16                     # 移行帯のなだらかさ

        s = _smoothstep(break_far_t - transition_width,
                        break_far_t + transition_width, far_t)
        depth = shallow_depth * (1.0 - s) + deep_depth * s
        return max(base * 0.5, depth + depth_span * col_noise * 0.20)

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
    """楕円形の局所的な水深変化を depth_delta_m に加算する (scour hole / rock hump)。

    符号仕様: delta_m > 0 → 深くなる / delta_m < 0 → 浅くなる。
    最終的な depth_m は _finalize_depths() で base_depth_m + depth_delta_m として
    再計算されるため、ここでは depth_delta_m のみを更新する。
    """
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
                cells[r][c].depth_delta_m += delta_m * weight


# ── StructureObject → influence 焼き込み ─────────────────────────────
#
# Phase C: 各スポットに配置された StructureObject を terrain.cells に反映する。
# 描画 (Phase D) には触れず、cover/shade/snag/vegetation/hardness/ambush と
# depth_delta_m を楕円状に加算し、hotspots(付き場候補) を生成するだけ。

def apply_radial_influence(
    terrain: "FishingTerrain",
    center_col: int,
    center_row: int,
    radius_col: float,
    radius_row: float,
    values: dict,
    falloff: str = "smooth",
) -> None:
    """楕円範囲のセルに influence 値を加算する。

    中心ほど強く、外周ほど弱く values を加算する。
    depth_delta_m 以外の数値フィールドは 0.0–1.0 にクランプする。
    bottom_type は内側 (weight>=0.5) のセルに設定する。

    Parameters
    ----------
    center_col, center_row : 中心セル座標
    radius_col, radius_row : 楕円半径 [cells]
    values : {"cover":0.7, "shade":0.5, "depth_delta_m":-0.3, "bottom_type":"wood", ...}
    falloff : "smooth" (smoothstep) | "linear" | "hard"
    """
    cells = terrain.cells
    rows, cols = terrain.grid_rows, terrain.grid_cols
    rc = max(1.0, float(radius_col))
    rr = max(1.0, float(radius_row))
    bottom_type = values.get("bottom_type")

    r0 = max(0, int(center_row - rr))
    r1 = min(rows, int(center_row + rr) + 1)
    c0 = max(0, int(center_col - rc))
    c1 = min(cols, int(center_col + rc) + 1)

    for r in range(r0, r1):
        for c in range(c0, c1):
            dr = (r - center_row) / rr
            dc = (c - center_col) / rc
            dist = math.sqrt(dr * dr + dc * dc)
            if dist > 1.0:
                continue
            n = 1.0 - dist
            if falloff == "smooth":
                w = n * n * (3.0 - 2.0 * n)   # smoothstep(0,1,1-dist)
            elif falloff == "hard":
                w = 1.0
            else:  # linear
                w = n

            tc = cells[r][c]
            for key, val in values.items():
                if key == "bottom_type":
                    continue
                cur = getattr(tc, key, None)
                if cur is None:
                    continue
                if key == "depth_delta_m":
                    tc.depth_delta_m = cur + val * w
                else:
                    setattr(tc, key, max(0.0, min(1.0, cur + val * w)))
            if bottom_type and w >= 0.5:
                tc.bottom_type = bottom_type


# 重要度 tier ごとの強度スケール
_TIER_MULT: dict = {"HERO": 1.0, "MID": 0.75, "LOW": 0.5}

# ストラクチャー種別 → 影響定義。
#   radius_m  : (横[m], 奥行[m]) の楕円半径 (scale 倍される)
#   values    : HERO 相当の加算値。tier / density でスケールされる
#               depth_delta_m > 0 → 深くなる / < 0 → 浅くなる
#   outer     : (任意) 本体前に適用する広域 depth_delta (岩周りの深み等)
#   hotspots  : (kind, dx_m, dy_m, score, [lures], risk) — rotation/scale で配置
_STRUCT_INFLUENCE: dict = {
    "laydown": {
        "radius_m": (4.0, 2.5),
        "values": {
            "cover": 0.85, "shade": 0.70, "snag": 0.80,
            "ambush": 0.90, "vegetation": 0.20, "depth_delta_m": +0.50,  # 根元えぐれ→深い
            "bottom_type": "wood",
        },
        "hotspots": [
            ("root_hole",  0.0, 0.0, 0.90, ["jig", "worm"],           "snag_high"),
            ("branch_tip", 3.5, 0.0, 0.75, ["crankbait", "spinnerbait"], "snag_high"),
            ("shade_line", 0.0, 1.5, 0.70, ["worm", "jig"],           "snag_med"),
        ],
    },
    "stake_cluster": {
        "radius_m": (1.8, 1.8),
        "values": {
            "cover": 0.65, "shade": 0.35, "snag": 0.35,
            "ambush": 0.55, "depth_delta_m": +0.18,  # 杭の洗掘→深い
            "bottom_type": "silt",
        },
        "hotspots": [
            ("stake_scour",  0.0,  0.0, 0.70, ["worm", "jig"], "snag_med"),
            ("outside_post", 1.5, -1.0, 0.60, ["spinnerbait"], "snag_low"),
        ],
    },
    "weed_bed": {
        "radius_m": (4.0, 3.0),
        "values": {
            "vegetation": 0.90, "cover": 0.60, "shade": 0.30,
            "snag": 0.35, "ambush": 0.45,
            "bottom_type": "weed",
        },
        "hotspots": [
            ("weed_edge", 3.5, 0.0, 0.65, ["spinnerbait", "crankbait"], "snag_low"),
        ],
    },
    "reed_bed": {
        "radius_m": (4.5, 3.0),
        "values": {
            "vegetation": 0.80, "cover": 0.65, "shade": 0.45,
            "snag": 0.45, "ambush": 0.60, "depth_delta_m": +0.25,  # 葦の切れ目ポケット→深い
            "bottom_type": "mud",
        },
        "hotspots": [
            ("reed_gap",     0.0,  0.0, 0.75, ["worm", "jig"],         "snag_med"),
            ("reed_pocket",  1.5,  1.0, 0.70, ["worm"],                "snag_med"),
            ("outside_edge", 0.0, -2.5, 0.65, ["spinnerbait", "crankbait"], "snag_low"),
        ],
    },
    "lily_pads": {
        "radius_m": (3.5, 3.0),
        "values": {
            "shade": 0.85, "vegetation": 0.70, "cover": 0.55,
            "snag": 0.65, "ambush": 0.70, "depth_delta_m": +0.25,  # パッドの穴→深い
            "bottom_type": "mud",
        },
        "hotspots": [
            ("pad_hole", 0.0, 0.0, 0.80, ["worm", "jig"],        "snag_high"),
            ("pad_edge", 2.5, 0.0, 0.70, ["topwater", "spinnerbait"], "snag_med"),
        ],
    },
    "rock_pile": {
        "radius_m": (2.5, 2.0),
        "outer": {"radius_m": (4.0, 3.0), "depth_delta_m": +0.15},  # 岩周りの深み→深い
        "values": {
            "hardness": 0.85, "cover": 0.50, "snag": 0.35,
            "ambush": 0.50, "depth_delta_m": -0.25,  # 岩本体の盛り上がり→浅い
            "bottom_type": "rock",
        },
        "hotspots": [
            ("rock_crevice",     0.0, 0.0, 0.75, ["jig", "worm"], "snag_med"),
            ("hard_bottom_edge", 2.5, 0.0, 0.65, ["crankbait"],   "snag_low"),
        ],
    },
    "stump_field": {
        "radius_m": (3.0, 2.5),
        "values": {
            "cover": 0.50, "snag": 0.50, "ambush": 0.50,
            "depth_delta_m": +0.10,  # 切り株の洗掘→深い
            "bottom_type": "wood",
        },
        "hotspots": [
            ("stump_shade", 0.0, 0.0, 0.60, ["jig", "worm"], "snag_med"),
        ],
    },
    "brush_pile": {
        "radius_m": (2.2, 2.2),
        "values": {
            "cover": 0.70, "snag": 0.80, "ambush": 0.60, "shade": 0.30,
            "bottom_type": "wood",
        },
        "hotspots": [
            ("brush_heart", 0.0, 0.0, 0.65, ["worm", "jig"], "snag_high"),
        ],
    },
}

# influence をクランプ [0,1] するソフト値キー (depth_delta_m は別扱い)
_SOFT_KEYS = ("cover", "shade", "snag", "vegetation", "hardness", "ambush")


def _sattr(struct, name: str, default):
    """StructureObject / dict 双方から属性を取り出す。"""
    if isinstance(struct, dict):
        return struct.get(name, default)
    return getattr(struct, name, default)


def _bake_structures(terrain: "FishingTerrain") -> None:
    """terrain.structures を cells に焼き込み hotspots を生成する。"""
    hotspots: List[dict] = []
    vw = terrain.view_width_m
    vd = terrain.view_depth_m
    cols = terrain.grid_cols
    rows = terrain.grid_rows

    for struct in terrain.structures:
        stype = _sattr(struct, "type", None)
        spec = _STRUCT_INFLUENCE.get(stype)
        if not spec:
            continue

        sx = float(_sattr(struct, "x", 0.0))
        sy = float(_sattr(struct, "y", 0.0))
        scale = float(_sattr(struct, "scale", 1.0))
        rotation = float(_sattr(struct, "rotation", 0.0))
        density = float(_sattr(struct, "density", 0.5))
        tier = _sattr(struct, "tier", "MID")
        tmult = _TIER_MULT.get(tier, 0.75)
        dmult = 0.6 + 0.4 * max(0.0, min(1.0, density))

        # 中心セル (メートル → grid)
        ccol = max(0, min(cols - 1, int(sx / vw * cols)))
        crow = max(0, min(rows - 1, int(sy / vd * rows)))

        rad_m = spec["radius_m"]
        rc = rad_m[0] * scale / vw * cols
        rr = rad_m[1] * scale / vd * rows

        # 岩周りの広域な深み等を本体より先に適用
        outer = spec.get("outer")
        if outer:
            orc = outer["radius_m"][0] * scale / vw * cols
            orr = outer["radius_m"][1] * scale / vd * rows
            apply_radial_influence(
                terrain, ccol, crow, orc, orr,
                {"depth_delta_m": outer["depth_delta_m"] * tmult},
                falloff="smooth",
            )

        # tier / density でスケールした values を作る
        scaled: dict = {}
        for key, val in spec["values"].items():
            if key == "bottom_type":
                scaled[key] = val
            elif key == "depth_delta_m":
                scaled[key] = val * tmult
            else:
                scaled[key] = val * tmult * dmult
        apply_radial_influence(terrain, ccol, crow, rc, rr, scaled, falloff="smooth")

        # hotspots (rotation/scale でオフセットを配置)
        rot = math.radians(rotation)
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        for kind, dx_m, dy_m, base_score, lures, risk in spec["hotspots"]:
            ox = (dx_m * cos_r - dy_m * sin_r) * scale
            oy = (dx_m * sin_r + dy_m * cos_r) * scale
            hx = max(0.0, min(vw, sx + ox))
            hy = max(0.0, min(vd, sy + oy))
            score = max(0.0, min(1.0, base_score * (0.75 + 0.25 * tmult)))
            hotspots.append({
                "kind": kind,
                "x": hx,
                "y": hy,
                "score": score,
                "preferred_lures": list(lures),
                "risk": risk,
                "source": stype,
            })

    terrain.hotspots = hotspots


def _finalize_depths(
    cells: List[List[TerrainCell]], grid_rows: int, grid_cols: int
) -> Tuple[float, float]:
    """depth_m = clamp(base_depth_m + depth_delta_m, 0.2) を再計算し min/max を返す。"""
    mn, mx = float("inf"), float("-inf")
    for r in range(grid_rows):
        for c in range(grid_cols):
            tc = cells[r][c]
            tc.depth_m = max(0.2, tc.base_depth_m + tc.depth_delta_m)
            if tc.depth_m < mn:
                mn = tc.depth_m
            if tc.depth_m > mx:
                mx = tc.depth_m
    if mn == float("inf"):
        mn, mx = 0.2, 1.0
    return mn, mx


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
            # base_depth_m はプロファイル純水深。局所/ストラクチャー変化は
            # depth_delta_m に蓄積し、_finalize_depths で depth_m を再計算する。
            tc = TerrainCell(depth_m=d, base_depth_m=d)
            row.append(tc)
        cells.append(row)

    # 局所的な深み/盛り上がり (scour holes / rock humps)
    rng_local = random.Random(seed)
    # scour hole 1〜2個: 楕円形に少し深くなる (depth_delta_m > 0)
    num_scour = 1 + (seed % 2)
    for _ in range(num_scour):
        fc = rng_local.randint(cols // 5, cols * 4 // 5)
        fr = rng_local.randint(rows // 5, rows * 2 // 3)
        delta = +(0.30 + rng_local.random() * 0.30)
        _apply_ellipse_depth_delta(cells, rows, cols, fc, fr, 3, 2, delta)
    # rock hump 1個: 局所的に少し浅くなる盛り上がり (depth_delta_m < 0)
    hc = (seed * 7 % (cols // 2)) + cols // 4
    hr = rows // 4 + (seed * 3 % (rows // 3))
    _apply_ellipse_depth_delta(cells, rows, cols, hc, hr, 2, 2, -0.35)

    # pocket depression 1〜2個: 葦/リリー切れ目の小さな深み (depth_delta_m > 0)。
    # 横一直線にしないよう列をばらつかせ、浅め側 (手前寄り) に配置する。
    num_pocket = 1 + (seed % 2)
    for _ in range(num_pocket):
        pc = rng_local.randint(cols // 6, cols * 5 // 6)
        pr = rng_local.randint(rows // 3, rows - 2)
        p_delta = +(0.15 + rng_local.random() * 0.20)
        _apply_ellipse_depth_delta(cells, rows, cols, pc, pr, 2, 1, p_delta)

    terrain = FishingTerrain(
        spot_id=spot_id,
        grid_cols=cols,
        grid_rows=rows,
        view_width_m=spot.view_width_m,
        view_depth_m=spot.view_depth_m,
        cells=cells,
        hotspots=[],
        structures=list(spot.structures),
    )

    # StructureObject の水中影響を焼き込む (cover/shade/snag/... + depth_delta_m)
    _bake_structures(terrain)

    # depth_m を base + delta から再計算 → slope を再計算 → min/max 更新
    mn, mx = _finalize_depths(cells, rows, cols)
    terrain.min_depth_m = mn
    terrain.max_depth_m = mx
    _compute_slopes(cells, rows, cols)

    return terrain


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
