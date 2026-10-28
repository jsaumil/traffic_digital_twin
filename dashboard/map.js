'use strict';
// Live junction map. Draws the real OSM geometry as a 2.5D street map, animates vehicles at the
// display frame rate by interpolating between the server's ~10 Hz snapshots, and supports
// zoom (wheel), pan (drag), reset (double-click) and hover inspection. World units are metres,
// x east / y north; a vehicle's local +y is forward, matching the snapshot heading.
const TwinMap = (() => {
  const canvas = document.getElementById('map');
  const ctx = canvas.getContext('2d');
  const SIGNAL = {RED: '#ff4d5e', YELLOW: '#ffbc3d', GREEN: '#3ee6a8'};
  const PALETTE = {
    ground: '#11222a', footpath: '#34444f', kerb: '#55697a', asphalt: '#252e38', box: '#28313b',
    median: '#4b5c58', planting: '#2f5a3f', lane: 'rgba(225,235,240,.55)', edge: 'rgba(235,240,245,.7)',
    medianEdge: 'rgba(255,205,90,.65)', zebra: 'rgba(235,240,245,.82)', roof: '#2c4250',
    wallLit: '#24394a', wallShade: '#192a36', tree: '#2e6b48', label: '#d5e4ee',
  };
  const WIDTH = {car: 1.75, bus: 2.6, truck: 2.3, motorcycle: 0.75, auto: 1.4};
  const CAR_COLORS = ['#e9edf0', '#bcc5cd', '#c8352f', '#2f6db3', '#2b2f36', '#8b959f', '#d8c7a4', '#e9edf0'];
  const HELMETS = ['#f4f1ea', '#e0463c', '#2d6fd0', '#f2c230', '#1b1f24', '#3fae6a'];
  const LEGEND = [['Two-wheeler', '#f2c230'], ['Car', '#bcc5cd'], ['Auto-rickshaw', '#2f8f4e'],
                  ['Bus', '#c8352f'], ['Truck', '#e07b24']];
  const RENDER_DELAY = 120;  // ms behind the newest snapshot, so there is always a pair to blend.
  const BUILDING_LEAN = [0.11, 0.15];  // Oblique roof offset per metre of height.

  let junction = null, frames = [], view = null, dpr = 1, width = 0, height = 0;
  let staticLayer = null, staticKey = '', pointer = null, drag = null, hovered = null;

  // ---- geometry helpers ---------------------------------------------------------------------
  function along(points, s) {
    let t = 0;
    for (let i = 1; i < points.length; i++) {
      const a = points[i - 1], b = points[i], l = Math.hypot(b[0] - a[0], b[1] - a[1]);
      if (l && (t + l >= s || i === points.length - 1)) {
        const d = [(b[0] - a[0]) / l, (b[1] - a[1]) / l], u = s - t;
        return {p: [a[0] + d[0] * u, a[1] + d[1] * u], d, n: [-d[1], d[0]]};
      }
      t += l;
    }
    return {p: points[0], d: [1, 0], n: [0, 1]};
  }
  const lateral = (frame, offset, forward = 0) =>
    [frame.p[0] + frame.n[0] * offset + frame.d[0] * forward, frame.p[1] + frame.n[1] * offset + frame.d[1] * forward];
  function offsetLine(points, d) {
    return points.map((p, i) => {
      const a = points[Math.max(0, i - 1)], b = points[Math.min(points.length - 1, i + 1)];
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1;
      return [p[0] - (b[1] - a[1]) / len * d, p[1] + (b[0] - a[0]) / len * d];
    });
  }
  function slice(points, from) {
    const out = [along(points, from).p];
    let t = 0;
    for (let i = 1; i < points.length; i++) {
      t += Math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]);
      if (t > from) out.push(points[i]);
    }
    return out;
  }
  function path(c, points, close = true) {
    c.beginPath();
    points.forEach((p, i) => i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]));
    if (close) c.closePath();
  }
  function strip(c, points, a, b) {
    path(c, [...offsetLine(points, a), ...offsetLine(points, b).reverse()]);
    c.fill();
  }
  function hash(text) {
    let h = 2166136261;
    for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    return h >>> 0;
  }
  function shade(hex, amount) {
    const n = parseInt(hex.slice(1), 16), f = v => Math.max(0, Math.min(255, Math.round(v + 255 * amount)));
    return `rgb(${f(n >> 16)},${f(n >> 8 & 255)},${f(n & 255)})`;
  }
  const lerp = (a, b, t) => a + (b - a) * t;
  function lerpAngle(a, b, t) {
    const d = Math.atan2(Math.sin(b - a), Math.cos(b - a));
    return a + d * t;
  }

  // ---- junction-derived data ----------------------------------------------------------------
  const lhs = () => junction.driving_side === 'left' ? 1 : -1;
  const inbound = arm => -lhs() * (arm.median / 2 + arm.in_lanes * arm.lane_width);
  const outbound = arm => lhs() * (arm.median / 2 + arm.out_lanes * arm.lane_width);

  function turnTargets() {
    // Same classification as simulation.junction.turn_targets: by angle between real road axes.
    const outward = arm => along(arm.axis, 30).d, result = {};
    for (const a of junction.arms) {
      const inc = outward(a).map(v => -v), options = {};
      for (const b of junction.arms) {
        if (b === a) continue;
        const o = outward(b), angle = Math.atan2(inc[0] * o[1] - inc[1] * o[0], inc[0] * o[0] + inc[1] * o[1]);
        const turn = Math.abs(angle) < 0.7 ? 'straight' : angle > 0 ? 'left' : 'right';
        options[turn] = true;
      }
      result[a.id] = options;
    }
    return result;
  }
  function laneTurns(arm, lane, targets) {
    const near = lhs() > 0 ? 'left' : 'right', far = near === 'left' ? 'right' : 'left';
    const turns = ['straight'];
    if (lane === 0) turns.push(near);
    if (lane === arm.in_lanes - 1) turns.push(far);
    return turns.filter(t => targets[arm.id][t]);
  }

  // ---- view -----------------------------------------------------------------------------------
  function fitView() {
    view = {cx: 0, cy: 0, z: Math.min(width, height) / (2 * 48)};
  }
  function clampZoom(z) {
    const extent = junction ? Math.max(...junction.arms.map(a => a.extent)) + 40 : 160;
    return Math.max(Math.min(width, height) / (2 * extent), Math.min(40, z));
  }
  const toWorld = (x, y) => [view.cx + (x - width / 2) / view.z, view.cy - (y - height / 2) / view.z];
  const toScreen = p => [width / 2 + (p[0] - view.cx) * view.z, height / 2 - (p[1] - view.cy) * view.z];
  function worldTransform(c) {
    c.setTransform(dpr * view.z, 0, 0, -dpr * view.z, dpr * (width / 2 - view.cx * view.z),
                   dpr * (height / 2 + view.cy * view.z));
  }
  const screenTransform = c => c.setTransform(dpr, 0, 0, dpr, 0, 0);

  function resize() {
    const rect = canvas.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    if (!view) fitView();
    staticKey = '';
  }

  // ---- static layer: ground, roads, markings, buildings, trees ------------------------------
  function drawStatic() {
    const key = [width, height, dpr, view.cx, view.cy, view.z].join();
    if (key === staticKey && staticLayer) return;
    staticKey = key;
    staticLayer = staticLayer || document.createElement('canvas');
    staticLayer.width = canvas.width;
    staticLayer.height = canvas.height;
    const c = staticLayer.getContext('2d');
    screenTransform(c);
    const ground = c.createRadialGradient(width / 2, height / 2, 0, width / 2, height / 2, Math.max(width, height) * 0.75);
    ground.addColorStop(0, '#15292f');
    ground.addColorStop(1, PALETTE.ground);
    c.fillStyle = ground;
    c.fillRect(0, 0, width, height);
    worldTransform(c);
    const arms = junction.arms, targets = turnTargets();

    // Footpaths first, then every carriageway, so no arm's footpath paints over another's road.
    c.fillStyle = PALETTE.footpath;
    for (const arm of arms) strip(c, arm.axis, outbound(arm) + lhs() * 3.2, inbound(arm) - lhs() * 3.2);
    c.fillStyle = PALETTE.kerb;
    for (const arm of arms) strip(c, arm.axis, outbound(arm) + lhs() * 0.35, inbound(arm) - lhs() * 0.35);
    c.fillStyle = PALETTE.asphalt;
    for (const arm of arms) strip(c, arm.axis, outbound(arm), inbound(arm));
    c.fillStyle = PALETTE.box;
    path(c, junction.box);
    c.fill();

    for (const arm of arms) {
      const m = arm.median / 2, beyond = slice(arm.axis, arm.stop), w = arm.lane_width;
      // Raised median with planting.
      c.fillStyle = PALETTE.median;
      strip(c, beyond, m, -m);
      c.fillStyle = PALETTE.planting;
      strip(c, slice(arm.axis, arm.stop + 1.5), Math.max(0.1, m - 0.3), -Math.max(0.1, m - 0.3));
      // Edge lines: white at the kerb, amber along the median.
      c.lineWidth = 0.15;
      c.strokeStyle = PALETTE.edge;
      for (const side of [outbound(arm) - lhs() * 0.3, inbound(arm) + lhs() * 0.3]) {
        path(c, offsetLine(beyond, side), false);
        c.stroke();
      }
      c.strokeStyle = PALETTE.medianEdge;
      for (const side of [m + 0.2, -m - 0.2]) {
        path(c, offsetLine(beyond, side), false);
        c.stroke();
      }
      // Lane dividers.
      c.strokeStyle = PALETTE.lane;
      c.setLineDash([3, 4.5]);
      for (let k = 1; k < arm.in_lanes; k++) {
        path(c, offsetLine(slice(arm.axis, arm.stop + 0.5), -lhs() * (m + k * w)), false);
        c.stroke();
      }
      for (let k = 1; k < arm.out_lanes; k++) {
        path(c, offsetLine(beyond, lhs() * (m + k * w)), false);
        c.stroke();
      }
      c.setLineDash([]);
      // Zebra crossing between the box and the stop line, across the whole road.
      c.strokeStyle = PALETTE.zebra;
      c.lineWidth = 0.5;
      const near = along(arm.axis, arm.stop - 3.6);
      const from = Math.min(inbound(arm), outbound(arm)) + 0.6, to = Math.max(inbound(arm), outbound(arm)) - 0.4;
      for (let d = from; d <= to; d += 1.0) {
        if (Math.abs(d) < m + 0.2) continue;
        c.beginPath();
        c.moveTo(...lateral(near, d));
        c.lineTo(...lateral(near, d, 3.0));
        c.stroke();
      }
      // Stop line across the inbound lanes.
      const stop = along(arm.axis, arm.stop);
      c.strokeStyle = PALETTE.zebra;
      c.lineWidth = 0.45;
      c.beginPath();
      c.moveTo(...lateral(stop, -lhs() * m));
      c.lineTo(...lateral(stop, inbound(arm)));
      c.stroke();
      // Turn arrows painted in each inbound lane.
      for (let lane = 0; lane < arm.in_lanes; lane++) {
        const offset = -lhs() * (m + (arm.in_lanes - lane - 0.5) * w);
        for (const s of [arm.stop + 7, arm.stop + 30]) drawArrow(c, along(arm.axis, s), offset, laneTurns(arm, lane, targets));
      }
    }

    // Buildings extruded to their OSM height; far ones first so nearer roofs overlap them.
    const lean = BUILDING_LEAN, buildings = [...junction.buildings].map(b => {
      const n = b.footprint.length, cx = b.footprint.reduce((s, p) => s + p[0], 0) / n,
            cy = b.footprint.reduce((s, p) => s + p[1], 0) / n;
      return {b, order: cx * lean[0] + cy * lean[1]};
    }).sort((a, b) => b.order - a.order);
    for (const {b} of buildings) {
      const h = Math.min(45, b.height || 8), v = [lean[0] * h, lean[1] * h], pts = b.footprint;
      const roof = pts.map(p => [p[0] + v[0], p[1] + v[1]]);
      for (let i = 0; i < pts.length; i++) {
        const a = pts[i], z = pts[(i + 1) % pts.length];
        const lit = (z[0] - a[0]) * 0.6 - (z[1] - a[1]) * 0.8 > 0;
        c.fillStyle = lit ? PALETTE.wallLit : PALETTE.wallShade;
        path(c, [a, z, roof[(i + 1) % pts.length], roof[i]]);
        c.fill();
      }
      c.fillStyle = PALETTE.roof;
      path(c, roof);
      c.fill();
      c.strokeStyle = 'rgba(160,200,220,.12)';
      c.lineWidth = 0.25;
      c.stroke();
    }

    // Roadside trees along the outer footpaths, deterministic per arm.
    for (const arm of arms) {
      for (const [side, base] of [[outbound(arm), arm.id + 'o'], [inbound(arm), arm.id + 'i']]) {
        for (let s = arm.stop + 10; s < arm.extent - 2; s += 13) {
          const r = hash(base + s), jitter = (r % 100) / 100;
          if (r % 7 === 0) continue;
          const p = lateral(along(arm.axis, s + jitter * 4), side + Math.sign(side) * (3.6 + jitter));
          const radius = 2.0 + jitter * 1.1;
          c.fillStyle = 'rgba(0,0,0,.28)';
          c.beginPath();
          c.arc(p[0] + 0.7, p[1] - 0.9, radius, 0, Math.PI * 2);
          c.fill();
          const g = c.createRadialGradient(p[0] + radius * .3, p[1] + radius * .3, 0, p[0], p[1], radius);
          g.addColorStop(0, '#4f9a68');
          g.addColorStop(1, PALETTE.tree);
          c.fillStyle = g;
          c.beginPath();
          c.arc(p[0], p[1], radius, 0, Math.PI * 2);
          c.fill();
        }
      }
    }
  }

  function drawArrow(c, frame, offset, turns) {
    // Travel direction is toward the junction, i.e. against the arm's outward axis.
    const f = [-frame.d[0], -frame.d[1]], left = [-f[1], f[0]], o = lateral(frame, offset);
    const at = (fwd, side) => [o[0] + f[0] * fwd + left[0] * side, o[1] + f[1] * fwd + left[1] * side];
    c.strokeStyle = c.fillStyle = 'rgba(230,238,242,.5)';
    c.lineWidth = 0.28;
    c.lineCap = 'round';
    path(c, [at(-2.2, 0), at(0.4, 0)], false);
    c.stroke();
    const head = (tip, dir) => {
      const side = [-dir[1], dir[0]];
      path(c, [tip, [tip[0] - dir[0] * 0.9 + side[0] * 0.5, tip[1] - dir[1] * 0.9 + side[1] * 0.5],
               [tip[0] - dir[0] * 0.9 - side[0] * 0.5, tip[1] - dir[1] * 0.9 - side[1] * 0.5]]);
      c.fill();
    };
    for (const turn of turns) {
      if (turn === 'straight') {
        path(c, [at(0.4, 0), at(1.6, 0)], false);
        c.stroke();
        head(at(2.3, 0), f);
      } else {
        const s = turn === 'left' ? 1 : -1;
        path(c, [at(0.4, 0), at(1.0, 0.25 * s), at(1.2, 0.9 * s)], false);
        c.stroke();
        head(at(1.2, 1.7 * s), [left[0] * s, left[1] * s]);
      }
    }
    c.lineCap = 'butt';
  }

  // ---- vehicles -------------------------------------------------------------------------------
  function vehicleSprite(c, v, night) {
    const L = v.length, W = WIDTH[v.type] || 1.75, r = hash(v.id);
    const braking = v.acceleration < -0.6 || v.speed < 0.3;
    c.fillStyle = 'rgba(0,0,0,.38)';
    c.beginPath();
    c.roundRect(-W / 2 + 0.25, -L / 2 - 0.3, W, L, Math.min(0.5, W / 3));
    c.fill();
    if (v.type === 'motorcycle') {
      c.fillStyle = '#20252c';
      c.beginPath();
      c.roundRect(-0.24, -L / 2, 0.48, L, 0.24);
      c.fill();
      c.strokeStyle = '#8994a0';
      c.lineWidth = 0.12;
      c.beginPath();
      c.moveTo(-0.38, L / 2 - 0.45);
      c.lineTo(0.38, L / 2 - 0.45);
      c.stroke();
      c.fillStyle = HELMETS[r % HELMETS.length];
      c.beginPath();
      c.arc(0, -0.05, 0.32, 0, Math.PI * 2);
      c.fill();
      c.fillStyle = 'rgba(255,255,255,.35)';
      c.beginPath();
      c.arc(0.08, 0.05, 0.12, 0, Math.PI * 2);
      c.fill();
      lights(c, v, 0.12, L, braking, night, true);
      return;
    }
    const glass = '#18232f';
    if (v.type === 'truck') {
      c.fillStyle = '#9ba5ae';
      c.beginPath();
      c.roundRect(-W / 2, -L / 2, W, L - 2.1, 0.2);
      c.fill();
      c.strokeStyle = 'rgba(0,0,0,.18)';
      c.lineWidth = 0.08;
      for (let y = -L / 2 + 0.7; y < L / 2 - 2.2; y += 0.7) {
        c.beginPath();
        c.moveTo(-W / 2 + 0.1, y);
        c.lineTo(W / 2 - 0.1, y);
        c.stroke();
      }
      c.fillStyle = '#e07b24';
      c.beginPath();
      c.roundRect(-W / 2 + 0.05, L / 2 - 1.95, W - 0.1, 1.95, 0.35);
      c.fill();
      c.fillStyle = glass;
      c.fillRect(-W / 2 + 0.2, L / 2 - 0.75, W - 0.4, 0.45);
    } else if (v.type === 'bus') {
      c.fillStyle = '#c8352f';
      c.beginPath();
      c.roundRect(-W / 2, -L / 2, W, L, 0.55);
      c.fill();
      c.fillStyle = '#dc5a4c';
      c.fillRect(-W / 2 + 0.3, -L / 2 + 0.6, W - 0.6, L - 1.6);
      c.fillStyle = '#e9edf0';
      c.fillRect(-0.6, -1.2, 1.2, 2.4);
      c.fillStyle = 'rgba(0,0,0,.25)';
      c.fillRect(-0.5, -L / 2 + 1.4, 1.0, 1.2);
      c.fillRect(-0.5, L / 2 - 3.6, 1.0, 1.2);
      c.fillStyle = glass;
      c.fillRect(-W / 2 + 0.15, L / 2 - 0.65, W - 0.3, 0.5);
    } else if (v.type === 'auto') {
      c.fillStyle = '#2f8f4e';
      path(c, [[-W / 2, -L / 2 + 0.2], [-W / 2 + 0.1, -L / 2], [W / 2 - 0.1, -L / 2], [W / 2, -L / 2 + 0.2],
               [W / 2 - 0.05, L / 2 - 1.0], [W * 0.18, L / 2], [-W * 0.18, L / 2], [-W / 2 + 0.05, L / 2 - 1.0]]);
      c.fill();
      c.fillStyle = '#f2cf3b';
      c.beginPath();
      c.roundRect(-W / 2 + 0.06, -L / 2 + 0.12, W - 0.12, L * 0.6, 0.45);
      c.fill();
      c.fillStyle = 'rgba(255,255,255,.25)';
      c.fillRect(-W / 2 + 0.25, -L / 2 + 0.4, W - 0.5, 0.18);
      c.fillStyle = glass;
      c.fillRect(-W / 2 + 0.2, -L / 2 + L * 0.6 + 0.1, W - 0.4, 0.38);
    } else {
      const body = CAR_COLORS[r % CAR_COLORS.length];
      c.fillStyle = body;
      c.beginPath();
      c.roundRect(-W / 2, -L / 2, W, L, 0.5);
      c.fill();
      c.fillStyle = glass;
      path(c, [[-W / 2 + 0.18, L / 2 - 1.75], [W / 2 - 0.18, L / 2 - 1.75], [W / 2 - 0.28, L / 2 - 1.1], [-W / 2 + 0.28, L / 2 - 1.1]]);
      c.fill();
      path(c, [[-W / 2 + 0.22, -L / 2 + 0.95], [W / 2 - 0.22, -L / 2 + 0.95], [W / 2 - 0.32, -L / 2 + 0.5], [-W / 2 + 0.32, -L / 2 + 0.5]]);
      c.fill();
      c.fillStyle = shade(body, 0.07);
      c.beginPath();
      c.roundRect(-W / 2 + 0.25, -L / 2 + 0.95, W - 0.5, L - 2.7, 0.25);
      c.fill();
    }
    lights(c, v, W / 2 - 0.25, L, braking, night, false);
  }

  function lights(c, v, x, L, braking, night, single) {
    const xs = single ? [0] : [-x, x];
    c.fillStyle = braking ? '#ff3b3b' : '#7a2222';
    for (const lx of xs) c.fillRect(lx - 0.17, -L / 2 - 0.02, 0.34, 0.16);
    c.fillStyle = night > 0.2 ? '#fff6d0' : 'rgba(255,250,225,.75)';
    for (const lx of xs) c.fillRect(lx - 0.15, L / 2 - 0.14, 0.3, 0.14);
    // Indicator blinks on the turn side until the vehicle is through the junction.
    if (v.turn !== 'straight' && v.state !== 'exiting' && Math.floor(performance.now() / 380) % 2) {
      const side = v.turn === 'left' ? -1 : 1, ix = single ? side * 0.3 : side * (WIDTH[v.type] / 2 - 0.08);
      c.fillStyle = '#ffb21e';
      c.fillRect(ix - 0.1, L / 2 - 0.3, 0.2, 0.3);
      c.fillRect(ix - 0.1, -L / 2, 0.2, 0.3);
    }
  }

  function glows(c, v, night) {
    // Additive light: brake lights always, headlight beams after dark.
    const L = v.length, braking = v.acceleration < -0.6 || v.speed < 0.3;
    if (braking) {
      const g = c.createRadialGradient(0, -L / 2, 0, 0, -L / 2, 1.6);
      g.addColorStop(0, `rgba(255,50,50,${0.35 + 0.35 * night})`);
      g.addColorStop(1, 'rgba(255,50,50,0)');
      c.fillStyle = g;
      c.fillRect(-1.6, -L / 2 - 1.6, 3.2, 3.2);
    }
    if (night > 0.05) {
      // Dipped and short when crawling in a queue, so stacked beams don't wash out the vehicles ahead.
      const moving = Math.min(1, v.speed / 6), reach = 4 + 10 * moving, spread = 0.8 + 1.8 * moving;
      const g = c.createLinearGradient(0, L / 2, 0, L / 2 + reach);
      g.addColorStop(0, `rgba(255,240,190,${night * (0.06 + 0.24 * moving)})`);
      g.addColorStop(1, 'rgba(255,240,190,0)');
      c.fillStyle = g;
      const half = (WIDTH[v.type] || 1) / 2;
      path(c, [[-half, L / 2], [half, L / 2], [half + spread, L / 2 + reach], [-half - spread, L / 2 + reach]]);
      c.fill();
    }
  }

  // ---- frame ----------------------------------------------------------------------------------
  function interpolated(now) {
    if (!frames.length) return {state: null, vehicles: []};
    const target = now - RENDER_DELAY;
    let a = frames[0], b = frames[0];
    for (let i = 1; i < frames.length; i++) {
      if (frames[i].t >= target) { a = frames[i - 1]; b = frames[i]; break; }
      a = b = frames[i];
    }
    const t = b === a ? 1 : Math.max(0, Math.min(1, (target - a.t) / (b.t - a.t)));
    const vehicles = [];
    for (const v of Object.values(b.state.vehicles)) {
      const p = a.state.vehicles[v.id];
      if (!p || Math.hypot(p.position[0] - v.position[0], p.position[1] - v.position[1]) > 15) {
        vehicles.push({...v, x: v.position[0], y: v.position[1], h: v.heading});
      } else {
        vehicles.push({...v, x: lerp(p.position[0], v.position[0], t), y: lerp(p.position[1], v.position[1], t),
                       h: lerpAngle(p.heading, v.heading, t), speed: lerp(p.speed, v.speed, t)});
      }
    }
    return {state: frames.at(-1).state, vehicles};
  }

  function nightness(hour) {
    if (hour >= 6.5 && hour <= 18.5) return 0;
    if (hour >= 19.5 || hour <= 5.5) return 1;
    return hour < 12 ? 6.5 - hour : hour - 18.5;
  }

  function draw(now) {
    requestAnimationFrame(draw);
    if (!junction || !view || !width) return;
    drawStatic();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.drawImage(staticLayer, 0, 0);
    const {state, vehicles} = interpolated(now);
    const night = state ? nightness(state.metrics.clock_hour ?? 12) : 0;
    worldTransform(ctx);
    if (state) drawSignals(ctx, state);
    // Long vehicles last, so two-wheelers filtering alongside a bus don't vanish beneath it.
    vehicles.sort((a, b) => (a.type === 'motorcycle') - (b.type === 'motorcycle') || a.length - b.length);
    for (const v of vehicles) {
      ctx.save();
      ctx.translate(v.x, v.y);
      ctx.rotate(v.h);
      vehicleSprite(ctx, v, night);
      ctx.restore();
    }
    if (night > 0) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = `rgba(3,7,22,${0.5 * night})`;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      worldTransform(ctx);
      streetLights(ctx, night);
    }
    ctx.globalCompositeOperation = 'lighter';
    for (const v of vehicles) {
      ctx.save();
      ctx.translate(v.x, v.y);
      ctx.rotate(v.h);
      glows(ctx, v, night);
      ctx.restore();
    }
    ctx.globalCompositeOperation = 'source-over';
    if (state) signalHeads(ctx, state);
    hovered = pick(vehicles);
    overlay(ctx, state, night);
  }

  function drawSignals(c, state) {
    // Coloured light bar just behind each stop line, so the arm's state reads at any zoom.
    for (const arm of junction.arms) {
      const color = SIGNAL[state.signals.groups[arm.id]] || SIGNAL.RED, f = along(arm.axis, arm.stop - 0.5);
      c.strokeStyle = color;
      c.globalAlpha = 0.85;
      c.lineWidth = 0.45;
      c.beginPath();
      c.moveTo(...lateral(f, -lhs() * arm.median / 2));
      c.lineTo(...lateral(f, inbound(arm)));
      c.stroke();
      c.globalAlpha = 1;
    }
  }

  function signalHeads(c, state) {
    screenTransform(c);
    const r = Math.max(2.6, Math.min(6, view.z * 0.55));
    for (const arm of junction.arms) {
      const group = state.signals.groups[arm.id], f = along(arm.axis, arm.stop + 1);
      const [x, y] = toScreen(lateral(f, inbound(arm) - lhs() * 1.8));
      const angle = Math.atan2(-f.d[1], f.d[0]);
      c.save();
      c.translate(x, y);
      c.rotate(angle);
      c.fillStyle = '#0a1118';
      c.strokeStyle = '#3c4f5e';
      c.lineWidth = 1;
      c.beginPath();
      c.roundRect(-r * 3.4, -r * 1.25, r * 6.8, r * 2.5, r * 1.1);
      c.fill();
      c.stroke();
      ['RED', 'YELLOW', 'GREEN'].forEach((name, i) => {
        const on = group === name, cx = (i - 1) * r * 2.2;
        if (on) {
          const g = c.createRadialGradient(cx, 0, 0, cx, 0, r * 4);
          g.addColorStop(0, SIGNAL[name] + 'aa');
          g.addColorStop(1, SIGNAL[name] + '00');
          c.fillStyle = g;
          c.beginPath();
          c.arc(cx, 0, r * 4, 0, Math.PI * 2);
          c.fill();
        }
        c.fillStyle = on ? SIGNAL[name] : '#25313b';
        c.beginPath();
        c.arc(cx, 0, r * 0.85, 0, Math.PI * 2);
        c.fill();
      });
      c.restore();
      if (group !== 'RED') {
        c.font = '600 11px ui-monospace, monospace';
        c.textAlign = 'center';
        c.fillStyle = SIGNAL[group];
        c.fillText(`${Math.ceil(state.signals.remaining)}s`, x, y - r * 2.2);
      }
    }
  }

  function streetLights(c, night) {
    c.globalCompositeOperation = 'lighter';
    for (const arm of junction.arms) {
      for (let s = arm.stop + 6; s < arm.extent; s += 24) {
        const p = along(arm.axis, s).p, g = c.createRadialGradient(p[0], p[1], 0, p[0], p[1], 9);
        g.addColorStop(0, `rgba(255,200,120,${0.22 * night})`);
        g.addColorStop(1, 'rgba(255,200,120,0)');
        c.fillStyle = g;
        c.fillRect(p[0] - 9, p[1] - 9, 18, 18);
      }
    }
    c.globalCompositeOperation = 'source-over';
  }

  function pick(vehicles) {
    if (!pointer || drag?.moved) return null;
    const [wx, wy] = toWorld(pointer.x, pointer.y);
    let best = null, bestDistance = Math.max(2.5, 8 / view.z);
    for (const v of vehicles) {
      const d = Math.hypot(v.x - wx, v.y - wy);
      if (d < bestDistance) { best = v; bestDistance = d; }
    }
    return best;
  }

  function overlay(c, state, night) {
    screenTransform(c);
    c.textBaseline = 'middle';
    // Road names along each arm, placed where the arm is on screen.
    c.font = '600 12px system-ui, sans-serif';
    for (const arm of junction.arms) {
      const text = `${arm.id} · ${arm.name}`, half = c.measureText(text).width / 2 + 10;
      for (let s = arm.extent - 4; s > arm.stop + 12; s -= 2) {
        const f = along(arm.axis, s), [x, y] = toScreen(lateral(f, outbound(arm) + lhs() * 6));
        let angle = Math.atan2(-f.d[1], f.d[0]);
        // Keep the whole label on screen, not just its centre.
        const ex = Math.abs(Math.cos(angle)) * half, ey = Math.abs(Math.sin(angle)) * half;
        if (x - ex < 8 || x + ex > width - 8 || y - ey < 8 || y + ey > height - 8) continue;
        if (angle > Math.PI / 2 || angle < -Math.PI / 2) angle += Math.PI;
        c.save();
        c.translate(x, y);
        c.rotate(angle);
        c.textAlign = 'center';
        c.lineWidth = 4;
        c.strokeStyle = 'rgba(8,16,24,.85)';
        c.strokeText(text, 0, 0);
        c.fillStyle = PALETTE.label;
        c.fillText(text, 0, 0);
        c.restore();
        break;
      }
    }
    // Legend.
    c.font = '11px system-ui, sans-serif';
    c.textAlign = 'left';
    const lw = 128, lh = 18 * LEGEND.length + 14;
    c.fillStyle = 'rgba(8,16,24,.72)';
    c.beginPath();
    c.roundRect(12, height - lh - 12, lw, lh, 8);
    c.fill();
    LEGEND.forEach(([name, color], i) => {
      const y = height - lh - 12 + 16 + i * 18;
      c.fillStyle = color;
      c.beginPath();
      c.roundRect(24, y - 4, 14, 8, 3);
      c.fill();
      c.fillStyle = '#c7d5df';
      c.fillText(name, 46, y);
    });
    // North arrow and scale bar.
    c.save();
    c.translate(width - 28, 30);
    c.fillStyle = '#c7d5df';
    path(c, [[0, -12], [6, 6], [0, 2], [-6, 6]]);
    c.fill();
    c.textAlign = 'center';
    c.font = '700 10px system-ui, sans-serif';
    c.fillText('N', 0, 17);
    c.restore();
    const metres = [5, 10, 20, 50, 100].find(m => m * view.z >= 60) || 100, px = metres * view.z;
    c.strokeStyle = '#c7d5df';
    c.lineWidth = 2;
    c.beginPath();
    c.moveTo(width - 16 - px, height - 18);
    c.lineTo(width - 16, height - 18);
    c.stroke();
    c.textAlign = 'right';
    c.fillStyle = '#c7d5df';
    c.fillText(`${metres} m`, width - 16, height - 30);
    c.fillStyle = 'rgba(199,213,223,.55)';
    c.textAlign = 'left';
    c.fillText(`${night > 0.5 ? 'Night · ' : ''}scroll to zoom · drag to pan · double-click to reset`, 152, height - 18);
    if (hovered) tooltip(c, hovered);
  }

  function tooltip(c, v) {
    const [x, y] = toScreen([v.x, v.y]);
    c.strokeStyle = '#ffffff';
    c.lineWidth = 1.5;
    c.beginPath();
    c.arc(x, y, Math.max(8, v.length * view.z * 0.65), 0, Math.PI * 2);
    c.stroke();
    const names = {motorcycle: 'Two-wheeler', car: 'Car', auto: 'Auto-rickshaw', bus: 'Bus', truck: 'Truck'};
    const lines = [`${names[v.type] || v.type} · ${v.id}`,
                   `${(v.speed * 3.6).toFixed(0)} km/h · ${v.state}`,
                   `${v.route.split('_')[0]} → ${v.destination} (${v.turn}) · waited ${v.waiting_time.toFixed(0)} s`];
    c.font = '11px system-ui, sans-serif';
    const w = Math.max(...lines.map(l => c.measureText(l).width)) + 20, h = lines.length * 16 + 12;
    const bx = Math.min(width - w - 8, x + 16), by = Math.max(8, Math.min(height - h - 8, y - h - 10));
    c.fillStyle = 'rgba(8,16,24,.92)';
    c.strokeStyle = '#3c5468';
    c.lineWidth = 1;
    c.beginPath();
    c.roundRect(bx, by, w, h, 7);
    c.fill();
    c.stroke();
    c.textAlign = 'left';
    lines.forEach((line, i) => {
      c.fillStyle = i ? '#a9bccb' : '#eef4f8';
      c.fillText(line, bx + 10, by + 14 + i * 16);
    });
  }

  // ---- interaction ----------------------------------------------------------------------------
  canvas.addEventListener('wheel', event => {
    if (!view) return;
    event.preventDefault();
    const rect = canvas.getBoundingClientRect(), x = event.clientX - rect.left, y = event.clientY - rect.top;
    const before = toWorld(x, y);
    view.z = clampZoom(view.z * Math.exp(-event.deltaY * 0.0015));
    const after = toWorld(x, y);
    view.cx += before[0] - after[0];
    view.cy += before[1] - after[1];
  }, {passive: false});
  canvas.addEventListener('pointerdown', event => {
    canvas.setPointerCapture(event.pointerId);
    drag = {x: event.clientX, y: event.clientY, cx: view.cx, cy: view.cy, moved: false};
    canvas.style.cursor = 'grabbing';
  });
  canvas.addEventListener('pointermove', event => {
    const rect = canvas.getBoundingClientRect();
    pointer = {x: event.clientX - rect.left, y: event.clientY - rect.top};
    if (!drag || !view) return;
    const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
    if (Math.hypot(dx, dy) > 3) drag.moved = true;
    view.cx = drag.cx - dx / view.z;
    view.cy = drag.cy + dy / view.z;
  });
  const endDrag = () => { drag = null; canvas.style.cursor = ''; };
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', () => { pointer = null; });
  canvas.addEventListener('dblclick', () => { fitView(); });
  new ResizeObserver(resize).observe(canvas);
  resize();
  requestAnimationFrame(draw);

  return {
    setJunction(data) {
      junction = data;
      staticKey = '';
    },
    update(state) {
      const last = frames.at(-1)?.state;
      // A reset reuses vehicle IDs; never glide a recycled ID across the map.
      if (last && (last.session_id !== state.session_id || state.timestamp < last.timestamp)) frames = [];
      frames.push({t: performance.now(), state});
      if (frames.length > 4) frames.shift();
    },
  };
})();
