"""星环号 · 二维化逃逸 —— 全局常量与场景配置.

单位约定:
    * 长度: AU (天文单位)
    * 时间: 秒 (太阳系坐标时)
    * 光速: C_AU_S = 1 / 499.004784 AU/s
    * 速度: 以 beta = v / c 表示
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# 基础常数
# --------------------------------------------------------------------------
AU_KM = 149_597_870.7
LIGHT_SECONDS_PER_AU = 499.004784
C_AU_S = 1.0 / LIGHT_SECONDS_PER_AU
DAY_S = 86_400.0
YEAR_S = 365.25 * DAY_S

# --------------------------------------------------------------------------
# 二维化平面 (皮亚诺/希尔伯特遍历)
#
# 绘画纹理采用多尺度分层, 从内太阳系一直覆盖到奥尔特云外缘:
#   inner  0    -  6.4 AU   (太阳、小行星带、内太阳系星尘)
#   outer  6.4  -  80 AU    (外太阳系、完整柯伊伯带、离散盘/类冥天体)
#   mid    80   -  3 000 AU (离散盘外侧、内奥尔特云)
#   far    3 000 - 120 000 AU (奥尔特云主体)
# --------------------------------------------------------------------------
PLANE_R_TEX = 120_000.0    # 最外层绘画纹理覆盖半径 = 奥尔特云外缘 (AU)
OUTER_R_TEX = 80.0         # 外太阳系纹理覆盖半径 (AU)
MID_R_TEX = 3_000.0        # 内奥尔特云纹理覆盖半径 (AU)
PLANE_TEX_SIZE = 2048
OUTER_TEX_SIZE = 2048
MID_TEX_SIZE = 1024
FAR_TEX_SIZE = 1024
INNER_TEX_SIZE = 2048

HILBERT_ORDER = 10         # 每个环带内希尔伯特曲线阶数 (2^10 x 2^10 单元)
ANNULUS_R0 = 0.22          # 最内层环带内半径 (AU)
ANNULUS_Q = 1.14           # 环带等比增长系数
ANNULUS_COUNT = int(math.ceil(math.log(PLANE_R_TEX / ANNULUS_R0) / math.log(ANNULUS_Q)))
ANNULUS_R_NORM = ANNULUS_R0 * (ANNULUS_Q ** ANNULUS_COUNT)  # 归一化最大半径

# 太阳系小天体带 / 奥尔特云 (AU)
ASTEROID_IN, ASTEROID_OUT = 2.06, 3.34
KUIPER_IN, KUIPER_OUT = 30.0, 50.0
SCATTERED_OUT = 1_000.0
OORT_INNER_IN, OORT_INNER_OUT = 2_000.0, 20_000.0
OORT_OUTER_OUT = 120_000.0

# --------------------------------------------------------------------------
# 飞船 "星环号" (Halo) —— 曲率驱动光速飞船
# --------------------------------------------------------------------------
SHIP_NAME_ZH = "星环号"
SHIP_NAME_EN = "HALO"
SHIP_R0 = 13.5            # 初始日心距 (AU)
SHIP_ELEV_DEG = 34.0       # 初始仰角(离开黄道面)
SHIP_AZIM_DEG = 24.0       # 初始方位角
SHIP_BETA0 = 0.62          # 默认 beta
SHIP_BETA_MIN = 0.10
SHIP_BETA_MAX = 0.9995
SHIP_BETA_TARGET_ESCAPE = 0.99935   # 全功率曲率驱动
SHIP_BETA_ESCAPE = 0.999            # 只有 β 达到该值才允许显示“已脱离二维化波前”
SHIP_FOV_DEG = 62.0        # 垂直视场角
SHIP_LOOK_SENS = 0.13      # 鼠标灵敏度 (度/像素)

# --------------------------------------------------------------------------
# 二维化波前
# --------------------------------------------------------------------------
WAVE_R0 = 4.6              # t=0 时二维化波前半径 (AU)
WAVE_SPEED = C_AU_S        # 二维化以光速推进
TIME_SCALE_DEFAULT = 90.0  # 时间压缩倍率(1 现实秒 = N 太阳系秒)
TIME_SCALE_MIN = 5.0
TIME_SCALE_MAX = 800.0

# --------------------------------------------------------------------------
# 行星 (3D 展示半径经过艺术放大, 否则在此尺度下不可见)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class PlanetSpec:
    key: str
    name_zh: str
    name_en: str
    a_au: float            # 轨道半径
    period_days: float
    display_radius: float  # 3D 展示半径 (AU, 艺术放大)
    painted_radius: float  # 二维化后绘画半径 (AU)
    color: tuple[float, float, float]
    rim: tuple[float, float, float]
    angle0_deg: float
    incline_deg: float     # 轨道倾角(很小, 增加立体感)
    bands: float           # 条纹频率


PLANETS: tuple[PlanetSpec, ...] = (
    PlanetSpec("mercury", "水星", "Mercury", 0.387, 87.969, 0.035, 0.30, (0.62, 0.55, 0.50), (0.75, 0.65, 0.55), 35.0, 0.8, 2.0),
    PlanetSpec("venus", "金星", "Venus", 0.723, 224.701, 0.050, 0.34, (1.00, 0.86, 0.58), (1.00, 0.72, 0.35), 142.0, 1.2, 1.0),
    PlanetSpec("earth", "地球", "Earth", 1.000, 365.256, 0.055, 0.36, (0.30, 0.55, 1.00), (0.45, 0.75, 1.00), 258.0, 0.0, 1.0),
    PlanetSpec("mars", "火星", "Mars", 1.524, 686.980, 0.045, 0.32, (0.92, 0.44, 0.30), (1.00, 0.55, 0.35), 318.0, 1.6, 1.0),
    PlanetSpec("jupiter", "木星", "Jupiter", 5.203, 4332.59, 0.230, 0.72, (0.90, 0.78, 0.64), (1.00, 0.82, 0.55), 15.0, 1.1, 7.0),
    PlanetSpec("saturn", "土星", "Saturn", 9.537, 10759.22, 0.200, 0.66, (0.91, 0.82, 0.62), (1.00, 0.90, 0.62), 203.0, 2.2, 5.0),
    PlanetSpec("uranus", "天王星", "Uranus", 19.191, 30685.4, 0.140, 0.48, (0.55, 0.85, 0.90), (0.65, 1.00, 1.00), 78.0, 1.9, 1.0),
    PlanetSpec("neptune", "海王星", "Neptune", 30.069, 60189.0, 0.140, 0.46, (0.35, 0.50, 1.00), (0.55, 0.70, 1.00), 296.0, 2.6, 1.0),
)

# 已被二维化(开局前)的内行星, 其绘画标记直接出现在平面纹理/动态标记里
PREPAINTED_PLANETS = ("mercury", "venus", "earth", "mars")

# --------------------------------------------------------------------------
# 其他逃亡飞船 (亚光速, 艺术虚构)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RefugeeSpec:
    key: str
    name_zh: str
    r0: float          # AU
    azim_deg: float
    elev_deg: float
    speed_c: float     # beta
    color: tuple[float, float, float]
    marker: str        # 单字/双字缩写, 用作 HUD 标签


REFUGEES: tuple[RefugeeSpec, ...] = (
    RefugeeSpec("wangxiang", "望乡", 13.2, 196.0, 7.0, 0.120, (0.55, 0.85, 1.00), "望"),
    RefugeeSpec("zhulong", "烛龙", 16.8, 42.0, 21.0, 0.165, (1.00, 0.72, 0.45), "烛"),
    RefugeeSpec("guzhou", "孤舟", 22.4, 301.0, 13.0, 0.185, (0.65, 1.00, 0.75), "孤"),
    RefugeeSpec("yaolan", "摇篮", 9.6, 108.0, 16.0, 0.085, (1.00, 0.85, 0.70), "摇"),
    RefugeeSpec("xinshi", "信使", 27.6, 252.0, 18.0, 0.145, (0.80, 0.75, 1.00), "信"),
    RefugeeSpec("changcheng", "长城", 9.9, 12.0, 5.0, 0.075, (1.00, 0.55, 0.50), "长"),
    RefugeeSpec("guyuan", "故园", 19.8, 145.0, 9.0, 0.130, (0.70, 0.95, 1.00), "故"),
)

# --------------------------------------------------------------------------
# 视觉 / 调色
# --------------------------------------------------------------------------
COL_HUD_CYAN = (120, 232, 255)
COL_HUD_AMBER = (255, 190, 92)
COL_HUD_RED = (255, 96, 82)
COL_HUD_DIM = (96, 134, 150)
COL_HUD_TEXT = (206, 236, 248)

DUST_COUNT = 520
TRAIL_LEN = 26

# 提示文字
CONTROLS_HINT = "鼠标 环视  ·  滚轮/W S 曲率功率  ·  空格 全功率逃逸  ·  O 观测跳转(快进二维化)  ·  V 相对论对比  ·  R 重启  ·  F12 截图  ·  ESC 退出"
