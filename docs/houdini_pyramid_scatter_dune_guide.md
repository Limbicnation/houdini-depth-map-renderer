# Houdini Pyramid Scatter & Dune-Inspired Cinematic Rendering Guide

A Technical Director's walkthrough for procedurally scattering pyramid geometry across a desert landscape, randomizing scale and **Y-axis-only** orientation, and assembling a surreal, *Dune*-inspired blockbuster render in Karma.

This guide is tailored to your current scene:

| Object | Path | Role |
|---|---|---|
| Pyramid asset | `/obj/anubis_pyramid` | Instanced geometry |
| Terrain mesh | `/obj/crater_landscape` | Scatter surface |
| Camera | `/obj/cam1` | Render + depth view |
| Depth tool | `/obj/depth_map_renderer1` | This repo's HDA |

> Tested against Houdini 20.0–21.x SOP/VEX semantics. All node names are current — no deprecated SOPs.

---

# Houdini Technical Setup

We build the scatter network inside a **single new geometry object** so the logic is self-contained and easy to re-time or wedge later. Everything below lives in the SOP context of `/obj/pyramid_scatter`.

### Step 0 — Create the host object

Create a new Geometry object: **Tab → Geometry**, rename it `pyramid_scatter`. Dive inside (double-click). Delete the default `file1` SOP.

### Step 1 — Bring in the terrain (Object Merge)

We reference the existing landscape rather than duplicating geometry.

- **Tab → Object Merge**, name it `OBJ_terrain`.
- `Object 1` → `/obj/crater_landscape`
- `Transform` → **Into This Object** (so the scatter inherits `crater_landscape`'s world transform and sits on the real terrain).

> Why Object Merge and not a direct reference: it pulls live geometry, so any edits to `crater_landscape` propagate downstream automatically.

### Step 2 — Scatter and Align

- **Tab → Scatter and Align** (`scatteralign`), name it `SCATTER_pyramids`. Wire `OBJ_terrain → SCATTER_pyramids`.
- **Generate** tab:
  - `Generate Method` → **Force Total Count**, `Force Total Count` → `250` (raise to taste; start low for fast iteration).
  - `Relax Iterations` → `25` — enforces even, Poisson-like spacing so pyramids don't clump.
  - `Override Global Seed` → enable, set a value you can change for new layouts.
- **Attributes** tab:
  - `Up Vector` → `0, 1, 0`.
  - **Disable** "Align to Surface Normal" / set the alignment so points are **not** tilted to the slope. We want the *position* on the terrain but vertical *orientation* — we will author `orient` ourselves in Step 3.

> The Scatter and Align node natively outputs `@P` and (optionally) `@N`/`@orient`. Because we override `@orient` downstream, any alignment it produces is harmless — but disabling slope-align keeps the viewport preview honest.

### Step 3 — Attribute Wrangle (yaw + scale)

- **Tab → Attribute Wrangle**, name it `RANDOMIZE`. Wire `SCATTER_pyramids → RANDOMIZE`.
- `Run Over` → **Points**.
- Paste the snippet from the [VEX / Attribute Randomization](#vex--attribute-randomization) section. This writes `p@orient` (Y-only), `f@pscale`, and a fallback `v@up`.
- The promoted channels (`seed`, `scale_min`, `scale_max`, `height_mult`) appear as sliders once you click **"Create parameters from channel references"** (the small gear / sliders icon, or press the button on the parameter pane).

### Step 4 — Pull in the pyramid (Object Merge)

- **Tab → Object Merge**, name it `OBJ_pyramid`.
- `Object 1` → `/obj/anubis_pyramid`, `Transform` → **Into This Object**.
- This becomes the **second input** of Copy to Points.

> Tip: keep `/obj/anubis_pyramid` modeled at a sensible base size (e.g. 1–2 m tall). `pscale` multiplies that base, so a base of 1 unit makes `pscale` read directly as final size.

### Step 5 — Copy to Points

- **Tab → Copy to Points** (`copytopoints`), name it `COPY_pyramids`.
- Input 0 (geometry to copy) → `OBJ_pyramid`.
- Input 1 (target points) → `RANDOMIZE`.
- Parameters:
  - `Pack and Instance` → **ON** — packs each pyramid as a lightweight instance. Essential at hundreds–thousands of copies; keeps memory flat and the viewport fast.
  - `Transform Using Target Point Orientations` → **ON** — this is what makes `@orient` (and `@pscale`) drive the per-point transform.

**Network summary:**

```
OBJ_terrain ──▶ SCATTER_pyramids ──▶ RANDOMIZE ──▶ COPY_pyramids (input 1)
                                                         ▲
OBJ_pyramid ─────────────────────────────────────────────┘ (input 0)
```

### Step 6 (optional) — Density mask for art-directed clusters

To control *where* pyramids appear (e.g. avoid crater centers, cluster on ridges):

- Insert **Attribute Paint** (`attribpaint`) between `OBJ_terrain` and `SCATTER_pyramids`, painting a `float` attribute `density` (0–1).
- In **Scatter and Align**, set `Density Attribute` → `density`. Painted-black areas get no points; white areas get full density.
- Alternative, fully procedural: **Attribute from Volume** or an **Attribute Wrangle** on the terrain that writes `f@density` from terrain height/slope (e.g. `@density = fit(@P.y, ymin, ymax, 0, 1);`).

---

# VEX / Attribute Randomization

All snippets run in the `RANDOMIZE` Attribute Wrangle from Step 3, **Run Over → Points**.

### Houdini orientation primer (read this first)

- `@orient` is a **`vector4` quaternion** stored as `(x, y, z, w)` where `(x,y,z)` is the imaginary/axis part and **`w` is the real (scalar) part**.
- A pure rotation of angle `θ` about the Y axis is `(0, sin(θ/2), 0, cos(θ/2))`.
- **Do not hand-roll the components** — it's easy to swap the order. Use the built-in `quaternion(angle, axis)`, which produces the correct convention every time.
- When Copy to Points sees `@orient`, it **ignores `@N` and `@up`**. So authoring a Y-only quaternion guarantees the pyramids stay perfectly vertical and only spin (yaw) — they can never tilt into or off the terrain.

### Y-axis (yaw) randomization

```vex
// RANDOMIZE — Run Over: Points
// Random spin around Y only. Pyramids stay upright; no slope tilt, no clipping.

float yaw = rand(@ptnum + ch("seed")) * 2 * PI;   // 0 → 2π radians
p@orient  = quaternion(yaw, {0, 1, 0});           // pure Y rotation, correct (x,y,z,w) order
v@up      = {0, 1, 0};                             // fallback if orient is ever stripped
```

- `PI` is a built-in VEX constant — **do not** use HScript's `$PI` (invalid in VEX).
- `ch("seed")` exposes a slider; nudge it to reshuffle every pyramid's rotation deterministically.

### Uniform scale randomization

```vex
// Unified pscale — uniform scaling, no stretching.
f@pscale = fit01(rand(@ptnum * 1.37 + ch("seed_scale")),
                 chf("scale_min"),
                 chf("scale_max"));
```

- The `* 1.37` offset decorrelates the scale RNG stream from the yaw RNG stream, so size and rotation vary independently.
- Suggested starting values: `scale_min = 0.6`, `scale_max = 2.5`.

### Controlled non-uniform scale (optional — varied silhouettes)

Use this only if you want some pyramids taller/sharper. It's mathematically bounded, so it never produces extreme stretching:

```vex
// Combine with the pscale block above (or replace it).
float base = fit01(rand(@ptnum * 1.37 + ch("seed_scale")),
                   chf("scale_min"), chf("scale_max"));
v@scale = set(base, base * chf("height_mult"), base);   // Y multiplied independently
```

- `height_mult` of `1.0` = uniform; `1.4` = noticeably taller; keep within `0.8–1.6` to stay believable.
- Copy to Points reads `@pscale` (uniform) **and** `@scale` (per-axis) together if both exist — `@scale` wins per component. Use one approach to avoid confusion; `@scale` is the more explicit choice when you want height variation.

### Non-VEX alternative (Attribute Adjust Float)

If you prefer a no-code path for scale, drop an **Attribute Adjust Float** (`attribadjustfloat`) after the wrangle:

- `Attribute` → `pscale`
- `Adjustment Method` → **Set** (or **Multiply** to layer on top of VEX values)
- `Value` → driven by a **Ramp** keyed to a random `0–1` input, with **Randomize** enabled and a `Seed` parameter.

This gives art-directable scale distribution (e.g. mostly-small with a few giants) via the ramp curve. Keep yaw in VEX — it's the cleaner tool for quaternion math.

### Attribute reference

| Attribute | Type | Meaning in this network |
|---|---|---|
| `@P` | `vector` | Point position on the terrain (from Scatter and Align) |
| `@N` | `vector` | Surface normal — **intentionally ignored** once `@orient` exists |
| `@up` | `vector` | Up direction; fallback `{0,1,0}` keeps copies vertical |
| `@orient` | `vector4` | Quaternion `(x,y,z,w)`; pure Y rotation drives the spin |
| `@pscale` | `float` | Uniform scale multiplier on the copied pyramid |
| `@scale` | `vector` | Optional per-axis scale (for controlled height variation) |
| `@Cd` | `vector` | Optional point color — handy for previewing density masks |

---

# Cinematic Art Direction & Rendering

Target look: vast, arid, monolithic. High-contrast low sun, hazy warm air, anamorphic compression, crushed-yet-warm palette. We render in **Karma** through Solaris (LOPs), but the lighting/camera principles apply to an OBJ-level setup too.

### A. Terrain & pyramid material

- **Principled / MaterialX Standard Surface** on both terrain and pyramids.
- Base color: desaturated warm — HSV ≈ `25° / 40–55% / 45–65%` (sandstone). Hex anchor `#C9A87A`.
- `Roughness` `0.7–0.9` (matte, sand-blasted stone). No metallic.
- Subtle **displacement** or fine triplanar noise on the terrain for grain at grazing light angles.
- Push the pyramids a touch darker/cooler than the sand so they read as foreign monoliths against the dunes.

### B. Lighting — the Dune signature

The whole look hinges on a **low-angle, hard, warm key** plus a **cool, soft fill**.

- **Key — Distant Light** (`distantlight` in LOPs, or a Directional/Distant light at OBJ):
  - Elevation **8–15°** above the horizon (raking light → long shadows, sculpted dune ripples).
  - Azimuth **210–240°** (back/side) for rim contrast on the pyramid edges.
  - Color: warm, **~3200–4000 K** (`#FFE4B5` → `#FFDAB9`). If using RGB, bias toward amber.
  - Intensity via **exposure ≈ 2.5–4.0**.
  - `Angle` (angular size) **0.3–0.6°** for crisp, hard-edged shadows — the sharp shadow is essential to the arid blockbuster feel.
- **Fill — Dome Light** with a clear-sky / desert **HDRI**:
  - Intensity low (`0.3–0.5`), tinted slightly **cool** (`#AEB9C4`).
  - This warm-key / cool-shadow split is the core of the cinematic contrast. (For the deep-Arrakis monochrome look instead, make the fill warm too and lean fully sepia.)
- **Optional Rim** — a second distant light, azimuth ≈ `170°`, elevation `~20°`, exposure `~0.8`, to separate pyramid silhouettes from the haze.

### C. Camera — `/obj/cam1`

- **Focal length 50–85 mm** — compresses depth, stacks the dunes and pyramids into the frame (the anamorphic "telephoto desert" look). Avoid wide lenses; they kill the sense of scale.
- **Physical DOF**: enable `Depth of Field`, `F-Stop` **f/2.8–f/4.0**, `Focus Distance` set to the **mid-ground pyramid cluster**. Foreground sand and far dunes fall into soft bokeh.
- **Aspect 2.39:1** (cinemascope). Set Resolution to e.g. **3840 × 1608**, or 2048 × 858 for fast previews.
- **Height low** (≈ 1.5–3 m) with a **−5° to −10° downward tilt** — grounds the viewer and emphasizes the pyramids' mass.
- **Optional 2× anamorphic squeeze**: set `Aspect Ratio` to `0.5` (or use Karma's anamorphic controls) for oval bokeh and edge stretch.

### D. Atmosphere & volumetrics

- **Height haze**: create a large **Box** SOP scaled to enclose the scene, convert to a constant-density **volume** (or use a Karma global/atmosphere volume). Density **0.01–0.05**, warm tint (`#D4A76A`).
- Add a **height falloff** so haze pools low (10–30 m band at terrain level) and thins with altitude — read `@P.y` in a Volume Wrangle and `fit()` density to zero above a cutoff.
- **Wind-blown dust** (optional): sprite particles or a sparse POP layer drifting across frame catches the low sun and sells motion/scale.

### E. Rendering — Karma

- Engine: **Karma CPU** (rock-solid volumes) or **Karma XPU** (faster, GPU-accelerated) — pick per your hardware.
- `Pixel Samples` **128–512** (raise until the haze is noise-free), or use adaptive sampling with a low noise threshold.
- Ray depths: **Diffuse 3–4**, **Reflection 4**, **Volume 2–4**. Keep diffuse modest — desert bounce is subtle.
- **Denoiser**: Intel **OIDN** (CPU) or **OptiX** (NVIDIA). Denoise the volume pass too.
- Output: **EXR, 16- or 32-bit float**, `4K` (3840 wide) for finals.
- Color: render in **ACEScg** (scene-referred), view/output transform **ACES RRT + sRGB**. This gives the filmic highlight roll-off that makes the sun and rim feel cinematic.

---

# Depth Pass via the Depth Map Renderer

You can produce a depth map of the finished pyramid field using this repo's HDA at `/obj/depth_map_renderer1` — matching the panel settings already on your node.

1. **Point it at the camera**: in the **Depth Map Renderer** tab → **Depth Settings**, set `Camera` to `/obj/cam1` (or click the "pick from scene" button). Enable **Auto-Render Scene Depth**.
2. **Set the range**: enable **Custom Near/Far Range** and set `Near = 0.01`, `Far = 50` (your current values). Tighten `Far` to the actual distance of the farthest pyramid so depth precision isn't wasted on empty sky.
3. **Normalization** → **LINEAR** for a perceptually even depth gradient (use **LOGARITHMIC** if you need more contrast in the near field; **RAW** for unmodified camera-space depth).
4. **Tune** `Scale Factor`, `Contrast`, `Brightness`, and **Invert** to match your downstream needs. The screenshot values (Scale `1.21`, Contrast `0.63`, Brightness `1.56`, Invert on) are a reasonable starting point.
5. **Output**: set `Output Path`, `Format` (PNG 16-bit, or EXR for full float), then go to the **Actions** tab → **Setup Depth Network** → **Render Depth Map**. For a moving camera, use **Render Animation**.

> Because the pyramids stay perfectly vertical (Y-only `@orient`), their silhouettes read cleanly in the depth pass — ideal for downstream relighting, fog compositing, or ControlNet-style depth conditioning.

---

## Quick Verification Checklist

- [ ] Pyramids sit *on* the terrain, all vertical, with visibly random spin and size.
- [ ] No pyramid is tilted to the slope or clipping into the ground (confirms `@orient` is Y-only).
- [ ] `Pack and Instance` is ON — scene stays responsive at high counts.
- [ ] Camera reads 50 mm+, 2.39:1, DOF focused on the mid cluster.
- [ ] Key light is low, warm, hard-shadowed; fill is cool and soft.
- [ ] Karma render is denoised, ACEScg, EXR.
- [ ] Depth Map Renderer outputs a clean depth pass from `/obj/cam1`.
