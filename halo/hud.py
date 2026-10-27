"""HUD: 用 pygame 字体渲染中文仪表盘, 上传为 OpenGL 纹理.

布局 (以 1600x900 为基准, 其余分辨率等比缩放):
    左上   飞船标识 / 相对论读数
    右上   时钟 / 帧率 / 时间压缩
    左下   航程 / 二维化读数
    右下   黄道面俯视小地图 + 事件日志
    底部   操作提示
"""
from __future__ import annotations

import math
import os
import time

import numpy as np
import pygame

from . import config as C
from . import relativity as rel
from . import viewmath
from .sim import SimFrame

FONT_CANDIDATES = (
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
)
MONO_CANDIDATES = (
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\CascadiaMono.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)

C_CYAN = (118, 232, 255)
C_CYAN_DIM = (70, 148, 170)
C_AMBER = (255, 189, 92)
C_RED = (255, 96, 82)
C_GREEN = (126, 255, 190)
C_TEXT = (208, 238, 250)
C_DIM = (110, 150, 168)
C_PANEL = (6, 13, 22, 168)
C_PANEL_EDGE = (54, 120, 145, 150)
C_SAD = (255, 150, 130)
C_ESCAPE = (150, 255, 210)


def _au_str(v: float) -> str:
    if v >= 10_000:
        return f"{v / 1000.0:,.1f}k AU"
    if v >= 1_000:
        return f"{v:,.0f} AU"
    return f"{v:.2f} AU"


def _pick_font(cands) -> str:
    for p in cands:
        if os.path.exists(p):
            return p
    return pygame.font.get_default_font()


class Hud:
    def __init__(self, size: tuple[int, int]):
        self.size = (int(size[0]), int(size[1]))
        self.scale = self.size[1] / 900.0
        self.surface = pygame.Surface(self.size, pygame.SRCALPHA)
        self.font_path = _pick_font(FONT_CANDIDATES)
        self.mono_path = _pick_font(MONO_CANDIDATES)
        self.fonts = {}
        self._last_bytes = None
        self.start_time = time.perf_counter()

    # ------------------------------------------------------------------
    def _f(self, px: float, mono: bool = False) -> pygame.font.Font:
        key = (int(px * self.scale), mono)
        if key not in self.fonts:
            self.fonts[key] = pygame.font.Font(self.mono_path if mono else self.font_path, key[0])
        return self.fonts[key]

    def _text(self, text: str, pos, px: float, color=C_TEXT, mono: bool = False,
              anchor: str = "topleft", alpha: int = 255):
        font = self._f(px, mono)
        surf = font.render(text, True, color)
        if alpha < 255:
            surf.set_alpha(alpha)
        rect = surf.get_rect()
        setattr(rect, anchor, (int(pos[0]), int(pos[1])))
        self.surface.blit(surf, rect)
        return rect

    def _panel(self, rect, alpha: int = 170, edge_alpha: int = 150, radius: int = 10):
        r = pygame.Rect(rect)
        panel = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 0))
        pygame.draw.rect(panel, (6, 13, 22, alpha), panel.get_rect(), border_radius=radius)
        pygame.draw.rect(panel, (54, 120, 145, edge_alpha), panel.get_rect(), width=max(1, int(round(self.scale))),
                         border_radius=radius)
        # 四角装饰
        arm = int(10 * self.scale)
        col = (118, 232, 255, 210)
        for cx, cy, dx, dy in ((0, 0, 1, 1), (r.w, 0, -1, 1), (0, r.h, 1, -1), (r.w, r.h, -1, -1)):
            pygame.draw.line(panel, col, (cx, cy + dy * arm), (cx, cy), width=1)
            pygame.draw.line(panel, col, (cx, cy), (cx + dx * arm, cy), width=1)
        self.surface.blit(panel, r.topleft)

    def _bar(self, rect, value: float, color=C_CYAN, bg=(20, 40, 52, 190), ticks: int = 10):
        r = pygame.Rect(rect)
        bar = pygame.Surface((r.w, r.h), pygame.SRCALPHA)
        pygame.draw.rect(bar, bg, bar.get_rect(), border_radius=max(1, r.h // 2))
        w = int(np.clip(value, 0.0, 1.0) * (r.w - 2))
        if w > 1:
            fill = pygame.Surface((w, max(1, r.h - 2)), pygame.SRCALPHA)
            for x in range(w):
                k = x / max(1, w - 1)
                c = (int(color[0] * (0.55 + 0.45 * k)), int(color[1] * (0.55 + 0.45 * k)),
                     int(color[2] * (0.55 + 0.45 * k)), 230)
                pygame.draw.line(fill, c, (x, 0), (x, fill.get_height()))
            bar.blit(fill, (1, 1))
        for i in range(ticks + 1):
            x = 1 + int((r.w - 2) * i / ticks)
            pygame.draw.line(bar, (90, 140, 160, 160), (x, 1), (x, max(2, r.h - 1)), 1)
        self.surface.blit(bar, r.topleft)

    # ------------------------------------------------------------------
    def render(self, f: SimFrame, *, fps: float, relativity_on: bool, hud_hint: bool = True,
               label_points: list[dict] | None = None, intro_t: float = 99.0,
               status_message: tuple[str, float] | None = None) -> bytes:
        s = self.surface
        s.fill((0, 0, 0, 0))
        W, H = self.size
        sc = self.scale
        pad = 26 * sc

        # ---------------- 左上: 船名 + 相对论仪表 ----------------
        self._panel((pad, pad, 372 * sc, 236 * sc))
        x0 = pad + 18 * sc
        y0 = pad + 14 * sc
        self._text(f"{C.SHIP_NAME_ZH} · {C.SHIP_NAME_EN}", (x0, y0), 25, C_CYAN)
        self._text("曲率驱动 / 二维化逃逸观察窗", (x0, y0 + 33 * sc), 13, C_DIM)
        pygame.draw.line(s, (70, 150, 175, 170), (x0, y0 + 56 * sc), (x0 + 336 * sc, y0 + 56 * sc), 1)

        # β 大字
        self._text("β", (x0, y0 + 70 * sc), 16, C_DIM)
        self._text(f"{f.beta:.4f}", (x0 + 20 * sc, y0 + 62 * sc), 34, C_TEXT, mono=True)
        self._text(f"γ = {f.gamma:.4f}", (x0 + 190 * sc, y0 + 74 * sc), 18, C_AMBER, mono=True)
        self._bar((x0, y0 + 112 * sc, 336 * sc, 9 * sc), f.beta, C_CYAN)
        self._text(f"光速的 {f.beta * 100:.2f}%   ·   {f.speed_kms:,.0f} km/s",
                   (x0, y0 + 127 * sc), 13, C_TEXT)

        rows = [
            ("固有时流逝率", f"1/{chr(947)} = {f.proper_rate * 100:.1f}%", C_GREEN),
            ("身后星光多普勒", f"D = {f.rear_doppler:.3f}  (redshift)", C_AMBER if f.rear_doppler < 0.9 else C_TEXT),
            ("光行差压缩", f"90{chr(176)} -> {f.aberr_half_angle:.1f}{chr(176)}", C_TEXT),
        ]
        for i, (k, v, col) in enumerate(rows):
            yy = y0 + 152 * sc + i * 24 * sc
            self._text(k, (x0, yy), 13, C_DIM)
            self._text(v, (x0 + 150 * sc, yy), 14, col, mono=True)

        # ---------------- 右上: 时钟 ----------------
        panel_w = 300 * sc
        self._panel((W - pad - panel_w, pad, panel_w, 146 * sc))
        x1 = W - pad - panel_w + 18 * sc
        yy = pad + 14 * sc
        self._text("太阳系坐标时", (x1, yy), 12, C_DIM)
        self._text(viewmath.fmt_duration(f.t_ext), (x1 + 128 * sc, yy - 3 * sc), 18, C_TEXT, mono=True)
        self._text("飞船固有时", (x1, yy + 30 * sc), 12, C_DIM)
        self._text(viewmath.fmt_duration(f.t_proper), (x1 + 128 * sc, yy + 27 * sc), 18, C_GREEN, mono=True)
        self._text("时间压缩", (x1, yy + 60 * sc), 12, C_DIM)
        self._text(f"×{f.time_scale:.0f}", (x1 + 128 * sc, yy + 57 * sc), 16, C_AMBER, mono=True)
        self._text("渲染帧率", (x1, yy + 86 * sc), 12, C_DIM)
        fps_col = C_GREEN if fps >= 50 else (C_AMBER if fps >= 30 else C_RED)
        self._text(f"{fps:5.1f} FPS", (x1 + 128 * sc, yy + 83 * sc), 16, fps_col, mono=True)
        mode = "相对论视觉: 开" if relativity_on else "相对论视觉: 关 (对照/观测)"
        self._text(mode, (x1 + 2 * sc, yy + 112 * sc), 12, C_CYAN if relativity_on else C_AMBER)

        # ---------------- 右侧: 事件日志 ----------------
        log_w = 310 * sc
        log_h = 252 * sc
        lrect = pygame.Rect(W - pad - log_w, pad + 164 * sc, log_w, log_h)
        self._panel(lrect)
        lx = lrect.x + 16 * sc
        ly = lrect.y + 10 * sc
        self._text("事件日志 · LOG", (lx, ly), 13, C_CYAN)
        pygame.draw.line(s, (70, 150, 175, 130), (lx, ly + 20 * sc), (lrect.right - 16 * sc, ly + 20 * sc), 1)
        kind_col = {"info": C_TEXT, "warn": C_AMBER, "danger": C_RED,
                    "sad": C_SAD, "escape": C_ESCAPE}
        events = f.events[-6:]
        for i, ev in enumerate(events):
            ey = ly + 30 * sc + i * 34 * sc
            col = kind_col.get(ev.kind, C_TEXT)
            self._text(viewmath.fmt_duration(ev.t_ext), (lx, ey), 10, C_DIM, mono=True)
            # 简单截断, 避免超出面板
            text = ev.text
            max_chars = int(19 * (310 / 310))
            if len(text) > max_chars:
                text = text[:max_chars - 1] + "…"
            self._text(text, (lx + 62 * sc, ey - 1 * sc), 11, col)

        # ---------------- 左下: 航程 / 二维化 ----------------
        panel_h = 196 * sc
        self._panel((pad, H - pad - panel_h - 42 * sc, 430 * sc, panel_h))
        x2 = pad + 18 * sc
        y2 = H - pad - panel_h - 42 * sc + 13 * sc
        self._text("航程 / 二维化态势", (x2, y2), 14, C_CYAN)
        pygame.draw.line(s, (70, 150, 175, 140), (x2, y2 + 22 * sc), (x2 + 394 * sc, y2 + 22 * sc), 1)
        self._text("日心距", (x2, y2 + 32 * sc), 12, C_DIM)
        self._text(f"{_au_str(f.dist_sun):>10}", (x2 + 82 * sc, y2 + 28 * sc), 17, C_TEXT, mono=True)
        self._text("二维化波前", (x2 + 218 * sc, y2 + 32 * sc), 12, C_DIM)
        self._text(f"{_au_str(f.wave_r):>10}", (x2 + 296 * sc, y2 + 28 * sc), 17, C_AMBER, mono=True)
        gap = f.gap
        danger = gap < 3.0
        self._text("与波前间距", (x2, y2 + 62 * sc), 12, C_DIM)
        self._text(f"{_au_str(gap):>10}", (x2 + 82 * sc, y2 + 58 * sc), 17, C_RED if danger else C_TEXT, mono=True)
        if f.escaped or not math.isfinite(f.eta_real):
            eta = "escape"
        elif f.eta_real < 9999:
            eta = f"{f.eta_real:6.0f} s"
        else:
            eta = f"{f.eta_real / 3600.0:6.1f} h"
        self._text("现实时间余量", (x2 + 218 * sc, y2 + 62 * sc), 12, C_DIM)
        self._text(eta, (x2 + 306 * sc, y2 + 58 * sc), 17, C_RED if danger else C_TEXT, mono=True)
        log_span = math.log(C.ANNULUS_R_NORM / C.ANNULUS_R0)
        logp = math.log(max(f.wave_r, C.ANNULUS_R0 * 1.01) / C.ANNULUS_R0) / log_span
        logp = max(0.0, min(1.0, logp))
        self._text("皮亚诺折叠进度 (对数)", (x2, y2 + 94 * sc), 12, C_DIM)
        self._text(f"{logp * 100:5.1f}%", (x2 + 306 * sc, y2 + 90 * sc), 17, C_CYAN, mono=True)
        self._bar((x2, y2 + 118 * sc, 394 * sc, 8 * sc), logp, C_CYAN, ticks=8)
        k_now = int(max(0, min(C.ANNULUS_COUNT - 1,
                               math.floor(math.log(max(f.wave_r, C.ANNULUS_R0 * 1.01) / C.ANNULUS_R0)
                                          / math.log(C.ANNULUS_Q)))))
        self._text(f"折叠前沿 {_au_str(f.progress * C.ANNULUS_R_NORM)}   ·   希尔伯特环带 {k_now + 1:03d} / {C.ANNULUS_COUNT}",
                   (x2, y2 + 134 * sc), 11, C_DIM)
        n_alive = sum(1 for sh in f.refugees if sh.alive)
        self._text(f"尚未二维化的亚光速飞船: {n_alive} / {len(f.refugees)}",
                   (x2, y2 + 156 * sc), 12, C_TEXT)
        if not relativity_on:
            self._text("相对论视觉关闭 · 对照/观测模式", (x2, y2 + 174 * sc), 12, C_AMBER)

        # ---------------- 右下: 小地图 ----------------
        mm = int(258 * sc)
        mrect = pygame.Rect(W - pad - mm, H - pad - mm - 42 * sc, mm, mm)
        self._panel(mrect, alpha=185)
        self._draw_minimap(f, mrect, sc)

        # ---------------- 底部操作提示 ----------------
        self._text(C.CONTROLS_HINT, (W // 2, H - 26 * sc), 12, C_DIM, anchor="center")
        # 顶部中央标题
        if intro_t < 9.0:
            alpha = int(255 * max(0.0, min(1.0, (9.0 - intro_t) / 2.5)) * min(1.0, intro_t / 0.8))
            cx = W // 2
            self._text("太阳系 · 二维化", (cx, 64 * sc), 34, C_CYAN, anchor="center", alpha=alpha)
            self._text("DEATH'S END  ·  HALO ESCAPE", (cx, 100 * sc), 14, C_DIM, anchor="center", alpha=alpha)

        # ---------------- 警告 ----------------
        if gap < 3.0 and not f.escaped and not f.flattening:
            blink = 0.55 + 0.45 * math.sin(f.t_real * 9.0)
            col = (int(255 * blink), int(70 * blink + 40), int(60 * blink + 30))
            self._text("警告 · 二维化波前正在逼近", (W // 2, 140 * sc), 22, col, anchor="center")
            self._text("按 [空格] 启动全功率曲率驱动逃逸", (W // 2, 170 * sc), 14, C_AMBER, anchor="center")
        if f.escaped:
            self._text("曲率航程 · 已脱离二维化波前", (W // 2, 140 * sc), 22, C_ESCAPE, anchor="center")
        # 状态消息 (如被二维化)
        if status_message is not None:
            msg, t = status_message
            alpha = int(255 * max(0.0, min(1.0, 1.0 - t / 14.0)))
            self._text(msg, (W // 2, H // 2 - 40 * sc), 40, C_RED, anchor="center", alpha=alpha)

        # ---------------- 飞船标签 ----------------
        if label_points:
            for lp in label_points:
                if not lp.get("visible", True):
                    continue
                px, py = lp["px"], lp["py"]
                name = lp["name"]
                col = tuple(lp.get("color", C_TEXT))
                alive = lp.get("alive", True)
                if alive:
                    pygame.draw.circle(s, (*col[:3], 200), (int(px), int(py)), int(3 * sc), 1)
                    self._text(f"「{name}」", (px + 8 * sc, py - 8 * sc), 12, col)
                    self._text(f"{lp['dist']:.1f} AU", (px + 8 * sc, py + 6 * sc), 10, C_DIM)
                else:
                    self._text(f"「{name}」已二维化", (px + 8 * sc, py - 8 * sc), 11, C_SAD, alpha=190)

        # ---------------- 中心准星 ----------------
        if hud_hint:
            cx, cy = W // 2, H // 2
            pygame.draw.circle(s, (110, 220, 245, 130), (cx, cy), int(9 * sc), 1)
            pygame.draw.circle(s, (110, 220, 245, 190), (cx, cy), int(1.6 * sc))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                pygame.draw.line(s, (110, 220, 245, 130),
                                 (cx + dx * 13 * sc, cy + dy * 13 * sc),
                                 (cx + dx * 20 * sc, cy + dy * 20 * sc), 1)

        data = pygame.image.tobytes(s, "RGBA", False)
        self._last_bytes = data
        return data

    # ------------------------------------------------------------------
    def _draw_minimap(self, f: SimFrame, rect: pygame.Rect, sc: float) -> None:
        s = self.surface
        cx = rect.x + rect.w // 2
        cy = rect.y + rect.h // 2
        R_pix = rect.w * 0.40
        R_au = max(34.0, min(C.PLANE_R_TEX, f.wave_r * 1.18))

        def to_px(x: float, z: float):
            return (cx + x / R_au * R_pix, cy + z / R_au * R_pix)

        self._text("黄道面俯视", (rect.x + 12 * sc, rect.y + 8 * sc), 12, C_CYAN)
        self._text(f"R ≤ {_au_str(R_au)}", (rect.right - 12 * sc, rect.y + 9 * sc), 10, C_DIM, anchor="topright")
        clip = pygame.Rect(rect.x + 6, rect.y + 26 * sc, rect.w - 12, rect.h - 34 * sc)
        old_clip = s.get_clip()
        s.set_clip(clip)
        # 仪器距离刻度环 (只是 HUD 网格, 不是行星轨道)
        for frac in (1.0 / 3.0, 2.0 / 3.0):
            rpx = frac * R_pix
            pygame.draw.circle(s, (42, 76, 92, 150), (int(cx), int(cy)), int(rpx), 1)
            lx = cx - rpx * 0.62
            ly = cy + rpx * 0.78
            self._text(_au_str(R_au * frac), (lx, ly), 9, (76, 118, 134), alpha=210)
        # 行星位置 (真实物质, 不再画"轨道圆")
        for i, p in enumerate(C.PLANETS):
            if float(f.planet_alive[i]) < 0.5:
                continue
            px, py = to_px(float(f.planet_pos[i][0]), float(f.planet_pos[i][2]))
            col = tuple(int(c * 255) for c in p.color)
            pygame.draw.circle(s, (*col, 220), (int(px), int(py)), max(1, int(1.7 * sc)))
        # 二维化波前 (fill)
        wr = f.wave_r / R_au * R_pix
        wave_surf = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.circle(wave_surf, (255, 150, 60, 38), (cx - rect.x, cy - rect.y), int(wr))
        pygame.draw.circle(wave_surf, (255, 190, 90, 210), (cx - rect.x, cy - rect.y), int(wr), 1)
        s.blit(wave_surf, rect.topleft)
        # 太阳
        pygame.draw.circle(s, (255, 236, 190, 255), (cx, cy), int(3 * sc))
        pygame.draw.circle(s, (255, 180, 90, 120), (cx, cy), int(7 * sc), 1)
        # 飞船
        sx, sy = to_px(float(f.ship_pos[0]), float(f.ship_pos[2]))
        pygame.draw.circle(s, (120, 240, 255, 255), (int(sx), int(sy)), int(3.2 * sc))
        pygame.draw.circle(s, (120, 240, 255, 110), (int(sx), int(sy)), int(8 * sc), 1)
        # 逃逸方向
        vx, vz = float(f.escape_dir[0]), float(f.escape_dir[2])
        n = math.hypot(vx, vz) or 1.0
        pygame.draw.line(s, (120, 240, 255, 200), (sx, sy),
                         (sx + vx / n * 16 * sc, sy + vz / n * 16 * sc), 1)
        # 亚光速飞船
        for sh in f.refugees:
            if not sh.alive:
                continue
            px, py = to_px(float(sh.pos[0]), float(sh.pos[2]))
            col = tuple(int(c * 255) for c in sh.spec.color)
            pygame.draw.circle(s, (*col, 230), (int(px), int(py)), int(2.0 * sc))
            self._text(sh.spec.marker, (px + 5 * sc, py - 6 * sc), 10, col, alpha=220)
        s.set_clip(old_clip)
        self._text(f"波前 {_au_str(f.wave_r)}", (rect.x + 12 * sc, rect.bottom - 18 * sc), 11, C_AMBER)
