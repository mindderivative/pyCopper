// pyCopper universal UI primitive shader.
//
// Every UI element -- boxes, borders, shadows, glyphs, images -- is one instance
// of a unit quad, drawn in a SINGLE instanced draw call. The fragment shader
// branches on `flags.x` to choose behaviour. See ARCHITECTURE.md 5.8.
//
// Two properties depend on this being a true signed distance field:
//   * antialiasing is analytic (fwidth over the distance), so no MSAA and no
//     resolve target, correct at any corner radius;
//   * clipping is a second SDF evaluation rather than a scissor rect, which
//     would split the draw call and cannot express rounded corners at all.
//
// All colours here are LINEAR (ARCHITECTURE.md 5.6.1) and output is
// PREMULTIPLIED, matching the One / OneMinusSrcAlpha blend state.

const KIND_BOX:    u32 = 0u;
const KIND_GLYPH:  u32 = 1u;
const KIND_IMAGE:  u32 = 2u;
const KIND_SHADOW: u32 = 3u;

// Sentinel meaning "use the literal colour, not a palette lookup".
const NO_TOKEN: u32 = 0xFFFFFFFFu;

struct Globals {
    projection : mat4x4<f32>,
    viewport   : vec2<f32>,
    pixel_ratio: f32,
    _pad       : f32,
};

@group(0) @binding(0) var<uniform> globals : Globals;
@group(0) @binding(1) var<storage, read> palette : array<vec4<f32>>;
@group(0) @binding(2) var glyph_atlas : texture_2d<f32>;
@group(0) @binding(3) var image_atlas : texture_2d<f32>;
@group(0) @binding(4) var atlas_sampler : sampler;

struct VertexIn {
    @location(0) corner     : vec2<f32>,   // unit quad, (0,0)..(1,1)
    // --- per instance ---
    @location(1) rect       : vec4<f32>,   // x, y, w, h  (physical px)
    @location(2) radii      : vec4<f32>,   // tl, tr, br, bl
    @location(3) clip       : vec4<f32>,
    @location(4) clip_radii : vec4<f32>,
    @location(5) fill       : vec4<f32>,
    @location(6) border     : vec4<f32>,
    @location(7) uv         : vec4<f32>,   // u0, v0, u1, v1
    @location(8) params     : vec4<f32>,   // border_w, blur, shadow_dx, shadow_dy
    @location(9) flags      : vec4<u32>,   // kind, atlas, fill_token, border_token
};

struct VertexOut {
    @builtin(position)                 position   : vec4<f32>,
    @location(0)                       frag_pos   : vec2<f32>,
    @location(1)                       uv         : vec2<f32>,
    @location(2) @interpolate(flat)    rect       : vec4<f32>,
    @location(3) @interpolate(flat)    radii      : vec4<f32>,
    @location(4) @interpolate(flat)    clip       : vec4<f32>,
    @location(5) @interpolate(flat)    clip_radii : vec4<f32>,
    @location(6) @interpolate(flat)    fill       : vec4<f32>,
    @location(7) @interpolate(flat)    border     : vec4<f32>,
    @location(8) @interpolate(flat)    params     : vec4<f32>,
    @location(9) @interpolate(flat)    flags      : vec4<u32>,
};

@vertex
fn vs_main(in: VertexIn) -> VertexOut {
    var out: VertexOut;
    let kind = in.flags.x;

    // The quad is grown so antialiasing and shadow blur are not clipped by
    // their own geometry. Textured kinds need no padding -- the atlas sample is
    // already antialiased, and padding would break the UV mapping.
    var pad = 0.0;
    if (kind == KIND_BOX) {
        pad = 1.5;
    } else if (kind == KIND_SHADOW) {
        pad = in.params.y * 3.0 + max(abs(in.params.z), abs(in.params.w)) + 2.0;
    }

    let origin = in.rect.xy - vec2<f32>(pad);
    let extent = in.rect.zw + vec2<f32>(pad * 2.0);
    let pos    = origin + in.corner * extent;

    out.position   = globals.projection * vec4<f32>(pos, 0.0, 1.0);
    out.frag_pos   = pos;
    out.uv         = mix(in.uv.xy, in.uv.zw, in.corner);
    out.rect       = in.rect;
    out.radii      = in.radii;
    out.clip       = in.clip;
    out.clip_radii = in.clip_radii;
    out.fill       = in.fill;
    out.border     = in.border;
    out.params     = in.params;
    out.flags      = in.flags;
    return out;
}

// Resolve a colour: palette lookup when a token index is present, else literal.
// Deliberately in the FRAGMENT stage -- storage buffers are not guaranteed
// visible to the vertex stage on every backend, and the cost here is trivial.
fn resolve(literal: vec4<f32>, token: u32) -> vec4<f32> {
    if (token == NO_TOKEN) {
        return literal;
    }
    let c = palette[token];
    return vec4<f32>(c.rgb, c.a * literal.a);   // literal.a carries opacity
}

// Signed distance to a rounded box centred at the origin.
// Negative inside, zero on the edge, positive outside.
fn sd_rounded_box(p: vec2<f32>, half: vec2<f32>, r: vec4<f32>) -> f32 {
    // r is (tl, tr, br, bl); pick the radius for the quadrant p falls in.
    let pair   = select(r.wz, r.xy, p.y < 0.0);   // top pair vs bottom pair
    let radius = select(pair.y, pair.x, p.x < 0.0);
    let q = abs(p) - half + radius;
    return min(max(q.x, q.y), 0.0) + length(max(q, vec2<f32>(0.0))) - radius;
}

// Analytic coverage from a distance field. This is the whole antialiasing story.
fn coverage(d: f32) -> f32 {
    let aa = max(fwidth(d), 1e-5);
    return 1.0 - smoothstep(-aa, aa, d);
}

fn premultiply(c: vec4<f32>) -> vec4<f32> {
    return vec4<f32>(c.rgb * c.a, c.a);
}

@fragment
fn fs_main(in: VertexOut) -> @location(0) vec4<f32> {
    let kind = in.flags.x;
    let fill   = resolve(in.fill, in.flags.z);
    let border = resolve(in.border, in.flags.w);

    let center = in.rect.xy + in.rect.zw * 0.5;
    let half   = in.rect.zw * 0.5;
    let p      = in.frag_pos - center;

    var color = vec4<f32>(0.0);

    if (kind == KIND_BOX) {
        let d = sd_rounded_box(p, half, in.radii);
        let outer = coverage(d);

        let bw = in.params.x;
        if (bw > 0.0) {
            // Inset the same field by the border width; the ring is the
            // difference of the two coverages, so fill and border never
            // double-composite.
            let inner = coverage(d + bw);
            color = premultiply(fill) * inner
                  + premultiply(border) * max(0.0, outer - inner);
        } else {
            color = premultiply(fill) * outer;
        }

    } else if (kind == KIND_SHADOW) {
        let blur = max(in.params.y, 1e-4);
        let offset = vec2<f32>(in.params.z, in.params.w);
        let d = sd_rounded_box(p - offset, half, in.radii);
        // Gaussian approximated by a smoothstep ramp across the blur radius.
        let a = 1.0 - smoothstep(-blur, blur, d);
        color = premultiply(fill) * a;

    } else if (kind == KIND_GLYPH) {
        // R8 coverage atlas tinted by the fill colour.
        let cov = textureSample(glyph_atlas, atlas_sampler, in.uv).r;
        color = premultiply(fill) * cov;

    } else if (kind == KIND_IMAGE) {
        let texel = textureSample(image_atlas, atlas_sampler, in.uv);
        color = premultiply(texel * fill);
    }

    // Rounded clipping, evaluated analytically so the draw call stays whole.
    // A zero-size clip rect means "unclipped".
    if (in.clip.z > 0.0 && in.clip.w > 0.0) {
        let cc = in.clip.xy + in.clip.zw * 0.5;
        let ch = in.clip.zw * 0.5;
        color *= coverage(sd_rounded_box(in.frag_pos - cc, ch, in.clip_radii));
    }

    return color;
}
