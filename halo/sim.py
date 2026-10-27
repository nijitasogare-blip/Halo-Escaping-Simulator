"""太阳系二维化 / 星环号逃逸 —— 状态机与物理积分.

坐标: 太阳系静止系, 黄道面为 y=0, 长度 AU, 时间秒.
飞船以固定方向 u_escape 径向远离太阳, 速度 beta*c.
二维化波前: R(t) = WAVE_R0 + c * t, 以光速扩张.
二维化平面内部的"折叠顺序": 每个环带内沿希尔伯特曲线推进 (见 hilbert.py).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import config as C
from . import hilbert, relativity, viewmath


# --------------------------------------------------------------------------
# 小数据结构
# --------------------------------------------------------------------------
@dataclass
class Event:
    t_ext: float
    text: str
    kind: str = "info"  # info | warn | danger | escape | sad


@dataclass
class PlanetState:
    spec: C.PlanetSpec
    angle: float
    pos: np.ndarray
    tangent: np.ndarray
    alive: bool = True
    collapsing: bool = False
    anim: float = 0.0          # 0 -> 1 压扁动画
    squash: float = 1.0
    flash: float = 0.0
    reveal: float = 0.0
    painted: bool = False


@dataclass
class RefugeeState:
    spec: C.RefugeeSpec
    pos: np.ndarray
    vel: np.ndarray
    alive: bool = True
    collapsing: bool = False
    anim: float = 0.0
    squash: float = 1.0
    flash: float = 0.0
    reveal: float = 0.0
    trail: list[np.ndarray] = field(default_factory=list)


@dataclass
class Mark:
    """已折入二维平面的物体印记 (由 GPU 在平面上绘制)."""
    x: float
    z: float
    size: float
    reveal: float
    color: tuple[float, float, float]
    flash: float
    dir_x: float
    dir_z: float
    label: str


# --------------------------------------------------------------------------
# 状态快照 (渲染器 / HUD 读取)
# --------------------------------------------------------------------------
@dataclass
class SimFrame:
    # 时间
    t_ext: float
    t_proper: float
    t_real: float
    beta: float
    gamma: float
    # 二维化
    wave_r: float
    progress: float
    pen: tuple[float, float, float]
    time_scale: float
    # 飞船 / 相机
    ship_pos: np.ndarray
    escape_dir: np.ndarray
    fwd: np.ndarray
    right: np.ndarray
    up: np.ndarray
    cam_right: np.ndarray
    cam_up: np.ndarray
    cam_fwd: np.ndarray
    yaw: float
    pitch: float
    # 物体
    planet_pos: np.ndarray
    planet_radius: np.ndarray
    planet_squash: np.ndarray
    planet_flash: np.ndarray
    planet_alive: np.ndarray
    planet_color: np.ndarray
    marks: list[Mark]
    refugees: list[RefugeeState]
    dust_pos: np.ndarray
    dust_alive: np.ndarray
    dust_color: np.ndarray
    dust_size: np.ndarray
    spark_pos: np.ndarray
    spark_color: np.ndarray
    spark_size: np.ndarray
    # 状态
    events: list[Event]
    flattening: bool
    flatten_t: float
    escaped: bool
    boost: float
    # 派生观测值
    gap: float
    eta_ext: float
    eta_real: float
    dist_sun: float
    rear_doppler: float
    aberr_half_angle: float
    proper_rate: float
    speed_kms: float


# --------------------------------------------------------------------------
# 主模拟
# --------------------------------------------------------------------------
class Sim:
    def __init__(self, time_scale: float = C.TIME_SCALE_DEFAULT, beta0: float = C.SHIP_BETA0):
        self.time_scale = float(np.clip(time_scale, C.TIME_SCALE_MIN, C.TIME_SCALE_MAX))
        self.beta0 = float(beta0)
        self.reset()

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self.t_ext = 0.0
        self.t_proper = 0.0
        self.t_real = 0.0
        self.beta = self.beta0
        self.beta_target = self.beta0
        self.time_scale = float(np.clip(self.time_scale, C.TIME_SCALE_MIN, C.TIME_SCALE_MAX))
        self._boost_timer = 0.0
        self._escape_announced = False

        elev = math.radians(C.SHIP_ELEV_DEG)
        azim = math.radians(C.SHIP_AZIM_DEG)
        self.escape_dir = np.array([
            math.cos(elev) * math.cos(azim),
            math.sin(elev),
            math.cos(elev) * math.sin(azim),
        ], dtype=np.float64)
        self.escape_dir /= np.linalg.norm(self.escape_dir)
        self.ship_r = C.SHIP_R0
        self.ship_pos = self.escape_dir * self.ship_r

        self.fwd, self.right, self.up = viewmath.ship_frame(tuple(self.escape_dir))
        self.yaw = math.radians(180.0)
        self.pitch = math.radians(-2.0)
        self.yaw_target = self.yaw
        self.pitch_target = self.pitch
        self._rebuild_camera()

        self.wave_r = C.WAVE_R0
        self.progress = self.wave_r / C.ANNULUS_R_NORM
        self.flattening = False
        self.flatten_t = 0.0
        self.escaped = False
        self.events: list[Event] = []
        self.marks: list[Mark] = []
        self.planets: list[PlanetState] = []
        self.refugees: list[RefugeeState] = []

        self._init_planets()
        self._init_refugees()
        self._init_dust()
        self._init_sparks()
        self._init_events()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _init_planets(self) -> None:
        for spec in C.PLANETS:
            ang = math.radians(spec.angle0_deg)
            pos = self._planet_pos(spec, ang)
            tangent = np.array([-math.sin(ang), 0.0, math.cos(ang)], dtype=np.float64)
            tangent /= np.linalg.norm(tangent)
            p = PlanetState(spec=spec, angle=ang, pos=pos, tangent=tangent)
            rev = hilbert.reveal_scalar(float(pos[0]), float(pos[2]))
            p.reveal = rev
            if rev <= self.progress:
                # 开局前就被二维化: 直接生成平面印记
                p.alive = False
                p.painted = True
                self.marks.append(Mark(
                    x=float(pos[0]), z=float(pos[2]),
                    size=spec.painted_radius * 1.15,
                    reveal=rev,
                    color=tuple(0.75 * np.array(spec.color) + 0.25 * np.array([0.8, 0.95, 1.0])),
                    flash=0.0,
                    dir_x=float(tangent[0]), dir_z=float(tangent[2]),
                    label=spec.name_zh,
                ))
            self.planets.append(p)

    def _planet_pos(self, spec: C.PlanetSpec, ang: float) -> np.ndarray:
        inc = math.radians(spec.incline_deg)
        return np.array([
            spec.a_au * math.cos(ang),
            spec.a_au * math.sin(inc) * math.sin(ang),
            spec.a_au * math.sin(ang),
        ], dtype=np.float64)

    def _init_refugees(self) -> None:
        for spec in C.REFUGEES:
            az = math.radians(spec.azim_deg)
            el = math.radians(spec.elev_deg)
            direction = np.array([
                math.cos(el) * math.cos(az),
                math.sin(el),
                math.cos(el) * math.sin(az),
            ])
            direction /= np.linalg.norm(direction)
            pos = direction * spec.r0
            # 轻微切向分量, 使尾迹弯曲
            tangent = np.cross(np.array([0.0, 1.0, 0.0]), direction)
            if np.linalg.norm(tangent) < 1e-6:
                tangent = np.array([1.0, 0.0, 0.0])
            tangent /= np.linalg.norm(tangent)
            vel = (direction + 0.10 * tangent) * spec.speed_c * C.C_AU_S
            st = RefugeeState(spec=spec, pos=pos, vel=vel)
            rev = hilbert.reveal_scalar(float(pos[0]), float(pos[2]))
            st.reveal = rev
            st.trail = [pos.copy() for _ in range(C.TRAIL_LEN)]
            if rev <= self.progress:
                st.alive = False
                self.marks.append(Mark(
                    x=float(pos[0]), z=float(pos[2]), size=0.22, reveal=rev,
                    color=tuple(0.6 * np.array(spec.color) + 0.4 * np.array([1.0, 0.85, 0.7])),
                    flash=0.0, dir_x=float(tangent[0]), dir_z=float(tangent[2]),
                    label=spec.name_zh,
                ))
            self.refugees.append(st)

    def _init_dust(self) -> None:
        rng = np.random.default_rng(90210)
        n = C.DUST_COUNT
        rr = 1.2 + 26.0 * rng.random(n) ** 0.85
        th = rng.uniform(0.0, 2.0 * math.pi, n)
        hh = rng.normal(0.0, 0.8, n)
        pos = np.stack([rr * np.cos(th), hh, rr * np.sin(th)], axis=1)
        # 尘埃缓慢向外漂移 + 少量切向
        speed = (0.003 + 0.012 * rng.random(n)) * C.C_AU_S
        radial = pos / np.maximum(1e-9, np.linalg.norm(pos, axis=1, keepdims=True))
        tang = np.stack([-radial[:, 2], np.zeros(n), radial[:, 0]], axis=1)
        vel = radial * speed[:, None] + tang * (speed * 0.25)[:, None] * rng.normal(0, 1, (n, 1))
        self.dust_pos = pos
        self.dust_vel = vel
        self.dust_alive = np.ones(n, dtype=bool)
        warm = np.array([1.0, 0.82, 0.62])
        cool = np.array([0.7, 0.85, 1.0])
        mix = rng.random(n)[:, None]
        tint = warm * mix + cool * (1.0 - mix)
        bright = (0.07 + 0.22 * rng.random(n) ** 2)[:, None]
        self.dust_color = tint * bright
        self.dust_size = 0.8 + 1.4 * rng.random(n) ** 2
        self._dust_flash_cd = np.zeros(n)

    def _init_sparks(self) -> None:
        self.spark_max = 2200
        self.spark_pos = np.zeros((self.spark_max, 3), dtype=np.float64)
        self.spark_vel = np.zeros((self.spark_max, 3), dtype=np.float64)
        self.spark_life = np.zeros(self.spark_max, dtype=np.float64)
        self.spark_max_life = np.ones(self.spark_max, dtype=np.float64)
        self.spark_color = np.zeros((self.spark_max, 3), dtype=np.float64)
        self.spark_size = np.ones(self.spark_max, dtype=np.float64)
        self.spark_count = 0

    def _init_events(self) -> None:
        self.events.append(Event(0.0, "太阳系二维化开始 · 波前以光速扩张", "danger"))
        self.events.append(Event(0.0, "水星 / 金星 / 地球 / 火星 已坠入二维平面", "sad"))
        self.events.append(Event(0.0, f"{C.SHIP_NAME_ZH} 曲率驱动航行中 · β = {self.beta:.2f}", "info"))
        self.events.append(Event(0.0, "「长城」号等 7 艘亚光速飞船正在加速逃离", "info"))

    # ------------------------------------------------------------------
    # 相机
    # ------------------------------------------------------------------
    def _rebuild_camera(self) -> None:
        self.cam_right, self.cam_up, self.cam_fwd = viewmath.camera_basis(
            self.fwd, self.right, self.up, self.yaw, self.pitch)

    def apply_mouse(self, dx: float, dy: float) -> None:
        self.yaw_target += math.radians(dx * C.SHIP_LOOK_SENS)
        self.pitch_target -= math.radians(dy * C.SHIP_LOOK_SENS)
        lim = math.radians(88.0)
        self.pitch_target = max(-lim, min(lim, self.pitch_target))

    def apply_key_look(self, dx_deg: float, dy_deg: float) -> None:
        self.yaw_target += math.radians(dx_deg)
        self.pitch_target -= math.radians(dy_deg)
        lim = math.radians(88.0)
        self.pitch_target = max(-lim, min(lim, self.pitch_target))

    # ------------------------------------------------------------------
    # 控制
    # ------------------------------------------------------------------
    def adjust_beta(self, delta: float) -> None:
        self.beta_target = float(np.clip(self.beta_target + delta, C.SHIP_BETA_MIN, C.SHIP_BETA_MAX))

    def set_beta(self, beta: float) -> None:
        self.beta_target = float(np.clip(beta, C.SHIP_BETA_MIN, C.SHIP_BETA_MAX))

    def boost_escape(self) -> None:
        self.beta_target = C.SHIP_BETA_TARGET_ESCAPE
        if not any("全功率" in e.text for e in self.events):
            self.events.append(Event(self.t_ext, "曲率驱动全功率输出 · 目标 β = 0.99935", "escape"))

    def adjust_time_scale(self, factor: float) -> None:
        self.time_scale = float(np.clip(self.time_scale * factor, C.TIME_SCALE_MIN, C.TIME_SCALE_MAX))

    def observation_jump(self, factor: float = 5.0) -> None:
        """观测模式: 把二维化前沿快速推进一个量级.

        物理上行星际和奥尔特云的二维化需要极长的时间, 为了能让用户直接观察
        外围结构 (柯伊伯带/离散盘/奥尔特云), 这里提供一个"快进"观测功能:
        二维化波前按光速跳到新的半径, 星环号也同步保持逃逸状态。
        这只是一个可视化辅助, 不改变相对论计算。
        """
        if self.flattening:
            return
        if self.beta < 0.99:
            self.beta = self.beta_target = C.SHIP_BETA_TARGET_ESCAPE
        target = min(self.wave_r * factor, C.ANNULUS_R_NORM * 0.999)
        if target <= self.wave_r * 1.001:
            return
        dt_ext = (target - self.wave_r) / C.C_AU_S
        self.t_ext += dt_ext
        self.t_proper += dt_ext / relativity.gamma_of(self.beta)
        # 观测跳转是可视化辅助, 不应该因为多次快进而把飞船"跳"进波前:
        # 保持跳跃前的飞船-波前间距, 只把两者一起向外平移.
        gap_keep = max(0.8, self.ship_r - self.wave_r)
        self.wave_r = target
        self.ship_r = self.wave_r + gap_keep
        self.ship_pos = self.escape_dir * self.ship_r
        k_ann, rk_ann, dr_ann = hilbert.annulus_params(self.wave_r)
        self.progress = max(rk_ann, self.wave_r - 0.62 * dr_ann) / C.ANNULUS_R_NORM

        # 所有已被二维化前沿越过的天体立即折叠
        for p in self.planets:
            if not p.alive:
                continue
            rev = hilbert.reveal_scalar(float(p.pos[0]), float(p.pos[2]))
            p.reveal = rev
            if self.progress >= rev:
                self._collapse_planet(p)
                p.anim = 1.0
                p.alive = False
        for sh in self.refugees:
            if not sh.alive:
                continue
            rev = hilbert.reveal_scalar(float(sh.pos[0]), float(sh.pos[2]))
            sh.reveal = rev
            if self.progress >= rev:
                self._collapse_refugee(sh)
                sh.anim = 1.0
                sh.alive = False
        r3 = np.linalg.norm(self.dust_pos, axis=1)
        hit = self.dust_alive & (r3 <= self.wave_r)
        if np.any(hit):
            self.dust_alive[hit] = False
            self._spawn_dust_flashes(self.dust_pos[hit])
        self.events.append(Event(self.t_ext, f"观测模式 · 二维化前沿快进至 {self.wave_r:,.0f} AU", "warn"))
        self.events.append(Event(self.t_ext, "提示: 按 V 可关闭相对论视觉, 便于观察外围结构", "info"))
        self.events = self.events[-32:]

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------
    def update(self, dt_real: float) -> None:
        dt_real = float(np.clip(dt_real, 0.0, 0.1))
        self.t_real += dt_real
        # 相机平滑
        k = min(1.0, dt_real * 18.0)
        self.yaw += (self.yaw_target - self.yaw) * k
        self.pitch += (self.pitch_target - self.pitch) * k
        self._rebuild_camera()

        if self.flattening:
            self.flatten_t += dt_real
            self._update_sparks(dt_real, timescale_active=False)
            return

        # beta 平滑趋近目标
        diff = self.beta_target - self.beta
        rate = 2.4 if diff > 0 else 3.2
        self.beta += diff * min(1.0, dt_real * rate)
        self.beta = float(np.clip(self.beta, C.SHIP_BETA_MIN, C.SHIP_BETA_MAX))
        gamma = relativity.gamma_of(self.beta)

        dt_ext = dt_real * self.time_scale
        self.t_ext += dt_ext
        self.t_proper += dt_ext / gamma
        self.ship_r += self.beta * C.C_AU_S * dt_ext
        self.ship_pos = self.escape_dir * self.ship_r
        self.wave_r = C.WAVE_R0 + C.C_AU_S * self.t_ext
        # 二维化平面以光速扩张 (wave_r = 平面外缘);
        # 而"折叠笔"落后约 0.62 个环带宽度, 这样窗外的二维化平面里
        # 会始终留出一圈正在被希尔伯特曲线填充的"未完成区"。
        k_ann, rk_ann, dr_ann = hilbert.annulus_params(self.wave_r)
        paint_front = max(rk_ann, self.wave_r - 0.62 * dr_ann)
        self.progress = paint_front / C.ANNULUS_R_NORM

        # 光速逃逸判定: 必须是当前速度 (而不是历史状态) 接近光速才算"已脱离".
        # 一旦降速, 二维化波前会重新逼近, 标语应立即消失.
        if self.beta > 0.995:
            self._boost_timer += dt_real
        else:
            self._boost_timer = 0.0
        # "已脱离"标语只在两种条件同时满足时显示:
        #   1) 曲率驱动仍处于全功率档位 (目标速度达到逃逸速度);
        #   2) 当前速度确实达到近光速, 且尚未被波前追上.
        # 一旦降低功率/降速, 标语立即消失, 波前重新逼近.
        in_full_power = self.beta_target >= C.SHIP_BETA_ESCAPE
        self.escaped = bool(in_full_power and self.beta >= C.SHIP_BETA_ESCAPE
                            and self.ship_r > self.wave_r)
        if self.escaped and self._boost_timer > 1.2 and not self._escape_announced:
            self._escape_announced = True
            self.events.append(Event(self.t_ext, "已进入光速航程 · 二维化波前被甩在身后", "escape"))
        if (not self.escaped) and self._escape_announced and (
                self.beta < C.SHIP_BETA_ESCAPE - 0.002 or self.beta_target < C.SHIP_BETA_ESCAPE):
            self._escape_announced = False
            self.events.append(Event(self.t_ext, "曲率功率不足 · 二维化波前重新逼近", "warn"))

        # 二维化笔尖 & 火花
        pen_x, pen_z, pen_r, pen_rev = hilbert.pen_position(self.progress)
        self.pen = (pen_x, pen_z, pen_r)
        if self.progress < 0.999:
            self._spawn_pen_sparks(pen_x, pen_z)

        self._update_planets(dt_real)
        self._update_refugees(dt_real, dt_ext)
        self._update_dust(dt_ext)
        self._update_sparks(dt_real)

        for m in self.marks:
            m.flash *= max(0.0, 1.0 - dt_real * 1.8)

        # 波前追上星环号
        if self.ship_r <= self.wave_r:
            self.flattening = True
            self.flatten_t = 0.0
            self.events.append(Event(self.t_ext, f"{C.SHIP_NAME_ZH} 被二维化波前吞没 · 太阳系完成二维化", "danger"))

    # ------------------------------------------------------------------
    def _update_planets(self, dt_real: float) -> None:
        for p in self.planets:
            if not p.alive:
                continue
            if p.collapsing:
                p.anim += dt_real / 0.9
                k = min(1.0, p.anim)
                p.squash = max(0.02, 1.0 - k * k)
                p.flash = max(0.0, 1.0 - k) * 1.5
                if p.anim >= 1.0:
                    p.alive = False
                continue
            rev = hilbert.reveal_scalar(float(p.pos[0]), float(p.pos[2]))
            p.reveal = rev
            if self.progress >= rev:
                self._collapse_planet(p)

    def _collapse_planet(self, p: PlanetState) -> None:
        p.collapsing = True
        p.anim = 0.0
        p.flash = 1.0
        p.painted = True
        color = 0.7 * np.array(p.spec.color) + 0.3 * np.array([1.0, 0.92, 0.75])
        self.marks.append(Mark(
            x=float(p.pos[0]), z=float(p.pos[2]),
            size=p.spec.painted_radius * 1.2, reveal=p.reveal,
            color=(float(color[0]), float(color[1]), float(color[2])),
            flash=1.0,
            dir_x=float(p.tangent[0]), dir_z=float(p.tangent[2]),
            label=p.spec.name_zh,
        ))
        self.events.append(Event(self.t_ext, f"{p.spec.name_zh} 已被二维化 · 平面印记生成", "sad"))
        self._spawn_burst(p.pos, 26, np.array([1.0, 0.75, 0.45]), spread=0.35)

    def _update_refugees(self, dt_real: float, dt_ext: float) -> None:
        trail_timer = getattr(self, "_trail_timer", 0.0) + dt_real
        emit_trail = trail_timer > 0.10
        if emit_trail:
            self._trail_timer = 0.0
        else:
            self._trail_timer = trail_timer
        for s in self.refugees:
            if not s.alive:
                continue
            if s.collapsing:
                s.anim += dt_real / 0.8
                k = min(1.0, s.anim)
                s.squash = max(0.02, 1.0 - k * k)
                s.flash = max(0.0, 1.0 - k) * 2.0
                if s.anim >= 1.0:
                    s.alive = False
                continue
            s.pos = s.pos + s.vel * dt_ext
            if emit_trail:
                s.trail.append(s.pos.copy())
                if len(s.trail) > C.TRAIL_LEN:
                    s.trail.pop(0)
            rev = hilbert.reveal_scalar(float(s.pos[0]), float(s.pos[2]))
            s.reveal = rev
            if self.progress >= rev:
                self._collapse_refugee(s)

    def _collapse_refugee(self, s: RefugeeState) -> None:
        s.collapsing = True
        s.anim = 0.0
        s.flash = 1.0
        color = 0.65 * np.array(s.spec.color) + 0.35 * np.array([1.0, 0.85, 0.6])
        self.marks.append(Mark(
            x=float(s.pos[0]), z=float(s.pos[2]), size=0.20, reveal=s.reveal,
            color=(float(color[0]), float(color[1]), float(color[2])),
            flash=1.0, dir_x=0.0, dir_z=0.0, label=s.spec.name_zh,
        ))
        self.events.append(Event(self.t_ext, f"「{s.spec.name_zh}」号没能逃出二维化 · 平面印记生成", "sad"))
        self._spawn_burst(s.pos, 18, np.array([0.7, 0.85, 1.0]), spread=0.25)

    def _update_dust(self, dt_ext: float) -> None:
        if not np.any(self.dust_alive):
            return
        self.dust_pos[self.dust_alive] += self.dust_vel[self.dust_alive] * dt_ext
        r3 = np.linalg.norm(self.dust_pos, axis=1)
        hit = self.dust_alive & (r3 <= self.wave_r)
        if np.any(hit):
            self.dust_alive[hit] = False
            self._spawn_dust_flashes(self.dust_pos[hit])

    def _spawn_dust_flashes(self, positions: np.ndarray) -> None:
        if len(positions) > 160:
            positions = positions[np.random.choice(len(positions), 160, replace=False)]
        self._spawn_burst(positions, 1, np.array([1.0, 0.7, 0.4]), spread=0.05, size=1.1, life=0.8)

    # ------------------------------------------------------------------
    # 火花
    # ------------------------------------------------------------------
    def _alloc_sparks(self, n: int) -> np.ndarray:
        n = min(n, self.spark_max)
        # 简单环形覆盖
        start = self.spark_count
        idx = (start + np.arange(n)) % self.spark_max
        self.spark_count = (start + n) % self.spark_max
        return idx

    def _spawn_burst(self, positions: np.ndarray, per_point: int,
                     color: np.ndarray, spread: float = 0.3,
                     size: float = 1.6, life: float = 1.4) -> None:
        positions = np.atleast_2d(positions)
        n = len(positions) * per_point
        if n <= 0:
            return
        idx = self._alloc_sparks(n)
        reps = np.repeat(positions, per_point, axis=0)
        rng = np.random.default_rng()
        dirs = rng.normal(0.0, 1.0, (len(reps), 3))
        dirs /= np.maximum(1e-9, np.linalg.norm(dirs, axis=1, keepdims=True))
        speed = spread * (0.4 + 1.6 * rng.random((len(reps), 1)))
        self.spark_pos[idx] = reps
        self.spark_vel[idx] = dirs * speed
        self.spark_life[idx] = life * (0.5 + 0.8 * rng.random(len(reps)))
        self.spark_max_life[idx] = self.spark_life[idx]
        tint = np.array(color) * (0.7 + 0.5 * rng.random((len(reps), 1)))
        self.spark_color[idx] = tint
        self.spark_size[idx] = size * (0.6 + 0.8 * rng.random(len(reps)))

    def _spawn_pen_sparks(self, pen_x: float, pen_z: float) -> None:
        n = 5
        idx = self._alloc_sparks(n)
        rng = np.random.default_rng()
        ang = rng.uniform(0, 2 * math.pi, n)
        rad = 0.10 + 0.35 * rng.random(n)
        pos = np.stack([
            pen_x + rad * np.cos(ang),
            rng.uniform(0.02, 0.4, n),
            pen_z + rad * np.sin(ang),
        ], axis=1)
        vel = np.stack([
            np.cos(ang) * (0.25 + 0.5 * rng.random(n)),
            0.35 + 1.6 * rng.random(n),
            np.sin(ang) * (0.25 + 0.5 * rng.random(n)),
        ], axis=1)
        self.spark_pos[idx] = pos
        self.spark_vel[idx] = vel
        life = 0.6 + 0.7 * rng.random(n)
        self.spark_life[idx] = life
        self.spark_max_life[idx] = life
        self.spark_color[idx] = np.stack([
            1.0 * np.ones(n), 0.75 + 0.2 * rng.random(n), 0.45 + 0.35 * rng.random(n)
        ], axis=1)
        self.spark_size[idx] = 1.4 + 2.6 * rng.random(n)

    def _update_sparks(self, dt_real: float, timescale_active: bool = True) -> None:
        alive = self.spark_life > 0.0
        self.spark_life[alive] -= dt_real
        self.spark_pos[alive] += self.spark_vel[alive] * dt_real
        self.spark_vel[alive] *= (1.0 - 2.2 * dt_real)
        self.spark_life[~alive] = 0.0

    # ------------------------------------------------------------------
    # 派生量
    # ------------------------------------------------------------------
    def frame(self) -> SimFrame:
        gamma = relativity.gamma_of(self.beta)
        gap = self.ship_r - self.wave_r
        eta_ext = math.inf
        denom = (1.0 - self.beta) * C.C_AU_S
        if denom > 1e-12:
            eta_ext = max(0.0, gap) / denom
        eta_real = eta_ext / max(1e-6, self.time_scale)

        planet_pos = np.stack([p.pos for p in self.planets], axis=0)
        planet_radius = np.array([p.spec.display_radius for p in self.planets], dtype=np.float64)
        planet_squash = np.array([p.squash if p.alive else 0.02 for p in self.planets])
        planet_flash = np.array([p.flash if p.alive else 0.0 for p in self.planets])
        planet_alive = np.array([1.0 if p.alive else 0.0 for p in self.planets])
        planet_color = np.array([p.spec.color for p in self.planets], dtype=np.float64)

        # 可见尘埃 / 火花 (渲染端只绘制存活项)
        alive_sparks = self.spark_life > 0.0
        spark_pos = self.spark_pos[alive_sparks]
        spark_life = self.spark_life[alive_sparks] / np.maximum(1e-6, self.spark_max_life[alive_sparks])
        spark_color = self.spark_color[alive_sparks] * (spark_life ** 1.5)[:, None]
        spark_size = self.spark_size[alive_sparks] * (0.4 + 0.9 * spark_life)

        rear_doppler = 1.0 / (gamma * (1.0 + self.beta))
        return SimFrame(
            t_ext=self.t_ext,
            t_proper=self.t_proper,
            t_real=self.t_real,
            beta=self.beta,
            gamma=gamma,
            wave_r=self.wave_r,
            progress=self.progress,
            pen=getattr(self, "pen", (0.0, 0.0, 0.0)),
            time_scale=self.time_scale,
            ship_pos=self.ship_pos.copy(),
            escape_dir=self.escape_dir.copy(),
            fwd=np.array(self.fwd),
            right=np.array(self.right),
            up=np.array(self.up),
            cam_right=np.array(self.cam_right),
            cam_up=np.array(self.cam_up),
            cam_fwd=np.array(self.cam_fwd),
            yaw=self.yaw,
            pitch=self.pitch,
            planet_pos=planet_pos,
            planet_radius=planet_radius,
            planet_squash=planet_squash,
            planet_flash=planet_flash,
            planet_alive=planet_alive,
            planet_color=planet_color,
            marks=list(self.marks),
            refugees=self.refugees,
            dust_pos=self.dust_pos.copy(),
            dust_alive=self.dust_alive.copy(),
            dust_color=self.dust_color.copy(),
            dust_size=self.dust_size.copy(),
            spark_pos=spark_pos,
            spark_color=spark_color,
            spark_size=spark_size,
            events=list(self.events),
            flattening=self.flattening,
            flatten_t=self.flatten_t,
            escaped=self.escaped,
            boost=float(np.clip((self.beta - 0.98) / 0.019, 0.0, 1.0)),
            gap=gap,
            eta_ext=eta_ext,
            eta_real=eta_real,
            dist_sun=self.ship_r,
            rear_doppler=rear_doppler,
            aberr_half_angle=math.degrees(math.acos(max(-1.0, min(1.0, self.beta)))),
            proper_rate=1.0 / gamma,
            speed_kms=self.beta * 299792.458,
        )
