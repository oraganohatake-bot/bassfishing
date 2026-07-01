"""structure_objects.py – ストラクチャー種別の物理パラメータ定義。

UnderwaterCell の terrain / cover / weed フラグと対応する
ゲームプレイ上のパラメータ（根がかり・ブロック・外れ方向）を保持する。

Phase 1（根がかりシステム）からこのモジュールを実際に使用する。
現段階では fishing_terrain.py と underwater_map.py から参照するのみ。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from constants import (
    TERRAIN_FLAT, TERRAIN_WEED, TERRAIN_COVER, TERRAIN_BREAK, TERRAIN_ROCK,
    DIR_NONE, DIR_DOWN,
)


# ── StructureObject: 釣りビュー内の視覚的ストラクチャー配置 ──────────
# StructureParams (物理パラメータ) とは別レイヤー。
# Phase D で描画に使用する。Phase A ではデータとして保持するのみ。

STRUCTURE_TYPES = frozenset({
    "stake_cluster",
    "laydown",
    "weed_bed",
    "rock_pile",
    "reed_bed",
    "lily_pads",
    "stump_field",
    "brush_pile",
})

STRUCTURE_TIERS = frozenset({"LOW", "MID", "HERO"})


@dataclass
class StructureObject:
    """釣りビュー上の視覚的ストラクチャー配置データ。

    Attributes
    ----------
    type     : ストラクチャー種別 (STRUCTURE_TYPES の値)
    x        : グリッド上のX座標 [col]
    y        : グリッド上のY座標 [row]
    scale    : 描画スケール係数 (1.0 = 標準)
    rotation : 回転角 [deg]
    density  : セル内の密度 0.0–1.0
    seed     : 描画ランダムシード
    tier     : 重要度/サイズ "LOW" | "MID" | "HERO"
    """
    type:     str
    x:        float
    y:        float
    scale:    float = 1.0
    rotation: float = 0.0
    density:  float = 0.5
    seed:     int   = 0
    tier:     str   = "MID"


@dataclass(frozen=True)
class StructureParams:
    """キャスト/根がかり/ライン干渉に使うストラクチャーパラメータ。

    Attributes
    ----------
    blocking    : True = キャスト着水をブロックする（岩・杭など）
    snag_weight : 根がかり発生の基本重み 0.0–1.0
    weak_dir    : 外れやすい引っ張り方向 (DIR_* 定数 / DIR_NONE)
    """
    blocking:    bool
    snag_weight: float
    weak_dir:    int


# ── 地形タイプ別パラメータ定数 ───────────────────────────────────────
# 参照頻度が高いのでモジュールレベルで singletons として定義する。

_FLAT  = StructureParams(blocking=False, snag_weight=0.00, weak_dir=DIR_NONE)
_WEED  = StructureParams(blocking=False, snag_weight=0.25, weak_dir=DIR_NONE)
_COVER = StructureParams(blocking=False, snag_weight=0.65, weak_dir=DIR_DOWN)
_BREAK = StructureParams(blocking=False, snag_weight=0.10, weak_dir=DIR_NONE)
_ROCK  = StructureParams(blocking=True,  snag_weight=0.85, weak_dir=DIR_NONE)

# 将来追加予定のタイプ（参考）
# _STUMP  = StructureParams(blocking=False, snag_weight=0.75, weak_dir=DIR_NONE)
# _PILING = StructureParams(blocking=True,  snag_weight=0.70, weak_dir=DIR_NONE)

# terrain int (+ cover/weed フラグ) → StructureParams のマッピング。
# cell_params() を経由して参照するが、直接使いたい場合のために公開する。
STRUCTURE_PARAMS: dict = {
    "flat":  _FLAT,
    "weed":  _WEED,
    "cover": _COVER,
    "break": _BREAK,
    "rock":  _ROCK,
}


def cell_params(terrain: int, is_cover: bool, is_weed: bool) -> StructureParams:
    """セルの terrain フラグと cover / weed フラグから StructureParams を返す。

    優先順位: ROCK > COVER フラグ > TERRAIN_COVER > WEED フラグ > TERRAIN_WEED
               > TERRAIN_BREAK > TERRAIN_FLAT

    Parameters
    ----------
    terrain  : UnderwaterCell.terrain (TERRAIN_* 定数)
    is_cover : UnderwaterCell.cover
    is_weed  : UnderwaterCell.weed
    """
    if terrain == TERRAIN_ROCK:
        return _ROCK
    if is_cover or terrain == TERRAIN_COVER:
        return _COVER
    if is_weed or terrain == TERRAIN_WEED:
        return _WEED
    if terrain == TERRAIN_BREAK:
        return _BREAK
    return _FLAT
