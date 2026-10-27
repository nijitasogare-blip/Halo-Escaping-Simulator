"""狭义相对论工具: 光行差(aberration)、多普勒因子、黑体颜色.

约定
----
* 太阳系静止系 S；星环号以速度 +beta * x_hat 相对 S 运动。
* ``d_rest``  : 静止系中"由观测者指向光源"的单位方向向量。
* ``d_app``   : 飞船系中"表观"方向(即窗外看到的方位)。
* 光子传播方向 n = -d。
* 从 S 到飞船系 (沿 +x 的洛伦兹助推):
      n'_x = (n_x - beta) / (1 - beta n_x)
      n'_perp = n_perp / (gamma (1 - beta n_x))
* 多普勒因子 D = nu_app / nu_rest = 1 / (gamma (1 - beta * d_app.x))
* 逆变换(给定表观方向恢复静止系方向):
      n_x = (n'_x + beta) / (1 + beta n'_x),  n_perp = n'_perp / (gamma (1 + beta n'_x))
"""
from __future__ import annotations

import math
from typing import Iterable

Vec3 = tuple[float, float, float]


def gamma_of(beta: float) -> float:
    beta = max(-0.999999999, min(0.999999999, float(beta)))
    return 1.0 / math.sqrt(max(1e-12, 1.0 - beta * beta))


def _norm(v: Iterable[float]) -> Vec3:
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z)
    if n <= 0.0:
        return (0.0, 0.0, 0.0)
    return (x / n, y / n, z / n)


def _boost_n_from_rest(n: Vec3, beta: float) -> Vec3:
    """光子传播方向: 静止系 -> 飞船系."""
    g = gamma_of(beta)
    den = 1.0 - beta * n[0]
    return ((n[0] - beta) / den, n[1] / (g * den), n[2] / (g * den))


def _boost_n_to_rest(np_: Vec3, beta: float) -> Vec3:
    """光子传播方向: 飞船系 -> 静止系."""
    g = gamma_of(beta)
    den = 1.0 + beta * np_[0]
    return ((np_[0] + beta) / den, np_[1] / (g * den), np_[2] / (g * den))


def apparent_direction(d_rest: Vec3, beta: float) -> Vec3:
    """静止系光源方向 -> 飞船系表观方向."""
    d_rest = _norm(d_rest)
    n = (-d_rest[0], -d_rest[1], -d_rest[2])
    n_app = _boost_n_from_rest(n, beta)
    return _norm((-n_app[0], -n_app[1], -n_app[2]))


def rest_direction(d_app: Vec3, beta: float) -> Vec3:
    """飞船系表观方向 -> 该光线在静止系中的来源方向."""
    d_app = _norm(d_app)
    n_app = (-d_app[0], -d_app[1], -d_app[2])
    n_rest = _boost_n_to_rest(n_app, beta)
    return _norm((-n_rest[0], -n_rest[1], -n_rest[2]))


def doppler_from_apparent(d_app: Vec3, beta: float) -> float:
    """nu_app / nu_rest, 由表观方向计算."""
    d_app = _norm(d_app)
    return 1.0 / (gamma_of(beta) * max(1e-12, 1.0 - beta * d_app[0]))


def doppler_from_rest(d_rest: Vec3, beta: float) -> float:
    """nu_app / nu_rest, 由静止系来源方向计算."""
    d_rest = _norm(d_rest)
    return gamma_of(beta) * (1.0 + beta * d_rest[0])


def rear_doppler(beta: float) -> float:
    """正后方光源的多普勒因子 (红移)."""
    return doppler_from_apparent((-1.0, 0.0, 0.0), beta)


def forward_doppler(beta: float) -> float:
    """正前方光源的多普勒因子 (蓝移)."""
    return doppler_from_apparent((1.0, 0.0, 0.0), beta)


def aberration_half_angle_deg(beta: float) -> float:
    """静止系中 90 度方向在飞船系中的表观角度(度): acos(beta).

    beta -> 1 时整个星空被压缩进前方半角 ~ 0 的光锥。
    """
    return math.degrees(math.acos(max(-1.0, min(1.0, beta))))


def proper_time_rate(beta: float) -> float:
    """飞船固有时流逝率 d(tau)/d(t) = 1/gamma."""
    return 1.0 / gamma_of(beta)


def relative_velocity_beta(beta: float, obj_velocity_c: Vec3) -> Vec3:
    """飞船系中观测到的物体速度 (以 c 为单位), 用于物体级多普勒.

    输入 obj_velocity_c 为太阳系系中的速度(单位 c)。返回飞船系速度向量。
    使用速度合成公式: 先把飞船系视为相对太阳系 +beta x_hat,
    u' = [u_par - beta, u_perp/gamma] / (1 - beta u_x)
    """
    ux, uy, uz = obj_velocity_c
    g = gamma_of(beta)
    den = 1.0 - beta * ux
    return ((ux - beta) / den, uy / (g * den), uz / (g * den))


def object_doppler(beta: float, d_rest: Vec3, obj_velocity_c: Vec3) -> float:
    """运动光源在飞船系中观测到的多普勒因子(近似, 忽略光行时).

    在物体的瞬时静止系中看飞船, 用合成速度计算:
        D = 1 / (gamma_rel (1 - beta_rel . d_app_rel))
    这里用 d_rest 近似表观方向, 对远离观察者的情形误差很小。
    """
    beta_rel = relative_velocity_beta(beta, obj_velocity_c)
    br = math.sqrt(sum(c * c for c in beta_rel))
    if br < 1e-9:
        return doppler_from_rest(d_rest, beta)
    d_app = apparent_direction(d_rest, beta)  # 近似
    g = gamma_of(br)
    dot = d_app[0] * beta_rel[0] / br + d_app[1] * beta_rel[1] / br + d_app[2] * beta_rel[2] / br
    return 1.0 / (g * max(1e-9, 1.0 - br * dot))


# --------------------------------------------------------------------------
# 黑体颜色 (近似, 用于给恒星按温度上色, 并随多普勒移动色温)
# --------------------------------------------------------------------------
def blackbody_rgb(temp_k: float) -> tuple[float, float, float]:
    """Tanner Helland 近似, 返回线性空间 RGB (0..1)."""
    t = max(1000.0, min(40000.0, temp_k)) / 100.0
    if t <= 66.0:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
    else:
        r = 329.698727446 * ((t - 60.0) ** -0.1332047592)
        g = 288.1221695283 * ((t - 60.0) ** -0.0755148492)
    if t >= 66.0:
        b = 255.0
    elif t <= 19.0:
        b = 0.0
    else:
        b = 138.5177312231 * math.log(t - 10.0) - 305.0447927307
    return (
        max(0.0, min(255.0, r)) / 255.0,
        max(0.0, min(255.0, g)) / 255.0,
        max(0.0, min(255.0, b)) / 255.0,
    )
