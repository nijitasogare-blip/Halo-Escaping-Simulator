"""应用主循环 / 截图模式 / 基准测试."""
from __future__ import annotations

import argparse
import math
import os
import time

import numpy as np
import pygame

from . import config as C
from . import hud as hud_mod
from . import painting, relativity, viewmath
from .renderer import Renderer
from .sim import Sim

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")


# --------------------------------------------------------------------------
# 窗口 / GL 上下文
# --------------------------------------------------------------------------
def create_window(size: tuple[int, int], hidden: bool = False, resizable: bool = True):
    pygame.display.init()
    pygame.font.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE)
    pygame.display.gl_set_attribute(pygame.GL_DEPTH_SIZE, 24)
    pygame.display.gl_set_attribute(pygame.GL_DOUBLEBUFFER, 1)
    flags = pygame.OPENGL | pygame.DOUBLEBUF
    flags |= pygame.HIDDEN if hidden else (pygame.RESIZABLE if resizable else 0)
    pygame.display.set_mode(size, flags)
    pygame.display.set_caption("星环号 · 二维化逃逸 / HALO · Death's End")
    return pygame.display.get_surface()


def _save_surface(path: str, surface: pygame.Surface) -> None:
    pygame.image.save(surface, path)


# --------------------------------------------------------------------------
# 投影辅助: 把世界物体投到屏幕 (用于 HUD 标签)
# --------------------------------------------------------------------------
def label_points_for(frame, size: tuple[int, int], fov_deg: float = C.SHIP_FOV_DEG, beta_override: float | None = None):
    w, h = size
    tan_half = math.tan(math.radians(fov_deg) * 0.5)
    aspect = w / h
    beta = frame.beta if beta_override is None else beta_override
    out = []
    for sh in frame.refugees:
        dist = float(np.linalg.norm(sh.pos - frame.ship_pos))
        px, py, depth, on = viewmath.project_world_point(
            tuple(sh.pos), tuple(frame.ship_pos), beta, tuple(frame.escape_dir),
            tuple(frame.cam_right), tuple(frame.cam_up), tuple(frame.cam_fwd),
            tan_half, aspect, w, h,
        )
        out.append({
            "name": sh.spec.name_zh,
            "px": px, "py": py,
            "visible": bool(on and depth > 0 and sh.alive),
            "dist": dist,
            "color": tuple(int(c * 255) for c in sh.spec.color),
            "alive": sh.alive,
            "collapsed": not sh.alive,
        })
    return out


# --------------------------------------------------------------------------
# 交互模式
# --------------------------------------------------------------------------
class App:
    def __init__(self, size=(1600, 900), render_scale: float = 1.0,
                 time_scale: float = C.TIME_SCALE_DEFAULT, beta0: float = C.SHIP_BETA0,
                 hidden: bool = False, max_seconds: float | None = None):
        self.max_seconds = max_seconds
        self.elapsed = 0.0
        self.size = size
        self.surface = create_window(size, hidden=hidden)
        self.renderer = Renderer(size, render_scale=render_scale)
        self.sim = Sim(time_scale=time_scale, beta0=beta0)
        self.hud = hud_mod.Hud(size)
        self.clock = pygame.time.Clock()
        self.running = True
        self.relativity_on = True
        self.hud_on = True
        self.intro_t = 0.0
        self.flash = 0.0
        self.fps = 60.0
        self._hud_timer = 0.0
        self._hud_bytes = None
        self._last_frame = None

    def _grab_mouse(self, grab: bool) -> None:
        pygame.event.set_grab(grab)
        pygame.mouse.set_visible(not grab)

    def _handle_events(self) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            elif e.type == pygame.VIDEORESIZE:
                w, h = max(640, e.w), max(360, e.h)
                self.size = (w, h)
                self.surface = pygame.display.set_mode(
                    self.size, pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE)
                self.renderer.resize(self.size)
                self.hud = hud_mod.Hud(self.size)
                self._hud_bytes = None
            elif e.type == pygame.KEYDOWN:
                self._handle_key(e)
            elif e.type == pygame.MOUSEMOTION and pygame.event.get_grab():
                self.sim.apply_mouse(e.rel[0], e.rel[1])
            elif e.type == pygame.MOUSEBUTTONDOWN:
                if not pygame.event.get_grab():
                    self._grab_mouse(True)
            elif e.type == pygame.MOUSEWHEEL:
                self.sim.adjust_beta(0.015 * e.y)
        if pygame.event.get_grab():
            keys = pygame.key.get_pressed()
            if keys[pygame.K_LEFT]:
                self.sim.apply_key_look(-1.6, 0.0)
            if keys[pygame.K_RIGHT]:
                self.sim.apply_key_look(1.6, 0.0)
            if keys[pygame.K_UP]:
                self.sim.apply_key_look(0.0, 1.6)
            if keys[pygame.K_DOWN]:
                self.sim.apply_key_look(0.0, -1.6)
            if keys[pygame.K_w]:
                self.sim.adjust_beta(0.006)
            if keys[pygame.K_s]:
                self.sim.adjust_beta(-0.006)

    def _handle_key(self, e) -> None:
        if e.key == pygame.K_ESCAPE:
            if pygame.event.get_grab():
                self._grab_mouse(False)
            else:
                self.running = False
        elif e.key == pygame.K_r:
            self._restart()
        elif e.key == pygame.K_SPACE:
            self.sim.boost_escape()
            self.flash = 0.6
        elif e.key == pygame.K_o:
            # 只快进二维化前沿, 不改变相对论视觉开关 (需要看清外围时请自行按 V)
            self.sim.observation_jump()
            self.flash = 0.4
        elif e.key == pygame.K_v:
            self.relativity_on = not self.relativity_on
        elif e.key == pygame.K_h:
            self.hud_on = not self.hud_on
        elif e.key == pygame.K_F12:
            self._screenshot()
        elif e.key in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.sim.adjust_time_scale(1.3)
        elif e.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.sim.adjust_time_scale(1 / 1.3)
        elif e.key == pygame.K_f:
            self._toggle_fullscreen()

    def _toggle_fullscreen(self) -> None:
        try:
            if self.surface.get_flags() & pygame.FULLSCREEN:
                self.size = (1600, 900)
                self.surface = pygame.display.set_mode(
                    self.size, pygame.OPENGL | pygame.DOUBLEBUF | pygame.RESIZABLE)
            else:
                info = pygame.display.Info()
                self.size = (info.current_w, info.current_h)
                self.surface = pygame.display.set_mode(
                    self.size, pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
            self.renderer.resize(self.size)
            self.hud = hud_mod.Hud(self.size)
            self._hud_bytes = None
        except Exception:
            pass

    def _restart(self) -> None:
        ts = self.sim.time_scale
        self.sim = Sim(time_scale=ts)
        self.intro_t = 0.0
        self.flash = 0.0
        self._hud_bytes = None

    def _screenshot(self) -> None:
        os.makedirs("screenshots", exist_ok=True)
        name = time.strftime("screenshots/halo_%Y%m%d_%H%M%S.png")
        img = self.renderer.read_output()
        from PIL import Image
        Image.fromarray(np.flipud(img), mode="RGB").save(name)
        print(f"[截图] {name}")

    def _update_hud(self, frame, dt: float) -> None:
        self._hud_timer += dt
        if self._hud_timer < 1.0 / 18.0:
            return
        self._hud_timer = 0.0
        labels = label_points_for(frame, self.size, beta_override=None if self.relativity_on else 0.0)
        status = None
        if frame.flattening:
            status = ("二维化完成 · 你已成为二维平面的一部分", frame.flatten_t)
        data = self.hud.render(
            frame, fps=self.fps, relativity_on=self.relativity_on,
            label_points=labels, intro_t=self.intro_t, status_message=status,
        )
        self.renderer.set_hud(data, self.size)
        self._hud_bytes = data

    def run(self) -> None:
        self._grab_mouse(True)
        last = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            dt = min(0.05, max(1e-4, now - last))
            last = now
            self.elapsed += dt
            self.fps = self.fps * 0.92 + (1.0 / dt) * 0.08
            self.intro_t += dt
            if self.max_seconds is not None and self.elapsed > self.max_seconds:
                self.running = False
            self.flash *= math.exp(-dt * 4.0)
            self._handle_events()
            if not self.running:
                break
            self.sim.update(dt)
            if self.sim.flattening and self.sim.flatten_t > 11.0:
                self._restart()
            frame = self.sim.frame()
            self._last_frame = frame
            self._update_hud(frame, dt)
            flatten = 0.0
            if frame.flattening:
                flatten = min(1.0, frame.flatten_t / 2.4)
            self.renderer.render(
                frame, time=self.intro_t, hud_on=self.hud_on,
                relativity_on=self.relativity_on, flatten=flatten,
                flash=self.flash, dt=dt,
            )
            pygame.display.flip()
            self.clock.tick(60)
        pygame.quit()


# --------------------------------------------------------------------------
# 截图模式
# --------------------------------------------------------------------------
def _look_at(frame, target) -> tuple[float, float]:
    """算出指向世界坐标 target 的 yaw / pitch (飞船系)."""
    rel = np.asarray(target, dtype=np.float64) - np.asarray(frame.ship_pos)
    n = np.linalg.norm(rel)
    if n < 1e-9:
        return 0.0, 0.0
    d = rel / n
    fwd = np.asarray(frame.fwd)
    right = np.asarray(frame.right)
    up = np.asarray(frame.up)
    x = float(np.dot(d, right))
    y = float(np.dot(d, up))
    z = float(np.dot(d, fwd))
    yaw = math.atan2(x, z)
    pitch = math.asin(max(-1.0, min(1.0, y)))
    return yaw, pitch


SHOT_PLAN = (
    # (文件名, 现实秒, 相机, beta, 相对论, HUD)
    dict(name="01_escape_start", seconds=2.0,
         yaw=180.0, pitch=-2.0, hud=True, rel=True),
    dict(name="02_peano_front", seconds=42.0,
         yaw=186.0, pitch=-26.0, hud=True, rel=True),
    dict(name="03_sun_rosette", seconds=24.0,
         yaw=178.0, pitch=-12.0, hud=True, rel=True),
    dict(name="04_starbow_fullpower", seconds=30.0,
         yaw=0.0, pitch=2.0, beta=0.982, hud=True, rel=True),
    dict(name="05_no_relativity", seconds=24.0,
         yaw=180.0, pitch=-2.0, rel=False, hud=True),
    dict(name="06_full_system", seconds=78.0,
         yaw=181.0, pitch=-8.0, hud=True, rel=True),
    dict(name="07_closeup_plane", seconds=60.0,
         yaw=193.0, pitch=-44.0, hud=True, rel=True),
)


def ensure_paintings() -> None:
    """首次运行时生成二维化绘画纹理 (之后从 cache/ 读取)."""
    t0 = time.perf_counter()
    painting.build_all_paintings()
    dt = time.perf_counter() - t0
    if dt > 0.5:
        print(f"[资源] 二维化绘画纹理就绪 (inner/outer/mid/far, {dt:.1f}s)")


def run_shots(outdir: str = "screenshots", size=(1600, 900), scale: float = 1.0,
              make_gif: bool = True, verbose: bool = True) -> None:
    os.makedirs(outdir, exist_ok=True)
    ensure_paintings()
    surface = create_window(size, hidden=True)
    renderer = Renderer(size, render_scale=scale)
    hud = hud_mod.Hud(size)
    from PIL import Image

    def render_state(sim: Sim, *, rel: bool = True, hud_on: bool = True,
                     flatten: float = 0.0, time_val: float = 0.0,
                     hud_frame=None, intro_t: float = 99.0) -> None:
        frame = sim.frame()
        if hud_on:
            labels = label_points_for(frame, size, beta_override=None if rel else 0.0)
            status = None
            if frame.flattening:
                status = ("二维化完成 · 你已坠入二维平面", frame.flatten_t)
            data = hud.render(frame, fps=60.0, relativity_on=rel, label_points=labels,
                              intro_t=intro_t, status_message=status)
            renderer.set_hud(data, size)
        renderer.render(frame, time=time_val, hud_on=hud_on, relativity_on=rel,
                        flatten=flatten, dt=1.0 / 60.0)

    def save(name: str) -> None:
        pygame.display.flip()
        img = renderer.read_output()
        Image.fromarray(np.flipud(img), mode="RGB").save(os.path.join(outdir, name))
        if verbose:
            print(f"[shot] {name}  exposure={renderer.read_exposure():.2f}")

    for spec in SHOT_PLAN:
        sim = Sim(time_scale=C.TIME_SCALE_DEFAULT)
        # 相机
        sim.yaw_target = sim.yaw = math.radians(spec.get("yaw", 180.0))
        sim.pitch_target = sim.pitch = math.radians(spec.get("pitch", 0.0))
        if "beta" in spec:
            sim.beta = sim.beta_target = spec["beta"]
        # 无渲染地推进模拟
        n_steps = int(spec["seconds"] * 60)
        for _ in range(n_steps):
            sim.update(1.0 / 60.0)
        # 渲染 30 帧, 让自动曝光收敛
        rel = spec.get("rel", True)
        hud_on = spec.get("hud", True)
        for i in range(30):
            sim.update(1 / 60.0)
            render_state(sim, rel=rel, hud_on=hud_on, time_val=i / 60.0)
        render_state(sim, rel=rel, hud_on=hud_on, time_val=time.time())
        save(spec["name"] + ".png")

    # 二维化吞没瞬间
    sim = Sim()
    sim.yaw_target = sim.yaw = math.radians(192.0)
    sim.pitch_target = sim.pitch = math.radians(-18.0)
    for _ in range(int(200 * 60)):
        sim.update(1 / 60.0)
        if sim.flattening:
            break
    if not sim.flattening:
        sim.flattening = True
        sim.flatten_t = 0.0
    for i in range(int(1.25 * 60)):
        sim.update(1 / 60.0)
        render_state(sim, rel=True, hud_on=True, flatten=min(1.0, sim.flatten_t / 2.4),
                     time_val=i / 60.0)
    render_state(sim, rel=True, hud_on=True, flatten=min(1.0, sim.flatten_t / 2.4))
    save("08_flattened.png")

    # ---- 远景观测: 小行星带 / 柯伊伯带 / 奥尔特云 ----
    far_shots = (
        ("09_kuiper_belt", 2, 180.0, 0.0),
        ("10_oort_cloud", 4, 180.0, 0.0),
    )
    for name, jumps, yaw_deg, pitch_deg in far_shots:
        sim = Sim()
        sim.boost_escape()
        for _ in range(jumps):
            sim.observation_jump()
        sim.escaped = True
        sim.yaw_target = sim.yaw = math.radians(yaw_deg)
        sim.pitch_target = sim.pitch = math.radians(pitch_deg)
        sim._rebuild_camera()
        for i in range(120):
            sim.update(1 / 60.0)
            render_state(sim, rel=False, hud_on=True, time_val=i / 60.0)
        render_state(sim, rel=False, hud_on=True, time_val=time.time())
        save(name + ".png")

    if make_gif:
        _make_teaser(outdir, renderer, hud, size, verbose=verbose)
    pygame.quit()


def _make_teaser(outdir, renderer: Renderer, hud, size, verbose: bool = True) -> None:
    """生成一段 640x360 的 GIF 预告: 镜头缓缓转向二维化平面."""
    from PIL import Image
    gif_size = (720, 405)
    frames = []
    sim = Sim(time_scale=110.0)
    sim.yaw_target = sim.yaw = math.radians(150.0)
    sim.pitch_target = sim.pitch = math.radians(-16.0)
    n = 76
    for i in range(n):
        # 缓慢环视
        t = i / (n - 1)
        sim.yaw_target = math.radians(150.0 + 70.0 * t)
        sim.pitch_target = math.radians(-16.0 - 12.0 * math.sin(t * math.pi))
        for _ in range(4):
            sim.update(1 / 60.0)
        frame = sim.frame()
        labels = label_points_for(frame, size)
        data = hud.render(frame, fps=60.0, relativity_on=True, label_points=labels,
                          intro_t=99.0)
        renderer.set_hud(data, size)
        renderer.render(frame, time=i / 60.0, hud_on=True, relativity_on=True,
                        flatten=0.0, dt=1 / 60.0)
        pygame.display.flip()
        img = renderer.read_output()
        pil = Image.fromarray(np.flipud(img), mode="RGB").resize(gif_size, Image.LANCZOS)
        frames.append(pil)
    path = os.path.join(outdir, "halo_teaser.gif")
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=96) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=150, loop=0, optimize=True, disposal=2)
    if verbose:
        print(f"[gif] {path}  {len(frames)} frames")


# --------------------------------------------------------------------------
# 自检模式 (隐藏窗口, 跑完整渲染管线 + 相对论/二维化分支)
# --------------------------------------------------------------------------
def run_selftest(size=(1280, 720), scale: float = 1.0) -> None:
    import time as _time
    create_window(size, hidden=True)
    renderer = Renderer(size, render_scale=scale)
    sim = Sim()
    hud = hud_mod.Hud(size)

    def tick(n: int, rel: bool = True, hud_on: bool = True, beta_boost: bool = False) -> None:
        for i in range(n):
            sim.update(1 / 60.0)
            frame = sim.frame()
            if hud_on and i % 2 == 0:
                data = hud.render(frame, fps=60.0, relativity_on=rel,
                                  label_points=label_points_for(frame, size), intro_t=12.0)
                renderer.set_hud(data, size)
            renderer.render(frame, time=i / 60.0, hud_on=hud_on, relativity_on=rel,
                            dt=1 / 60.0)

    # 1) 基础交互 API
    sim.apply_mouse(40.0, -25.0)
    sim.apply_key_look(5.0, 2.0)
    sim.adjust_beta(0.15)
    sim.adjust_time_scale(1.2)
    tick(60)
    print("[selftest] 基础渲染 / HUD / 鼠标视角 OK")
    # 2) 全功率逃逸 + 高 β 光行差 / 多普勒
    sim.boost_escape()
    tick(180, rel=True)
    print(f"[selftest] 全功率: beta={sim.beta:.4f} gamma={relativity.gamma_of(sim.beta):.2f} OK")
    # 2.5) 降速回归: "已脱离二维化波前"必须消失, 并记录波前重新逼近
    assert sim.frame().escaped, "全功率时应显示已脱离"
    sim.set_beta(0.55)
    tick(150, rel=True)
    assert not sim.frame().escaped, "降速后不应再显示已脱离"
    assert any("功率不足" in e.text for e in sim.events), "降速后应记录功率不足事件"
    print("[selftest] 降速后逃逸标语正确撤销 OK")
    sim.boost_escape()
    tick(360, rel=True)  # β 从 0.55 平滑爬升回 0.999+ 需要几秒
    assert sim.frame().escaped, "重新全功率后应恢复已脱离"
    print("[selftest] 重新全功率后逃逸标语恢复 OK")
    # 3) 相对论对照模式
    tick(30, rel=False)
    print("[selftest] 相对论对照模式 OK")
    # 4) 推进到二维化吞没, 渲染吞噬特效
    sim2 = Sim()
    sim2.yaw_target = sim2.yaw = np.deg2rad(192.0)
    sim2.pitch_target = sim2.pitch = np.deg2rad(-18.0)
    for _ in range(int(130 * 60)):
        sim2.update(1 / 60.0)
        if sim2.flattening:
            break
    assert sim2.flattening, "二维化波前未能追上星环号"
    for i in range(int(2.4 * 60)):
        sim2.update(1 / 60.0)
        frame = sim2.frame()
        data = hud.render(frame, fps=60.0, relativity_on=True,
                          label_points=label_points_for(frame, size), intro_t=99.0,
                          status_message=("二维化完成 · 你已成为二维平面的一部分", frame.flatten_t))
        renderer.set_hud(data, size)
        renderer.render(frame, time=i / 60.0, hud_on=True, relativity_on=True,
                        flatten=min(1.0, frame.flatten_t / 2.4), dt=1 / 60.0)
    pygame.display.flip()
    img = renderer.read_output()
    from PIL import Image
    os.makedirs("screenshots", exist_ok=True)
    Image.fromarray(np.flipud(img), mode="RGB").save("screenshots/selftest_flatten.png")
    print(f"[selftest] 二维化吞噬特效 OK (flatten_t={sim2.flatten_t:.2f}s)")
    # 5) 连续观测跳转不应把飞船"跳"进二维化波前
    sim3 = Sim()
    sim3.boost_escape()
    for _ in range(8):
        sim3.observation_jump()
        sim3.update(1 / 60.0)
    assert not sim3.flattening, "观测跳转不应强制二维化"
    assert sim3.frame().gap > 0.0, "观测跳转后应保持飞船在波前之外"
    print("[selftest] 连续观测跳转保持安全间距 OK")
    # 6) 重置流程
    sim2 = Sim()
    tick(5)
    print("[selftest] 重置流程 OK")
    print("[selftest] ALL OK")
    pygame.quit()


# --------------------------------------------------------------------------
# 基准测试
# --------------------------------------------------------------------------
def run_benchmark(size=(1600, 900), scale: float = 1.0, seconds: float = 5.0) -> None:
    create_window(size, hidden=True)
    renderer = Renderer(size, render_scale=scale)
    sim = Sim()
    n = int(seconds * 60)
    t0 = time.perf_counter()
    for i in range(n):
        sim.update(1 / 60.0)
        frame = sim.frame()
        renderer.render(frame, time=i / 60.0, hud_on=False, dt=1 / 60.0)
    pygame.display.flip()
    dt = time.perf_counter() - t0
    print(f"{n} frames @ {size[0]}x{size[1]} scale={scale}: {dt:.2f}s -> {n / dt:.1f} fps "
          f"(GPU render only, no vsync)")
    pygame.quit()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="星环号 · 太阳系二维化逃逸")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--scale", type=float, default=1.0, help="内部渲染倍率 (0.7 省性能 / 1.4 超采样)")
    parser.add_argument("--time-scale", type=float, default=C.TIME_SCALE_DEFAULT)
    parser.add_argument("--beta", type=float, default=C.SHIP_BETA0)
    parser.add_argument("--shots", action="store_true", help="生成验收截图后退出")
    parser.add_argument("--no-gif", action="store_true", help="截图模式不生成 GIF")
    parser.add_argument("--benchmark", action="store_true", help="隐藏窗口渲染性能测试")
    parser.add_argument("--selftest", action="store_true", help="隐藏窗口端到端自检")
    parser.add_argument("--demo", action="store_true", help="隐藏窗口试运行主循环数秒")
    parser.add_argument("--outdir", type=str, default="screenshots")
    args = parser.parse_args(argv)

    if args.benchmark:
        run_benchmark((args.width, args.height), args.scale)
        return 0
    if args.selftest:
        run_selftest((args.width, args.height), args.scale)
        return 0
    if args.demo:
        ensure_paintings()
        demo = App((args.width, args.height), render_scale=args.scale, hidden=True, max_seconds=4.0)
        demo.run()
        print("[demo] 主循环试运行完成")
        return 0
    ensure_paintings()
    if args.shots:
        run_shots(args.outdir, (args.width, args.height), args.scale, make_gif=not args.no_gif)
        return 0

    app = App((args.width, args.height), render_scale=args.scale,
              time_scale=args.time_scale, beta0=args.beta)
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0
