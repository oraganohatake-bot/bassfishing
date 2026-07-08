"""fishing_spots.py – スポット固有の固定メタデータ。

spot_templates.py が手続き的地形生成パラメータを保持するのに対し、
このファイルはゲームデザイン上の「スポット個性」を宣言的に定義する。

設計方針
--------
- プレイヤー向きによる動的切り出しは行わない (spot_id ごとの固定ビュー方式)
- UnderwaterMap の手続き生成を上書きするのではなく、補完するレイヤーとして機能する
- Phase A では器のみ。実際の影響はフェーズ移行ごとに追加していく
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from structure_objects import StructureObject


# ── FishingSpot: spot_id ベースの固定ビュー定義 ───────────────────────
# SpotMeta (スポット個性) とは別レイヤー。
# FishingTerrain 生成の入力として機能する。

@dataclass
class FishingSpot:
    """釣りビューの固定ビュー定義。

    Attributes
    ----------
    spot_id        : "spot_01" 〜 "spot_10" の固有ID
    name           : 表示名 (SPOT_CONFIGS / SpotMeta のキーと一致)
    entry_tile     : フィールドマップ上の入口タイル座標 (仮値可)
    view_width_m   : 釣りビューの横幅 [m]
    view_depth_m   : 釣りビューの縦幅 (水深方向) [m]
    grid_cols      : グリッド列数
    grid_rows      : グリッド行数
    base_depth_m   : 手前端 (プレイヤー側) の基準水深 [m]
    max_depth_m    : 奥端の最大水深 [m]
    depth_profile  : "shallow_flat" | "normal_slope" | "steep_break" | "deep_edge"
    structures     : 配置済み StructureObject リスト (Phase A では空)
    """
    spot_id:       str
    name:          str
    entry_tile:    Tuple[int, int]
    view_width_m:  float
    view_depth_m:  float
    grid_cols:     int
    grid_rows:     int
    base_depth_m:  float
    max_depth_m:   float
    depth_profile: str
    structures:    List = field(default_factory=list)


# ── 全スポット定義 ────────────────────────────────────────────────────
# entry_tile は現フェーズで未使用のため仮値 (0,0)。
# depth_profile は spot_templates.py の depth_profile + SpotMeta.depth_range を参考に設定。

FISHING_SPOTS: dict[str, FishingSpot] = {
    "spot_01": FishingSpot(
        spot_id="spot_01", name="North Point",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.8, max_depth_m=3.8,
        depth_profile="steep_break",
        # D-2.6: 岩場 + 旧桟橋跡のポイント。岩を主役に、杭列は離した位置で
        # 岸→沖の桟橋跡 (old_pier_remnant; 近くに葦が無いので決定的) に見せる。
        structures=[
            StructureObject(type="rock_pile", x=21.0, y=8.0,
                            scale=1.15, rotation=0.0, density=0.8,
                            seed=1011, tier="HERO"),
            StructureObject(type="stake_cluster", x=8.0, y=15.0,
                            scale=1.0, rotation=0.0, density=0.75,
                            seed=1012, tier="MID"),
        ],
    ),
    "spot_02": FishingSpot(
        spot_id="spot_02", name="NE Weed Flat",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.4, max_depth_m=1.2,
        depth_profile="shallow_flat",
        # D-2.6: 役割分担した構図。奥左に葦原、その縁に古い杭列(reed_fence)、
        # 手前右にリリーパッド、中央手前に下地のウィード。中心をベタ重ねしない。
        structures=[
            # 奥・左岸際の葦原 (横に長め・高密度)
            StructureObject(type="reed_bed", x=6.0, y=5.0,
                            scale=1.25, rotation=8.0, density=0.9,
                            seed=2012, tier="MID"),
            # 葦原の外側エッジ沿いの古い杭列 → _stake_variant が reed_fence 判定
            StructureObject(type="stake_cluster", x=8.5, y=6.5,
                            scale=0.9, rotation=0.0, density=0.6,
                            seed=2014, tier="LOW"),
            # 手前右のリリーパッド (葦・ウィードから離す)
            StructureObject(type="lily_pads", x=13.0, y=8.5,
                            scale=1.1, rotation=15.0, density=0.75,
                            seed=2013, tier="MID"),
            # 中央手前の下地ウィード (広め・薄め; reed/lily の真下に重ねない)
            StructureObject(type="weed_bed", x=11.0, y=11.0,
                            scale=1.4, rotation=0.0, density=0.6,
                            seed=2011, tier="HERO"),
        ],
    ),
    "spot_03": FishingSpot(
        spot_id="spot_03", name="East Shore",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.6, max_depth_m=2.8,
        depth_profile="normal_slope",
        # D-2.7: 岸沿いの葦際ポイント。主役=奥右の葦原、補助=手前の薄い下地
        # ウィード1つのみ。spot_02 との差別化でリリー・杭は置かない。
        # 狙い目は葦の切れ目 (reed_pocket) と外側エッジ (outside_edge)。
        structures=[
            # 主役: 奥・右岸際の葦原
            StructureObject(type="reed_bed", x=20.0, y=6.0,
                            scale=1.35, rotation=-8.0, density=0.9,
                            seed=3011, tier="MID"),
            # 補助: 手前側の下地ウィード (D-3.3: 量感UPで岸際感を出す)
            StructureObject(type="weed_bed", x=13.0, y=16.0,
                            scale=1.45, rotation=0.0, density=0.75,
                            seed=3012, tier="LOW"),
        ],
    ),
    "spot_04": FishingSpot(
        spot_id="spot_04", name="SE Cove",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=1.0, max_depth_m=2.0,
        depth_profile="normal_slope",
        structures=[
            StructureObject(type="laydown", x=18.0, y=15.0,
                            scale=1.0, rotation=-12.0, density=0.8,
                            seed=12031, tier="HERO"),
            StructureObject(type="laydown", x=9.0, y=8.0,
                            scale=0.8, rotation=20.0, density=0.6,
                            seed=4041, tier="MID"),
            StructureObject(type="stump_field", x=24.0, y=18.0,
                            scale=1.0, rotation=0.0, density=0.7,
                            seed=4042, tier="LOW"),
        ],
    ),
    "spot_05": FishingSpot(
        spot_id="spot_05", name="South Flat",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=1.0, max_depth_m=2.0,
        depth_profile="shallow_flat",
        # D-2.7: 浅いフラットのパッド撃ちに特化。主役=中〜手前のリリーパッド、
        # 補助=外側の薄いウィードのみ。葦・杭は置かない。
        # 狙い目はパッドの穴 (pad_hole) と通し筋/外周 (pad_lane / pad_edge)。
        structures=[
            # 主役: 中央やや手前のリリーパッド (穴/laneが見える大きさ)
            StructureObject(type="lily_pads", x=14.0, y=11.0,
                            scale=1.2, rotation=12.0, density=0.75,
                            seed=5011, tier="HERO"),
            # 補助: 外側手前の下地ウィード (薄め)
            StructureObject(type="weed_bed", x=9.0, y=15.0,
                            scale=1.3, rotation=0.0, density=0.5,
                            seed=5012, tier="LOW"),
        ],
    ),
    "spot_06": FishingSpot(
        spot_id="spot_06", name="SW Brush",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.8, max_depth_m=2.2,
        depth_profile="shallow_flat",
        structures=[
            StructureObject(type="brush_pile", x=14.0, y=12.0,
                            scale=1.1, rotation=0.0, density=0.85,
                            seed=6011, tier="HERO"),
            StructureObject(type="laydown", x=22.0, y=16.0,
                            scale=0.9, rotation=8.0, density=0.7,
                            seed=6012, tier="MID"),
        ],
    ),
    "spot_07": FishingSpot(
        spot_id="spot_07", name="West Bank",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.8, max_depth_m=3.5,
        depth_profile="steep_break",
        # D-2.7: 急なブレイク沿いの倒木ポイント。主役=岸から沖へ斜めに伸びる
        # 倒木、補助=少し離した切り株フィールド LOW のみ。植物系は増やさない。
        # 狙い目は根元のえぐれ (root_hole) と枝先/影 (branch_tip / shade_line)。
        structures=[
            # 主役: 手前(浅)→奥(深)へ斜めに倒れ込む倒木
            StructureObject(type="laydown", x=12.0, y=13.0,
                            scale=1.1, rotation=-25.0, density=0.8,
                            seed=7011, tier="HERO"),
            # 補助: 離れた位置の切り株フィールド (絡み過ぎない)
            StructureObject(type="stump_field", x=22.0, y=17.0,
                            scale=0.9, rotation=0.0, density=0.6,
                            seed=7012, tier="LOW"),
        ],
    ),
    "spot_08": FishingSpot(
        spot_id="spot_08", name="NW Drop-off",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=1.0, max_depth_m=4.5,
        depth_profile="deep_edge",
        # D-2.7: 深場のハードボトム一点狙い。主役=深場寄りの岩、補助=少し離した
        # 小さめの岩 LOW のみ。リリー・葦・杭は置かない。深く暗い雰囲気は既存地形任せ。
        # 狙い目は岩の隙間 (rock_crevice) とハードボトムの縁 (hard_bottom_edge)。
        structures=[
            # 主役: 奥(深場)寄りの岩塊
            StructureObject(type="rock_pile", x=18.0, y=7.0,
                            scale=1.2, rotation=0.0, density=0.85,
                            seed=8011, tier="HERO"),
            # 補助: 少し離した小さめの岩 (主役の真上に重ねない)
            StructureObject(type="rock_pile", x=25.0, y=12.0,
                            scale=0.85, rotation=0.0, density=0.6,
                            seed=8012, tier="LOW"),
        ],
    ),
    "spot_09": FishingSpot(
        spot_id="spot_09", name="Island Point",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=0.5, max_depth_m=3.5,
        depth_profile="normal_slope",
        # D-2.7: 島周りの複合ポイント (ただし全部入りにしない)。主役=先端側の岩、
        # 補助=周囲の薄いウィードをエッジとして。杭は置かない。
        # 01/10 の岩+杭とは差別化し、岩+ウィードの島周りにする。
        # 狙い目はハードボトムの縁 (hard_bottom_edge) とウィードエッジ (weed_edge)。
        structures=[
            # 主役: ポイント先端側 (奥) の岩塊
            StructureObject(type="rock_pile", x=16.0, y=8.0,
                            scale=1.1, rotation=0.0, density=0.8,
                            seed=9011, tier="HERO"),
            # 補助: 岩の外側に広がるウィードエッジ (D-3.3: 量感UP・少し内側へ)
            StructureObject(type="weed_bed", x=19.5, y=13.0,
                            scale=1.45, rotation=0.0, density=0.7,
                            seed=9012, tier="LOW"),
        ],
    ),
    "spot_10": FishingSpot(
        spot_id="spot_10", name="Rock Pile",
        entry_tile=(0, 0),
        view_width_m=30.0, view_depth_m=24.0,
        grid_cols=32, grid_rows=24,
        base_depth_m=1.5, max_depth_m=3.5,
        depth_profile="steep_break",
        # D-2.6: 岩場 + 杭跡の複合。岩2つは中心をずらし、杭列は岩の真上でなく
        # 手前脇へ (old_pier_remnant として絡ませる)。中央に集めすぎない。
        structures=[
            StructureObject(type="rock_pile", x=13.0, y=9.0,
                            scale=1.3, rotation=0.0, density=0.9,
                            seed=1001, tier="HERO"),
            StructureObject(type="rock_pile", x=25.0, y=14.0,
                            scale=0.9, rotation=0.0, density=0.7,
                            seed=1002, tier="MID"),
            StructureObject(type="stake_cluster", x=7.0, y=18.0,
                            scale=1.0, rotation=0.0, density=0.7,
                            seed=1003, tier="LOW"),
        ],
    ),
}

# スポット名 → spot_id 変換テーブル
_SPOT_NAME_TO_ID: dict[str, str] = {
    spot.name: sid for sid, spot in FISHING_SPOTS.items()
}

_DEFAULT_SPOT = FishingSpot(
    spot_id="spot_00", name="Generic",
    entry_tile=(0, 0),
    view_width_m=30.0, view_depth_m=24.0,
    grid_cols=32, grid_rows=24,
    base_depth_m=0.8, max_depth_m=3.5,
    depth_profile="normal_slope",
)


def spot_name_to_id(name: str) -> str:
    """スポット名を spot_id に変換する。未登録の場合は "spot_00" を返す。"""
    return _SPOT_NAME_TO_ID.get(name, "spot_00")


def get_fishing_spot(spot_id: str) -> FishingSpot:
    """spot_id から FishingSpot を取得する。未登録の場合はデフォルトを返す。"""
    return FISHING_SPOTS.get(spot_id, _DEFAULT_SPOT)


@dataclass
class SpotMeta:
    """スポットごとの固定メタデータ。

    Attributes
    ----------
    depth_range
        (min_m, max_m): このスポットで想定される水深レンジ。
        UnderwaterMap の depth_profile と対応する設計意図として記録する。
    snag_rating
        根がかり難易度 0.0（ほぼなし） – 1.0（ヘビーカバー）。
        fishing_terrain.check_snag() の spot 補正として使用する。
    fish_size_bias
        魚サイズのバイアス係数。
        1.0 = 標準 / > 1.0 = 大型傾向 / < 1.0 = 小型傾向。
        将来 FishPopulationManager の生成調整に使用する。
    hotspot_hints
        事前指定のホットスポットセル (x, y)。
        空リストの場合は UnderwaterMap.best_positions() に任せる。
    placed_structures
        手動配置ストラクチャー (x, y, terrain_type)。
        フェーズ移行で特定位置に杭・切り株などを置く際に使用する。
        Phase A では全スポット空リスト。
    notes
        フレーバーテキスト。将来の NPC ヒントシステムの元ネタ。
    """
    depth_range:       Tuple[float, float]       = (0.5, 3.5)
    snag_rating:       float                     = 0.5
    fish_size_bias:    float                     = 1.0
    hotspot_hints:     List[Tuple[int, int]]     = field(default_factory=list)
    placed_structures: List[Tuple[int, int, int]] = field(default_factory=list)
    notes:             str                        = ""


# ── 全スポット定義 ────────────────────────────────────────────────────
# キーは spot_templates.py の SPOT_CONFIGS キーと一致させる。

SPOT_META: dict[str, SpotMeta] = {
    "North Point": SpotMeta(
        depth_range=(0.8, 3.8),
        snag_rating=0.70,
        fish_size_bias=1.20,
        notes="岩盤が多く根がかり注意。大型が付きやすい岬先端。",
    ),
    "NE Weed Flat": SpotMeta(
        depth_range=(0.4, 1.2),
        snag_rating=0.25,
        fish_size_bias=0.85,
        notes="ウィードが密生するシャロー。スイミング系ルアーは底ギリを意識。",
    ),
    "East Shore": SpotMeta(
        depth_range=(0.6, 2.8),
        snag_rating=0.45,
        fish_size_bias=1.00,
        notes="入門向きのバランスの良い護岸。あらゆるルアーが機能する。",
    ),
    "SE Cove": SpotMeta(
        depth_range=(1.0, 2.0),
        snag_rating=0.80,
        fish_size_bias=1.15,
        notes="倒木だらけのカバーゾーン。ラインブレイクリスクが高いが魚は付く。",
    ),
    "South Flat": SpotMeta(
        depth_range=(1.0, 2.0),
        snag_rating=0.20,
        fish_size_bias=0.90,
        notes="ストラクチャーが少ないオープンフラット。ベイトの回遊を狙う。",
    ),
    "SW Brush": SpotMeta(
        depth_range=(0.8, 2.2),
        snag_rating=0.75,
        fish_size_bias=1.10,
        notes="ブラッシュにバスが潜む。ワームのフリッピングが有効。",
    ),
    "West Bank": SpotMeta(
        depth_range=(0.8, 3.5),
        snag_rating=0.60,
        fish_size_bias=1.05,
        notes="岩盤の間を流す。根がかり覚悟で奥を攻める価値がある。",
    ),
    "NW Drop-off": SpotMeta(
        depth_range=(1.0, 4.5),
        snag_rating=0.35,
        fish_size_bias=1.30,
        notes="急深ドロップオフ。ブレイクラインに大型が定位しやすい。",
    ),
    "Island Point": SpotMeta(
        depth_range=(0.5, 3.5),
        snag_rating=0.55,
        fish_size_bias=1.15,
        notes="多様な地形が混在する岬。あらゆるサイズが狙える万能スポット。",
    ),
    "Rock Pile": SpotMeta(
        depth_range=(1.5, 3.5),
        snag_rating=0.90,
        fish_size_bias=1.40,
        notes="岩の積み重なりがトロフィーバスを産む。タックルを万全に。",
    ),
}

_DEFAULT_META = SpotMeta()


def get_spot_meta(spot_name: str) -> SpotMeta:
    """スポット名から SpotMeta を返す。未登録スポットはデフォルト値を返す。"""
    return SPOT_META.get(spot_name, _DEFAULT_META)
