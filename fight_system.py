"""FightSystem – Beta v0.9: tension-managed fight (fight_system_design_v001.md).

ファイトは「魚のHPを削るゲーム」ではない。
2つの内部値で成立する:

  hook_hold    : フッキングの質。0以下でフックアウト。
  fish_stamina : 魚の体力 (プレイヤーには非表示)。

テンションゾーン:
  BLUE  (<0.25)      : hook_hold 減少。緩めすぎるとフックアウト。
  GREEN (0.25-0.55)  : 理想状態。hook_hold 維持。
  YELLOW(0.55-0.80)  : fish_stamina 減少。
  RED   (>0.80)      : fish_stamina 大幅減少。ラインブレイク / フックアウト危険。

操作:
  ↓ (rod_y=+1) : テンション増加 / 魚を浮かせる / ランディング / 沖走りを止める
  ↑ (rod_y=-1) : テンション減少 / 魚を走らせる
  ← →(rod_x)   : 魚の頭の向きを制御 (進行方向と逆へ倒すと制御しやすい)
  リール       : 距離を詰める (REDで巻くと危険)

逆方向ロッド操作 (control_success):
  魚の進行方向 (head_dir) と逆へロッドを倒す、または沖走り/潜りを↓で止めると
  「制御成功」。fish_stamina が余分に減り、沖へのライン放出が抑制される
  (= 伸びが止まる手応え)。同方向 (間違い) に倒すと沖へ走られやすくなる。

サイズ別ファイト設計 (tuning.FIGHT_SIZE_AI / FIGHT_STAMINA_PER_CM):
  〜33cm はほぼ巻くだけ、40UP は沖へ逃げ、50UP は複数回走り、60UP は
  長距離ランを繰り返す別格。max_stamina = size × run_power × PER_CM で
  大型ほど非線形に持久力が増し、ファイトが長期化する。
  fish_stamina が下がると RUN/DIVE/向き変更の頻度・移動速度が落ち、
  ライン放出も弱まり、リールで寄せやすくなる。

ランディング: 距離1.5m以内 + ↓長押し。元気な魚 (stamina 高) ほど最後の
  突っ込みが起きやすく、バテた魚ほど成功しやすい。
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

from constants import HOOK_QUALITY_HOLD, UW_SIZE
import tuning as TU

# ── テンションゾーン境界 (tuning.py から; 他モジュールが参照する別名) ──
T_BLUE   = TU.FIGHT_T_BLUE
T_GREEN  = TU.FIGHT_T_GREEN
T_YELLOW = TU.FIGHT_T_YELLOW

# ── ランディング ──────────────────────────────────────────────────────
LANDING_DIST_M   = TU.FIGHT_LANDING_DIST_M
LANDING_FRAMES   = TU.FIGHT_LANDING_FRAMES

# ── 結果 ──────────────────────────────────────────────────────────────
OUTCOME_LANDED     = "LANDED"
OUTCOME_HOOKOUT    = "HOOKOUT"
OUTCOME_LINE_BREAK = "LINE_BREAK"

# ── 魚の行動 ──────────────────────────────────────────────────────────
B_HOLD  = "HOLD"
B_RUN   = "RUN"
B_DIVE  = "DIVE"
B_SHAKE = "SHAKE"
B_TURN  = "TURN"


class FightState:
    """1回のファイトの全状態。FishingView が FS_FIGHT 中に毎フレーム update する。"""

    def __init__(
        self,
        fish_size: float,
        hook_quality: str,
        anchor_cell: Tuple[float, float],
        start_cell: Tuple[float, float],
        meters_per_cell: float = TU.FIGHT_METERS_PER_CELL,
        legend: bool = False,
        rng: Optional[random.Random] = None,
    ) -> None:
        self._rng = rng or random.Random()
        self.fish_size = fish_size
        self.legend = legend

        self.hook_quality = hook_quality
        self.hook_hold: float = HOOK_QUALITY_HOLD.get(hook_quality, 55.0)
        self._hook_hold_max = self.hook_hold

        # サイズ別AIパラメータ (tuning.FIGHT_SIZE_AI から検索)。
        # max_stamina 計算で run_power を使うため、先に確定させる。
        for size_min, run_power, turn_freq, run_len in TU.FIGHT_SIZE_AI:
            if fish_size >= size_min:
                self._run_power = run_power
                self._turn_freq = turn_freq
                self._run_len   = run_len
                break

        # スタミナ: サイズ × run_power に比例。run_power がサイズ階層を兼ねるため、
        # 大型ほど非線形にスタミナが増え、ファイトが長期化する。
        # (50cm→1.30倍, 64cm→1.80倍 → 60UP は別格の持久力)
        self.max_stamina: float = (
            fish_size * TU.FIGHT_STAMINA_PER_CM * self._run_power)
        self.stamina: float = self.max_stamina

        # ── 2D 位置モデル (v0.95) ────────────────────────────────────
        # プレイヤーの立ち位置 (足場) を水中グリッド上の基準点として持つ。
        # 魚はグリッド座標 (fish_x, fish_y) で動き、line_length_m は
        # 魚 → アンカーの 2D 斜距離 × meters_per_cell で常に再計算される。
        # → 横に大きく走れば同じ Y でもライン長が伸びる。リールはアンカー方向へ寄せる。
        self.meters_per_cell = meters_per_cell
        self.anchor_x: float = anchor_cell[0]
        self.anchor_y: float = anchor_cell[1]
        self.fish_x: float = start_cell[0]
        self.fish_y: float = start_cell[1]

        self.tension: float = TU.FIGHT_START_TENSION

        # 頭の向き: -1.0(左) 〜 +1.0(右)。ライン角度でプレイヤーへ伝える
        # head_dir は描画/判定用の現在値。_head_target へ旋回速度分だけ追従する
        # (魚体の回頭には時間がかかる)
        self.head_dir: float = self._rng.choice([-1.0, 1.0]) * self._rng.uniform(0.4, 1.0)
        self._head_target: float = self.head_dir

        # 移動速度 (セル/f)。急加速できない慣性モデル
        self._vx: float = 0.0
        self._vy: float = 0.0

        # 行動AI
        self.behavior: str = B_HOLD
        self._behavior_timer: int = 30

        # 逆方向ロッド操作の制御状態 (毎フレーム _update_steering で更新)
        # control_success: 進行方向と逆へ倒せている (= 魚を疲れさせている)
        # wrong_dir      : 同方向へ倒している (= 沖へ走られやすい)
        self.control_success: bool = False
        self.wrong_dir: bool = False

        # ライン負荷 (REDゾーン継続でラインブレイク)
        self._line_stress: float = 0.0

        # 障害物
        self.obstacle_lock: bool = False   # 潜り込まれている
        self._obstacle_dir: float = 0.0    # 障害物の方向 (head_dir と同符号)

        # ランディング
        self.landing_progress: int = 0
        self._final_dash_done: bool = False

        self.outcome: Optional[str] = None
        self.events: List[str] = []        # UI フラッシュ用 (毎フレーム消費)
        self.frame: int = 0

    # ── プロパティ ────────────────────────────────────────────────────

    @property
    def stamina_ratio(self) -> float:
        return max(0.0, self.stamina / self.max_stamina)

    @property
    def line_length_m(self) -> float:
        """放出中のライン長 (m) = 魚 → プレイヤー立ち位置(アンカー)の 2D 斜距離。

        画面Yだけでは決まらない: 横に大きく走られると同じ Y でもライン長が伸びる。
        ランディング/スプールの唯一の基準。
        """
        dx = self.fish_x - self.anchor_x
        dy = self.fish_y - self.anchor_y
        return math.hypot(dx, dy) * self.meters_per_cell

    @property
    def distance(self) -> float:
        """line_length_m の別名 (後方互換)。"""
        return self.line_length_m

    @property
    def line_stress_ratio(self) -> float:
        """ラインブレイクまでの負荷 0.0〜1.0 (UI警告用)。"""
        return min(1.0, self._line_stress / TU.FIGHT_LINE_BREAK_STRESS)

    @property
    def zone(self) -> str:
        if self.tension < T_BLUE:
            return "BLUE"
        if self.tension < T_GREEN:
            return "GREEN"
        if self.tension < T_YELLOW:
            return "YELLOW"
        return "RED"

    @property
    def done(self) -> bool:
        return self.outcome is not None

    # ── メイン更新 ────────────────────────────────────────────────────

    def update(self, reel: bool, rod_y: float, rod_x: float) -> None:
        """毎フレーム呼び出す。
        reel  : リール巻き中か
        rod_y : +1=↓(立てる/テンション増)  -1=↑(下げる/抜く)  0=中立
        rod_x : -1=← +1=→ 0=中立
        """
        if self.done:
            return
        self.frame += 1

        self._update_behavior()
        self._update_steering(rod_x, rod_y)
        self._update_tension(reel, rod_y)
        self._update_zones(reel, rod_y)
        self._update_position(reel, rod_y)   # 2D 移動 (沖逃げ / 寄せ)
        self._update_obstacle(rod_x)
        self._update_landing(rod_y)
        self._check_outcome()

    # ── 行動AI ────────────────────────────────────────────────────────

    def _update_behavior(self) -> None:
        self._behavior_timer -= 1
        if self._behavior_timer > 0:
            return

        sr = self.stamina_ratio
        r = self._rng.random()

        if self.legend and r < TU.FIGHT_LEGEND_FEINT_P:
            # レジェンド級: 停止 → 急反転 → ダッシュ
            self.behavior = B_HOLD
            self._behavior_timer = self._rng.randint(20, 40)
            self._head_target = -self.head_dir
            self.events.append("!!")
            return

        # スタミナが低いほど HOLD 中心 (バテると走らない・向きも変えない)。
        # 沖へ走る/潜る頻度は run_power(サイズ)に比例 → 大型ほどよく走る。
        run_p   = TU.FIGHT_RUN_P_BASE * sr * self._run_power
        dive_p  = TU.FIGHT_DIVE_P_BASE * sr * (0.5 + 0.5 * self._run_power)
        shake_p = TU.FIGHT_SHAKE_P
        turn_p  = self._turn_freq * (0.4 + 0.6 * sr)

        if r < run_p:
            self.behavior = B_RUN
            self._behavior_timer = self._rng.randint(*self._run_len)
            if abs(self.head_dir) < 0.3:
                self._head_target = (
                    self._rng.choice([-1.0, 1.0]) * self._rng.uniform(0.5, 1.0))
        elif r < run_p + dive_p:
            self.behavior = B_DIVE
            self._behavior_timer = self._rng.randint(40, 80)
        elif r < run_p + dive_p + shake_p:
            self.behavior = B_SHAKE
            self._behavior_timer = self._rng.randint(25, 50)
        elif r < run_p + dive_p + shake_p + turn_p:
            self.behavior = B_TURN
            self._behavior_timer = self._rng.randint(15, 30)
            self._head_target = -self.head_dir
        else:
            self.behavior = B_HOLD
            self._behavior_timer = self._rng.randint(30, 70)

        # 高スタミナのRUN開始時、障害物へ向かうことがある (中型以上のみ)
        if (self.behavior == B_RUN and sr > 0.45
                and self.fish_size >= TU.FIGHT_COVER_MIN_SIZE
                and self._rng.random() < TU.FIGHT_COVER_TARGET_P):
            self._obstacle_dir = 1.0 if self.head_dir > 0 else -1.0
            self.events.append("OBSTACLE")

    # ── 操舵 (頭の向き制御) ───────────────────────────────────────────

    def _update_steering(self, rod_x: float, rod_y: float) -> None:
        """逆方向ロッド操作で魚を制御する。

        fish_move_dir (= head_dir の符号; ラインの走る向き) と
        rod_input_dir (rod_x) を比較し、逆向き (積 < 0) なら control_success。
        沖へ走る/潜る最中に ↓ (rod_y>0) で浮かせる・止めるのも制御成功扱い。
        control_success 中は余分に stamina が減り、沖へのライン放出が抑制される。
        間違った方向 (同符号) に倒すと wrong_dir = 沖へ走られやすくなる。
        """
        self.control_success = False
        self.wrong_dir = False

        # ── 横方向の制御 (左右ステア) ──
        if rod_x != 0.0:
            if rod_x * self.head_dir < 0:           # 逆方向 = 正解
                self.control_success = True
                self._head_target *= 0.975
                self.stamina -= TU.FIGHT_CONTROL_STAMINA_DRAIN
            else:                                    # 同方向 = 間違い
                self.wrong_dir = True
                self.tension = min(1.0, self.tension + 0.004)

        # ── 沖方向の制御 (沖走り/潜りを↓で止める) ──
        if rod_y > 0 and self.behavior in (B_RUN, B_DIVE):
            self.control_success = True
            self.stamina -= (TU.FIGHT_CONTROL_STAMINA_DRAIN
                             * TU.FIGHT_CONTROL_OFFSHORE_SCALE)

        # 回頭は瞬間ではなく旋回速度分だけ追従する (生物感)
        self.head_dir += (self._head_target - self.head_dir) * TU.FIGHT_HEAD_TURN_RATE

    # ── テンション ────────────────────────────────────────────────────

    def _update_tension(self, reel: bool, rod_y: float) -> None:
        # 魚の引きによる基礎テンション (行動依存)
        pull = {
            B_RUN:   0.62 + 0.18 * self.stamina_ratio * self._run_power,
            B_DIVE:  0.58 + 0.12 * self.stamina_ratio,
            B_SHAKE: 0.46,
            B_TURN:  0.40,
            B_HOLD:  0.34,
        }[self.behavior]

        target = pull
        if reel:
            target += 0.26 if self.behavior == B_RUN else 0.16
        if rod_y > 0:       # ↓ ロッドを立てる
            target += 0.15
        elif rod_y < 0:     # ↑ テンションを抜く
            target -= 0.30

        # SHAKE は振動ノイズ
        noise = 0.0
        if self.behavior == B_SHAKE:
            noise = self._rng.uniform(-0.06, 0.06)

        self.tension += (target - self.tension) * 0.10 + noise
        self.tension = max(0.0, min(1.0, self.tension))

    # ── ゾーン効果 ────────────────────────────────────────────────────

    def _update_zones(self, reel: bool, rod_y: float = 0.0) -> None:
        z = self.zone
        if z == "BLUE":
            # フックポイントが変動するのは「やり取りの最中」のみ。
            # 魚が動いていない (HOLD) なら放置でテンション最低でも外れない (UX)
            if self.behavior != B_HOLD:
                decay = (TU.FIGHT_BLUE_SEVERE_DECAY if self.tension < 0.08
                         else TU.FIGHT_BLUE_HOLD_DECAY)
                self.hook_hold -= decay
        elif z == "GREEN":
            self.hook_hold = min(self._hook_hold_max,
                                 self.hook_hold + TU.FIGHT_GREEN_HOLD_RECOVER)
            self.stamina -= TU.FIGHT_GREEN_STAMINA_DRAIN
        elif z == "YELLOW":
            self.stamina -= TU.FIGHT_YELLOW_STAMINA_DRAIN
        else:  # RED
            self.stamina -= TU.FIGHT_RED_STAMINA_DRAIN
            self.hook_hold -= TU.FIGHT_RED_HOLD_DECAY
            # 負荷が溜まるのはプレイヤーが張っている間 (巻く / ↓で立てる) のみ。
            # 気づいて入力を離せば REDのままでも負荷は抜けていく = 助かる設計
            if reel:
                self._line_stress += TU.FIGHT_RED_STRESS_REELING
            elif rod_y > 0:
                self._line_stress += TU.FIGHT_RED_STRESS_IDLE
            else:
                self._line_stress = max(
                    0.0, self._line_stress - TU.FIGHT_RED_STRESS_RELEASE_DECAY)
            if reel and self._rng.random() < TU.FIGHT_RED_REEL_HOOKOUT_P:
                self.outcome = OUTCOME_HOOKOUT
                self.events.append("HOOK OUT!")
                return

        if z != "RED":
            self._line_stress = max(0.0, self._line_stress - TU.FIGHT_STRESS_DECAY)

    # ── 2D 移動 (沖逃げ / 立ち位置方向への寄せ) ───────────────────────

    def _update_position(self, reel: bool, rod_y: float) -> None:
        """魚をグリッド上で動かす。line_length_m は位置から自動再計算される。

        基準ベクトル:
          off  = アンカー(立ち位置)→魚 の単位ベクトル (= 沖方向 / 離れる向き)
          -off = 魚→アンカー (= 寄せ方向 / リールで引く向き)
        head_dir は横成分 (グリッド x の左右) として速度に加わる。
        """
        ax, ay = self.anchor_x, self.anchor_y
        dx, dy = self.fish_x - ax, self.fish_y - ay
        d = math.hypot(dx, dy) or 1e-6
        off_x, off_y = dx / d, dy / d
        sr = self.stamina_ratio

        tvx = tvy = 0.0
        # 横揺れ (head_dir 由来) は別枠で集計し、リール中は減衰させる
        # → 「巻けば立ち位置方向へ寄る」を横走りに邪魔されないようにする
        lat = 0.0

        # 沖方向への移動倍率: 逆方向ロッド操作(制御成功)中は抑制、
        # 間違った方向に倒している間は伸びやすくする。
        if self.control_success:
            out_mult = TU.FIGHT_CONTROL_OUTWARD_SUPPRESS
        elif self.wrong_dir:
            out_mult = TU.FIGHT_WRONG_DIR_OUTWARD_MULT
        else:
            out_mult = 1.0

        # ── 行動による移動 (沖成分 off + 横成分 head_dir) ──
        if self.behavior == B_RUN:
            run = TU.FIGHT_RUN_SPEED_BASE * self._run_power * (0.4 + 0.6 * sr)
            if rod_y < 0:   # テンションを抜いて走らせると hook_hold に優しい
                run *= 1.25
            tvx += off_x * run * 0.5 * out_mult
            tvy += off_y * run * 0.5 * out_mult
            lat += self.head_dir * TU.FIGHT_LATERAL_RUN_SPEED * self._run_power
        elif self.behavior == B_DIVE:
            dive = TU.FIGHT_DIVE_OUTWARD * self._run_power * (0.4 + 0.6 * sr)
            tvx += off_x * dive * out_mult
            tvy += off_y * dive * 1.3 * out_mult   # 沖方向強め
        elif self.behavior == B_SHAKE:
            lat += self._rng.uniform(-1.0, 1.0) * 0.05   # 小刻み左右
        elif self.behavior == B_TURN:
            lat += self.head_dir * 0.06
        else:  # HOLD
            lat += self.head_dir * 0.02

        # ── 巻いていない間: 魚がじわっと沖へ (張れば抑制) ──
        if not reel and self.line_length_m > LANDING_DIST_M:
            brake = max(0.0, 1.0 - self.tension / T_YELLOW)
            drift = (TU.FIGHT_IDLE_DRIFT * self._run_power
                     * (0.3 + 0.7 * sr) * brake * out_mult)
            tvx += off_x * drift
            tvy += off_y * drift

        # ── リール: アンカー(立ち位置)方向へ寄せる ──
        if reel and self.tension < 0.92:
            # v0.95: 寄せ速度はリール係数 (retrieve_speed_mps) から導出。
            # m/s → セル/フレーム換算し、疲労した魚ほど効率を上げる。
            base = TU.EQUIPPED_REEL.retrieve_speed_mps / (self.meters_per_cell * 60.0)
            gain = base * (1.0 - 0.1 + (1.0 - sr) * TU.FIGHT_REEL_FATIGUE_BONUS)
            if self.behavior == B_RUN:
                gain *= 0.55   # 走られている間は寄せ効率が落ちる (が寄りはする)
            gain = max(TU.FIGHT_REEL_GAIN_FLOOR, gain)
            tvx -= off_x * gain
            tvy -= off_y * gain
            lat *= 0.25        # 巻いている間は横走りを抑えてアンカー方向へ収束させる

        tvx += lat

        # ── ↓で浮かせる(寄せ補助) ──
        if rod_y > 0 and self.behavior != B_RUN and self.zone in ("GREEN", "YELLOW"):
            tvx -= off_x * 0.006
            tvy -= off_y * 0.006

        # 慣性で速度追従 → 位置更新 → グリッドにクランプ
        self._vx += (tvx - self._vx) * TU.FIGHT_DIST_ACCEL
        self._vy += (tvy - self._vy) * TU.FIGHT_DIST_ACCEL
        self.fish_x = max(0.0, min(float(UW_SIZE - 1), self.fish_x + self._vx))
        self.fish_y = max(0.0, min(float(UW_SIZE - 1), self.fish_y + self._vy))

        # グリッド端まで泳いだら自然に向きを変える (横走りの反転)
        if self.fish_x <= 0.5 and self._head_target < 0:
            self._head_target = -self._head_target
        elif self.fish_x >= UW_SIZE - 1.5 and self._head_target > 0:
            self._head_target = -self._head_target

    # ── 障害物 ────────────────────────────────────────────────────────

    def _update_obstacle(self, rod_x: float) -> None:
        if self._obstacle_dir == 0.0:
            return
        if self.obstacle_lock:
            # 潜り込まれている: hook_hold が徐々に削れる
            self.hook_hold -= TU.FIGHT_COVER_HOLD_DECAY
            # 逆方向ロッド (テンション緩みすぎ以外) で素早く引き剥がせる。
            # 何もしなくても魚はいずれ自力で出てくる (時間とhook_holdを失う)。
            if rod_x * self._obstacle_dir < 0 and self.tension > T_BLUE:
                escape_p = TU.FIGHT_COVER_ESCAPE_P
            else:
                escape_p = TU.FIGHT_COVER_SELF_ESCAPE_P
            if self._rng.random() < escape_p:
                self.obstacle_lock = False
                self._obstacle_dir = 0.0
                self.events.append("ESCAPED COVER!")
        else:
            # RUN 継続中に障害物到達判定
            if self.behavior == B_RUN and self._rng.random() < TU.FIGHT_COVER_LOCK_P:
                self.obstacle_lock = True
                self.events.append("IN COVER!")
            elif self.behavior != B_RUN:
                self._obstacle_dir = 0.0  # RUNが終われば障害物は回避された

    # ── ランディング ──────────────────────────────────────────────────

    def _update_landing(self, rod_y: float) -> None:
        if self.distance > LANDING_DIST_M:
            self.landing_progress = max(0, self.landing_progress - 2)
            return

        if rod_y > 0:   # ↓長押し
            self.landing_progress += 1
            if self.landing_progress >= LANDING_FRAMES:
                # 最後の突っ込みチェック。元気な魚 (stamina 高) ほど突っ込み
                # やすく、バテた魚は素直に獲れる (= 低スタミナで成功率上昇)。
                if (not self._final_dash_done
                        and self.fish_size >= TU.FIGHT_FINAL_DASH_MIN_SIZE
                        and self.stamina_ratio > TU.FIGHT_FINAL_DASH_MIN_STAMINA
                        and self._rng.random()
                            < self.stamina_ratio * TU.FIGHT_FINAL_DASH_P_SCALE):
                    self._final_dash_done = True
                    self.landing_progress = 0
                    # 瞬間ワープではなく沖方向の速度として与える (滑らかに離れる)
                    dash = self._rng.uniform(*TU.FIGHT_FINAL_DASH_DIST)
                    dx, dy = self.fish_x - self.anchor_x, self.fish_y - self.anchor_y
                    d = math.hypot(dx, dy) or 1e-6
                    cells = dash / self.meters_per_cell
                    self._vx = (dx / d) * (cells / 40.0)
                    self._vy = (dy / d) * (cells / 40.0)
                    self.stamina -= self.max_stamina * 0.22
                    self.behavior = B_RUN
                    self._behavior_timer = self._rng.randint(40, 70)
                    self.events.append("LAST DASH!")
                else:
                    self.outcome = OUTCOME_LANDED
                    self.events.append("LANDED!")
        else:
            self.landing_progress = max(0, self.landing_progress - 1)

    # ── 結果判定 ──────────────────────────────────────────────────────

    def _check_outcome(self) -> None:
        if self.done:
            return
        if self.hook_hold <= 0:
            self.outcome = OUTCOME_HOOKOUT
            self.events.append("HOOK OUT!")
        elif self._line_stress >= TU.FIGHT_LINE_BREAK_STRESS:
            self.outcome = OUTCOME_LINE_BREAK
            self.events.append("LINE BREAK!")
        elif self.distance > TU.FIGHT_SPOOL_LIMIT_M:
            # スプール限界
            self.outcome = OUTCOME_LINE_BREAK
            self.events.append("SPOOLED!")

    # ── UIヘルパー ────────────────────────────────────────────────────

    def pop_events(self) -> List[str]:
        ev, self.events = self.events, []
        return ev
