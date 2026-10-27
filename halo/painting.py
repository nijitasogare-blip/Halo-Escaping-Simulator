"""生成"二维化太阳系"多尺度绘画纹理 (从太阳一直到奥尔特云).

渲染端使用四层纹理, 按半径平滑混合:

    inner   0      - 6.4 AU     太阳玫瑰花结 / 小行星带 / 内太阳系星尘
    outer   6.4    - 80 AU      外太阳系 / 完整柯伊伯带 / 类冥天体 / 离散盘内侧
    mid     80     - 3 000 AU   离散盘外侧 / 内奥尔特云
    far     3 000  - 120 000 AU 奥尔特云主体 (内/外奥尔特云)

所有内容都是"世界坐标"的解析函数或哈希点集, 因此各层在重叠区天然一致。

纹理坐标约定 (与 GLSL 一致):
    u = 0.5 + x / (2R),  v = 0.5 + z / (2R)
    numpy rows 对应 v (row 0 -> v = 0 -> z = -R), cols 对应 u。
"""
from __future__ import annotations

import hashlib
import os

import numpy as np
from scipy.ndimage import gaussian_filter, zoom

from . import config as C

INNER_R_TEX = 6.4
PAINTING_VERSION = 19       # 修改绘制逻辑后 +1, 使缓存失效
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")


# --------------------------------------------------------------------------
# 哈希 / 噪声 (世界坐标, 分辨率无关)
# --------------------------------------------------------------------------
def _hash2(ix: np.ndarray, iz: np.ndarray, seed: int) -> np.ndarray:
    u = (ix.astype(np.uint64) & np.uint64(0xFFFFFFFF)) * np.uint64(0x9E3779B185EBCA87)
    v = (iz.astype(np.uint64) & np.uint64(0xFFFFFFFF)) * np.uint64(0xC2B2AE3D27D4EB4F)
    h = u ^ v ^ np.uint64((seed * 0x165667B19E3779F9) & 0xFFFFFFFFFFFFFFFF)
    h ^= h >> np.uint64(33)
    h *= np.uint64(0xFF51AFD7ED558CCD)
    h ^= h >> np.uint64(33)
    h *= np.uint64(0xC4CEB9FE1A85EC53)
    h ^= h >> np.uint64(33)
    return (h & np.uint64(0xFFFFFFFF)).astype(np.float64) / 4294967295.0


def _value_noise(x: np.ndarray, z: np.ndarray, freq: float, seed: int) -> np.ndarray:
    px, pz = x * freq, z * freq
    ix, iz = np.floor(px), np.floor(pz)
    fx, fz = px - ix, pz - iz
    sx = fx * fx * (3.0 - 2.0 * fx)
    sz = fz * fz * (3.0 - 2.0 * fz)
    ixi, izi = ix.astype(np.int64), iz.astype(np.int64)
    c00 = _hash2(ixi, izi, seed)
    c10 = _hash2(ixi + 1, izi, seed)
    c01 = _hash2(ixi, izi + 1, seed)
    c11 = _hash2(ixi + 1, izi + 1, seed)
    top = c00 * (1 - sx) + c10 * sx
    bot = c01 * (1 - sx) + c11 * sx
    return top * (1 - sz) + bot * sz


def _fbm(x: np.ndarray, z: np.ndarray, freq: float, seed: int, octaves: int = 4) -> np.ndarray:
    acc = np.zeros(np.broadcast_shapes(x.shape, z.shape), dtype=np.float64)
    amp = 0.5
    total = 0.0
    for o in range(octaves):
        acc += _value_noise(x, z, freq * (2.0 ** o), seed + o * 17) * amp
        total += amp
        amp *= 0.5
    return acc / total


def _fbm_grid(n: int, r_tex: float, freq: float, seed: int, octaves: int = 4,
              grid: int = 768) -> np.ndarray:
    """在低分辨率世界网格上求 fbm 再双线性放大, 保持世界坐标一致性."""
    gc = (np.arange(grid, dtype=np.float32) + 0.5) / grid * 2.0 - 1.0
    gx = np.broadcast_to((gc[None, :] * r_tex), (grid, grid)).astype(np.float64)
    gz = np.broadcast_to((gc[:, None] * r_tex), (grid, grid)).astype(np.float64)
    low = _fbm(gx, gz, freq, seed, octaves)
    out = zoom(low, (n / grid, n / grid), order=1)
    return out[:n, :n].astype(np.float32)


def _hash_cells_to_points(cell: float, r_max: float, seed: int, density: float):
    """用哈希网格生成世界坐标点集 (位置 x,z, 色温, 亮度)."""
    n = int(np.ceil(r_max / cell)) + 1
    gi = np.arange(-n, n + 1, dtype=np.int64)
    IX, IZ = np.meshgrid(gi, gi)
    cx = (IX + 0.5) * cell
    cz = (IZ + 0.5) * cell
    inside = np.hypot(cx, cz) < r_max
    h1 = _hash2(IX, IZ, seed)
    h2 = _hash2(IX, IZ, seed + 101)
    h3 = _hash2(IX, IZ, seed + 202)
    h4 = _hash2(IX, IZ, seed + 303)
    present = (h1 < density) & inside
    px = (cx + (h2 - 0.5) * cell * 0.72)[present]
    pz = (cz + (h3 - 0.5) * cell * 0.72)[present]
    temp = 2600.0 + 9600.0 * (h4[present] ** 1.7)
    lum = 0.25 + 0.75 * (_hash2(IX, IZ, seed + 404)[present] ** 3.2)
    return px, pz, temp, lum


def _blackbody_rgb_np(temp_k: np.ndarray) -> np.ndarray:
    t = np.clip(temp_k, 1000.0, 40000.0) / 100.0
    r = np.where(t <= 66.0, 255.0,
                 329.698727446 * np.power(np.maximum(t - 60.0, 1e-3), -0.1332047592))
    g = np.where(t <= 66.0,
                 99.4708025861 * np.log(np.maximum(t, 1e-3)) - 161.1195681661,
                 288.1221695283 * np.power(np.maximum(t - 60.0, 1e-3), -0.0755148492))
    b = np.where(t >= 66.0, 255.0,
                 np.where(t <= 19.0, 0.0,
                          138.5177312231 * np.log(np.maximum(t - 10.0, 1e-3)) - 305.0447927307))
    return np.clip(np.stack([r, g, b], axis=-1), 0.0, 255.0) / 255.0


def _splat(canvas: np.ndarray, px, pz, color, sigma_au: float, r_tex: float) -> None:
    """把世界坐标点集叠加为高斯光斑 (sigma 以 AU 计)."""
    if len(px) == 0:
        return
    N = canvas.shape[0]
    ix = np.clip(((px / r_tex * 0.5 + 0.5) * N).astype(np.int64), 0, N - 1)
    iz = np.clip(((pz / r_tex * 0.5 + 0.5) * N).astype(np.int64), 0, N - 1)
    layer = np.zeros((N, N, 3), dtype=np.float32)
    np.add.at(layer, (iz, ix), color.astype(np.float32))
    px_per_au = N / (2.0 * r_tex)
    sigma_px = max(0.55, sigma_au * px_per_au)
    layer = gaussian_filter(layer, sigma=(sigma_px, sigma_px, 0.0))
    canvas += layer


# --------------------------------------------------------------------------
# 空间背景
# --------------------------------------------------------------------------
def _add_space_background(col, x, z, r, r_tex, seed, amp=1.0, freq=0.055):
    neb = _fbm_grid(col.shape[0], r_tex, freq, seed, octaves=4, grid=768)
    neb2 = _fbm_grid(col.shape[0], r_tex, freq * 2.9, seed + 7, octaves=4, grid=768)
    scale = amp
    col += (neb ** 2.6)[..., None] * (np.array([0.034, 0.068, 0.150], np.float32) * scale)
    col += (np.clip(neb2 - 0.58, 0, 1) ** 1.6)[..., None] * (np.array([0.095, 0.031, 0.026], np.float32) * scale)
    col += np.array([0.009, 0.012, 0.026], np.float32)
    col += (np.exp(-(r / (r_tex * 0.22 + 1e-9)) ** 2) * 0.025 * scale)[..., None] * np.array([0.8, 0.95, 1.2], np.float32)


# --------------------------------------------------------------------------
# 小天体带
# --------------------------------------------------------------------------
def _add_asteroid_belt(col, x, z, r, r_tex, seed):
    """主小行星带 2.06–3.34 AU: 明显可见的尘埃带 + 大小分层碎屑 + 明亮主带天体."""
    mid, width = 2.68, 0.66
    haze = np.exp(-((r - mid) / width) ** 2)
    n = _fbm_grid(col.shape[0], r_tex, 0.9, seed + 301, octaves=3, grid=512)
    n2 = _fbm_grid(col.shape[0], r_tex, 0.22, seed + 302, octaves=3, grid=512)
    band = haze * (0.35 + 0.85 * n) * (0.6 + 0.6 * n2)
    col += band[..., None] * np.array([0.150, 0.128, 0.100], np.float32)

    layers = (
        (0.075, 0.55, 0.55, 0.008, (0.82, 0.78, 0.70)),
        (0.045, 0.45, 0.95, 0.006, (0.88, 0.84, 0.76)),
        (0.22, 0.32, 2.30, 0.016, (0.95, 0.90, 0.82)),
        (0.55, 0.10, 3.40, 0.028, (1.00, 0.94, 0.86)),
    )
    for k, (cell, dens, gain, sig, tint) in enumerate(layers):
        px, pz, _temp, lum = _hash_cells_to_points(cell, 3.5, seed + 500 + k * 37, dens)
        rr = np.hypot(px, pz)
        keep = (rr > C.ASTEROID_IN) & (rr < C.ASTEROID_OUT)
        px, pz, lum = px[keep], pz[keep], lum[keep]
        rgb = np.tile(np.array(tint, np.float32), (len(px), 1)) * (gain * (0.55 + 0.75 * lum))[:, None]
        _splat(col, px, pz, rgb, sig, r_tex)

    # 四颗最大的主带天体 (Ceres / Vesta / Pallas / Hygiea)
    bodies = ((2.77, 1.15, 1.00), (2.36, 3.30, 0.85), (2.77, 5.10, 0.75), (3.14, 0.35, 0.55))
    for dist, ang, bright in bodies:
        px = dist * np.cos(ang)
        pz = dist * np.sin(ang)
        rgb = np.array([[1.00, 0.94, 0.82]], np.float32) * (bright * 3.6)
        _splat(col, np.array([px]), np.array([pz]), rgb, 0.030, r_tex)


def _add_kuiper_belt(col, x, z, r, r_tex, seed):
    """柯伊伯带 30–50 AU: 冰质碎屑 + 类冥天体 + 弥漫冰尘."""
    mid, width = 40.0, 8.5
    n = _fbm_grid(col.shape[0], r_tex, 0.045, seed + 611, octaves=4, grid=768)
    n2 = _fbm_grid(col.shape[0], r_tex, 0.012, seed + 612, octaves=3, grid=512)
    haze = np.exp(-((r - mid) / width) ** 2) * (0.30 + 0.90 * n) * (0.55 + 0.75 * n2)
    col += haze[..., None] * np.array([0.030, 0.042, 0.062], np.float32)

    clump = _fbm_grid(col.shape[0], r_tex, 0.035, seed + 613, octaves=3, grid=512)
    layers = (
        (1.30, 0.26, 0.38, 0.24, (0.72, 0.84, 1.00)),
        (0.55, 0.15, 0.65, 0.10, (0.80, 0.90, 1.00)),
        (0.24, 0.075, 1.05, 0.048, (0.88, 0.95, 1.00)),
        (0.10, 0.028, 1.60, 0.022, (0.95, 1.00, 1.00)),
    )
    for k, (cell, dens, gain, sig, tint) in enumerate(layers):
        px, pz, _temp, lum = _hash_cells_to_points(cell, 52.0, seed + 700 + k * 53, dens)
        rr = np.hypot(px, pz)
        keep = (rr > C.KUIPER_IN) & (rr < C.KUIPER_OUT)
        px, pz, lum = px[keep], pz[keep], lum[keep]
        N = col.shape[0]
        ci = np.clip(((px / r_tex * 0.5 + 0.5) * N).astype(np.int64), 0, N - 1)
        cj = np.clip(((pz / r_tex * 0.5 + 0.5) * N).astype(np.int64), 0, N - 1)
        cl = clump[cj, ci]
        mod = 0.35 + 1.5 * cl
        rgb = np.tile(np.array(tint, np.float32), (len(px), 1)) * (gain * (0.45 + 0.9 * lum) * mod)[:, None]
        _splat(col, px, pz, rgb, sig, r_tex)

    # 类冥天体: Pluto / Haumea / Makemake
    bodies = ((39.48, 2.10, 1.00), (43.13, 4.70, 0.70), (45.79, 0.90, 0.62))
    for dist, ang, bright in bodies:
        px = dist * np.cos(ang)
        pz = dist * np.sin(ang)
        rgb = np.array([[0.90, 0.95, 1.00]], np.float32) * (bright * 3.4)
        _splat(col, np.array([px]), np.array([pz]), rgb, 0.10, r_tex)


def _add_scattered_disc(col, x, z, r, r_tex, seed, r_in, r_out,
                        cell=25.0, density=0.30, gain=1.0, sigma=12.0):
    """离散盘: 冰质天体, 从柯伊伯带外缘一直分布到约 1000 AU."""
    freq = max(0.01, 6.0 / r_tex)
    n = _fbm_grid(col.shape[0], r_tex, freq, seed + 811, octaves=3, grid=512)
    haze = (np.clip(n - 0.35, 0, 1) ** 1.5) * np.exp(-r / (0.55 * r_tex)) * 0.35
    col += haze[..., None] * np.array([0.026, 0.036, 0.054], np.float32)

    px, pz, _temp, lum = _hash_cells_to_points(cell, r_out, seed + 900, density)
    rr = np.hypot(px, pz)
    keep = (rr > r_in) & (rr < r_out)
    px, pz, lum = px[keep], pz[keep], lum[keep]
    rgb = np.tile(np.array([0.70, 0.82, 1.00], np.float32), (len(px), 1)) * (gain * (0.35 + 0.75 * lum))[:, None]
    _splat(col, px, pz, rgb, sigma, r_tex)


def _add_oort_cloud(col, x, z, r, r_tex, seed, r_in, r_out, layers, haze_amp=0.40):
    """奥尔特云: 由内向外密度缓慢下降的巨大冰质彗星云.

    layers: ((cell_au, density, gain, sigma_au, tint), ...)
    """
    f1 = _fbm_grid(col.shape[0], r_tex, max(0.004, 8.0 / r_tex), seed + 1001, octaves=4, grid=640)
    f2 = _fbm_grid(col.shape[0], r_tex, max(0.002, 2.0 / r_tex), seed + 1002, octaves=3, grid=512)
    radial = np.clip((r - r_in) / max(1e-6, r_out - r_in), 0.0, 1.0)
    envelope = (1.0 - 0.40 * radial) * np.exp(-np.clip(r - r_in, 0, None) / (0.55 * r_out))
    cloud = np.clip(f1 - 0.30, 0, 1) ** 1.6 * (0.35 + 0.9 * f2)
    col += (cloud * envelope * haze_amp)[..., None] * np.array([0.036, 0.047, 0.068], np.float32)

    for k, (cell, dens, gain, sig, tint) in enumerate(layers):
        n_cells = int(np.ceil(r_out / cell)) + 1
        gi = np.arange(-n_cells, n_cells + 1, dtype=np.int64)
        IX, IZ = np.meshgrid(gi, gi)
        h0 = _hash2(IX, IZ, seed + 1100 + k * 71)
        h1 = _hash2(IX, IZ, seed + 1201 + k * 71)
        h2 = _hash2(IX, IZ, seed + 1302 + k * 71)
        h3 = _hash2(IX, IZ, seed + 1403 + k * 71)
        cx = (IX + (h1 - 0.5) * 0.98) * cell
        cz = (IZ + (h2 - 0.5) * 0.98) * cell
        rr = np.hypot(cx, cz)
        keep = (h0 < dens) & (rr > r_in) & (rr < r_out)
        px = cx[keep]
        pz = cz[keep]
        lum = 0.25 + 0.75 * (h3[keep] ** 2.0)
        if len(px) == 0:
            continue
        rgb = np.tile(np.array(tint, np.float32), (len(px), 1)) * (gain * (0.30 + 0.75 * lum))[:, None]
        _splat(col, px, pz, rgb, sig, r_tex)


# --------------------------------------------------------------------------
# 单张绘画纹理
# --------------------------------------------------------------------------
def _render_painting(size: int, kind: str, seed: int = 20261027) -> np.ndarray:
    N = int(size)
    if kind == "inner":
        r_tex = INNER_R_TEX
    elif kind == "outer":
        r_tex = C.OUTER_R_TEX
    elif kind == "mid":
        r_tex = C.MID_R_TEX
    elif kind == "far":
        r_tex = C.PLANE_R_TEX
    else:
        raise ValueError(kind)

    coord = (np.arange(N, dtype=np.float32) + 0.5) / N * 2.0 - 1.0
    x = np.broadcast_to((coord[None, :] * r_tex), (N, N)).astype(np.float32)
    z = np.broadcast_to((coord[:, None] * r_tex), (N, N)).astype(np.float32)
    r = np.hypot(x, z)
    theta = np.arctan2(z, x)
    r_safe = np.maximum(r, 1e-5)
    col = np.zeros((N, N, 3), dtype=np.float32)

    # ---- 空间背景 -------------------------------------------------------
    if kind in ("inner", "outer"):
        _add_space_background(col, x, z, r, r_tex, seed, amp=1.0, freq=0.055)
        if kind == "outer":
            col *= (0.55 + 0.45 * np.exp(-np.clip(r - 45.0, 0, None) / 45.0))[..., None]
    elif kind == "mid":
        _add_space_background(col, x, z, r, r_tex, seed, amp=0.35, freq=0.0022)
    else:  # far
        _add_space_background(col, x, z, r, r_tex, seed, amp=0.28, freq=0.00006)

    # ---- 逐层内容 -------------------------------------------------------
    if kind == "inner":
        for cell, dens, sig, gain in ((0.55, 0.018, 0.010, 0.9),
                                       (0.17, 0.008, 0.006, 0.55),
                                       (0.062, 0.003, 0.0035, 0.35)):
            px, pz, temp, lum = _hash_cells_to_points(cell, r_tex * 1.01, seed + int(cell * 1000), dens)
            rgb = _blackbody_rgb_np(temp) * (lum * gain)[:, None]
            _splat(col, px, pz, rgb, sig, r_tex)
        grain = _hash2(np.floor(x * 260.0).astype(np.int64), np.floor(z * 260.0).astype(np.int64), seed + 55)
        col += ((grain > 0.9982).astype(np.float32) * 0.045)[..., None] * np.array([0.7, 0.8, 1.0], np.float32)

        _add_asteroid_belt(col, x, z, r, r_tex, seed)

        # 太阳: 被压扁的玫瑰花结
        gran = _fbm_grid(N, r_tex, 9.0, seed + 61, octaves=3, grid=1024)
        disc_edge = 0.255 + 0.012 * (gran - 0.5)
        photosphere = 1.0 / (1.0 + np.exp(np.clip((r - disc_edge) / 0.010, -40.0, 40.0)))
        limb = 0.45 + 0.55 * np.sqrt(np.clip(1.0 - (r / np.maximum(disc_edge, 1e-3)) ** 2, 0.0, 1.0))
        gran_tint = 0.82 + 0.36 * gran
        col += (photosphere * limb * gran_tint)[..., None] * np.array([1.0, 0.88, 0.60], np.float32)
        core = np.exp(-(r / 0.075) ** 2) * 1.8 + np.exp(-(r / 0.26) ** 2) * 0.55
        col += core[..., None] * np.array([1.0, 0.96, 0.84], np.float32)

        logr = np.log(r_safe + 0.02)
        cor_ang = _value_noise(theta * 2.2, logr * 1.7, 6.0, seed + 71)
        halo = np.exp(-r / 0.44) * (0.60 + 1.05 * cor_ang ** 2) + np.exp(-r / 1.6) * 0.055
        rays = (0.5 + 0.5 * np.sin(theta * 23.0 + 3.2 * np.sin(theta * 5.0 + 1.3) + logr * 3.0)) ** 10
        rays *= np.exp(-r / 0.50) * 0.80
        spiral = (0.5 + 0.5 * np.sin(theta * 11.0 - logr * 10.5 + 2.0 * cor_ang)) ** 7
        spiral *= np.exp(-((r - 0.75) / 0.75) ** 2) * 0.75
        fine = (0.5 + 0.5 * np.sin(theta * 83.0 + logr * 34.0)) ** 12
        fine *= np.exp(-((r - 0.5) / 0.5) ** 2) * 0.30
        sun_glow = halo + rays + spiral + fine
        col += sun_glow[..., None] * np.array([1.00, 0.74, 0.40], np.float32)

        wisp = _fbm_grid(N, r_tex, 0.24, seed + 91, octaves=4, grid=768)
        wisp2 = _fbm_grid(N, r_tex, 0.55, seed + 93, octaves=3, grid=768)
        wisp_env = np.exp(-r / 4.5) * (0.55 + 0.45 * np.sin(theta * 3.0 + 1.0))
        wisp_str = np.clip(wisp2 - 0.45, 0, 1) ** 2 * wisp_env
        col += (wisp_str * 0.55)[..., None] * np.array([0.16, 0.24, 0.42], np.float32)
        col += (np.clip(wisp - 0.55, 0, 1) ** 2 * 0.6)[..., None] * np.array([0.28, 0.18, 0.30], np.float32)

        grooves = 0.5 + 0.5 * np.sin(r * 96.0 + np.sin(theta * 3.0) * 1.5 + wisp * 2.0)
        col *= (0.958 + 0.042 * grooves)[..., None]

    elif kind == "outer":
        _add_kuiper_belt(col, x, z, r, r_tex, seed)
        _add_scattered_disc(col, x, z, r, r_tex, seed, C.KUIPER_OUT, C.OUTER_R_TEX,
                            cell=2.2, density=0.35, gain=0.75, sigma=0.28)
        px, pz, temp, lum = _hash_cells_to_points(0.9, r_tex, seed + 1201, 0.18)
        rgb = _blackbody_rgb_np(temp) * (lum * 0.45)[:, None]
        _splat(col, px, pz, rgb, 0.10, r_tex)

    elif kind == "mid":
        _add_scattered_disc(col, x, z, r, r_tex, seed, C.KUIPER_OUT, C.SCATTERED_OUT,
                            cell=55.0, density=0.45, gain=0.95, sigma=9.0)
        _add_oort_cloud(col, x, z, r, r_tex, seed, C.OORT_INNER_IN, C.MID_R_TEX,
                        layers=((90.0, 0.50, 0.90, 24.0, (0.68, 0.82, 1.00)),
                                (320.0, 0.28, 1.60, 70.0, (0.80, 0.90, 1.00))),
                        haze_amp=0.40)

    else:  # far
        _add_oort_cloud(col, x, z, r, r_tex, seed, C.MID_R_TEX, C.PLANE_R_TEX,
                        layers=((1500.0, 0.45, 0.95, 350.0, (0.66, 0.80, 1.00)),
                                (4200.0, 0.30, 1.10, 900.0, (0.78, 0.88, 1.00)),
                                (12000.0, 0.22, 2.40, 1400.0, (0.90, 0.96, 1.00))),
                        haze_amp=0.34)

    # ---- 边缘淡出 --------------------------------------------------------
    edge = np.clip((r_tex - r) / max(0.8, r_tex * 0.0035), 0.0, 1.0)
    col *= edge[..., None]

    col = np.clip(col * 1.15, 0.0, 1.0)
    return (col * 255.0 + 0.5).astype(np.uint8)


# --------------------------------------------------------------------------
# 缓存 / 对外接口
# --------------------------------------------------------------------------
def _texture_spec(kind: str) -> tuple[int, float]:
    if kind == "inner":
        return C.INNER_TEX_SIZE, INNER_R_TEX
    if kind == "outer":
        return C.OUTER_TEX_SIZE, C.OUTER_R_TEX
    if kind == "mid":
        return C.MID_TEX_SIZE, C.MID_R_TEX
    if kind == "far":
        return C.FAR_TEX_SIZE, C.PLANE_R_TEX
    raise ValueError(kind)


def _cache_path(kind: str, size: int, r_tex: float) -> str:
    key = f"{kind}_{size}_{r_tex:.3f}_v{PAINTING_VERSION}"
    h = hashlib.md5(key.encode()).hexdigest()[:10]
    return os.path.join(CACHE_DIR, f"painting_{kind}_{h}.npy")


def build_painting(kind: str, force: bool = False) -> np.ndarray:
    size, r_tex = _texture_spec(kind)
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(kind, size, r_tex)
    if not force and os.path.exists(path):
        try:
            arr = np.load(path, mmap_mode=None)
            if arr.shape == (size, size, 3):
                return arr
        except Exception:
            pass
    arr = _render_painting(size, kind)
    np.save(path, arr)
    return arr


def build_inner_painting(force: bool = False) -> np.ndarray:
    return build_painting("inner", force)


def build_outer_painting(force: bool = False) -> np.ndarray:
    return build_painting("outer", force)


def build_mid_painting(force: bool = False) -> np.ndarray:
    return build_painting("mid", force)


def build_far_painting(force: bool = False) -> np.ndarray:
    return build_painting("far", force)


def build_all_paintings(force: bool = False) -> dict[str, np.ndarray]:
    return {kind: build_painting(kind, force) for kind in ("inner", "outer", "mid", "far")}


def save_painting_png(path: str, array: np.ndarray) -> None:
    from PIL import Image

    Image.fromarray(np.flipud(array), mode="RGB").save(path)


if __name__ == "__main__":
    import time

    for kind in ("inner", "outer", "mid", "far"):
        t0 = time.perf_counter()
        img = build_painting(kind)
        print(f"{kind} painting {img.shape} in {time.perf_counter() - t0:.2f}s")
        save_painting_png(f"shots/painting_{kind}.png", img)
