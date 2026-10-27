"""OpenGL 渲染管线 (pygame + moderngl).

管线:
    scene FBO(16F)  <- 世界光线追踪 + 点精灵(尘埃/飞船/火花, 加性混合)
    bloom            <- 亮部提取 + 两级高斯模糊
    auto exposure    <- 亮度下采样链 + GPU 端自适应曝光
    composite        <- ACES 色调映射 / 舷窗框 / 二维化吞噬 / HUD
    output FBO(8bit) -> 屏幕 (present)
"""
from __future__ import annotations

import math

import moderngl
import numpy as np

from . import config as C
from . import painting, relativity, shaders
from .sim import SimFrame


def _vec3(v) -> tuple[float, float, float]:
    return (float(v[0]), float(v[1]), float(v[2]))


def _frag(source: str, defines: bool = True) -> str:
    head = "#version 330\n"
    if defines:
        head += shaders.DEFINES
    return head + source


def _vert(source: str) -> str:
    return "#version 330\n" + source


class Renderer:
    def __init__(self, size: tuple[int, int], render_scale: float = 1.0):
        self.ctx = moderngl.create_context(require=330)
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.render_scale = float(max(0.4, min(2.0, render_scale)))
        self.point_capacity = 40000
        self.point_count = 0
        self.point_buffer = None
        self.point_vao = None
        self.exposure_index = 0
        self._hud_key = None
        self._hud_tex = None
        self._init_programs()
        self._init_quad()
        self._init_textures()
        self._init_points()
        self.resize(size)

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------
    def _init_programs(self) -> None:
        ctx = self.ctx
        self.prog_world = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                      fragment_shader=_frag(shaders.WORLD_FRAG))
        self.prog_points = ctx.program(vertex_shader=_vert(shaders.POINTS_VERT),
                                       fragment_shader=_frag(shaders.POINTS_FRAG, defines=False))
        self.prog_bright = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                       fragment_shader=_frag(shaders.BRIGHT_FRAG, defines=False))
        self.prog_blur = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                     fragment_shader=_frag(shaders.BLUR_FRAG, defines=False))
        self.prog_lum = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                    fragment_shader=_frag(shaders.LUM_FRAG, defines=False))
        self.prog_adapt = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                      fragment_shader=_frag(shaders.ADAPT_FRAG, defines=False))
        self.prog_composite = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                          fragment_shader=_frag(shaders.COMPOSITE_FRAG))
        self.prog_present = ctx.program(vertex_shader=_vert(shaders.QUAD_VERT),
                                        fragment_shader=_frag(shaders.PRESENT_FRAG, defines=False))

    def _init_quad(self) -> None:
        verts = np.array([
            -1.0, -1.0, 1.0, -1.0, -1.0, 1.0,
            1.0, -1.0, 1.0, 1.0, -1.0, 1.0,
        ], dtype="f4")
        vbo = self.ctx.buffer(verts.tobytes())
        self.quad_vaos = {}
        for prog in (self.prog_world, self.prog_bright, self.prog_blur, self.prog_lum,
                     self.prog_adapt, self.prog_composite, self.prog_present):
            self.quad_vaos[prog] = self.ctx.vertex_array(prog, [(vbo, "2f", "in_pos")])

    def _init_textures(self) -> None:
        self.paint_inner = self._upload_painting(painting.build_inner_painting())
        self.paint_outer = self._upload_painting(painting.build_outer_painting())
        self.paint_mid = self._upload_painting(painting.build_mid_painting())
        self.paint_far = self._upload_painting(painting.build_far_painting())

    def _upload_painting(self, arr: np.ndarray) -> moderngl.Texture:
        n = arr.shape[0]
        data = np.ascontiguousarray(arr, dtype=np.uint8).tobytes()
        tex = self.ctx.texture((n, n), 3, data)
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.repeat_x = False
        tex.repeat_y = False
        try:
            tex.anisotropy = 8.0
        except Exception:
            pass
        return tex

    def _init_points(self) -> None:
        self.point_vbo = self.ctx.buffer(reserve=self.point_capacity * 7 * 4, dynamic=True)
        self.point_vao = self.ctx.vertex_array(
            self.prog_points,
            [(self.point_vbo, "3f 3f 1f", "in_pos", "in_col", "in_size")],
        )

    # ------------------------------------------------------------------
    # 尺寸 / 资源
    # ------------------------------------------------------------------
    def resize(self, size: tuple[int, int]) -> None:
        self.size = (int(size[0]), int(size[1]))
        w, h = self.size
        self.render_size = (max(2, int(w * self.render_scale)), max(2, int(h * self.render_scale)))
        rw, rh = self.render_size
        ctx = self.ctx
        # 释放旧资源
        for attr in ("scene_fbo", "scene_tex", "out_fbo", "out_tex", "b1a_tex", "b1b_tex",
                     "b2a_tex", "b2b_tex", "bloom1_fbo", "bloom1b_fbo", "bloom2_fbo", "bloom2b_fbo",
                     "lum1_tex", "lum2_tex", "lum1_fbo", "lum2_fbo", "expo_a_tex", "expo_b_tex",
                     "expo_a_fbo", "expo_b_fbo"):
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    obj.release()
                except Exception:
                    pass
                setattr(self, attr, None)

        self.scene_tex = ctx.texture((rw, rh), 4, dtype="f2")
        self.scene_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.scene_tex.repeat_x = False
        self.scene_tex.repeat_y = False
        self.scene_fbo = ctx.framebuffer(color_attachments=[self.scene_tex])

        self.out_tex = ctx.texture((w, h), 4, dtype="f1")
        self.out_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.out_fbo = ctx.framebuffer(color_attachments=[self.out_tex])

        bw, bh = max(2, rw // 2), max(2, rh // 2)
        self.b1a_tex = ctx.texture((bw, bh), 4, dtype="f2")
        self.b1b_tex = ctx.texture((bw, bh), 4, dtype="f2")
        for t in (self.b1a_tex, self.b1b_tex):
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.bloom1_fbo = ctx.framebuffer(color_attachments=[self.b1a_tex])
        self.bloom1b_fbo = ctx.framebuffer(color_attachments=[self.b1b_tex])

        qw, qh = max(2, rw // 8), max(2, rh // 8)
        self.b2a_tex = ctx.texture((qw, qh), 4, dtype="f2")
        self.b2b_tex = ctx.texture((qw, qh), 4, dtype="f2")
        for t in (self.b2a_tex, self.b2b_tex):
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.bloom2_fbo = ctx.framebuffer(color_attachments=[self.b2a_tex])
        self.bloom2b_fbo = ctx.framebuffer(color_attachments=[self.b2b_tex])

        l1w, l1h = max(2, rw // 8), max(2, rh // 8)
        l2w, l2h = max(2, rw // 64), max(2, rh // 64)
        self.lum1_tex = ctx.texture((l1w, l1h), 2, dtype="f2")
        self.lum2_tex = ctx.texture((l2w, l2h), 2, dtype="f2")
        for t in (self.lum1_tex, self.lum2_tex):
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.lum1_fbo = ctx.framebuffer(color_attachments=[self.lum1_tex])
        self.lum2_fbo = ctx.framebuffer(color_attachments=[self.lum2_tex])

        self.expo_a_tex = ctx.texture((1, 1), 4, dtype="f4")
        self.expo_b_tex = ctx.texture((1, 1), 4, dtype="f4")
        for t in (self.expo_a_tex, self.expo_b_tex):
            t.filter = (moderngl.NEAREST, moderngl.NEAREST)
            t.repeat_x = t.repeat_y = False
            t.write(np.array([1.0, 0.0, 0.0, 1.0], dtype="f4").tobytes())
        self.expo_a_fbo = ctx.framebuffer(color_attachments=[self.expo_a_tex])
        self.expo_b_fbo = ctx.framebuffer(color_attachments=[self.expo_b_tex])
        self.exposure_index = 0
        self._hud_key = None

    # ------------------------------------------------------------------
    # HUD 纹理
    # ------------------------------------------------------------------
    def set_hud(self, data: bytes, size: tuple[int, int]) -> None:
        key = (size, len(data))
        if self._hud_tex is None or self._hud_key != key:
            if self._hud_tex is not None:
                try:
                    self._hud_tex.release()
                except Exception:
                    pass
            self._hud_tex = self.ctx.texture(size, 4, data)
            self._hud_tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self._hud_tex.repeat_x = False
            self._hud_tex.repeat_y = False
            self._hud_key = key
        else:
            self._hud_tex.write(data)

    # ------------------------------------------------------------------
    # 点精灵数据
    # ------------------------------------------------------------------
    @staticmethod
    def _clamp(v, lo, hi):
        return max(lo, min(hi, v))

    def _build_points(self, f: SimFrame) -> np.ndarray:
        chunks = []

        # --- 尘埃 ---
        alive = f.dust_alive
        if np.any(alive):
            pos = f.dust_pos[alive]
            dist = np.linalg.norm(pos - f.ship_pos, axis=1)
            col = f.dust_color[alive]
            size = f.dust_size[alive] * np.clip(5.0 / (dist + 1.0), 0.35, 2.2)
            col = col * np.clip(2.2 / (dist + 0.6), 0.15, 1.6)[:, None]
            chunks.append(np.concatenate([pos, col, size[:, None]], axis=1))

        # --- 火花 ---
        if len(f.spark_pos):
            sp = f.spark_pos
            dist = np.linalg.norm(sp - f.ship_pos, axis=1)
            size = f.spark_size * np.clip(6.0 / (dist + 1.0), 0.4, 2.5)
            col = f.spark_color * np.clip(3.0 / (dist + 0.8), 0.2, 2.0)[:, None]
            chunks.append(np.concatenate([sp, col, size[:, None]], axis=1))

        # --- 亚光速逃亡飞船: 核心 + 光晕 + 尾迹 ---
        rows = []
        for s in f.refugees:
            if not s.alive:
                continue
            dist = float(np.linalg.norm(s.pos - f.ship_pos))
            scale = self._clamp(8.0 / (dist + 2.0), 0.35, 1.8)
            base = np.array(s.spec.color)
            # 尾迹
            trail = s.trail
            for i, p in enumerate(trail):
                a = (i + 1) / max(1, len(trail))
                d = float(np.linalg.norm(p - f.ship_pos))
                rows.append([*p, *(base * 0.55 * a * a), 1.1 * scale * a + 0.4])
            core = base * 2.4 + np.array([0.5, 0.5, 0.5])
            rows.append([*s.pos, *core, 13.0 * scale * 1.8])
            rows.append([*s.pos, *(base * 0.55), 52.0 * scale])
            if s.collapsing:
                flash = base * 3.5 * (1.0 - s.anim)
                rows.append([*s.pos, *flash, 40.0 * scale * (1.0 + 2.0 * s.anim)])
        if rows:
            chunks.append(np.array(rows, dtype=np.float64))

        # --- 二维化笔尖的辉光 ---
        pen_x, pen_z = f.pen[0], f.pen[1]
        if f.progress < 0.999:
            p = np.array([pen_x, 0.06, pen_z])
            d = float(np.linalg.norm(p - f.ship_pos))
            scale = self._clamp(8.0 / (d + 2.0), 0.4, 2.0)
            rows = [
                [*p, 3.2, 2.6, 1.6, 38.0 * scale],
                [*p, 1.5, 2.2, 2.4, 90.0 * scale],
                [pen_x, 0.9, pen_z, 0.7, 1.3, 1.7, 130.0 * scale],
            ]
            chunks.append(np.array(rows, dtype=np.float64))

        if not chunks:
            return np.zeros((0, 7), dtype="f4")
        data = np.concatenate(chunks, axis=0).astype("f4")
        return data

    def _upload_points(self, data: np.ndarray) -> None:
        n = data.shape[0]
        if n > self.point_capacity:
            self.point_capacity = int(n * 1.5)
            self.point_vbo.release()
            self.point_vao.release()
            self._init_points()
        if n:
            self.point_vbo.write(np.ascontiguousarray(data).tobytes())
        self.point_count = n

    # ------------------------------------------------------------------
    # 渲染
    # ------------------------------------------------------------------
    def render(self, f: SimFrame, *, time: float, hud_on: bool = True,
               relativity_on: bool = True, flatten: float = 0.0,
               flash: float = 0.0, gain: float = 1.0, vignette: float = 1.0,
               dt: float = 1.0 / 60.0) -> None:
        ctx = self.ctx
        beta = f.beta if relativity_on else 0.0
        gamma = relativity.gamma_of(beta)
        tan_half = math.tan(math.radians(C.SHIP_FOV_DEG) * 0.5)
        aspect = self.render_size[0] / self.render_size[1]

        # ---------------- 1. 世界 ----------------
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.disable(moderngl.BLEND)
        self.scene_fbo.use()
        ctx.viewport = (0, 0, self.render_size[0], self.render_size[1])
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        prog = self.prog_world
        self._set_paint_samplers(prog)
        self._u(prog, "u_res", self.render_size)
        self._u(prog, "u_cam_right", _vec3(f.cam_right))
        self._u(prog, "u_cam_up", _vec3(f.cam_up))
        self._u(prog, "u_cam_fwd", _vec3(f.cam_fwd))
        self._u(prog, "u_tan_half_fov", tan_half)
        self._u(prog, "u_aspect", aspect)
        self._u(prog, "u_ship_pos", _vec3(f.ship_pos))
        self._u(prog, "u_escape", _vec3(f.escape_dir))
        self._u(prog, "u_beta", beta)
        self._u(prog, "u_gamma", gamma)
        self._u(prog, "u_progress", f.progress)
        self._u(prog, "u_wave_r", f.wave_r)
        self._u(prog, "u_time", time)

        planet_pos = np.zeros((8, 4), dtype="f4")
        planet_aux = np.zeros((8, 4), dtype="f4")
        planet_col = np.zeros((8, 4), dtype="f4")
        n = min(8, len(f.planet_pos))
        for i in range(n):
            planet_pos[i, :3] = f.planet_pos[i]
            planet_pos[i, 3] = f.planet_radius[i]
            planet_aux[i, 0] = float(f.planet_squash[i])
            planet_aux[i, 1] = float(f.planet_flash[i])
            planet_aux[i, 2] = float(f.planet_alive[i])
            planet_col[i, :3] = f.planet_color[i]
        self._uw(prog, "u_planet_pos", planet_pos)
        self._uw(prog, "u_planet_aux", planet_aux)
        self._uw(prog, "u_planet_col", planet_col)

        marks = f.marks[:24]
        mark_a = np.zeros((24, 4), dtype="f4")
        mark_b = np.zeros((24, 4), dtype="f4")
        mark_c = np.zeros((24, 4), dtype="f4")
        for i, m in enumerate(marks):
            mark_a[i] = (m.x, m.z, m.size, m.reveal)
            mark_b[i, :3] = m.color
            mark_b[i, 3] = m.flash
            mark_c[i, :2] = (m.dir_x, m.dir_z)
        self._uw(prog, "u_mark_a", mark_a)
        self._uw(prog, "u_mark_b", mark_b)
        self._uw(prog, "u_mark_c", mark_c)
        self._u(prog, "u_nmarks", len(marks))

        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

        # ---------------- 2. 点精灵 ----------------
        points = self._build_points(f)
        self._upload_points(points)
        if self.point_count:
            pprog = self.prog_points
            self._u(pprog, "u_ship_pos", _vec3(f.ship_pos))
            self._u(pprog, "u_escape", _vec3(f.escape_dir))
            self._u(pprog, "u_cam_right", _vec3(f.cam_right))
            self._u(pprog, "u_cam_up", _vec3(f.cam_up))
            self._u(pprog, "u_cam_fwd", _vec3(f.cam_fwd))
            self._u(pprog, "u_beta", beta)
            self._u(pprog, "u_gamma", gamma)
            self._u(pprog, "u_tan_half_fov", tan_half)
            self._u(pprog, "u_aspect", aspect)
            self._u(pprog, "u_px_scale", self.render_size[1] / 900.0)
            ctx.enable(moderngl.BLEND)
            ctx.blend_func = (moderngl.ONE, moderngl.ONE)
            self.point_vao.render(moderngl.POINTS, self.point_count)
            ctx.disable(moderngl.BLEND)

        rw, rh = self.render_size
        # ---------------- 3. bloom ----------------
        ctx.disable(moderngl.BLEND)
        self.bloom1_fbo.use()
        ctx.viewport = (0, 0, self.b1a_tex.size[0], self.b1a_tex.size[1])
        prog = self.prog_bright
        self._u(prog, "u_src", 0)
        self._u(prog, "u_src_texel", (1.0 / rw, 1.0 / rh))
        self._u(prog, "u_threshold", 1.1)
        self._u(prog, "u_knee", 0.6)
        self.scene_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

        self._blur_pass(self.b1a_tex, self.bloom1b_fbo, True)
        self._blur_pass(self.b1b_tex, self.bloom1_fbo, False)

        # 第二级 bloom (更宽)
        self.bloom2_fbo.use()
        ctx.viewport = (0, 0, self.b2a_tex.size[0], self.b2a_tex.size[1])
        prog = self.prog_bright
        self._u(prog, "u_src", 0)
        self._u(prog, "u_src_texel", (1.0 / self.b1a_tex.size[0], 1.0 / self.b1a_tex.size[1]))
        self._u(prog, "u_threshold", 0.0)
        self._u(prog, "u_knee", 0.5)
        self.b1a_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)
        self._blur_pass(self.b2a_tex, self.bloom2b_fbo, True)
        self._blur_pass(self.b2b_tex, self.bloom2_fbo, False)

        # ---------------- 4. 自动曝光 ----------------
        self.lum1_fbo.use()
        ctx.viewport = (0, 0, self.lum1_tex.size[0], self.lum1_tex.size[1])
        prog = self.prog_lum
        self._u(prog, "u_src", 0)
        self._u(prog, "u_src_size", (float(rw), float(rh)))
        self._u(prog, "u_out_size", (float(self.lum1_tex.size[0]), float(self.lum1_tex.size[1])))
        self._u(prog, "u_packed", 0)
        self.scene_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

        self.lum2_fbo.use()
        ctx.viewport = (0, 0, self.lum2_tex.size[0], self.lum2_tex.size[1])
        self._u(prog, "u_src", 0)
        self._u(prog, "u_src_size", (float(self.lum1_tex.size[0]), float(self.lum1_tex.size[1])))
        self._u(prog, "u_out_size", (float(self.lum2_tex.size[0]), float(self.lum2_tex.size[1])))
        self._u(prog, "u_packed", 1)
        self.lum1_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

        prev_expo = self.expo_b_tex if self.exposure_index == 0 else self.expo_a_tex
        cur_expo = self.expo_a_tex if self.exposure_index == 0 else self.expo_b_tex
        cur_fbo = self.expo_a_fbo if self.exposure_index == 0 else self.expo_b_fbo
        cur_fbo.use()
        ctx.viewport = (0, 0, 1, 1)
        prog = self.prog_adapt
        self._u(prog, "u_lum", 0)
        self._u(prog, "u_prev", 1)
        self._u(prog, "u_dt", max(1e-4, dt))
        self.lum2_tex.use(0)
        prev_expo.use(1)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)
        exposure_tex = cur_expo
        self.last_expo_tex = exposure_tex

        # ---------------- 5. 合成 ----------------
        self.out_fbo.use()
        ctx.viewport = (0, 0, self.size[0], self.size[1])
        prog = self.prog_composite
        self._u(prog, "u_scene", 0)
        self._u(prog, "u_bloom1", 1)
        self._u(prog, "u_bloom2", 2)
        self._u(prog, "u_exposure", 3)
        self._u(prog, "u_hud", 4)
        self._u(prog, "u_time", time)
        self._u(prog, "u_flatten", flatten)
        self._u(prog, "u_hud_on", 1.0 if (hud_on and self._hud_tex is not None) else 0.0)
        self._u(prog, "u_vignette", vignette)
        self._u(prog, "u_gain", gain)
        self._u(prog, "u_flash", flash)
        self._u(prog, "u_res", (float(self.size[0]), float(self.size[1])))
        self.scene_tex.use(0)
        self.b1a_tex.use(1)
        self.b2a_tex.use(2)
        exposure_tex.use(3)
        if self._hud_tex is not None:
            self._hud_tex.use(4)
        else:
            self.scene_tex.use(4)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)
        self.exposure_index = 1 - self.exposure_index

        # ---------------- 6. 呈现 ----------------
        ctx.screen.use()
        ctx.viewport = (0, 0, self.size[0], self.size[1])
        prog = self.prog_present
        self._u(prog, "u_src", 0)
        self.out_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

    # ------------------------------------------------------------------
    def _blur_pass(self, src_tex, dst_fbo, horizontal: bool) -> None:
        ctx = self.ctx
        w, h = src_tex.size
        dst_fbo.use()
        ctx.viewport = (0, 0, w, h)
        prog = self.prog_blur
        self._u(prog, "u_src", 0)
        self._u(prog, "u_dir", (1.0 / w, 0.0) if horizontal else (0.0, 1.0 / h))
        src_tex.use(0)
        self.quad_vaos[prog].render(moderngl.TRIANGLES, 6)

    # ------------------------------------------------------------------
    # uniform helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _u(prog, name, value) -> None:
        try:
            prog[name].value = value
        except KeyError:
            pass
        except Exception:
            pass

    @staticmethod
    def _uw(prog, name, arr: np.ndarray) -> None:
        try:
            prog[name].write(np.ascontiguousarray(arr, dtype="f4").tobytes())
        except Exception:
            pass

    def _set_paint_samplers(self, prog) -> None:
        self._u(prog, "u_paint_inner", 0)
        self._u(prog, "u_paint_outer", 1)
        self._u(prog, "u_paint_mid", 2)
        self._u(prog, "u_paint_far", 3)
        self.paint_inner.use(0)
        self.paint_outer.use(1)
        self.paint_mid.use(2)
        self.paint_far.use(3)

    # ------------------------------------------------------------------
    def read_output(self) -> np.ndarray:
        """读取 output FBO (RGBA uint8, 行方向为自底向上)."""
        raw = self.out_fbo.read(components=3, dtype="f1")
        w, h = self.size
        return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)

    def read_exposure(self) -> float:
        """读取 1x1 自适应曝光值 (调试用, 会同步 GPU)."""
        try:
            data = self.last_expo_tex.read()
            return float(np.frombuffer(data, dtype="f4")[0])
        except Exception:
            return -1.0
