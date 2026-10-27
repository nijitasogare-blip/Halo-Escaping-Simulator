"""基础数学自检: 希尔伯特曲线与狭义相对论公式.

运行:  python tools/verify_physics.py
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from halo import config as C
from halo import hilbert, relativity


def test_hilbert() -> None:
    for order in (1, 2, 3, 4, 5):
        n = 1 << order
        seen = set()
        prev = None
        for d in range(n * n):
            x, y = hilbert.d2xy(order, d)
            assert 0 <= x < n and 0 <= y < n, (d, x, y)
            assert (x, y) not in seen, "非双射"
            seen.add((x, y))
            assert hilbert.xy2d(order, x, y) == d, "逆映射失败"
            if prev is not None:
                assert abs(x - prev[0]) + abs(y - prev[1]) == 1, "相邻序号不相邻"
            prev = (x, y)
    # 向量化版本与标量版本一致
    rng = np.random.default_rng(7)
    order = 4
    n = 1 << order
    xs = rng.integers(0, n, 5000)
    ys = rng.integers(0, n, 5000)
    vec = hilbert.xy2d_np(order, xs, ys)
    for xi, yi, vi in zip(xs[:500], ys[:500], vec[:500]):
        assert hilbert.xy2d(order, int(xi), int(yi)) == int(vi)
    print("[ok] 希尔伯特曲线: 双射 / 相邻 / 逆映射 / 向量化")


def test_reveal_monotone_pieces() -> None:
    # reveal 应落在 [0,1], 且随半径环带整体递增(环带边界处不连续)
    rng = np.random.default_rng(11)
    x = rng.uniform(-35, 35, 20000)
    z = rng.uniform(-35, 35, 20000)
    rv = hilbert.reveal_np(x, z)
    assert np.all(rv >= 0.0) and np.all(rv <= 1.0000001)
    # 同一环带内, 环带号随半径增大; reveal 归一化近似跟随半径
    r = np.hypot(x, z)
    k, rk, dr = hilbert.annulus_params(r)
    approx = (rk + 0.5 * dr) / C.ANNULUS_R_NORM
    err = np.abs(rv - approx)
    assert np.median(err) < 0.35 * (dr / C.ANNULUS_R_NORM).mean() + 1e-6, np.median(err)
    # 笔尖位置与 reveal 一致
    for prog in (0.128, 0.2, 0.35, 0.5, 0.8):
        px, pz, pr, rvv = hilbert.pen_position(prog)
        assert abs(rvv - prog) < 1e-6
        assert abs(hilbert.reveal_scalar(px, pz) - prog) < 2.5 * (hilbert.annulus_params(pr)[2] / C.ANNULUS_R_NORM)
    print("[ok] 二维化 reveal 场 / 笔尖位置")


def test_aberration_roundtrip() -> None:
    rng = np.random.default_rng(3)
    for beta in (0.0, 0.25, 0.5, 0.72, 0.9, 0.99, 0.9995):
        for _ in range(400):
            v = rng.normal(size=3)
            v /= np.linalg.norm(v)
            d_rest = tuple(float(c) for c in v)
            d_app = relativity.apparent_direction(d_rest, beta)
            back = relativity.rest_direction(d_app, beta)
            assert abs(sum(a * b for a, b in zip(back, d_rest)) - 1.0) < 1e-9, (beta, d_rest, back)
            # 两种多普勒公式一致
            d1 = relativity.doppler_from_rest(d_rest, beta)
            d2 = relativity.doppler_from_apparent(d_app, beta)
            assert abs(d1 - d2) < 1e-9, (d1, d2)
            # 与光子四动量的直接洛伦兹变换一致
            g = relativity.gamma_of(beta)
            n = (-d_rest[0], -d_rest[1], -d_rest[2])
            e_ratio = g * (1.0 - beta * n[0])
            assert abs(e_ratio - d1) < 1e-9
            # 表观方向必须仍是单位向量且与逆变换可逆
            assert abs(sum(c * c for c in d_app) - 1.0) < 1e-9
    print("[ok] 光行差往返 / 多普勒公式一致性")


def test_doppler_limits() -> None:
    for beta in (0.3, 0.72, 0.95, 0.999):
        d_rear = relativity.rear_doppler(beta)
        d_fwd = relativity.forward_doppler(beta)
        assert d_rear < 1.0 < d_fwd
        assert abs(d_rear - math.sqrt((1 - beta) / (1 + beta))) < 1e-9
        assert abs(d_fwd - math.sqrt((1 + beta) / (1 - beta))) < 1e-9
        # 多普勒因子与角度: 正横方向 D = 1/gamma
        d_side = relativity.doppler_from_apparent((0.0, 1.0, 0.0), beta)
        assert abs(d_side - 1.0 / relativity.gamma_of(beta)) < 1e-9
    print("[ok] 多普勒极限 / 红移 / 蓝移 / 横向多普勒")


def test_painting_coverage() -> None:
    # 多尺度绘画纹理必须覆盖到奥尔特云, 且层序合理
    assert C.PLANE_R_TEX >= C.OORT_OUTER_OUT >= C.OORT_INNER_OUT >= C.OORT_INNER_IN
    assert C.OORT_INNER_IN > C.SCATTERED_OUT > C.KUIPER_OUT > C.KUIPER_IN > C.ASTEROID_OUT
    assert C.OUTER_R_TEX > C.KUIPER_OUT
    assert C.MID_R_TEX > C.SCATTERED_OUT
    assert C.PLANE_R_TEX > C.MID_R_TEX > C.OUTER_R_TEX > 6.4
    assert C.ANNULUS_R_NORM >= C.PLANE_R_TEX
    # 初始波前应位于火星与木星之间
    assert 1.524 < C.WAVE_R0 < 5.203
    print("[ok] 太阳系多尺度范围 (小行星带→柯伊伯带→奥尔特云) / 初始波前位置")


if __name__ == "__main__":
    test_hilbert()
    test_reveal_monotone_pieces()
    test_aberration_roundtrip()
    test_doppler_limits()
    test_painting_coverage()
    print("\n全部自检通过。")
