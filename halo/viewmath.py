"""相机 / 投影 / 相对论观测的几何工具 (Python 侧, 供 HUD 与截图模式复用)."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from . import relativity

Vec3 = tuple[float, float, float]


def normalize(v: Iterable[float]) -> Vec3:
    a = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        return (0.0, 0.0, 0.0)
    a = a / n
    return (float(a[0]), float(a[1]), float(a[2]))


def ship_frame(escape_dir: Vec3) -> tuple[Vec3, Vec3, Vec3]:
    """根据飞船飞行方向建立飞船系: (forward, right, up).

    forward = 速度方向; right = up_world x forward; up = forward x right.
    """
    fwd = np.asarray(normalize(escape_dir), dtype=np.float64)
    up_world = np.array([0.0, 1.0, 0.0])
    if abs(float(np.dot(fwd, up_world))) > 0.985:
        up_world = np.array([0.0, 0.0, 1.0])
    right = np.cross(up_world, fwd)
    right /= np.linalg.norm(right)
    up = np.cross(fwd, right)
    up /= np.linalg.norm(up)
    return (
        (float(fwd[0]), float(fwd[1]), float(fwd[2])),
        (float(right[0]), float(right[1]), float(right[2])),
        (float(up[0]), float(up[1]), float(up[2])),
    )


def look_direction(fwd: Vec3, right: Vec3, up: Vec3, yaw_rad: float, pitch_rad: float) -> Vec3:
    """飞船系中由 yaw/pitch 得到视线方向."""
    d = (
        math.cos(pitch_rad) * (math.cos(yaw_rad) * fwd[0] + math.sin(yaw_rad) * right[0])
        + math.sin(pitch_rad) * up[0],
        math.cos(pitch_rad) * (math.cos(yaw_rad) * fwd[1] + math.sin(yaw_rad) * right[1])
        + math.sin(pitch_rad) * up[1],
        math.cos(pitch_rad) * (math.cos(yaw_rad) * fwd[2] + math.sin(yaw_rad) * right[2])
        + math.sin(pitch_rad) * up[2],
    )
    return normalize(d)


def camera_basis(fwd: Vec3, right: Vec3, up: Vec3, yaw_rad: float, pitch_rad: float) -> tuple[Vec3, Vec3, Vec3]:
    """相机基: 返回 (cam_right, cam_up, cam_forward) 在飞船系中的表达."""
    f = np.asarray(look_direction(fwd, right, up, yaw_rad, pitch_rad))
    r = np.cross(np.asarray(up), f)
    r /= max(1e-12, np.linalg.norm(r))
    u = np.cross(f, r)
    u /= max(1e-12, np.linalg.norm(u))
    return (
        (float(r[0]), float(r[1]), float(r[2])),
        (float(u[0]), float(u[1]), float(u[2])),
        (float(f[0]), float(f[1]), float(f[2])),
    )


def aberrate_direction(d_rest: Vec3, beta: float, axis: Vec3) -> Vec3:
    """静止系方向 -> 飞船系表观方向 (任意助推方向)."""
    d = np.asarray(normalize(d_rest))
    u = np.asarray(normalize(axis))
    g = relativity.gamma_of(beta)
    n = -d
    n_par = float(np.dot(n, u))
    n_perp = n - u * n_par
    den = 1.0 - beta * n_par
    n_app = u * ((n_par - beta) / den) + n_perp / (g * den)
    n_app /= max(1e-12, np.linalg.norm(n_app))
    return (-float(n_app[0]), -float(n_app[1]), -float(n_app[2]))


def doppler_from_apparent_axis(d_app: Vec3, beta: float, axis: Vec3) -> float:
    u = np.asarray(normalize(axis))
    d = np.asarray(normalize(d_app))
    return 1.0 / (relativity.gamma_of(beta) * max(1e-12, 1.0 - beta * float(np.dot(d, u))))


def doppler_from_rest_axis(d_rest: Vec3, beta: float, axis: Vec3) -> float:
    u = np.asarray(normalize(axis))
    d = np.asarray(normalize(d_rest))
    return relativity.gamma_of(beta) * (1.0 + beta * float(np.dot(d, u)))


def project_apparent(d_app: Vec3, cam_right: Vec3, cam_up: Vec3, cam_fwd: Vec3,
                     tan_half_fov: float, aspect: float, width: float, height: float):
    """把表观方向投到屏幕. 返回 (px, py, depth, on_screen)."""
    r = np.asarray(cam_right)
    u = np.asarray(cam_up)
    f = np.asarray(cam_fwd)
    d = np.asarray(d_app, dtype=np.float64)
    cz = float(np.dot(d, f))
    if cz <= 1e-5:
        return (0.0, 0.0, cz, False)
    cx = float(np.dot(d, r))
    cy = float(np.dot(d, u))
    ndc_x = (cx / cz) / (tan_half_fov * aspect)
    ndc_y = (cy / cz) / tan_half_fov
    px = (ndc_x * 0.5 + 0.5) * width
    py = (1.0 - (ndc_y * 0.5 + 0.5)) * height
    on = (-1.05 <= ndc_x <= 1.05) and (-1.05 <= ndc_y <= 1.05)
    return (px, py, cz, on)


def project_world_point(world_pos: Vec3, ship_pos: Vec3, beta: float, axis: Vec3,
                        cam_right: Vec3, cam_up: Vec3, cam_fwd: Vec3,
                        tan_half_fov: float, aspect: float, width: float, height: float,
                        fov_scale: float = 1.0):
    """世界坐标 -> 屏幕坐标 (含光行差). 返回 (px, py, depth, on_screen)."""
    rel = np.asarray(world_pos, dtype=np.float64) - np.asarray(ship_pos, dtype=np.float64)
    dist = float(np.linalg.norm(rel))
    if dist < 1e-9:
        return (0.0, 0.0, 0.0, False)
    d_rest = (float(rel[0] / dist), float(rel[1] / dist), float(rel[2] / dist))
    d_app = aberrate_direction(d_rest, beta, axis)
    return project_apparent(d_app, cam_right, cam_up, cam_fwd, tan_half_fov * fov_scale, aspect, width, height)


# --------------------------------------------------------------------------
# 中文时间格式化
# --------------------------------------------------------------------------
def fmt_duration(seconds: float) -> str:
    """把秒数格式化为 HH:MM:SS 或 D天 HH:MM:SS."""
    if not math.isfinite(seconds):
        return "--:--:--"
    s = max(0.0, float(seconds))
    if s >= 86400.0:
        d = int(s // 86400)
        s -= d * 86400
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = int(s % 60)
        return f"{d}天 {h:02d}:{m:02d}:{sec:02d}"
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def fmt_au(au: float) -> str:
    """AU 距离格式化, 带光行时."""
    if not math.isfinite(au):
        return "∞"
    lm = au * 499.004784 / 60.0
    return f"{au:6.2f} AU ({lm:7.1f} 光分)"
