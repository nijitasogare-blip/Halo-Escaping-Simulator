"""希尔伯特(皮亚诺)空间填充曲线 —— 二维化"折叠顺序"的核心.

设计
----
二维化平面被划分为若干等比环带 (annulus):

    r in [R0 * Q^k, R0 * Q^(k+1)),   k = 0 .. ANNULUS_COUNT-1

在每个环带内部, 我们建立 (角度 u, 径向 rho) 归一化坐标, 并用量化后的
希尔伯特曲线顺序遍历该环带:

    u   = atan2(z, x) / (2*pi) + 0.5        (0..1)
    rho = (r - r_k) / (r_{k+1} - r_k)       (0..1)
    idx = hilbert_xy2d(floor(u*S), floor(rho*S))       S = 2^HILBERT_ORDER

于是"二维化时刻"为

    reveal(x, z) = (r_k + (r_{k+1}-r_k) * idx / S^2) / R_NORM

它同时满足两个直觉:
    * 宏观上由内向外推进(环带序号递增);
    * 微观上每一圈都由一条希尔伯特蛇形曲线填充 —— 这就是"类似皮亚诺曲线"
      的二维化过程: 波前是一个沿空间填充曲线蔓延的分形折线。

渲染端 (GLSL) 内联实现了同一函数, 两边必须保持一致。
"""
from __future__ import annotations

import numpy as np

from . import config as C


# --------------------------------------------------------------------------
# 基础希尔伯特曲线 (标量 + 向量化)
# --------------------------------------------------------------------------
def d2xy(order: int, d: int) -> tuple[int, int]:
    """希尔伯特曲线: 序号 -> 网格坐标. order=1 => 2x2, order=2 => 4x4."""
    x = y = 0
    s = 1
    t = d
    n = 1 << order
    while s < n:
        rx = 1 & (t // 2)
        ry = 1 & (t ^ rx)
        # rot(s, x, y, rx, ry)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        t //= 4
        s *= 2
    return x, y


def xy2d(order: int, x: int, y: int) -> int:
    """希尔伯特曲线: 网格坐标 -> 序号."""
    d = 0
    s = 1 << (order - 1)
    xx, yy = int(x), int(y)
    while s > 0:
        rx = 1 if (xx & s) else 0
        ry = 1 if (yy & s) else 0
        d += s * s * ((3 * rx) ^ ry)
        # rot(s, xx, yy, rx, ry)
        if ry == 0:
            if rx == 1:
                xx = s - 1 - xx
                yy = s - 1 - yy
            xx, yy = yy, xx
        s >>= 1
    return d


def xy2d_np(order: int, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """向量化 xy2d. x, y 为整数数组, 取值 [0, 2^order)."""
    x = np.asarray(x, dtype=np.int64).copy()
    y = np.asarray(y, dtype=np.int64).copy()
    d = np.zeros(x.shape, dtype=np.int64)
    s = 1 << (order - 1)
    while s > 0:
        rx = (x & s) != 0
        ry = (y & s) != 0
        d += s * s * ((3 * rx.astype(np.int64)) ^ ry.astype(np.int64))
        flip = (~ry) & rx
        x2 = np.where(flip, s - 1 - x, x)
        y2 = np.where(flip, s - 1 - y, y)
        swap = ~ry
        x = np.where(swap, y2, x2)
        y = np.where(swap, x2, y2)
        s >>= 1
    return d


# --------------------------------------------------------------------------
# 环带几何
# --------------------------------------------------------------------------
def annulus_edges() -> np.ndarray:
    """所有环带边界半径, 长度 ANNULUS_COUNT+1."""
    k = np.arange(C.ANNULUS_COUNT + 1, dtype=np.float64)
    return C.ANNULUS_R0 * np.power(C.ANNULUS_Q, k)


def annulus_params(r: np.ndarray | float):
    """给定半径, 返回 (k, r_k, dr) 数组/标量。超出范围时裁剪。"""
    r = np.asarray(r, dtype=np.float64)
    r_safe = np.clip(r, C.ANNULUS_R0 * (1.0 + 1e-9), C.ANNULUS_R_NORM * (1.0 - 1e-9))
    k = np.floor(np.log(r_safe / C.ANNULUS_R0) / np.log(C.ANNULUS_Q)).astype(np.int64)
    k = np.clip(k, 0, C.ANNULUS_COUNT - 1)
    rk = C.ANNULUS_R0 * np.power(C.ANNULUS_Q, k.astype(np.float64))
    dr = rk * (C.ANNULUS_Q - 1.0)
    return (k, rk, dr) if isinstance(r, np.ndarray) else (int(k), float(rk), float(dr))


def reveal_scalar(x: float, z: float) -> float:
    """二维化归一化时刻 reveal(x,z) in [0,1]; 小于 ANNULUS_R0 视为 0."""
    r = float(np.hypot(x, z))
    if r <= C.ANNULUS_R0:
        return 0.0
    if r >= C.ANNULUS_R_NORM:
        r = C.ANNULUS_R_NORM * 0.999999
    k, rk, dr = annulus_params(r)
    rho = (r - rk) / dr
    u = float(np.arctan2(z, x)) / (2.0 * np.pi) + 0.5
    S = 1 << C.HILBERT_ORDER
    ix = min(S - 1, max(0, int(u * S)))
    iy = min(S - 1, max(0, int(rho * S)))
    idx = xy2d(C.HILBERT_ORDER, ix, iy)
    return (rk + dr * (idx / float(S * S))) / C.ANNULUS_R_NORM


def reveal_np(x: np.ndarray, z: np.ndarray) -> np.ndarray:
    """向量化 reveal."""
    x = np.asarray(x, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    r = np.hypot(x, z)
    out = np.zeros(r.shape, dtype=np.float64)
    inner = r <= C.ANNULUS_R0
    r_c = np.clip(r, C.ANNULUS_R0 * (1.0 + 1e-9), C.ANNULUS_R_NORM * (1.0 - 1e-9))
    k, rk, dr = annulus_params(r_c)
    rho = np.clip((r_c - rk) / dr, 0.0, 0.999999)
    u = np.arctan2(z, x) / (2.0 * np.pi) + 0.5
    S = 1 << C.HILBERT_ORDER
    ix = np.clip((u * S).astype(np.int64), 0, S - 1)
    iy = np.clip((rho * S).astype(np.int64), 0, S - 1)
    idx = xy2d_np(C.HILBERT_ORDER, ix, iy)
    val = (rk + dr * (idx.astype(np.float64) / float(S * S))) / C.ANNULUS_R_NORM
    out = np.where(inner, 0.0, val)
    outside = r >= C.ANNULUS_R_NORM
    out = np.where(outside, 1.0, out)
    return out


def pen_position(progress: float) -> tuple[float, float, float, float]:
    """当前"二维化笔尖"在平面上的位置.

    返回 (x, z, r, reveal) —— 波前所在的环带内, 已折入平面的最后一点。
    progress 为 R_wave / R_NORM。
    """
    r_wave = float(np.clip(progress, 0.0, 1.0)) * C.ANNULUS_R_NORM
    if r_wave <= C.ANNULUS_R0:
        return (0.0, 0.0, 0.0, 0.0)
    k, rk, dr = annulus_params(min(r_wave, C.ANNULUS_R_NORM * 0.999999))
    fill = float(np.clip((r_wave - rk) / dr, 0.0, 0.999999))
    S = 1 << C.HILBERT_ORDER
    idx = int(fill * S * S)
    idx = min(S * S - 1, max(0, idx))
    ix, iy = d2xy(C.HILBERT_ORDER, idx)
    u = (ix + 0.5) / S
    rho = (iy + 0.5) / S
    theta = (u - 0.5) * 2.0 * np.pi
    r = rk + dr * rho
    x = r * np.cos(theta)
    z = r * np.sin(theta)
    return (float(x), float(z), float(r), float(r_wave / C.ANNULUS_R_NORM))


def annulus_outer_radius(progress: float) -> float:
    """当前环带外半径 (用于未绘制区域着色等)."""
    r_wave = float(np.clip(progress, 0.0, 1.0)) * C.ANNULUS_R_NORM
    if r_wave <= C.ANNULUS_R0:
        return C.ANNULUS_R0
    k, rk, dr = annulus_params(min(r_wave, C.ANNULUS_R_NORM * 0.999999))
    return min(rk + dr, C.ANNULUS_R_NORM)
