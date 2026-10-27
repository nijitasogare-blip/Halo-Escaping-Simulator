# HALO · Death's End — Escaping the 2-D Collapse

[中文](README.md) | **English**

> A real-time, **Python 3.13 + OpenGL 3.3** visualization of the Solar System's
> two-dimensional collapse from Liu Cixin's *Death's End* (*Remembrance of Earth's Past #3*):
> you sit inside the light-speed ship **Halo** and look out of its window as the Solar System
> is devoured by a plane expanding at the speed of light.
> Mouse-look around the **Hilbert / Peano-curve** folding front, the flattened planets,
> the asteroid and Kuiper belts, and 7 sub-light refugee ships desperately accelerating away.
> The 2-D painting extends all the way to the **Oort cloud (120,000 AU)**, and everything
> observed from the ship is processed with **special relativity**: aberration, Doppler shift
> and beaming, and time dilation.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![OpenGL](https://img.shields.io/badge/OpenGL-3.3%20Core-5586A4?logo=opengl&logoColor=white)](https://www.opengl.org/)
[![pygame](https://img.shields.io/badge/pygame-2.6-7EC94A)](https://www.pygame.org/)
[![moderngl](https://img.shields.io/badge/moderngl-5.13-FF6F61)](https://moderngl.readthedocs.io/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2011-0078D4)](#requirements)

![HALO · 2-D folding front](screenshots/02_peano_front.png)

**Contents** · [Features](#features-en) · [Quick start](#quickstart-en) · [Controls](#controls-en) ·
[Acceptance](#acceptance-en) · [Physics & algorithms](#physics-en) · [Screenshots](#screenshots-en) ·
[Structure](#structure-en) · [Performance & verification](#perf-en) · [Notes](#notes-en) ·
[Changelog](#changelog-en) · [中文](README.md)

---

<a id="features-en"></a>

## 1. Features

- **Relativity outside the window** — every pixel is relativistic. Aberration, Doppler shift
  and relativistic beaming are applied per ray: as $\beta\to 1$ the whole sky is compressed into
  a forward light cone, the universe behind is red-shifted and dimmed. The HUD shows
  $\beta$, $\gamma$, the proper-time rate, the rear Doppler factor and the aberration angle.
  Press `V` to toggle a "Newtonian" comparison view.
- **Hilbert (Peano-like) 2-D-ization** — the plane is divided into 101 geometrically growing
  annuli; each annulus is folded in the order of a $2^{10}\times 2^{10}$ Hilbert curve.
  The "collapse time" is the distance travelled along the space-filling curve. The light-speed
  front leads the folding pen by about 0.62 of an annulus, so a glowing fractal front is always
  visible.
- **Full-scale Solar System painting** — four multi-scale textures cover everything from the Sun
  out to the **Oort cloud at 120,000 AU**: asteroid belt, full Kuiper belt, scattered disc,
  inner/outer Oort cloud. Flattened planets and ships leave coloured, motion-aligned marks
  on the plane.
- **7 sub-light refugee ships** — engine glow, stretched trails, HUD labels and a top-down
  ecliptic minimap. When the front catches them they are crushed, flash and leave marks in
  the painting, all recorded in the event log.
- **The real "only light speed escapes"** — the 2-D-ization expands at $c$; even
  $\beta=0.99935$ only runs just ahead of the front. If you slow down, the HUD retracts the
  "escaped" banner, shows a finite time-to-impact, and the front eventually consumes the ship.
- **Real-time performance** — 230–290 FPS at 1600×900 (hidden-window GPU render time);
  interactive mode is vsync-locked at 60 FPS.

<a id="quickstart-en"></a>

## 2. Quick Start

### Requirements

- **Python 3.13** (developed and tested with 3.13.12)
- Packages: `numpy`, `scipy`, `Pillow`, `pygame 2.6+`, `moderngl 5.8+`
- A GPU/driver with **OpenGL 3.3 Core**
- Tested on: Windows 11 · Intel Core Ultra 7 155H · Intel Arc Graphics
- CJK fonts: Microsoft YaHei on Windows; Linux/macOS fall back to common CJK fonts
  (Noto Sans CJK, WenQuanYi, PingFang, …).

### Install & run

```bash
git clone https://github.com/nijitasogare-blip/Halo-Escaping-Simulator.git
cd Halo-Escaping-Simulator

python -m pip install -r requirements.txt
python run.py
```

On Windows you can also double-click `run.bat`.

> **First launch** builds four 2-D painting textures (inner $2048^2$, outer $2048^2$,
> mid $1024^2$, far $1024^2$; coverage $0$–$120{,}000$ AU) and caches them in `cache/`.
> This takes about **30 s**; later launches take < 1 s. `cache/` is git-ignored.

### Command-line options

| Option | Meaning |
| --- | --- |
| `--width 1920 --height 1080` | Window size (default 1600×900) |
| `--scale 1.25` | Internal render scale (>1 supersampling, <1 for performance) |
| `--time-scale 45` | Initial time-compression factor (default $90\times$, range $5$–$800\times$) |
| `--beta 0.55` | Initial $\beta$ (default 0.62) |
| `--shots` | Render all acceptance screenshots + GIF in a hidden window, then exit |
| `--no-gif` | Skip GIF generation with `--shots` |
| `--benchmark` | Hidden-window render benchmark |
| `--selftest` | End-to-end self-test (rendering / HUD / relativity / collapse / regressions) |
| `--demo` | Run the main loop for 4 s in a hidden window |

<a id="controls-en"></a>

## 3. Controls

| Input | Action |
| --- | --- |
| **Mouse** | Free first-person look from the cockpit window |
| Wheel / `W` `S` | Curvature-drive throttle ($\beta \in [0.10, 0.9995]$) |
| **`Space`** | Full-power curvature drive ($\beta \to 0.99935$), start escaping the 2-D front |
| **`O`** | **Observation jump**: fast-forward the 2-D front by $5\times$ to inspect the Kuiper belt / Oort cloud; preserves the ship–front separation and does not change the relativistic view |
| `V` | Toggle relativistic vision (aberration + Doppler) for comparison |
| `-` / `=` | Decrease / increase time compression ($5\times$–$800\times$) |
| Arrow keys | Alternative look controls |
| `H` | Toggle HUD |
| `F12` | Save a screenshot to `screenshots/` |
| `F` | Fullscreen |
| `ESC` | Release the mouse / press again to quit |

> The mouse is captured on start. Press `ESC` to release it.
> If the front catches Halo, the "flattened into an oil painting" transition plays and the
> simulation restarts automatically.

<a id="acceptance-en"></a>

## 4. Scene & Acceptance Mapping

| Requirement | Implementation |
| --- | --- |
| **Mouse-look camera** | First-person mouse look with smoothed yaw/pitch; arrow keys as a fallback |
| **Watch the 2-D-ization outside** | A light-speed 2-D plane expanding through the Solar System; Hilbert-curve folding per annulus; visible folding front, energy grid, completed 2-D painting; planets are crushed, disappear and leave marks on the plane |
| **Other sub-light escaping ships** | 7 sub-light ships with engine glow, trails, HUD labels and minimap dots; when caught they are flattened, flash, leave marks and are logged as events |
| **Relativity on a light-speed ship** | Per-pixel aberration, Doppler shift, relativistic beaming and time dilation (coordinate time vs proper time); HUD shows $\beta$, $\gamma$, proper-time rate, rear Doppler and aberration angle; `V` for comparison |
| **Peano-like 2-D-ization** | Each annulus is traversed in the order of a $2^{10}\times 2^{10}$ Hilbert curve; the front is a prefix of the curve, seen as a glowing fractal pen stroke |
| **Asteroid / Kuiper belts / Oort cloud** | Asteroid belt ($2.06$–$3.34$ AU) and Kuiper belt ($30$–$50$ AU) rendered as dust glow + size-layered debris + bright main-belt bodies; the painting covers the scattered disc and inner/outer Oort cloud up to $120{,}000$ AU |
| **Dynamic "escaped" state** | The "escaped the 2-D front" banner appears only while the drive is still at full power and $\beta \ge 0.999$; slowing down or lowering the throttle retracts it and logs "the front is closing in again" |

<a id="physics-en"></a>

## 5. Physics & Algorithms

### 5.1 Special-relativistic observation

Halo moves with $\beta c$ along the unit vector $\hat{u}$ relative to the Solar-System frame.
The Lorentz factor is

$$
\gamma = \frac{1}{\sqrt{1-\beta^2}} .
$$

For every screen pixel:

1. Compute the **apparent direction** $\hat{d}_{\mathrm{app}}$ in the ship frame from the camera pose.
2. Boost the photon back to the rest frame. With $n = -\hat{d}$ the photon propagation direction,

$$
n'_x = \frac{n_x-\beta}{1-\beta n_x},\qquad
n'_\perp = \frac{n_\perp}{\gamma\,(1-\beta n_x)},
$$

   where parallel and perpendicular components are taken with respect to $\hat{u}$.
3. The Doppler factor and relativistic beaming are

$$
D = \frac{1}{\gamma\,\bigl(1-\beta\,\hat{d}_{\mathrm{app}}\cdot\hat{u}\bigr)},\qquad
\nu_{\mathrm{obs}} = D\,\nu_{\mathrm{emit}},\qquad
I_{\mathrm{obs}} = D^3\,I_{\mathrm{emit}} .
$$

   For reference, the aberration relation between the rest-frame angle $\theta$ and the
   apparent angle $\theta'$ is

$$
\tan\frac{\theta'}{2} = \sqrt{\frac{1-\beta}{1+\beta}}\,\tan\frac{\theta}{2}.
$$

   At $\beta=0.9995$ a $90^\circ$ direction is compressed to about $1.8^\circ$, and $D$ varies
   from about $63$ straight ahead to about $0.016$ straight behind.
4. Stars are recoloured as blackbodies with $T_{\mathrm{obs}} = D\,T_{\mathrm{rest}}$;
   coloured surfaces (planets, the 2-D plane) use a per-channel gain plus a $D^2$ brightness
   correction. HUD values of $D$ are exact.
5. Time dilation: $d\tau = dt/\gamma$; the HUD shows both coordinate time and proper time.

### 5.2 2-D plane and Hilbert folding

The plane is split into geometric annuli:

$$
r \in \bigl[R_0 Q^k,\; R_0 Q^{k+1}\bigr),\qquad
R_0 = 0.22\ \mathrm{AU},\quad Q = 1.14,\quad k = 0,\dots,100 .
$$

For a point $(x,z)$ on the plane, with $r = \sqrt{x^2+z^2}$ and $\theta = \mathrm{atan2}(z,x)$:

$$
u = \frac{\theta}{2\pi}+\frac{1}{2},\qquad
\rho = \frac{r-r_k}{r_{k+1}-r_k},
$$

$$
h = \mathrm{Hilbert}_{10}\!\bigl(\lfloor uS\rfloor,\ \lfloor \rho S\rfloor\bigr),
\qquad S = 2^{10},
$$

$$
\mathrm{reveal}(x,z) = \frac{r_k + (r_{k+1}-r_k)\,h/S^2}{R_{\mathrm{norm}}} .
$$

The GLSL renderer and the Python side implement exactly the same function. A pixel with
$\mathrm{reveal}(x,z) < p$ is considered already flattened, where $p$ is the current
folding progress. $p$ lags the plane edge by about $0.62$ annulus widths, leaving a visible
band that is currently being filled by the Hilbert curve; the front is the glowing fractal pen stroke.

### 5.3 Multi-scale 2-D painting textures

| Texture | Range | Content |
| --- | --- | --- |
| `inner` $2048^2$ | $0$ – $6.4$ AU | solar rosette, asteroid belt, inner-system stardust |
| `outer` $2048^2$ | $6.4$ – $80$ AU | full Kuiper belt ($30$–$50$ AU), dwarf planets, inner scattered disc |
| `mid` $1024^2$ | $80$ – $3000$ AU | outer scattered disc, inner Oort cloud |
| `far` $1024^2$ | $3000$ – $120{,}000$ AU | main Oort cloud (icy clouds + comet nuclei) |

Everything is a world-space analytic function or hash-based point set, so the four layers are
naturally consistent and are blended smoothly by radius in the shader.
**Planetary orbits are not drawn as circles** — in reality an orbit is only a trajectory,
there is no visible ring in space. The plane keeps only real matter (Sun, planet positions,
dust belts, stardust) plus the footprints of flattened planets and ships. The concentric circles
on the HUD minimap are merely instrument range rings.

### 5.4 Render pipeline

```text
World ray tracing (HDR RGBA16F)
  ├─ per-pixel relativistic aberration + Doppler
  ├─ nebula / three star layers (blackbody colours)
  ├─ 2-D plane (4 textures + Hilbert reveal + folding stroke + marks + solar glow)
  ├─ 8 planets (squash animation + bands + atmosphere rim + coverage AA)
  └─ star-field occlusion
Point sprites (additive): dust / 7 ships + trails / folding pen / sparks
Bright pass → two-level Gaussian bloom
GPU auto exposure (non-black pixels only)
Composite: ACES tonemapping / slight chromatic dispersion / cockpit frame + glass reflection /
           vignette / 2-D collapse transition / HUD
```

The HUD is rendered with pygame fonts to a Surface and uploaded as a texture: relativistic
readouts, dual clocks, range/situation, Hilbert-annulus index, event log, top-down ecliptic
minimap, ship labels and warnings (Chinese, with CJK font fallback on Linux/macOS).

### 5.5 Ships, planets and the collapse

- Halo flies radially along a fixed escape direction; $\beta$ approaches the user's target
  smoothly and $dr = \beta c\,dt$.
- Planets orbit slowly (artistic licence: display radii are exaggerated ~100–500×,
  otherwise they would be sub-pixel).
- A planet/ship is flattened when the $\mathrm{reveal}$ value at its projected plane
  position is smaller than the current $p$: it is squashed, flashes and leaves a motion-aligned
  mark on the plane.
- When the front catches Halo ($r_{\mathrm{ship}} \le R_{\mathrm{wave}}$), a full-screen
  "flattened into a 2-D painting" transition plays and the scene restarts after 11 s.
- After `Space`, $\beta \to 0.99935$. If you later slow down or lower the throttle, the
  "escaped" banner disappears immediately, a finite time-to-impact appears and the front
  closes in again — this is the physical core of "only light speed escapes".

### 5.6 Observation mode (`O`)

A real 2-D-ization front expanding at $c$ would take tens of thousands of years to reach the
Oort cloud. `O` is a visualization aid: it fast-forwards the front by $5\times$ while
**keeping the ship–front separation** (repeated jumps never force Halo into the plane) and
leaves the relativistic view unchanged. Near $\beta\approx 1$ the outer plane is dimmed by
relativistic beaming; press `V` if you want a brighter inspection view. All HUD physics values
remain exact.

<a id="screenshots-en"></a>

## 6. Screenshots

| First look (relativity ON) | Hilbert folding front |
| --- | --- |
| ![01](screenshots/01_escape_start.png) | ![02](screenshots/02_peano_front.png) |
| **Solar rosette** | **Full power: starlight compressed into a forward cone** |
| ![03](screenshots/03_sun_rosette.png) | ![04](screenshots/04_starbow_fullpower.png) |
| **Comparison mode (`V`)** | **The whole Solar System** |
| ![05](screenshots/05_no_relativity.png) | ![06](screenshots/06_full_system.png) |
| **Kuiper belt (`O` jump)** | **Oort cloud (`O` jump)** |
| ![09](screenshots/09_kuiper_belt.png) | ![10](screenshots/10_oort_cloud.png) |
| **Flattened** | **Close-up of the 2-D plane** |
| ![08](screenshots/08_flattened.png) | ![07](screenshots/07_closeup_plane.png) |

Teaser GIF: [`screenshots/halo_teaser.gif`](screenshots/halo_teaser.gif) (76 frames, slow camera pan)

> `09` and `10` were captured with the `O` observation jump; `V` was used to disable
> relativistic vision so that the outer plane is clearly visible.

Regenerate all screenshots / GIF:

```bash
python run.py --shots --outdir screenshots
```

<a id="structure-en"></a>

## 7. Project Structure

```text
Halo-Escaping-Simulator/
├─ run.py                 entry point (argparse)
├─ run.bat                Windows launcher
├─ requirements.txt
├─ README.md / README.en.md
├─ halo/
│  ├─ config.py           scene constants, planets/ships, palette, multi-scale ranges
│  ├─ relativity.py       aberration / Doppler / blackbody colours
│  ├─ hilbert.py          Hilbert curve + annulus reveal field + pen position
│  ├─ painting.py         four-layer 2-D painting textures (belts + Oort cloud)
│  ├─ sim.py              state machine: ship, front, planets, refugees, dust, sparks, events
│  ├─ viewmath.py         camera basis, projection, labels, time formatting
│  ├─ shaders.py          GLSL: world ray tracing / sprites / bloom / exposure / composite
│  ├─ renderer.py         OpenGL pipeline and FBO/texture management
│  ├─ hud.py              pygame Chinese HUD + minimap + event log
│  └─ app.py              main loop / input / screenshot mode / self-test / benchmark
├─ tools/verify_physics.py  math and scale checks
├─ cache/                 painting-texture cache (generated on first run, git-ignored)
├─ shots/                 debug output (git-ignored)
└─ screenshots/           acceptance screenshots + GIF
```

<a id="perf-en"></a>

## 8. Performance & Verification

Tested on: Windows 11 · Intel Core Ultra 7 155H · Intel Arc Graphics · OpenGL 3.3

```bash
python run.py --benchmark --width 1600 --height 900
# 300 frames @ 1600x900: about 1.0–1.3 s -> 230–290 fps (hidden window, GPU render time, no vsync)
```

Interactive mode is vsync-locked at 60 FPS. `--scale` controls the internal render scale
(1.25 supersamples; 0.7 is useful on low-end machines or remote desktops).

```bash
python tools/verify_physics.py
# Hilbert bijection/inverse/adjacency, aberration round-trips,
# analytic vs four-momentum Doppler consistency, multi-scale Solar-System ranges

python run.py --selftest
# full hidden-window pipeline: look controls / full power / retracting the escape banner /
# re-boosting / repeated observation jumps staying safe / 2-D collapse / reset

python run.py --demo
# run the main loop for 4 s in a hidden window
```

<a id="notes-en"></a>

## 9. Scientific Notes & Artistic Licence

**Rigorous**

- Aberration, Doppler shift, relativistic beaming and time dilation: exact formulas and numbers;
- the 2-D-ization front expands at $c$, so only near-light-speed flight can escape;
- HUD values are exact; the Hilbert folding order is bit-identical between GLSL and Python.

**Artistic licence / known limitations**

- Planetary 3-D display radii are exaggerated by about two orders of magnitude;
- time compression defaults to $90\times$ (shown in the HUD); otherwise the scene would be
  almost static on human timescales;
- the Doppler tint strength is visually damped by a factor of $0.35$; HUD numbers remain exact;
- asteroid/Kuiper/Oort features are brightened and clumped for visibility (real belts are sparser);
- the Hilbert folding order, energy grid and 2-D painting details are an original
  visual interpretation of the novel, not a literal description; the polar mapping has a seam
  at $\theta=\pi$ (the "fold" visible at the annulus seam);
- the 7 sub-light ships and their trajectories are fictional, meant to convey the tragedy of
  "anything below light speed cannot escape";
- the `O` observation jump is a visualization aid and does not change the physics formulas;
- this is a personal, non-commercial fan project, not affiliated with the copyright holders of
  *The Three-Body Problem*; all rights to the original novel belong to Liu Cixin.

**Suggested viewing flow**: look around at the stars and the Solar System behind you → lower
$\beta$ to about 0.45 with the wheel and enjoy the 2-D plane expanding and folding → when the
front approaches, press `Space` for full power and watch the sky collapse into a forward light
cone while the Solar System behind red-shifts → press `V` to compare → then use `O` to tour the
Kuiper belt and Oort cloud.

<a id="changelog-en"></a>

## 10. Changelog

**v1.0.0 — 2026-10-27**

- First public release: relativistic cockpit view, Hilbert 2-D-ization, 8 planets,
  7 refugee ships, HUD/minimap/event log;
- multi-scale painting textures extended to the Oort cloud at 120,000 AU; asteroid and
  Kuiper belts enhanced;
- `O` observation jump (preserves ship–front separation, leaves relativistic view untouched);
- the "escaped the 2-D front" banner is now dynamic: it only appears at full power with
  $\beta \ge 0.999$, and retracts as soon as you slow down;
- four-layer texture cache, auto exposure, bloom, ACES, Chinese HUD, self-test and benchmark modes;
- README now uses GitHub MathJax LaTeX and includes this English edition.

## 11. Credits & Disclaimer

- Inspired by the 2-D-ization of the Solar System and the light-speed ship in Liu Cixin's
  *Death's End* (*Remembrance of Earth's Past #3*);
- Tech stack: Python, pygame, moderngl, NumPy, SciPy, Pillow;
- A personal, non-commercial fan project for learning and sharing. If there is any copyright
  concern, please open an issue and it will be addressed promptly.

If this project reminds you of the first time you read about the 2-D-ization of the Solar
System, a ⭐ is welcome.
