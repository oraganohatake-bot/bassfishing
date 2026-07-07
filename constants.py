# Build/version id — DBG/F2 デバッグON時に画面へ表示し、Web(pygbag)配信時に
# スマホが最新 payload を掴んでいるかを一発で切り分けるための識別子。
BUILD_ID = "D3 laydown-rock"

SCREEN_W = 1280
SCREEN_H = 720
TILE_SIZE = 32
MAP_W = 50
MAP_H = 50
FPS = 60

# Tile types
TILE_LAND = 0
TILE_WATER = 1
TILE_PATH = 2
TILE_SHORE = 3

# Underwater terrain types
TERRAIN_FLAT = 0
TERRAIN_WEED = 1
TERRAIN_COVER = 2
TERRAIN_BREAK = 3
TERRAIN_ROCK = 4

# Colors - exploration
C_LAND = (78, 115, 50)
C_WATER = (30, 80, 180)
C_PATH = (160, 140, 100)
C_SHORE = (90, 130, 60)
C_PLAYER = (255, 220, 50)
C_FISHING_SPOT = (255, 200, 0)

# Colors - underwater map cells
C_FLAT = (50, 100, 180)
C_WEED_CELL = (40, 160, 80)
C_COVER_CELL = (100, 70, 40)
C_BREAK_CELL = (20, 60, 140)
C_ROCK_CELL = (120, 115, 130)
C_FISH_IDLE = (160, 120, 80)
C_FISH_ACTIVE = (255, 180, 0)
C_LURE = (255, 80, 0)

# Colors - UI
C_BLACK = (0, 0, 0)
C_WHITE = (255, 255, 255)
C_GRAY = (150, 150, 150)
C_DARK = (20, 30, 50)
C_YELLOW = (255, 220, 50)
C_RED = (220, 50, 50)
C_GREEN = (50, 200, 80)

# Game states
ST_EXPLORE = "explore"
ST_FISHING = "fishing"

# Fishing phase states  (FishingView.state)
FS_IDLE = "idle"
FS_CAST_CHARGE = "cast_charge"     # Beta v0.9: holding LMB, charging cast power
FS_CASTING = "casting"             # v0.95: lure flying through the air to landing point
FS_RETRIEVE = "retrieve"
FS_BITE = "bite"
FS_WEIGHT = "weight"               # Hooking v1: ワーム系 重みが乗る (ティップが少し入る / ラインが張る)
FS_LINE_RUN = "line_run"           # Hooking v1: ワーム系 魚方向へラインが走る (ライン角度が変化)
FS_FIGHT = "fight"                 # Beta v0.9: tension-managed fight (50cm+)
FS_KEEP_RELEASE = "keep_release"   # Phase 10: waiting for K / R decision
FS_RESULT = "result"

# ── Beta v0.9: Cast quality ──────────────────────────────────────────
CAST_PERFECT = "PERFECT"
CAST_GOOD    = "GOOD"
CAST_EARLY   = "EARLY"
CAST_LATE    = "LATE"

# ── Beta v0.9: Hookset modes (per lure) ──────────────────────────────
HOOKSET_DELAY        = "DELAY_HOOKSET"         # Worm / Jig
HOOKSET_AUTO         = "AUTO_HOOKSET"          # Crankbait / Spinnerbait
HOOKSET_HYBRID       = "HYBRID_HOOKSET"        # Minnow
HOOKSET_VISUAL_DELAY = "VISUAL_DELAY_HOOKSET"  # Topwater

# ── Beta v0.9: Bite feedback types ───────────────────────────────────
BITE_LIGHT_TICK   = "LIGHT_TICK"     # worm / finesse
BITE_MEDIUM_TICK  = "MEDIUM_TICK"    # jig / texas
BITE_HEAVY_STRIKE = "HEAVY_STRIKE"   # crank / spinnerbait

# ── Beta v0.9: Hook quality → initial hook_hold ──────────────────────
HOOK_QUALITY_HOLD: dict = {
    "JUST":   100.0,
    "GOOD":    75.0,
    "NORMAL":  55.0,
    "POOR":    35.0,
}

# Lure action types
ACTION_IDLE = "idle"
ACTION_RETRIEVE = "retrieve"
ACTION_STOP = "stop"
ACTION_TWITCH = "twitch"
ACTION_LIFT = "lift"
ACTION_FALL = "fall"

# Fish reaction stages  (Fish.state)
REACT_IGNORE = "ignore"
REACT_NOTICE = "notice"
REACT_APPROACH = "approach"
REACT_CHASE = "chase"
REACT_BITE = "bite"
REACT_SPOOK = "spook"
FISH_CAUGHT = "caught"

# Reaction priority (for sorting / display)
REACTION_PRIORITY: dict = {
    REACT_IGNORE: 0,
    REACT_NOTICE: 1,
    REACT_APPROACH: 2,
    REACT_CHASE: 3,
    REACT_BITE: 4,
    REACT_SPOOK: -1,
    FISH_CAUGHT: -2,
}

# Underwater map dimensions
# UW_SIZE: 従来の正方グリッド辺。後方互換のため「奥行き(縦/depth)」の別名として残す。
UW_SIZE = 32

# Hooking/Exploration v2: 釣りビューを横に広げ、左右移動で探索感を出す。
#   UW_W = 横(幅)のセル数, UW_H = 奥行き(縦)のセル数。
#   幅だけを 1.5x にする (奥行きは据え置き)。x軸境界は UW_W、y軸境界は UW_H を使う。
FISHING_VIEW_WIDTH_SCALE = 1.5            # 釣りビューの横幅倍率 (ここ1箇所で調整)
UW_H = UW_SIZE                            # 奥行き = 従来どおり 32
UW_W = int(round(UW_SIZE * FISHING_VIEW_WIDTH_SCALE))  # 幅 = 48 (=32*1.5)

# Colors – fish reaction stages (sidebar dots + status panel)
C_FISH_NOTICE   = (200, 185,  50)
C_FISH_APPROACH = (230, 130,  20)
C_FISH_BITE_COL = (255,  40,  40)
C_FISH_SPOOK    = (160,  50, 220)

# Rendering zoom / pixel-art pipeline
ZOOM_W     = 700   # 世界の何px分を表示するか（小さいほどズームイン）
PIX_DIV    = 2     # 縮小率（1/2解像度→2倍拡大でドット感）
SIZE_BOOST = 1.45  # pscale に掛けるサイズ倍率

# ── Structure interaction directions ─────────────────────────────────
# weak_dir: 根がかりから外れやすい引っ張り方向。DIR_NONE = 特定方向なし。
DIR_NONE  = -1   # 外れやすい方向なし (岩など)
DIR_UP    =  0   # 奥方向 (far shore)
DIR_DOWN  =  1   # 手前 (near player)
DIR_LEFT  =  2
DIR_RIGHT =  3
