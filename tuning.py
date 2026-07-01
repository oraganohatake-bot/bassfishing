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
REEL_FAST_MULT    = 1.7   # 早巻き速度倍率 (v0.96: 1.5→1.7。早巻きも少しテンポUP)
REEL_CREEP_MULT   = 0.40  # チョイ巻き速度倍率 (v0.96: ワーム/ジグのスロー操作を維持)

# ── リール性能 (ReelSpec) ────────────────────────────────────────────
# v0.95: 巻き速度を「直接固定値」ではなくリール係数から導出する。
# 将来の装備システムでリール性能差を入れるための土台。今は Beginner 固定。
#   retrieve_speed_mps : 釣り中の通常リトリーブ基準速度 (m/秒)
#   fight_reel_base_mps: ファイト中の基準巻き取り速度 (m/秒)。サイズ係数で増減
#   drag_power         : 高テンション時に耐えられる力 (0..1, 大=強い)
#   line_control       : テンション変化の安定性 (0..1, 大=安定)
# v0.96: リトリーブとファイトの巻き速度を分離。リトリーブはテンポよく、
# ファイトは fight_reel_base_mps × サイズ係数 (FIGHT_SIZE_AI) でやり取りを変える。
class ReelSpec:
    """リール1個分の性能。装備システム未実装のため Beginner を既定値に使う。"""

    def __init__(self, name, retrieve_speed_mps, fight_reel_base_mps,
                 drag_power, line_control):
        self.name = name
        self.retrieve_speed_mps = retrieve_speed_mps
        self.fight_reel_base_mps = fight_reel_base_mps
        self.drag_power = drag_power
        self.line_control = line_control


# 序盤リールは弱い前提。現実の早巻きでも序盤タックルは1秒0.5m程度。
BEGINNER_REEL = ReelSpec(
    name="Beginner Reel",
    retrieve_speed_mps=0.65,        # v0.96: 0.45→0.65 (約1.45倍)。ただ巻きをテンポUP
    fight_reel_base_mps=0.45,       # ファイト基準。サイズ係数で小物=速/大物=遅
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
# v0.96: 0.65 m/s → 約0.0217 セル/f。32セル ≒ 25秒で寄る (旧0.45の約1.45倍)。
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

# ── ロッド描画の向き (ライン方向基準) ──────────────────────────────
# v0.96: ロッドの傾きを画面固定ではなく「バット→ルアー/魚 (line_vec)」基準で作る。
# 真上(立てた状態)からルアー方向への倒れ込み量を lean とし、↑/↓ で前後させる。
ROD_LINE_NEUTRAL_LEAN = 0.32   # 中立時にルアー側へ寄せる割合 (0=真上, 1=ライン方向)
ROD_LINE_INPUT_LEAN   = 0.55   # ↑(倒す)/↓(立てる) で lean を増減させる量
ROD_LINE_STEER_DEG    = 16.0   # ←→ でライン基準に左右へいなす角度 (度)

# v0.96 ファイト時のロッド荷重: テンションが抜けても竿先が魚方向へ引かれたまま
# になるよう曲げの下限を与える (= 魚に引っ張られている見た目)。↓で竿を立てても
# ティップはこの分だけ魚側へ入る。大物ほど深く入る (fishing_view 側で size 加算)。
# 0 にすると従来どおりテンション依存のみ (↑でまっすぐに戻ってしまう)。
ROD_FIGHT_BEND_FLOOR  = 0.42

# ── 足場移動 (キャスト前のみ) / キャストカーソル ────────────────────
# Exploration v2: 釣りビューを横1.5xに拡張。岸の端まで立てるよう可動域を広げ、
# 移動距離が増えたぶん歩行速度も少し上げて移動を快適にした。
STANCE_MOVE_SPEED = 0.003   # ←→/A・D で動く player_stance_x の速度 (/frame)
STANCE_MIN        = 0.05    # 足場移動の左端 (岸の端近くまで)
STANCE_MAX        = 0.95    # 足場移動の右端 (岸の端近くまで)
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

# ── Beta v0.96: ライン長 / スラック / エフェクティブテンション ────────
# line_out_m       = 実際に出ているライン長 (m) = (PLAYER_Y - lure.y) × これ
# slack_m          = ラインスラック量 (= Lure.slack)
# effective_tension = max(0, line_out_m - slack_m)  張っているライン量
# リール=回収担当 (まずスラックを取り、その後 line_out_m を縮める)。
# ロッド=操作担当 (アクション/いなし/テンション調整; line_out_m は動かさない)。
LINE_METERS_PER_CELL   = 0.80   # y距離→ライン長(m)換算 (FIGHT_METERS_PER_CELL と一致)

# ── ルアー種別ごとの適正スラックレンジ → バイト/フッキング品質 ────────
# 適正レンジ内=最良、NEAR_TOL以内のずれ=やや低下、大きく外れる=大幅低下。
# hard_bait はテンション維持(低スラック)が有利、soft/bottom はフォール(高スラック)が有利。
SLACK_NEAR_TOL     = 0.30   # 適正レンジからこの距離(m)までは "やや外れ"
SLACK_BITE_OPTIMAL = 1.00   # 適正レンジ内のバイト/フック倍率
SLACK_BITE_NEAR    = 0.70   # 少し外れたとき
SLACK_BITE_FAR     = 0.30   # 大きく外れたとき

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

# ── Hooking v1: ワーム系 WEIGHT → LINE_RUN ──────────────────────────
# ワーム/ジグはバイト後に「重みが乗る(WEIGHT)」→「ラインが走る(LINE_RUN)」工程を
# 通す。WEIGHT→LINE_RUN への切替は経過フレームで判定 (= 魚が走り出すタイミング)。
WORM_WEIGHT_TO_RUN   = 28      # この経過fで重みが乗りきり魚が走り出す (≒DELAY_GOOD1_END)
WORM_LINE_RUN_SPEED  = 0.10    # LINE_RUN中に魚+ルアーが走る速度 (セル/f)

# ── Hooking v1: RUN_START — フッキング直後の最初の突っ走り ───────────
# フック成立 → ファイト開始の瞬間に、サイズ別で line_out_m を一気に増やす。
# (size下限, (最小m, 最大m)) を上から評価。
RUN_START_LINE_OUT = [
    (60.0, (6.0, 10.0)),   # 60UP: 一気に6〜10m持っていかれる
    (50.0, (4.0,  7.0)),   # 50cm台
    (40.0, (2.0,  4.0)),   # 40cm台
    (30.0, (1.0,  2.0)),   # 30cm台
    (0.0,  (0.5,  1.5)),   # それ未満
]
RUN_START_BURST_FRAMES = 24    # 突っ走り演出 (B_RUN固定) を維持するフレーム数

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
# Beta v0.96: フッキング瞬間のスラック適合度が hook_hold に乗る (テンション伝達)。
# 適正スラックで掛ければ満点、外れるほど保持率が落ちる = 魚を止めにくい。
FIGHT_SLACK_HOOKHOLD_FLOOR   = 0.60   # 最悪スラック時でも残る hook_hold 倍率
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
# v0.96: 寄せ速度は fight_reel_base_mps × サイズ係数 (reel_mult) から導出する。
# 固定の FIGHT_REEL_GAIN_BASE / PULL_MULT は廃止。
# 基準 = fight_reel_base_mps を「セル/フレーム」換算 (fight は META_PER_CELL)。
# 疲労した魚ほど寄せ効率が上がる: 元気(sr=1)で約0.9倍、バテ(sr=0)で約1.4倍。
# その上に reel_mult (小物1.3 / 50UP 0.45 / 60UP 0.22) が乗る。
FIGHT_REEL_FATIGUE_BONUS = 0.5   # 疲労による寄せ効率の上乗せ (最大 +50%)
FIGHT_REEL_GAIN_FLOOR    = 0.0010 # 寄せ速度の下限 (セル/f)。走られても最低限は寄る
                                  # (v0.96: 0.004→0.001。大物の重さをサイズ係数で出す)
FIGHT_RUN_SPEED_BASE   = 0.045   # 魚が走る最高速度 (v0.96: 0.035→0.045。沖走りを強調)
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
# v0.96 ファイト調整: 沖へ走る/潜る/向き変えの頻度を上げて「やりとりしている感」
# を強める。run_p = FIGHT_RUN_P_BASE × stamina_ratio × run_power(サイズ別)。
# → 大型・高スタミナほど頻繁に走り、バテると走らなくなる。turn_freq(サイズ別)
#   も上げ、左右への動きを画面上で分かりやすくした。
# 「走りすぎ」と感じたら BASE を下げる。
FIGHT_RUN_P_BASE  = 0.66   # RUN 基礎発生率 (v0.96: 0.60→0.66)
FIGHT_DIVE_P_BASE = 0.30   # DIVE 基礎発生率 (v0.96: 0.28→0.30)。run_power でサイズ補正

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
# 横移動: 魚は head_dir の向きへこの速度で泳ぐ (m/f)。描画位置はこの積分。
# run_power(サイズ別)が乗るため、小物は控えめ・大物ほど大きく左右に走る。
# v0.96: 0.045→0.075。ファイト中の左右の動きを画面上で明確にした。
FIGHT_LATERAL_RUN_SPEED = 0.075
FIGHT_LATERAL_MAX       = 7.0    # 横移動の範囲 (m)。超えると自然に反転

# ── 沖方向への逃げ (line_length_m 増加) ──────────────────────────────
# DIVE 中は沖+下方向へ突っ込み、ライン放出量が増える (m/f)。
# v0.96: 0.022→0.030。沖走りで line_out_m がはっきり増えるようにした。
FIGHT_DIVE_OUTWARD = 0.030
# 巻いていない間、魚は常にじわっとラインを出す (m/f)。
# テンションが高いほど抑えられる (張れば止められる)。run_power でサイズ補正。
# 「巻かないと沖へ逃げる」感覚の核。0 にすると HOLD 中は距離が動かない。
# v0.96: 0.006→0.008。巻きを止めると沖へ逃げる手応えを強めた。
FIGHT_IDLE_DRIFT = 0.008

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

# ── ポンピング (v0.96) ───────────────────────────────────────────────
# 「竿を立てて溜める → 送りながら巻く」で通常巻きより速くラインを回収する操作。
#   ↓長押し  : 竿を立てて pump_charge を溜める。テンション上昇・高負荷
#              (スタミナ消費、RED中は line_stress / hook_hold にペナルティ)。
#   ↑ + REEL : 竿を送りつつ巻くと pump_charge を消費して一気に寄せる。
# ↓だけ・↑だけでは寄らない (REED併用が必須)。小物は通常巻きで十分なため
# pump_charge の溜まりが小さく、大物ほど効く (charge gain が run_power 比例)。
FIGHT_PUMP_LIFT_FRAMES   = 14     # ↓をこの長さ立て続けると charge が溜まり始める
FIGHT_PUMP_POWER         = 0.012  # 立てている間の charge 蓄積 (/frame, run_power比例)
FIGHT_PUMP_CHARGE_MAX    = 1.0    # charge の上限 (溜めすぎ防止)
FIGHT_PUMP_SPEND_RATE    = 0.06   # ↑+REEL 中に消費する charge (/frame)
FIGHT_PUMP_REEL_BONUS    = 0.26   # charge → 追加寄せ速度 (セル/f) への変換係数
FIGHT_PUMP_COOLDOWN      = 24     # charge を使い切った後の再溜めまでの待ち (frame)
FIGHT_PUMP_STAMINA_COST  = 0.10   # 立てている間の追加スタミナ消費 (/frame)
FIGHT_PUMP_RED_STRESS    = 1.6    # RED中に無理に立てた時の line_stress 上乗せ (/frame)
FIGHT_PUMP_RED_HOLD_DECAY = 0.08  # RED中に無理に立てた時の hook_hold 減 (/frame)

# ── サイズ別AI: (run_power, turn_freq, run_len_range, reel_mult) ──────
# 50UPの緊張感はここ。run_power↑=引きが強い, turn_freq↑=向きが読みにくい,
# run_len↑=1回のランが長い(沖まで走る)。run_power は RUN/DIVE 発生率にも乗る。
# v0.96: reel_mult = ファイト中の巻き取り効率倍率。小物ほど大 (巻くだけで速く
#   寄る)、大物ほど小 (強リールでも簡単には寄らない)。fight_reel_base_mps に乗る。
# v0.96 movement調整: turn_freq と run_len を引き上げ、左右/沖への動きを強化。
#   run_power / reel_mult は据え置き (目標ファイト時間を崩さない)。
#   サイズ別の体感:
#     〜33cm: ほぼ巻ける (run_power低・turn少)
#     34〜39: 少し左右に走る   / 40〜49: 明確に走る
#     50UP : 複数回沖へ走る    / 60UP : 急反転・沖走り・障害物へ突っ込み
# v0.96 ファイト設計の目標ファイト時間 (最適操作時):
#   〜33cm: 10〜20s / 34〜39: 20〜40s / 40〜49: 40〜80s
#   50〜59: 90〜140s (巻いても重い) / 60UP: 180〜300s (かなり重い)
FIGHT_SIZE_AI = [
    # (size_min, run_power, turn_freq, run_len, reel_mult)
    (65.0, 1.80, 0.26, (130, 210), 0.16),  # 別格: 急反転+長い沖走りを繰り返す
    (60.0, 1.55, 0.22, (100, 165), 0.20),  # かなり重い・複数回沖へ
    (50.0, 1.30, 0.17, ( 70, 125), 0.38),  # 50UP: 複数回走られる
    (40.0, 1.05, 0.13, ( 45,  85), 0.65),  # 40台: 明確に走る
    (35.0, 0.88, 0.09, ( 30,  58), 0.85),  # 30後半: 少し左右に走る
    (0.0,  0.46, 0.045,( 14,  30), 1.55),  # 小物: ほぼ巻ける
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
