"""tuning.py – Beta v0.9 プレイフィール調整パラメータ集約。

全ての「手触り」に関わる数値をここに集める。
ゲームを再起動するだけで調整結果を試せる。

各セクションはプレイフィール確認項目に対応:
  [CAST]  PERFECT帯の広さ / EARLY・LATEの理不尽さ
  [REEL]  チョイ巻き・早巻きの反応
  [ROD]   トゥイッチ判定・ストップの間
  [BITE]  ワーム/ジグの待ち時間 / トップの我慢
  [FIGHT] テンション読みやすさ / バラシの理不尽さ / 50UPの緊張感

※ 60fps 前提。フレーム数 ÷ 60 = 秒。
"""

# ════════════════════════════════════════════════════════════════════
# [CAST] キャストゲージ
# ════════════════════════════════════════════════════════════════════

# ゲージ速度 (per frame)。100/40 = 約0.67秒で満タン (v0.95: 旧1.0秒比 ~33%速)。
# 「振りかぶる→ロッドの弾性で離す」のキビキビ感を出す。0.55〜0.75秒が目安。
# ゲージは 0→100→0 を往復し続ける (ピンポン式)。自動リリースはない。
CAST_CHARGE_RATE = 100.0 / 40.0

# ゲージ上限 (往復の折り返し点)。
CAST_CHARGE_MAX = 100.0

# PERFECT帯。幅21% ≒ 8.4frame ≒ 140ms の入力窓。
# v0.95: ゲージ高速化に合わせて帯を広げ、短縮後もPERFECTを狙えるよう維持。
# 「狭すぎる」と感じたら LO を下げ HI を上げる。
CAST_PERFECT_LO = 72.0
CAST_PERFECT_HI = 93.0

# GOOD帯の下限。これ未満は EARLY。
CAST_GOOD_LO = 56.0

# 品質 → (ガウスσ, 最大ズレセル数)
CAST_DEV_PERFECT = (0.25, 1)
CAST_DEV_GOOD    = (1.00, 2)
CAST_DEV_EARLY   = (1.20, 2)
CAST_DEV_LATE    = (2.00, 4)

# EARLY: ゲージ不足分 × FACTOR だけ手前に落ちる (CAP = 最大短縮率)。
# 「理不尽」と感じたら FACTOR / CAP を下げる。
CAST_EARLY_SHORTFALL_FACTOR = 0.50
CAST_EARLY_SHORTFALL_CAP    = 0.40

# LATE: 対岸側へのオーバーシュート量 (セル)。
CAST_LATE_OVERSHOOT = (1.5, 3.5)

# PERFECTキャスト時の大型魚 (40cm+) バイトチャージ倍率。
# 「ピンスポットに入った感覚」の核。上げるほどPERFECTの価値が増す。
CAST_PERFECT_BIG_FISH_MULT = 1.5

# ════════════════════════════════════════════════════════════════════
# [REEL] リール操作
# ════════════════════════════════════════════════════════════════════

REEL_TAP_FRAMES   = 7     # これ以下の押下 = チョイ巻き (117ms)
REEL_FAST_CLICKS  = 3     # この回数のクリックで早巻き発動
REEL_FAST_WINDOW  = 40    # 連打判定ウィンドウ (667ms)
REEL_FAST_FRAMES  = 25    # 早巻き持続フレーム
REEL_CREEP_FRAMES = 8     # チョイ巻き持続フレーム
REEL_FAST_MULT    = 1.5   # 早巻き速度倍率 (v0.95: 1.8→1.5。早巻きも遅めに)
REEL_CREEP_MULT   = 0.45  # チョイ巻き速度倍率

# ── リール性能 (ReelSpec) ────────────────────────────────────────────
# v0.95: 巻き速度を「直接固定値」ではなくリール係数から導出する。
# 将来の装備システムでリール性能差を入れるための土台。今は Beginner 固定。
#   retrieve_speed_mps : リトリーブ/ファイト時の基準巻き取り速度 (m/秒)
#   drag_power         : 高テンション時に耐えられる力 (0..1, 大=強い)
#   line_control       : テンション変化の安定性 (0..1, 大=安定)
class ReelSpec:
    """リール1個分の性能。装備システム未実装のため Beginner を既定値に使う。"""

    def __init__(self, name, retrieve_speed_mps, drag_power, line_control):
        self.name = name
        self.retrieve_speed_mps = retrieve_speed_mps
        self.drag_power = drag_power
        self.line_control = line_control


# 序盤リールは弱い前提。現実の早巻きでも序盤タックルは1秒0.5m程度。
BEGINNER_REEL = ReelSpec(
    name="Beginner Reel",
    retrieve_speed_mps=0.45,   # 0.35〜0.60 の中央。通常リトリーブの基準速度
    drag_power=0.45,
    line_control=0.40,
)

# 現在装備中のリール (装備システム実装までは Beginner 固定)。
EQUIPPED_REEL = BEGINNER_REEL

# 水中グリッド1セルの水平距離 (m)。32セル ≒ 16m のキャスト距離相当。
# retrieve_speed_mps をリトリーブの「セル/フレーム」へ換算するのに使う。
REEL_CELL_M = 0.5


def mps_to_cells_per_frame(mps, cell_m, fps=60.0):
    """m/秒 → セル/フレーム。リール係数を画面上の速度へ橋渡しする。"""
    return mps / (cell_m * fps)


# 通常巻き速度 (セル/フレーム)。リール係数から導出。
# 0.45 m/s → 約0.015 セル/f。32セル ≒ 35秒で寄る (v0.95: 旧0.04の約4割)。
REEL_RETRIEVE_SPEED = mps_to_cells_per_frame(
    EQUIPPED_REEL.retrieve_speed_mps, REEL_CELL_M)
REEL_RISE_RATE      = 0.003  # 巻き中にレンジ上限へ向けてゆっくり浮く速度 (m/f)

# ════════════════════════════════════════════════════════════════════
# [ROD] ロッド入力
# ════════════════════════════════════════════════════════════════════

ROD_TWITCH_FRAMES       = 11    # ↓この長さ以下で離す = トゥイッチ (183ms)
ROD_TWITCH_PULSE_FRAMES = 9     # トゥイッチアクション持続
ROD_STOP_WINDOW_FRAMES  = 110   # 操作後この間の中立 = ストップ (1.8s)
ROD_RETURN_SPEED        = 0.18  # 描画値の中立復帰速度 (大=キビキビ)

# 表示上のロッド長 (px)。短くすると画面下から少し出るだけになり、
# ロッドがUIではなく手元の一部に見える。ファイトのしなりは別途 rod_flex で表現。
ROD_VISUAL_LENGTH       = 150

# ── 足場移動 (キャスト前のみ) / キャストカーソル ────────────────────
STANCE_MOVE_SPEED = 0.004   # ←→/A・D で動く player_stance_x の速度 (/frame)
STANCE_MIN        = 0.20    # 足場移動の左端
STANCE_MAX        = 0.80    # 足場移動の右端
CAST_CURSOR_SPEED = 0.30    # 十字キーでのキャストカーソル移動速度 (セル/frame)

# ←→ステアでルアーが横にずれる量の上限 (セル)。竿先の可動分のみ。
# 巻いて前進している間はラインが追従し、ずれが基準位置に吸収されて
# 再びステア可能になる。
ROD_STEER_MAX   = 0.3
ROD_STEER_SPEED = 0.02   # ステア中の横移動速度 (セル/フレーム)

# リフト1回で動かせる量 (竿先の可動分)。これ以上はラインを巻かない限り
# 動かない。ロッドを戻すと引いた分は糸ふけ (slack) になる。
ROD_LIFT_MAX_RISE_M  = 0.6   # 深度の引き上げ上限 (m)
ROD_LIFT_MAX_PULL_C  = 0.4   # 手前への移動上限 (セル)

# ════════════════════════════════════════════════════════════════════
# [LINE] ラインスラック (糸ふけ)
# ════════════════════════════════════════════════════════════════════
# ロッドで引いた分はロッドを戻すと弛みに変わる。弛みがある間は
# リール=糸ふけ回収 (ルアー停止)、トゥイッチ/リフト=効かない。

LINE_SLACK_MAX         = 2.5    # 弛みの最大量 (m)
LINE_SLACK_TWITCH      = 0.12   # トゥイッチ1回で出る弛み (m)
LINE_SLACK_SINK_FACTOR = 0.5    # 沈下1mあたりに出る弛み (フォール/放置中)
LINE_SLACK_REEL_TAKEUP = 0.04   # リールでの回収速度 (m/f ≒ 2.4m/秒)
LINE_SLACK_ROD_TAKEUP  = 0.015  # 竿さばき (リフト) での回収速度 (m/f)

# ════════════════════════════════════════════════════════════════════
# [BITE] バイト発生・フッキング
# ════════════════════════════════════════════════════════════════════

# バイトチャージ発火閾値
BITE_TRIGGER = 0.88

# アクション別チャージ速度 (魚が射程内のとき per frame)
BITE_CHARGE_RATE_STOP     = 0.022
BITE_CHARGE_RATE_TWITCH   = 0.028
BITE_CHARGE_RATE_FALL     = 0.018
BITE_CHARGE_RATE_LIFT     = 0.009
BITE_CHARGE_RATE_RETRIEVE = 0.005
BITE_CHARGE_RATE_IDLE     = 0.007
BITE_CHARGE_DECAY         = 0.010   # 射程外での減衰

# ── イベント駆動バイト (実釣的な「触る/吸う/弾く」瞬間) ──────────────
# 魚が射程内にいる「だけ」では食わない。以下の瞬間に bite_check が走る:
#   ルアー停止 / フォール開始 / ロッドアクション直後 / ストラクチャ通過 /
#   魚がルアーに追いついた瞬間。
# 各イベントで 1 回だけ確率判定 (= base × 環境 × ルアー適合 × 記憶 × キャスト)。
BITE_EVENT_BASE_P   = 0.30   # イベント時の基礎バイト確率
BITE_EVENT_WEIGHTS  = {      # イベント種別ごとの倍率 (吸い込みやすさ)
    "stop":      1.25,   # 止めた瞬間 = 最も食う
    "fall":      1.10,   # フォール開始
    "rod":       1.00,   # トゥイッチ/リフト直後
    "structure": 0.90,   # ストラクチャ通過直後
    "reach":     0.75,   # 魚が追いついた瞬間 (リアクション)
}
# 近接ゲージは「弱い保険」に降格 (放置でもごく稀に食う程度)
BITE_PASSIVE_SCALE  = 0.30
BITE_EVENT_COOLDOWN = 12     # 連続イベントでの過剰発火を防ぐ最小間隔(f)

# ── AUTO系ルアー (クランク/スピナベ): ↓入力タイミング窓 ──────────────
# 自動フッキングは廃止。ゴン!と来たら即↓が正解 (窓は広め)。
# フッキングしなければタイムアウトで逃げられる。
AUTO_JUST_END = 45     # 0.75秒以内 = JUST
AUTO_GOOD_END = 90     # 1.5秒以内 = GOOD
AUTO_TIMEOUT  = 120    # 2秒で見切られる

# ── DELAY (ワーム/ジグ): ↓入力タイミング → フック品質 ────────────────
# 「一呼吸置く」気持ちよさの核。JUST窓を広げると簡単になる。
#   0 ─ POOR_END ─ GOOD1_END ─ JUST_END ─ GOOD2_END ─ (NORMAL) ─ TIMEOUT
DELAY_POOR_END  = 15     # 早合わせ (250ms未満) = POOR
DELAY_GOOD1_END = 28     # 早めGOOD
DELAY_JUST_END  = 95     # ベスト窓 28〜95f (0.47〜1.58s) = JUST
DELAY_GOOD2_END = 130    # 遅めGOOD
DELAY_TIMEOUT   = 180    # 3秒で見切られる

# ── HYBRID手動分岐の窓 ───────────────────────────────────────────────
HYBRID_GOOD_END = 10
HYBRID_JUST_END = 60
HYBRID_TIMEOUT  = 100

# ── VISUAL_DELAY (トップ): 我慢ゲーム ────────────────────────────────
TOPWATER_WEIGHT_ON_RANGE = (35, 65)   # バシャ!から重みが乗るまで (0.58〜1.08s)
TOPWATER_EARLY_MISS_P    = 0.50       # 重み前の早合わせすっぽ抜け率
TOPWATER_JUST_END        = 45         # 重み後45fまで = JUST
TOPWATER_GOOD_END        = 90
TOPWATER_TIMEOUT_AFTER   = 120        # 重み後これで見切り

# ════════════════════════════════════════════════════════════════════
# [FIGHT] ファイト
# ════════════════════════════════════════════════════════════════════

# このサイズ以上でファイト発生。0.0 = 全サイズでファイト
# (小型魚はほぼ巻くだけで寄るが、リアルさのためファイト工程を通す)
FIGHT_MIN_SIZE = 0.0

# ── テンションゾーン境界 ─────────────────────────────────────────────
# GREEN帯を広げる = 簡単に / 狭める = シビアに
FIGHT_T_BLUE   = 0.25
FIGHT_T_GREEN  = 0.55
FIGHT_T_YELLOW = 0.80

# ── ゾーン別効果 (per frame) ─────────────────────────────────────────
FIGHT_BLUE_HOLD_DECAY        = 0.12   # 緩み: hook_hold減 (100→0 が約14秒)
FIGHT_BLUE_SEVERE_DECAY      = 0.30   # 完全に緩んだ時 (<0.08)
FIGHT_GREEN_HOLD_RECOVER     = 0.01
FIGHT_GREEN_STAMINA_DRAIN    = 0.03
FIGHT_YELLOW_STAMINA_DRAIN   = 0.10
FIGHT_RED_STAMINA_DRAIN      = 0.30
FIGHT_RED_HOLD_DECAY         = 0.05
FIGHT_RED_STRESS_REELING     = 1.0    # REDで巻く: ライン負荷/フレーム (警告→ブレイクまで余裕≥1秒)
FIGHT_RED_STRESS_IDLE        = 0.5    # REDで↓を入れている (ロッドで張っている)
FIGHT_RED_STRESS_RELEASE_DECAY = 0.5  # REDでも入力を離せば負荷が抜ける (気づけば助かる)
FIGHT_STRESS_DECAY           = 1.2    # RED以外でのライン負荷回復
FIGHT_LINE_BREAK_STRESS      = 100.0  # この負荷でラインブレイク
# REDで巻いている間のフックアウト確率/フレーム。
# 「バラシが理不尽」と感じたらここを下げる。0.003 ≒ 16%/秒
FIGHT_RED_REEL_HOOKOUT_P     = 0.003

# ── スタミナ・距離 (line_length_m) ──────────────────────────────────
FIGHT_STAMINA_PER_CM   = 3.4     # max_stamina = size × run_power × これ
FIGHT_START_TENSION    = 0.45
# v0.95: 寄せ速度はリール係数 (retrieve_speed_mps) から導出する。
# 固定の FIGHT_REEL_GAIN_BASE / PULL_MULT は廃止。
# 基準 = retrieve_speed_mps を「セル/フレーム」換算した値 (fight は META_PER_CELL)。
# 疲労した魚ほど寄せ効率が上がる: 元気(sr=1)で約0.9倍、バテ(sr=0)で約1.4倍。
#   sr=1: 0.45m/s × 0.9 ≒ 0.40 m/s / sr=0: 0.45 × 1.4 ≒ 0.63 m/s (目安0.35〜0.60)
FIGHT_REEL_FATIGUE_BONUS = 0.5   # 疲労による寄せ効率の上乗せ (最大 +50%)
FIGHT_REEL_GAIN_FLOOR    = 0.004 # 寄せ速度の下限 (セル/f)。走られても最低限は寄る
FIGHT_RUN_SPEED_BASE   = 0.035   # 魚が走る最高速度
FIGHT_SPOOL_LIMIT_M    = 45.0    # これ以上走られるとスプール限界
# フッキング時の初期 line_length_m = (PLAYER_Y - lure.y) セル × これ。
# 魚が掛かった地点までのライン放出量。大きいほど寄せに時間がかかる
FIGHT_METERS_PER_CELL  = 0.80
FIGHT_START_LEN_MIN    = 2.0     # 初期ライン長の下限 (m)
FIGHT_START_LEN_MAX    = 26.0    # 初期ライン長の上限 (m)
# 描画用: この距離(m)以上のラインは画面上で水平線付近に張り付く。
# screen Y はこのレンジで補間し、line_length_m 管理とは分離する。
FIGHT_VISUAL_RANGE_M   = 14.0

# ── 行動発生率 (やりとり感の核) ──────────────────────────────────────
# v0.95 ファイト調整: 沖へ走る/潜る頻度を上げて「やりとりしている感」を強める。
# run_p = FIGHT_RUN_P_BASE × stamina_ratio × run_power(サイズ別)。
# → 大型・高スタミナほど頻繁に走り、バテると走らなくなる。
# 「走りすぎ」と感じたら BASE を下げる。
FIGHT_RUN_P_BASE  = 0.60   # RUN 基礎発生率 (旧 0.45)
FIGHT_DIVE_P_BASE = 0.28   # DIVE 基礎発生率 (旧 0.20)。run_power でサイズ補正

# ── 逆方向ロッド操作による制御 (control_success) ─────────────────────
# 魚の進行方向と逆へロッドを倒す/沖走りを↓で止めると「制御成功」。
#   ・fish_stamina が余分に減る (魚を疲れさせる)
#   ・沖方向へのライン放出が抑制される (伸びが止まる手応え)
# 逆に同方向へ倒す (間違い) と沖へのラインが伸びやすくなる。
FIGHT_CONTROL_STAMINA_DRAIN   = 0.08   # 制御成功中の stamina 減 (/frame)
FIGHT_CONTROL_OFFSHORE_SCALE  = 0.6    # 沖走りを↓で止めた時の drain 倍率
FIGHT_CONTROL_OUTWARD_SUPPRESS = 0.35  # 制御成功中の沖移動量の倍率 (<1 で抑制)
FIGHT_WRONG_DIR_OUTWARD_MULT  = 1.5    # 同方向(間違い)に倒した時の沖移動倍率

# ── 生物感 (慣性) ────────────────────────────────────────────────────
# 距離変化は速度モデル: 目標速度へ毎フレームこの割合で加速する。
# 小さいほど「重い」動き出し。1.0 = 旧仕様 (即座に速度が変わる)
FIGHT_DIST_ACCEL = 0.06
# 頭の向きの旋回速度 (目標向きへの追従率/フレーム)。魚体の回頭の重さ
FIGHT_HEAD_TURN_RATE = 0.06
# 首振り (SHAKE) の発生率。多すぎると不自然
FIGHT_SHAKE_P = 0.08
# 横移動: 魚は head_dir の向きへこの速度で泳ぐ (m/f)。描画位置はこの積分
FIGHT_LATERAL_RUN_SPEED = 0.045
FIGHT_LATERAL_MAX       = 7.0    # 横移動の範囲 (m)。超えると自然に反転

# ── 沖方向への逃げ (line_length_m 増加) ──────────────────────────────
# DIVE 中は沖+下方向へ突っ込み、ライン放出量が増える (m/f)。
FIGHT_DIVE_OUTWARD = 0.022
# 巻いていない間、魚は常にじわっとラインを出す (m/f)。
# テンションが高いほど抑えられる (張れば止められる)。run_power でサイズ補正。
# 「巻かないと沖へ逃げる」感覚の核。0 にすると HOLD 中は距離が動かない。
FIGHT_IDLE_DRIFT = 0.006

# ── ランディング ─────────────────────────────────────────────────────
FIGHT_LANDING_DIST_M   = 1.5
FIGHT_LANDING_FRAMES   = 50      # ↓長押し必要フレーム (0.83s)
# ラストダッシュ発生確率 = stamina_ratio × これ。
# 元気な魚 (sr 高) ほど最後の突っ込みが起きやすく、バテた魚ほど素直に獲れる。
# → fish_stamina が低いほどランディング成功率が上がる設計。
FIGHT_FINAL_DASH_P_SCALE = 0.92
FIGHT_FINAL_DASH_MIN_STAMINA = 0.12   # これ未満では突っ込まない (バテた魚は素直)
FIGHT_FINAL_DASH_DIST  = (3.0, 5.0)   # 突っ込みで離れる距離 (m)
FIGHT_FINAL_DASH_MIN_SIZE = 45.0      # このサイズ未満はラストダッシュなし

# ── サイズ別AI: (run_power, turn_freq, run_len_range) ────────────────
# 50UPの緊張感はここ。run_power↑=引きが強い, turn_freq↑=向きが読みにくい,
# run_len↑=1回のランが長い(沖まで走る)。run_power は RUN/DIVE 発生率にも乗る。
# v0.95 ファイト設計の目標ファイト時間 (最適操作時):
#   〜33cm: 10〜20s / 34〜39: 20〜40s / 40〜49: 40〜80s
#   50〜59: 90〜140s (複数回走る) / 60UP: 180〜300s (長距離ランを複数回)
FIGHT_SIZE_AI = [
    # (size_min, run_power, turn_freq, run_len)
    (65.0, 1.80, 0.18, (120, 200)),  # 別格: 長距離ランを複数回
    (60.0, 1.55, 0.16, ( 90, 150)),  # 長距離ラン + 方向転換多め
    (50.0, 1.30, 0.12, ( 60, 110)),  # 複数回の沖走り (ダッシュ)
    (40.0, 1.05, 0.09, ( 40,  75)),  # やりとりが必要 (沖へ逃げる)
    (35.0, 0.88, 0.07, ( 28,  55)),  # 少し抵抗する
    (0.0,  0.48, 0.035,( 14,  30)),  # 小物: ほぼ巻くだけで寄る
]

# このサイズ未満の魚はカバー突進をしない
FIGHT_COVER_MIN_SIZE = 40.0

# レジェンド特殊行動 (停止→急反転→ダッシュ) の発生率
FIGHT_LEGEND_FEINT_P = 0.25

# ── 障害物 (IN COVER) ────────────────────────────────────────────────
# 「バラシが理不尽」の最大要因だった箇所。
# 潜られたら hook_hold が減るが、逆方向ステアで素早く脱出できる。
# ステアしなくても魚は自力で出てくる (時間と hook_hold は失う)。
FIGHT_COVER_TARGET_P      = 0.30    # 高スタミナRUN開始時に障害物へ向かう率
FIGHT_COVER_LOCK_P        = 0.008   # RUN中の潜り込み判定/フレーム
FIGHT_COVER_HOLD_DECAY    = 0.06    # 潜られ中の hook_hold 減 (0.06 → 75が約21秒)
FIGHT_COVER_ESCAPE_P      = 0.05    # 逆方向ステア中の脱出率/フレーム (平均0.33秒)
FIGHT_COVER_SELF_ESCAPE_P = 0.004   # 放置でも自力脱出/フレーム (平均約4秒)

# ════════════════════════════════════════════════════════════════════
# [DEBUG] F4 大型魚テストモード
# ════════════════════════════════════════════════════════════════════

# F4 ON時、釣りビュー開始時に追加スポーンするテスト魚 (サイズ, activity)
# fish_id なし = 個体管理外なので population を汚さない
TEST_BIG_FISH = [
    (52.0, 0.95),
    (58.0, 0.95),
    (64.0, 0.90),
]
