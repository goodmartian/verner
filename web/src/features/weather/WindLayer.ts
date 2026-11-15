import type { CustomLayerInterface, Map as MaplibreMap } from 'maplibre-gl';
import {
  adapt,
  boxPixels,
  MAX_PARTICLES,
  MAX_ZOOM,
  particleCount,
  viewOnField,
  type Box,
} from './windMath';

type GL = WebGL2RenderingContext;

/** The side of the texture that holds the positions of the particles. */
const SIDE = 128;
/** Pixels a particle goes in a frame for each metre a second of wind. */
const PIXELS_PER_MS = 0.14;
/** What is left of a trail from one frame to the next. */
const FADE = 0.94;
/** How long one hour of the field takes to give way to the next, in milliseconds. */
const CROSSFADE_MS = 1000;
/** The wind at which a particle is as bright as it gets, in metres a second. */
const BRIGHT = 18;
/** How opaque the head of a particle is, for the weakest wind and the strongest, over a light map and over a dark one. */
const OPACITY = { dark: [0.38, 0.5], light: [0.42, 0.6] } as const;
/** The colours of the lines: a grey-blue that does not argue with the layers under it, and white. */
const COLOR = { dark: [0.33, 0.42, 0.52], light: [1, 1, 1] } as const;

export interface WindField {
  /** What the picture covers. */
  bounds: Box;
  /** The wind a value of 0 and of 255 stand for, `[u, v]`. */
  min: readonly [number, number];
  max: readonly [number, number];
}

/** A quad over the whole target: the pass that moves the particles, and the one that lays a picture over another. */
const QUAD_VERTEX = `
attribute vec2 a_pos;
varying vec2 v_tex_pos;
void main() {
  v_tex_pos = a_pos;
  gl_Position = vec4(2.0 * a_pos - 1.0, 0.0, 1.0);
}`;

const SHARED = `
precision highp float;
uniform sampler2D u_wind0;
uniform sampler2D u_wind1;
uniform float u_mix;
uniform vec2 u_wind_min;
uniform vec2 u_wind_max;
uniform vec4 u_geo;
// the wind (m/s) and whether the field has a value there: the picture is clear where there is none
vec3 windAt(vec2 pos) {
  vec4 a = texture2D(u_wind0, pos);
  vec4 b = texture2D(u_wind1, pos);
  vec4 t = mix(a, b, u_mix);
  // how sure the field is of a value here: it fades to nothing toward its edge, where the cells are half a cell of the coast
  float known = clamp((t.a - 0.5) / 0.45, 0.0, 1.0);
  vec2 rg = t.rg / max(t.a, 0.001);
  return vec3(mix(u_wind_min, u_wind_max, rg), known);
}`;

const UPDATE = `${SHARED}
uniform sampler2D u_particles;
uniform float u_rand_seed;
uniform float u_speed;
uniform float u_deg_per_px;
uniform float u_drop_rate;
uniform vec4 u_view;
varying vec2 v_tex_pos;
const vec3 rand_constants = vec3(12.9898, 78.233, 4375.85453);
float rand(const vec2 co) {
  float t = dot(rand_constants.xy, co);
  return fract(sin(t) * (rand_constants.z + t));
}
void main() {
  vec4 color = texture2D(u_particles, v_tex_pos);
  vec2 pos = vec2(color.r / 255.0 + color.b, color.g / 255.0 + color.a);
  vec3 w = windAt(pos);
  float lat = u_geo.w - pos.y * (u_geo.w - u_geo.y);
  // a pixel east is u_deg_per_px of longitude, a pixel north that much times cos(lat) of latitude
  float dlon = w.x * u_speed * u_deg_per_px;
  float dlat = w.y * u_speed * u_deg_per_px * cos(radians(lat));
  vec2 moved = pos + vec2(dlon / (u_geo.z - u_geo.x), -dlat / (u_geo.w - u_geo.y));
  vec2 seed = (pos + v_tex_pos) * u_rand_seed;
  float drop = step(1.0 - u_drop_rate, rand(seed));
  vec2 fresh = u_view.xy + vec2(rand(seed + 1.3), rand(seed + 2.1)) * (u_view.zw - u_view.xy);
  // a particle that leaves the field, or stands where the field has no wind, starts again in view
  float outside = 1.0 - step(0.0, moved.x) * step(moved.x, 1.0) * step(0.0, moved.y) * step(moved.y, 1.0);
  float unknown = 1.0 - step(0.001, windAt(clamp(moved, 0.0, 1.0)).z);
  moved = mix(moved, fresh, max(max(drop, outside), unknown));
  gl_FragColor = vec4(fract(moved * 255.0), floor(moved * 255.0) / 255.0);
}`;

const DRAW_VERTEX = `${SHARED}
attribute float a_index;
uniform sampler2D u_particles;
uniform float u_side;
uniform vec2 u_center;
uniform float u_scale;
uniform vec2 u_size;
uniform float u_point;
uniform vec2 u_opacity;
varying float v_bright;
const float PI = 3.14159265359;
void main() {
  vec4 color = texture2D(u_particles, vec2(fract(a_index / u_side), floor(a_index / u_side) / u_side));
  vec2 pos = vec2(color.r / 255.0 + color.b, color.g / 255.0 + color.a);
  vec3 w = windAt(pos);
  float lon = mix(u_geo.x, u_geo.z, pos.x);
  float lat = mix(u_geo.w, u_geo.y, pos.y);
  vec2 world = vec2((lon + 180.0) / 360.0, 0.5 - log(tan(PI / 4.0 + radians(lat) / 2.0)) / (2.0 * PI));
  vec2 px = (world - u_center) * u_scale;
  gl_Position = vec4(px.x / (u_size.x / 2.0), -px.y / (u_size.y / 2.0), 0.0, 1.0);
  gl_PointSize = u_point;
  v_bright = w.z * mix(u_opacity.x, u_opacity.y, clamp(length(w.xy) / ${String(BRIGHT)}.0, 0.0, 1.0));
}`;

const DRAW_FRAGMENT = `
precision highp float;
uniform vec3 u_color;
varying float v_bright;
void main() {
  float a = v_bright;
  gl_FragColor = vec4(u_color * a, a);
}`;

const SCREEN = `
precision highp float;
uniform sampler2D u_screen;
uniform float u_opacity;
varying vec2 v_tex_pos;
void main() {
  vec4 color = texture2D(u_screen, v_tex_pos);
  // the floor lets a faint trail reach nothing, instead of staying at its last step
  gl_FragColor = floor(255.0 * color * u_opacity) / 255.0;
}`;

interface Program {
  program: WebGLProgram;
  uniforms: Record<string, WebGLUniformLocation | null>;
  attributes: Record<string, number>;
}

function compile(gl: GL, vertex: string, fragment: string): Program {
  const make = (type: number, source: string) => {
    const shader = gl.createShader(type);
    if (!shader) throw new Error('no shader');
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) ?? 'shader did not compile');
    }
    return shader;
  };
  const program = gl.createProgram();
  gl.attachShader(program, make(gl.VERTEX_SHADER, vertex));
  gl.attachShader(program, make(gl.FRAGMENT_SHADER, fragment));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) ?? 'program did not link');
  }
  const uniforms: Record<string, WebGLUniformLocation | null> = {};
  for (let i = 0; i < Number(gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS)); i += 1) {
    const name = gl.getActiveUniform(program, i)?.name;
    if (name) uniforms[name] = gl.getUniformLocation(program, name);
  }
  const attributes: Record<string, number> = {};
  for (let i = 0; i < Number(gl.getProgramParameter(program, gl.ACTIVE_ATTRIBUTES)); i += 1) {
    const name = gl.getActiveAttrib(program, i)?.name;
    if (name) attributes[name] = gl.getAttribLocation(program, name);
  }
  return { program, uniforms, attributes };
}

function texture(
  gl: GL,
  width: number,
  height: number,
  data: ArrayBufferView | ImageBitmap | null,
  filter: number,
) {
  const made = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, made);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, filter);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, filter);
  if (data instanceof ImageBitmap) {
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, data);
  } else {
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, width, height, 0, gl.RGBA, gl.UNSIGNED_BYTE, data);
  }
  return made;
}

/** The units of texture the passes use. */
const UNITS = [0, 1, 2, 3];

/**
 * What the map had set in the GL context, kept to be set again after a pass of the layer: the map keeps its own account of
 * the state (the stencil that clips its tiles, the textures it has bound) and does not ask the context, so a state left
 * changed shows as pieces of the map drawn wrong.
 */
function keepState(gl: GL): () => void {
  const frame = gl.getParameter(gl.FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
  const viewport = gl.getParameter(gl.VIEWPORT) as Int32Array;
  const program = gl.getParameter(gl.CURRENT_PROGRAM) as WebGLProgram | null;
  const buffer = gl.getParameter(gl.ARRAY_BUFFER_BINDING) as WebGLBuffer | null;
  const array = gl.getParameter(gl.VERTEX_ARRAY_BINDING) as WebGLVertexArrayObject | null;
  const unit = gl.getParameter(gl.ACTIVE_TEXTURE) as number;
  const textures = UNITS.map((at) => {
    gl.activeTexture(gl.TEXTURE0 + at);
    return gl.getParameter(gl.TEXTURE_BINDING_2D) as WebGLTexture | null;
  });
  const enabled = [gl.DEPTH_TEST, gl.STENCIL_TEST, gl.BLEND, gl.SCISSOR_TEST].map((flag) =>
    gl.isEnabled(flag),
  );
  const blend = [
    gl.getParameter(gl.BLEND_SRC_RGB),
    gl.getParameter(gl.BLEND_DST_RGB),
    gl.getParameter(gl.BLEND_SRC_ALPHA),
    gl.getParameter(gl.BLEND_DST_ALPHA),
  ] as [number, number, number, number];
  const clear = gl.getParameter(gl.COLOR_CLEAR_VALUE) as Float32Array;
  gl.activeTexture(unit);
  return () => {
    UNITS.forEach((at, index) => {
      gl.activeTexture(gl.TEXTURE0 + at);
      gl.bindTexture(gl.TEXTURE_2D, textures[index] ?? null);
    });
    gl.activeTexture(unit);
    gl.bindFramebuffer(gl.FRAMEBUFFER, frame);
    gl.viewport(viewport[0] ?? 0, viewport[1] ?? 0, viewport[2] ?? 0, viewport[3] ?? 0);
    gl.useProgram(program);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bindVertexArray(array);
    [gl.DEPTH_TEST, gl.STENCIL_TEST, gl.BLEND, gl.SCISSOR_TEST].forEach((flag, index) => {
      if (enabled[index]) gl.enable(flag);
      else gl.disable(flag);
    });
    gl.blendFuncSeparate(...blend);
    gl.clearColor(clear[0] ?? 0, clear[1] ?? 0, clear[2] ?? 0, clear[3] ?? 0);
  };
}

/** A texture the passes draw into, with the frame buffer that draws into it. */
interface Target {
  texture: WebGLTexture;
  frame: WebGLFramebuffer;
}

function target(gl: GL, width: number, height: number): Target {
  const made = texture(gl, width, height, new Uint8Array(width * height * 4), gl.NEAREST);
  const frame = gl.createFramebuffer();
  gl.bindFramebuffer(gl.FRAMEBUFFER, frame);
  gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, made, 0);
  return { texture: made, frame };
}

/**
 * The wind as moving lines, after the scheme of webgl-wind (mapbox, ISC): the positions of the particles live in a texture
 * and are moved by the wind field in a shader; they are drawn as points into a picture that fades a little at each frame,
 * which leaves their trails; that picture is laid over the map. The particles are over the field only, in view, under the
 * markers of the fires.
 */
export class WindLayer implements CustomLayerInterface {
  readonly id = 'wind-particles';
  readonly type = 'custom' as const;
  readonly renderingMode = '2d' as const;

  private map: MaplibreMap | null = null;
  private gl: GL | null = null;
  private update!: Program;
  private draw!: Program;
  private screen!: Program;
  private vao: WebGLVertexArrayObject | null = null;
  private quad: WebGLBuffer | null = null;
  private indices: WebGLBuffer | null = null;
  private particles: [Target, Target] | null = null;
  private trails: [Target, Target] | null = null;
  private size: [number, number] = [0, 0];
  private field: WindField | null = null;
  private current: WebGLTexture | null = null;
  private incoming: WebGLTexture | null = null;
  private fadeStart = 0;
  private moving = false;
  private tone: 'dark' | 'light' = 'dark';
  private share = 1;
  private frames = 0;
  private windowStart = 0;
  private last = 0;
  private loading: AbortController | null = null;
  private alive = false;

  /** The lines are dark over a light map and light over a dark one. */
  setTone(tone: 'dark' | 'light') {
    this.tone = tone;
    this.map?.triggerRepaint();
  }

  /** Takes the field of an hour: it fades in over the one on screen. */
  async setField(field: WindField, address: string) {
    this.loading?.abort();
    const controller = new AbortController();
    this.loading = controller;
    this.field = field;
    const blob = await fetch(address, { signal: controller.signal }).then((response) =>
      response.blob(),
    );
    const picture = await createImageBitmap(blob, {
      premultiplyAlpha: 'none',
      colorSpaceConversion: 'none',
    });
    const gl = this.gl;
    if (!gl || controller.signal.aborted || !this.alive) return;
    const made = texture(gl, picture.width, picture.height, picture, gl.LINEAR);
    if (this.current === null) {
      this.current = made;
    } else {
      if (this.incoming) gl.deleteTexture(this.incoming);
      this.incoming = made;
      this.fadeStart = performance.now();
    }
    this.map?.triggerRepaint();
  }

  onAdd(map: MaplibreMap, gl: GL) {
    this.map = map;
    this.gl = gl;
    this.alive = true;
    this.update = compile(gl, QUAD_VERTEX, UPDATE);
    this.draw = compile(gl, DRAW_VERTEX, DRAW_FRAGMENT);
    this.screen = compile(gl, QUAD_VERTEX, SCREEN);
    this.vao = gl.createVertexArray();
    this.quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1]),
      gl.STATIC_DRAW,
    );
    this.indices = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.indices);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array(Array.from({ length: MAX_PARTICLES }, (_, i) => i)),
      gl.STATIC_DRAW,
    );
    const random = new Uint8Array(SIDE * SIDE * 4);
    crypto.getRandomValues(random);
    this.particles = [target(gl, SIDE, SIDE), target(gl, SIDE, SIDE)];
    gl.bindTexture(gl.TEXTURE_2D, this.particles[0].texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, SIDE, SIDE, 0, gl.RGBA, gl.UNSIGNED_BYTE, random);
    // while the map is moved the picture of trails would smear: nothing is drawn, and it starts again when the map is still
    map.on('movestart', this.onMoveStart);
    map.on('moveend', this.onMoveEnd);
    document.addEventListener('visibilitychange', this.onVisible);
  }

  onRemove() {
    this.alive = false;
    this.loading?.abort();
    this.map?.off('movestart', this.onMoveStart);
    this.map?.off('moveend', this.onMoveEnd);
    document.removeEventListener('visibilitychange', this.onVisible);
    const gl = this.gl;
    if (gl) {
      for (const item of [...(this.particles ?? []), ...(this.trails ?? [])]) {
        gl.deleteTexture(item.texture);
        gl.deleteFramebuffer(item.frame);
      }
      for (const item of [this.current, this.incoming]) if (item) gl.deleteTexture(item);
      gl.deleteVertexArray(this.vao);
      gl.deleteBuffer(this.quad);
      gl.deleteBuffer(this.indices);
      for (const program of [this.update, this.draw, this.screen])
        gl.deleteProgram(program.program);
    }
    this.particles = null;
    this.trails = null;
    this.current = null;
    this.incoming = null;
    this.gl = null;
    this.map = null;
  }

  private readonly onMoveStart = () => {
    this.moving = true;
  };

  private readonly onMoveEnd = () => {
    this.moving = false;
    this.clearTrails();
    this.map?.triggerRepaint();
  };

  // a tab that is hidden stops asking for frames; it asks again when it is shown
  private readonly onVisible = () => {
    if (!document.hidden) {
      this.last = performance.now();
      this.map?.triggerRepaint();
    }
  };

  private clearTrails() {
    const gl = this.gl;
    if (!gl || !this.trails) return;
    for (const item of this.trails) {
      gl.bindFramebuffer(gl.FRAMEBUFFER, item.frame);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
    }
  }

  private ensureTrails(gl: GL) {
    const width = gl.drawingBufferWidth;
    const height = gl.drawingBufferHeight;
    if (this.trails && this.size[0] === width && this.size[1] === height) return;
    for (const item of this.trails ?? []) {
      gl.deleteTexture(item.texture);
      gl.deleteFramebuffer(item.frame);
    }
    this.size = [width, height];
    this.trails = [target(gl, width, height), target(gl, width, height)];
  }

  private bindQuad(gl: GL, program: Program) {
    gl.bindBuffer(gl.ARRAY_BUFFER, this.quad);
    const at = program.attributes.a_pos ?? 0;
    gl.enableVertexAttribArray(at);
    gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0);
  }

  private bindTexture(
    gl: GL,
    unit: number,
    item: WebGLTexture | null,
    program: Program,
    name: string,
  ) {
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, item);
    gl.uniform1i(program.uniforms[name] ?? null, unit);
  }

  private uniformsOfField(gl: GL, program: Program, field: WindField, mix: number) {
    this.bindTexture(gl, 2, this.current, program, 'u_wind0');
    this.bindTexture(gl, 3, this.incoming ?? this.current, program, 'u_wind1');
    gl.uniform1f(program.uniforms.u_mix ?? null, this.incoming ? mix : 0);
    gl.uniform2f(program.uniforms.u_wind_min ?? null, field.min[0], field.min[1]);
    gl.uniform2f(program.uniforms.u_wind_max ?? null, field.max[0], field.max[1]);
    gl.uniform4f(program.uniforms.u_geo ?? null, ...field.bounds);
  }

  prerender(gl: GL) {
    const restore = keepState(gl);
    gl.bindVertexArray(this.vao);
    try {
      this.step(gl);
    } finally {
      restore();
    }
  }

  private step(gl: GL) {
    const map = this.map;
    const field = this.field;
    if (!map || !field || !this.current || !this.particles || document.hidden || this.moving)
      return;
    if (map.getZoom() > MAX_ZOOM) return;
    const now = performance.now();
    const elapsed = Math.min(now - (this.last || now), 100);
    this.last = now;
    this.measure(now);
    const view = map.getBounds();
    const box = viewOnField(
      [view.getWest(), view.getSouth(), view.getEast(), view.getNorth()],
      field.bounds,
    );
    if (!box) return;
    this.ensureTrails(gl);
    if (!this.trails) return;
    const mix = Math.min(1, (now - this.fadeStart) / CROSSFADE_MS);
    gl.disable(gl.DEPTH_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.disable(gl.BLEND);

    // the particles move
    const [old, next] = this.particles;
    gl.bindFramebuffer(gl.FRAMEBUFFER, next.frame);
    gl.viewport(0, 0, SIDE, SIDE);
    gl.useProgram(this.update.program);
    this.bindQuad(gl, this.update);
    this.uniformsOfField(gl, this.update, field, mix);
    this.bindTexture(gl, 0, old.texture, this.update, 'u_particles');
    const zoom = map.getZoom();
    gl.uniform1f(this.update.uniforms.u_rand_seed ?? null, Math.random());
    gl.uniform1f(this.update.uniforms.u_speed ?? null, PIXELS_PER_MS * (elapsed / 16.67));
    gl.uniform1f(this.update.uniforms.u_deg_per_px ?? null, 360 / (512 * 2 ** zoom));
    gl.uniform1f(this.update.uniforms.u_drop_rate ?? null, 0.004);
    gl.uniform4f(this.update.uniforms.u_view ?? null, ...box);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    this.particles = [next, old];

    // the trails fade, and the particles are drawn over them
    const [before, after] = this.trails;
    gl.bindFramebuffer(gl.FRAMEBUFFER, after.frame);
    gl.viewport(0, 0, this.size[0], this.size[1]);
    gl.useProgram(this.screen.program);
    this.bindQuad(gl, this.screen);
    this.bindTexture(gl, 0, before.texture, this.screen, 'u_screen');
    gl.uniform1f(this.screen.uniforms.u_opacity ?? null, FADE);
    gl.drawArrays(gl.TRIANGLES, 0, 6);

    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.draw.program);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.indices);
    const index = this.draw.attributes.a_index ?? 0;
    gl.enableVertexAttribArray(index);
    gl.vertexAttribPointer(index, 1, gl.FLOAT, false, 0, 0);
    this.uniformsOfField(gl, this.draw, field, mix);
    this.bindTexture(gl, 0, this.particles[0].texture, this.draw, 'u_particles');
    const center = map.getCenter();
    const centreY =
      0.5 - Math.log(Math.tan(Math.PI / 4 + (center.lat * Math.PI) / 360)) / (2 * Math.PI);
    gl.uniform1f(this.draw.uniforms.u_side ?? null, SIDE);
    gl.uniform2f(this.draw.uniforms.u_center ?? null, (center.lng + 180) / 360, centreY);
    gl.uniform1f(this.draw.uniforms.u_scale ?? null, 512 * 2 ** zoom);
    const canvas = map.getContainer();
    gl.uniform2f(this.draw.uniforms.u_size ?? null, canvas.clientWidth, canvas.clientHeight);
    gl.uniform1f(this.draw.uniforms.u_point ?? null, Math.max(1, window.devicePixelRatio));
    const [low, high] = OPACITY[this.tone];
    gl.uniform2f(this.draw.uniforms.u_opacity ?? null, low, high);
    const [red, green, blue] = COLOR[this.tone];
    gl.uniform3f(this.draw.uniforms.u_color ?? null, red, green, blue);
    const pixels = boxPixels(
      [
        field.bounds[0] + box[0] * (field.bounds[2] - field.bounds[0]),
        field.bounds[3] - box[3] * (field.bounds[3] - field.bounds[1]),
        field.bounds[0] + box[2] * (field.bounds[2] - field.bounds[0]),
        field.bounds[3] - box[1] * (field.bounds[3] - field.bounds[1]),
      ],
      zoom,
    );
    gl.drawArrays(gl.POINTS, 0, Math.round(particleCount(pixels) * this.share));
    gl.disable(gl.BLEND);
    this.trails = [after, before];
    if (mix >= 1 && this.incoming) {
      gl.deleteTexture(this.current);
      this.current = this.incoming;
      this.incoming = null;
    }
  }

  render(gl: GL) {
    const restore = keepState(gl);
    gl.bindVertexArray(this.vao);
    try {
      this.compose(gl);
    } finally {
      restore();
    }
  }

  private compose(gl: GL) {
    const map = this.map;
    if (
      !map ||
      !this.trails ||
      !this.current ||
      document.hidden ||
      this.moving ||
      map.getZoom() > MAX_ZOOM
    )
      return;
    // the picture of trails is laid over the map, premultiplied
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.useProgram(this.screen.program);
    this.bindQuad(gl, this.screen);
    this.bindTexture(gl, 0, this.trails[0].texture, this.screen, 'u_screen');
    gl.uniform1f(this.screen.uniforms.u_opacity ?? null, 1);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    // the next frame is asked for here, so that nothing runs while the tab is hidden or the map is moved
    map.triggerRepaint();
  }

  /** Counts the frames of each second: the particles are fewer when they come slowly. */
  private measure(now: number) {
    this.frames += 1;
    if (this.windowStart === 0) this.windowStart = now;
    if (now - this.windowStart >= 1000) {
      this.share = adapt(this.share, (this.frames * 1000) / (now - this.windowStart));
      this.frames = 0;
      this.windowStart = now;
    }
  }
}
