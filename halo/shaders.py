"""所有 GLSL 着色器 (OpenGL 3.3 core).

世界着色器是整个作品的视觉核心: 它把"窗外"的太阳系、二维化平面、行星、星空
全部以光线追踪方式解析绘制, 并对每个像素执行:
    * 相对论光行差 (apparent direction <- rest direction)
    * 多普勒频移 + 相对论集束 (D^3)
    * 二维化平面内部的希尔伯特折叠场
"""
from __future__ import annotations

import math

from . import config as C
from . import painting

# --------------------------------------------------------------------------
# 注入常量
# --------------------------------------------------------------------------
DEFINES = f"""#define PI 3.141592653589793
#define ANN_R0 {C.ANNULUS_R0:.16f}
#define ANN_Q {C.ANNULUS_Q:.16f}
#define ANN_LOG_Q {math.log(C.ANNULUS_Q):.16f}
#define ANN_COUNT {float(C.ANNULUS_COUNT):.1f}
#define ANN_RNORM {C.ANNULUS_R_NORM:.16f}
#define HILB_ORDER {C.HILBERT_ORDER}
#define HILB_SIDE {float(1 << C.HILBERT_ORDER):.1f}
#define PLANE_R {C.PLANE_R_TEX:.16f}
#define INNER_R {painting.INNER_R_TEX:.16f}
#define OUTER_R {C.OUTER_R_TEX:.16f}
#define MID_R {C.MID_R_TEX:.16f}
#define MAX_PLANETS 8
#define MAX_MARKS 24
"""

COMMON_FUNCS = r"""
// ---------------------------------------------------------------- hashes
float hash11(float p) {
    p = fract(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return fract(p);
}
float hash12(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float hash13(vec3 p3) {
    p3 = fract(p3 * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
vec3 hash33(vec3 p3) {
    p3 = fract(p3 * vec3(0.1031, 0.1030, 0.0973));
    p3 += dot(p3, p3.yxz + 33.33);
    return fract((p3.xxy + p3.yxx) * p3.zyx);
}

// ---------------------------------------------------------------- value noise
float vnoise(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    vec3 u = f * f * (3.0 - 2.0 * f);
    float n000 = hash13(i + vec3(0.0, 0.0, 0.0));
    float n100 = hash13(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash13(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash13(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash13(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash13(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash13(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash13(i + vec3(1.0, 1.0, 1.0));
    return mix(mix(mix(n000, n100, u.x), mix(n010, n110, u.x), u.y),
               mix(mix(n001, n101, u.x), mix(n011, n111, u.x), u.y), u.z);
}
float fbm3(vec3 p) {
    float a = 0.5;
    float s = 0.0;
    for (int i = 0; i < 4; i++) {
        s += a * vnoise(p);
        p *= 2.07;
        a *= 0.5;
    }
    return s;
}

// ---------------------------------------------------------------- blackbody
vec3 bbColor(float temp) {
    float T = clamp(temp, 1000.0, 40000.0) / 100.0;
    float r, g, b;
    if (T <= 66.0) {
        r = 255.0;
        g = 99.4708025861 * log(T) - 161.1195681661;
    } else {
        r = 329.698727446 * pow(T - 60.0, -0.1332047592);
        g = 288.1221695283 * pow(T - 60.0, -0.0755148492);
    }
    if (T >= 66.0) {
        b = 255.0;
    } else if (T <= 19.0) {
        b = 0.0;
    } else {
        b = 138.5177312231 * log(T - 10.0) - 305.0447927307;
    }
    return clamp(vec3(r, g, b) / 255.0, 0.0, 1.0);
}

// 彩色物体的近似多普勒染色: D>1 偏蓝, D<1 偏红 (视觉化, 强度略微收敛)
vec3 spectralShift(vec3 c, float D) {
    float s = log(clamp(D, 0.02, 80.0)) * 0.35;
    vec3 gain = exp(vec3(-0.55, 0.18, 1.15) * s);
    return c * gain;
}

// ---------------------------------------------------------------- hilbert
int hilbertIndex(ivec2 p) {
    int d = 0;
    int n = 1 << HILB_ORDER;
    int s = n >> 1;
    ivec2 xy = ivec2(clamp(p, ivec2(0), ivec2(n - 1)));
    while (s > 0) {
        int rx = (xy.x & s) != 0 ? 1 : 0;
        int ry = (xy.y & s) != 0 ? 1 : 0;
        d += s * s * ((3 * rx) ^ ry);
        if (ry == 0) {
            if (rx == 1) {
                xy.x = s - 1 - xy.x;
                xy.y = s - 1 - xy.y;
            }
            int t = xy.x;
            xy.x = xy.y;
            xy.y = t;
        }
        s >>= 1;
    }
    return d;
}

// 二维化折叠时刻: reveal(p) in [0,1]; 与 Python halo/hilbert.py 完全一致
float revealTime(vec2 p) {
    float r = length(p);
    if (r <= ANN_R0) return 0.0;
    float rc = clamp(r, ANN_R0 * (1.0 + 1e-7), ANN_RNORM * (1.0 - 1e-7));
    float kf = floor(log(rc / ANN_R0) / ANN_LOG_Q);
    kf = clamp(kf, 0.0, ANN_COUNT - 1.0);
    float rk = ANN_R0 * pow(ANN_Q, kf);
    float dr = rk * (ANN_Q - 1.0);
    float rho = clamp((rc - rk) / dr, 0.0, 0.999998);
    float u = atan(p.y, p.x) / (2.0 * PI) + 0.5;
    ivec2 q = ivec2(clamp(u * HILB_SIDE, 0.0, HILB_SIDE - 1.0),
                    clamp(rho * HILB_SIDE, 0.0, HILB_SIDE - 1.0));
    float idx = float(hilbertIndex(q)) / (HILB_SIDE * HILB_SIDE);
    return (rk + dr * idx) / ANN_RNORM;
}

// ---------------------------------------------------------------- window sdf
float sdRoundBox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}
"""

# --------------------------------------------------------------------------
# 世界着色器
# --------------------------------------------------------------------------
WORLD_FRAG = COMMON_FUNCS + r"""
uniform vec2 u_res;
uniform vec3 u_cam_right;
uniform vec3 u_cam_up;
uniform vec3 u_cam_fwd;
uniform float u_tan_half_fov;
uniform float u_aspect;

uniform vec3 u_ship_pos;
uniform vec3 u_escape;
uniform float u_beta;
uniform float u_gamma;

uniform float u_progress;
uniform float u_wave_r;
uniform float u_time;

uniform sampler2D u_paint_inner;
uniform sampler2D u_paint_outer;
uniform sampler2D u_paint_mid;
uniform sampler2D u_paint_far;

uniform vec4 u_planet_pos[MAX_PLANETS];   // xyz + radius
uniform vec4 u_planet_aux[MAX_PLANETS];   // squash, flash, alive, bands
uniform vec4 u_planet_col[MAX_PLANETS];   // rgb + rim

uniform int u_nmarks;
uniform vec4 u_mark_a[MAX_MARKS];         // x, z, size, reveal
uniform vec4 u_mark_b[MAX_MARKS];         // rgb, flash
uniform vec4 u_mark_c[MAX_MARKS];         // dirx, dirz, 0, 0

out vec4 fragColor;

const vec3 SUN_COL = vec3(1.0, 0.86, 0.62);
const vec3 PLANE_N = vec3(0.0, 1.0, 0.0);

// ---------------------------------------------------------------- 平面绘画采样 (四层)
vec3 samplePainting(vec2 p) {
    float r = length(p);
    vec3 c = texture(u_paint_inner, p / (2.0 * INNER_R) + 0.5).rgb;
    c = mix(c, texture(u_paint_outer, p / (2.0 * OUTER_R) + 0.5).rgb,
            smoothstep(INNER_R * 0.80, INNER_R * 0.985, r));
    c = mix(c, texture(u_paint_mid, p / (2.0 * MID_R) + 0.5).rgb,
            smoothstep(OUTER_R * 0.86, OUTER_R * 0.995, r));
    c = mix(c, texture(u_paint_far, p / (2.0 * PLANE_R) + 0.5).rgb,
            smoothstep(MID_R * 0.88, MID_R * 0.995, r));
    return c;
}

// ---------------------------------------------------------------- 星空
vec3 starLayer(vec3 d, float scale, float density, float brightPow, float sizePx, float D) {
    vec3 p = d * scale;
    vec3 id = floor(p);
    vec3 f = p - id;
    vec3 j = hash33(id + vec3(3.1, 7.7, 1.3));
    vec3 sp = vec3(0.2) + 0.6 * j;
    float dist = length(f - sp);
    float h = hash13(id + vec3(17.0, 29.0, 5.0));
    float sel = step(1.0 - density, h);
    float mag = pow(hash13(id + vec3(23.0, 11.0, 41.0)), brightPow);
    float temp = 3000.0 + 9000.0 * pow(hash13(id + vec3(31.0, 3.0, 19.0)), 1.6);
    float radius = sizePx * (0.6 + 1.1 * mag);
    float g = smoothstep(radius, 0.0, dist) * sel * mag;
    vec3 c = bbColor(temp * D);
    return c * g * 9.0;
}

vec3 starField(vec3 d, float D) {
    vec3 c = vec3(0.0);
    c += starLayer(d, 55.0, 0.34, 5.5, 0.085, D) * 1.0;
    c += starLayer(d, 150.0, 0.30, 7.0, 0.065, D) * 0.9;
    c += starLayer(d, 380.0, 0.26, 9.0, 0.050, D) * 0.75;
    // 银河 / 星云
    float bandTilt = dot(d, normalize(vec3(0.28, 0.86, -0.43)));
    float band = exp(-pow(bandTilt * 2.4, 2.0));
    float n1 = fbm3(d * 2.6 + 5.0);
    float n2 = fbm3(d * 7.5 - 3.0);
    vec3 neb = vec3(0.05, 0.09, 0.20) * (0.35 + 0.9 * n1) * (0.35 + band);
    neb += vec3(0.16, 0.07, 0.10) * pow(clamp(n2 - 0.35, 0.0, 1.0), 2.0) * (0.3 + 0.7 * band);
    neb += vec3(0.02, 0.03, 0.06) * band;
    return (c + neb * 0.07) * 2.2;
}

// ---------------------------------------------------------------- 行星
vec3 shadePlanet(int i, vec3 ro, vec3 rd, float sy, vec3 n, vec3 hitPos) {
    vec3 base = u_planet_col[i].rgb;
    float bands = 0.82 + 0.18 * sin(n.y * 26.0 + 3.0 * sin(n.x * 7.0 + n.z * 5.0));
    vec3 L = normalize(-hitPos);
    float ndl = dot(n, L);
    float lit = smoothstep(-0.22, 0.30, ndl);
    vec3 col = base * bands * (0.10 + 1.05 * lit);
    col += base * 0.16 * pow(1.0 - abs(ndl), 2.0);
    // 大气边缘
    float rim = pow(1.0 - max(dot(n, -rd), 0.0), 3.0);
    col += vec3(0.35, 0.65, 1.0) * rim * (0.25 + 0.9 * lit);
    // 二维化压扁时的闪光
    float flatAmount = 1.0 - sy;
    col += vec3(1.0, 0.72, 0.38) * pow(flatAmount, 1.5) * 2.2 * u_planet_aux[i].y;
    return col;
}

void main() {
    vec2 ndc = (gl_FragCoord.xy / u_res) * 2.0 - 1.0;
    vec3 d_app = normalize(u_cam_fwd
        + u_cam_right * (ndc.x * u_aspect * u_tan_half_fov)
        + u_cam_up * (ndc.y * u_tan_half_fov));

    // ---------- 相对论光行差: 表观方向 -> 静止系方向 ----------
    vec3 u = u_escape;
    float b = u_beta;
    float g = u_gamma;
    vec3 n_app = -d_app;
    float npar = dot(n_app, u);
    vec3 nper = n_app - u * npar;
    float den = 1.0 + b * npar;
    vec3 n_rest = u * ((npar + b) / den) + nper / (g * den);
    vec3 d = normalize(-n_rest);
    float D = 1.0 / (g * (1.0 - b * dot(d_app, u)));
    float beam3 = pow(D, 3.0);
    float beam2 = pow(D, 2.0);

    vec3 ro = u_ship_pos;

    // ---------- 二维化平面 ----------
    float planeT = 1e9;
    vec3 planeCol = vec3(0.0);
    float planeCover = 0.0;
    vec2 planePoint = vec2(0.0);
    vec3 bgCol = starField(d, D);
    vec3 col = bgCol;
    if (abs(d.y) > 1e-7) {
        float t = -ro.y / d.y;
        if (t > 0.0) {
            vec2 pp = ro.xz + t * d.xz;
            float rp = length(pp);
            float rev = revealTime(pp);
            float kf = clamp(floor(log(max(rp, 0.001) / ANN_R0) / ANN_LOG_Q), 0.0, ANN_COUNT - 1.0);
            float rkk = ANN_R0 * pow(ANN_Q, kf);
            float drk = rkk * (ANN_Q - 1.0);
            float drn = drk / ANN_RNORM;
            float frac = clamp((rp - rkk) / max(drk, 1e-6), 0.0, 1.0);
            float cov = 1.0 - smoothstep(u_wave_r - max(0.12, 0.30 * drk), u_wave_r + 0.02, rp);
            if (cov > 0.0015) {
                planePoint = pp;
                float mask = 1.0 - smoothstep(u_progress - 0.12 * drn, u_progress + 0.12 * drn, rev);
                vec3 paint = samplePainting(pp);

                // --- 已完成二维化的"油画" ---
                vec3 paintC = pow(max(paint, vec3(0.0)), vec3(1.28));
                vec3 painted = paintC * 1.9 * vec3(0.93, 0.99, 1.10);
                float sr2 = dot(pp, pp);
                painted += SUN_COL * (1.5 * exp(-sr2 / 0.022) + 0.45 * exp(-sr2 / 0.38)
                                    + 0.14 * exp(-sr2 / 3.0));
                float grazing = 1.0 - abs(d.y);
                painted += vec3(0.05, 0.10, 0.17) * pow(grazing, 5.0);
                painted *= 0.92 + 0.08 * hash12(floor(pp / max(0.02, drk * 0.03)));

                // --- 正在被二维化的空间: 能量网格 ---
                float hsh = hash12(floor(pp / max(0.02, drk * 0.40)) + floor(u_time * 0.7));
                float flow = 0.5 + 0.5 * sin(frac * 42.0 - u_time * 1.6
                                             + 3.0 * sin(frac * 14.0 + u_time * 0.5));
                vec3 rawCol = vec3(0.006, 0.014, 0.038);
                rawCol += vec3(0.10, 0.32, 0.62) * (0.10 + 0.55 * pow(flow, 10.0));
                rawCol += vec3(0.20, 0.10, 0.35) * hsh * 0.10;
                rawCol += paintC * 0.030;

                // --- 折叠前线 (希尔伯特蛇形) ---
                float band = exp(-pow((rev - u_progress) / (0.075 * drn), 2.0));
                vec3 edge = vec3(0.72, 1.0, 1.18) * band * 2.2;
                edge += vec3(1.0, 0.62, 0.30) * band * 0.45;
                // 沿希尔伯特曲线最近几个百分点的"折叠笔迹", 让皮亚诺推进方式可见
                float hloc = clamp((rev * ANN_RNORM - rkk) / max(drk, 1e-6), 0.0, 1.0);
                float kc = floor(log(max(u_progress * ANN_RNORM, ANN_R0 * 1.001) / ANN_R0) / ANN_LOG_Q);
                float rc = ANN_R0 * pow(ANN_Q, kc);
                float drc = rc * (ANN_Q - 1.0);
                float hp = clamp((u_progress * ANN_RNORM - rc) / max(drc, 1e-6), 0.0, 1.0);
                float sameAnn = 1.0 - smoothstep(0.35, 0.49, abs(kf - kc));
                float trail = smoothstep(hp - 0.035, hp - 0.020, hloc) * (1.0 - smoothstep(hp - 0.004, hp, hloc));
                edge += vec3(0.85, 1.0, 1.0) * trail * sameAnn * 1.1;
                edge += vec3(0.22, 0.55, 0.85) * exp(-pow((rev - u_progress) / (0.28 * drn), 2.0)) * 0.55;

                // --- 光速推进的平面外缘 ---
                float rimw = max(0.06, 0.11 * drk);
                float rim = exp(-pow((rp - (u_wave_r - 1.7 * rimw)) / rimw, 2.0));
                edge += vec3(0.52, 0.80, 1.05) * rim * 0.85;

                planeCol = mix(rawCol, painted, mask) + edge;
                planeCover = cov;
                planeT = t;
            }
        }
    }

    // ---------- 平面上的物体印记 (行星 / 飞船) ----------
    if (planeT < 1e8) {
        vec2 pp = planePoint;
        for (int i = 0; i < MAX_MARKS; i++) {
            if (i >= u_nmarks) break;
            vec4 A = u_mark_a[i];
            if (u_progress < A.w) continue;
            vec4 B = u_mark_b[i];
            vec4 Cc = u_mark_c[i];
            vec2 dp = pp - A.xy;
            float along = dot(dp, Cc.xy);
            float perp = length(dp - Cc.xy * along);
            float dd = sqrt((along / (A.z * 1.9)) * (along / (A.z * 1.9))
                          + (perp / A.z) * (perp / A.z));
            float glow = exp(-dd * dd * 2.4);
            float core = exp(-dd * dd * 14.0);
            planeCol += B.rgb * (glow * 0.55 + core * 1.5) * (1.0 + B.w * 3.0);
        }
        col = mix(bgCol, planeCol, planeCover);
    }

    // ---------- 行星 ----------
    float bestT = planeT;
    vec3 bestCol = col;
    for (int i = 0; i < MAX_PLANETS; i++) {
        if (u_planet_aux[i].z < 0.5) continue;
        float sy = clamp(u_planet_aux[i].x, 0.02, 1.0);
        float rad = u_planet_pos[i].w;
        vec3 oc = ro - u_planet_pos[i].xyz;
        oc.y /= sy;
        vec3 rd = d;
        rd.y /= sy;
        float a = dot(rd, rd);
        float hb = dot(oc, rd);
        float c2 = dot(oc, oc) - rad * rad;
        float disc = hb * hb - a * c2;
        if (disc < 0.0) {
            // 边缘柔化光晕
            continue;
        }
        float t = (-hb - sqrt(disc)) / a;
        if (t < 0.0005) continue;
        if (t >= bestT) continue;
        vec3 hitPos = ro + t * d;
        vec3 hitLocal = oc + t * rd;
        vec3 nLocal = normalize(hitLocal);
        vec3 nrm = normalize(vec3(nLocal.x, nLocal.y / sy, nLocal.z));
        // 覆盖率抗锯齿
        float hImpact = sqrt(max(0.0, dot(oc, oc) - hb * hb / a));
        float cover = 1.0 - smoothstep(rad * 0.975, rad * 1.025, hImpact);
        vec3 pc = shadePlanet(i, ro, d, sy, nrm, hitPos);
        vec3 prev = bestCol;
        bestCol = mix(prev, pc, cover);
        bestT = t;
    }

    // ---------- 多普勒染色 + 相对论集束 ----------
    vec3 finalCol = spectralShift(max(bestCol, vec3(0.0)), D) * pow(D, 2.0);
    fragColor = vec4(max(finalCol, vec3(0.0)), 1.0);
}
"""


# --------------------------------------------------------------------------
# 点精灵 (尘埃 / 飞船 / 火花)
# --------------------------------------------------------------------------
POINTS_VERT = r"""
in vec3 in_pos;
in vec3 in_col;
in float in_size;

uniform vec3 u_ship_pos;
uniform vec3 u_escape;
uniform vec3 u_cam_right;
uniform vec3 u_cam_up;
uniform vec3 u_cam_fwd;
uniform float u_beta;
uniform float u_gamma;
uniform float u_tan_half_fov;
uniform float u_aspect;
uniform float u_px_scale;

out vec3 v_col;

void main() {
    vec3 rel = in_pos - u_ship_pos;
    float dist = length(rel);
    if (dist < 1e-6) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        return;
    }
    vec3 d_rest = rel / dist;
    vec3 n = -d_rest;
    float npar = dot(n, u_escape);
    vec3 nper = n - u_escape * npar;
    float den = 1.0 - u_beta * npar;
    vec3 napp = u_escape * ((npar - u_beta) / den) + nper / (u_gamma * den);
    vec3 d_app = -normalize(napp);

    float cz = dot(d_app, u_cam_fwd);
    if (cz <= 1e-4) {
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        gl_PointSize = 0.0;
        return;
    }
    float cx = dot(d_app, u_cam_right);
    float cy = dot(d_app, u_cam_up);
    vec2 ndc = vec2((cx / cz) / (u_tan_half_fov * u_aspect), (cy / cz) / u_tan_half_fov);
    gl_Position = vec4(ndc, 0.0, 1.0);

    float D = 1.0 / (u_gamma * (1.0 - u_beta * dot(d_app, u_escape)));
    float s = log(clamp(D, 0.02, 80.0));
    vec3 gain = exp(vec3(-0.5, 0.16, 1.0) * s);
    v_col = in_col * gain * pow(D, 2.2);
    gl_PointSize = clamp(in_size * u_px_scale, 1.0, 180.0);
}
"""

POINTS_FRAG = r"""
in vec3 v_col;
out vec4 fragColor;
void main() {
    vec2 p = gl_PointCoord * 2.0 - 1.0;
    float r2 = dot(p, p);
    if (r2 > 1.0) discard;
    float core = exp(-r2 * 8.0);
    float halo = exp(-r2 * 2.2) * 0.30;
    fragColor = vec4(v_col * (core + halo), 1.0);
}
"""


# --------------------------------------------------------------------------
# 后处理
# --------------------------------------------------------------------------
QUAD_VERT = r"""
in vec2 in_pos;
out vec2 v_uv;
void main() {
    v_uv = in_pos * 0.5 + 0.5;
    gl_Position = vec4(in_pos, 0.0, 1.0);
}
"""

BRIGHT_FRAG = r"""
uniform sampler2D u_src;
uniform vec2 u_src_texel;
uniform float u_threshold;
uniform float u_knee;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec3 c = (texture(u_src, v_uv + vec2(-0.5, -0.5) * u_src_texel).rgb
            + texture(u_src, v_uv + vec2(0.5, -0.5) * u_src_texel).rgb
            + texture(u_src, v_uv + vec2(-0.5, 0.5) * u_src_texel).rgb
            + texture(u_src, v_uv + vec2(0.5, 0.5) * u_src_texel).rgb) * 0.25;
    float l = max(max(c.r, c.g), c.b);
    float s = clamp((l - u_threshold + u_knee) / (2.0 * u_knee), 0.0, 1.0);
    s = s * s;
    fragColor = vec4(c * s, 1.0);
}
"""

BLUR_FRAG = r"""
uniform sampler2D u_src;
uniform vec2 u_dir;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec3 c = texture(u_src, v_uv).rgb * 0.2270270270;
    c += (texture(u_src, v_uv + u_dir * 1.0).rgb + texture(u_src, v_uv - u_dir * 1.0).rgb) * 0.1945945946;
    c += (texture(u_src, v_uv + u_dir * 2.0).rgb + texture(u_src, v_uv - u_dir * 2.0).rgb) * 0.1216216216;
    c += (texture(u_src, v_uv + u_dir * 3.0).rgb + texture(u_src, v_uv - u_dir * 3.0).rgb) * 0.0540540541;
    c += (texture(u_src, v_uv + u_dir * 4.0).rgb + texture(u_src, v_uv - u_dir * 4.0).rgb) * 0.0162162162;
    fragColor = vec4(c, 1.0);
}
"""

LUM_FRAG = r"""
uniform sampler2D u_src;
uniform vec2 u_src_size;
uniform vec2 u_out_size;
uniform int u_packed;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    vec2 texel = 1.0 / u_src_size;
    vec2 stepv = u_src_size / u_out_size * texel;
    float sum = 0.0;
    float cnt = 0.0;
    for (int y = 0; y < 4; y++) {
        for (int x = 0; x < 4; x++) {
            vec2 off = (vec2(float(x), float(y)) + 0.5) / 4.0 - 0.5;
            vec2 uv = v_uv + off * stepv * 4.0;
            if (u_packed == 1) {
                vec2 v = texture(u_src, uv).rg;
                sum += v.r;
                cnt += v.g;
            } else {
                vec3 c = texture(u_src, uv).rgb;
                float lum = dot(c, vec3(0.2126, 0.7152, 0.0722));
                // 只统计"有内容"的像素, 避免大面积纯黑太空把曝光推爆
                float m = step(0.012, lum);
                sum += min(lum, 60.0) * m;
                cnt += m;
            }
        }
    }
    fragColor = vec4(sum, cnt, 0.0, 1.0);
}
"""

ADAPT_FRAG = r"""
uniform sampler2D u_lum;
uniform sampler2D u_prev;
uniform float u_dt;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    float sum = 0.0;
    float cnt = 0.0;
    for (int y = 0; y < 4; y++) {
        for (int x = 0; x < 4; x++) {
            vec2 uv = (vec2(float(x), float(y)) + 0.5) / 4.0;
            vec2 v = texture(u_lum, uv).rg;
            sum += v.r;
            cnt += v.g;
        }
    }
    float lum = sum / max(cnt, 1.0);
    float prev = texture(u_prev, vec2(0.5)).r;
    float target = 0.135 / max(lum, 0.002);
    float k = 1.0 - exp(-u_dt * 2.0);
    float e = mix(prev, clamp(target, 0.30, 2.3), clamp(k, 0.01, 1.0));
    fragColor = vec4(e, 0.0, 0.0, 1.0);
}
"""

COMPOSITE_FRAG = COMMON_FUNCS + r"""
uniform sampler2D u_scene;
uniform sampler2D u_bloom1;
uniform sampler2D u_bloom2;
uniform sampler2D u_exposure;
uniform sampler2D u_hud;

uniform float u_time;
uniform float u_flatten;
uniform float u_hud_on;
uniform float u_vignette;
uniform float u_gain;
uniform float u_flash;
uniform vec2 u_res;

in vec2 v_uv;
out vec4 fragColor;

vec3 aces(vec3 x) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec2 uv = v_uv;
    vec2 cc = uv - 0.5;
    float exposure = texture(u_exposure, vec2(0.5)).r * u_gain;

    // ---------- 场景 + 泛光 + 轻微色散 ----------
    float ca = 0.0011 * (0.35 + 1.4 * dot(cc, cc));
    vec2 uvR = uv + cc * ca;
    vec2 uvB = uv - cc * ca;
    vec3 scene;
    scene.r = texture(u_scene, uvR).r;
    scene.g = texture(u_scene, uv).g;
    scene.b = texture(u_scene, uvB).b;
    vec3 bloom = texture(u_bloom1, uv).rgb * 0.035 + texture(u_bloom2, uv).rgb * 0.018;
    vec3 hdr = (scene + bloom) * exposure;

    // ---------- 二维化吞没效果 ----------
    if (u_flatten > 0.001) {
        float f = clamp(u_flatten, 0.0, 1.0);
        float squash = smoothstep(0.0, 0.55, f);
        vec2 uv2 = vec2(uv.x + 0.020 * sin(uv.y * 210.0 + u_time * 4.0) * f,
                        0.5 + (uv.y - 0.5) * (1.0 - 0.985 * squash));
        vec3 fc = texture(u_scene, uv2).rgb * exposure;
        // "压成油画" 的偏色: 金红 + 暗紫
        float lum = dot(fc, vec3(0.34, 0.5, 0.16));
        vec3 oil = mix(fc, vec3(1.15, 0.58, 0.22) * lum, 0.72 * f);
        oil = mix(oil, vec3(0.75, 0.30, 0.10) * pow(lum, 0.65), 0.45 * f);
        oil += vec3(0.10, 0.03, 0.02) * (0.4 + 0.6 * hash12(floor(gl_FragCoord.xy * 0.5)));
        // 二维化闪白 + 收尾变黑
        hdr = mix(hdr, oil, smoothstep(0.0, 0.30, f));
        hdr += vec3(1.0, 0.86, 0.66) * exp(-f * 6.0) * 1.6;
        hdr = mix(hdr, vec3(0.004, 0.002, 0.004), smoothstep(0.75, 1.0, f) * 0.94);
    }

    vec3 mapped = aces(hdr);
    vec3 col = pow(max(mapped, vec3(0.0)), vec3(1.0 / 2.2));
    // 轻度提高饱和度, 让二维化油画更有层次
    float lumCol = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col = clamp(mix(vec3(lumCol), col, 1.18), 0.0, 1.0);

    // ---------- 窗框 / 舷窗玻璃 ----------
    vec2 wp = vec2((uv.x - 0.5), (uv.y - 0.515));
    float sd = sdRoundBox(wp, vec2(0.452, 0.438), 0.030);
    float inside = smoothstep(0.0015, -0.0025, sd);
    float innerGlow = exp(-abs(sd) * 190.0);
    // 舷窗框: 深色复合装甲 + 冷光边
    vec3 hull = vec3(0.010, 0.014, 0.021);
    hull += vec3(0.018, 0.030, 0.042) * smoothstep(0.35, -0.35, wp.y);
    hull += vec3(0.06, 0.16, 0.20) * innerGlow * 0.85;
    hull += vec3(0.35, 0.75, 0.90) * innerGlow * 0.25;
    // 玻璃: 边缘轻微变暗 + 反射条
    float edgeShade = smoothstep(0.10, 0.0, -sd);
    col *= mix(1.0, 0.55, edgeShade * 0.65 * inside);
    float refl = smoothstep(0.65, 1.0, sin((uv.x + uv.y) * 4.2 + 1.2) * 0.5 + 0.5);
    col += vec3(0.05, 0.09, 0.12) * refl * 0.10 * inside;
    // 玻璃灰尘 / 划痕
    float dust = hash12(floor(gl_FragCoord.xy * 0.85) + 3.0);
    col += (dust - 0.5) * 0.012 * inside;
    // 暗角
    float vig = smoothstep(1.18, 0.30, length(cc * vec2(1.0, 1.12)));
    col *= mix(1.0, 0.42, (1.0 - vig) * u_vignette);

    vec3 finalCol = mix(hull, col, inside);
    // 舷窗外的黑暗区域内也能看到微弱泛光
    finalCol += bloom * exposure * 0.020 * (1.0 - inside);

    // 闪光 (全功率启动时)
    finalCol += vec3(1.0, 0.95, 0.85) * u_flash;

    // ---------- HUD ----------
    if (u_hud_on > 0.5) {
        vec4 h = texture(u_hud, vec2(uv.x, 1.0 - uv.y));
        finalCol = mix(finalCol, h.rgb, clamp(h.a, 0.0, 1.0));
    }

    fragColor = vec4(finalCol, 1.0);
}
"""

PRESENT_FRAG = r"""
uniform sampler2D u_src;
in vec2 v_uv;
out vec4 fragColor;
void main() {
    fragColor = vec4(texture(u_src, v_uv).rgb, 1.0);
}
"""
