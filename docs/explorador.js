// Explorador del lazo tactico: simulacion pedagogica del grafo de airsim-loop
// (capture -> perception -> navigate -> motor) con sus umbrales reales, mas una
// escena Three.js ortografica e inspector. Sin build: modulo ES cargado con importmap.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

const DEG = Math.PI / 180;

// Umbrales de config/.env (ver grafo-de-control.html, seccion 10)
const CFG = {
  DT: 0.2,                    // LOOP_HZ = 5.0
  TTC_EVASION: 3.2,           // TTC_EVASION_THRESHOLD
  TTC_SAFE: 4.6,              // TTC_SAFE_THRESHOLD
  FOV_BLOCKED: 0.6,           // FOV_BLOCKED_THRESHOLD
  OPTICAL_MIN_ALT: 4.5,       // OPTICAL_MIN_ALT_M
  CRUISE: 3.0,                // REACTIVE_FORWARD_SPEED
  ACCEPT: 3.5,                // WAYPOINT_ACCEPTANCE_RADIUS
  TAKEOFF_TOL: 1.0,           // TAKEOFF_ALT_TOL_M
  STOP_CYCLES: 10,            // STOPPED_DELIBERATIVE_CYCLES
  STOP_MIN_CMD: 0.30,         // STOPPED_MIN_CMD_MPS
  NOPROG_CYCLES: 50,          // WP_NO_PROGRESS_THRESHOLD
  NOPROG_MIN_M: 2.0,          // WP_NO_PROGRESS_MIN_M
  SCAN_HEADINGS: 4,           // SCAN_HEADING_COUNT_DEEP
  SCAN_SETTLE: 2,             // SCAN_SETTLE_CYCLES_DEEP
  SCAN_ROT_TIMEOUT: 10,       // SCAN_ROT_TIMEOUT_CYCLES
  DEPTH_FREE_M: 15,           // DEPTH_FREE_M
  DEPTH_PERIOD: 1.0,          // DEPTH_STRATEGIC_PERIOD_S
  VLM_PERIOD: 3.0,            // VLM_STRATEGIC_PERIOD_S
  MAX_AGE: 10,                // VLM_STRATEGIC_MAX_AGE_S
  SUBGOAL_DIST: 15,           // VLM_SUBGOAL_DIST_M
  MIN_AHEAD: 4,               // VLM_SUBGOAL_MIN_AHEAD_M
  MAX_DZ: 4,                  // VLM_MAX_DZ_M
  MIN_SUB_ALT: 6,             // VLM_SUBGOAL_MIN_ALT_M
  NEAR_WP: 8,                 // VLM_NEAR_WP_M
  SLM_MIN_ALT: 8,             // SLM_MIN_ALT_M
  GOAL_CROP_DEG: 33.7,        // recorte cuadrado del VLM
  DEDUP: 10,                  // SUBGOAL_DEDUP_M
  MAX_ESCAPE_ALT: 30,         // MAX_ESCAPE_ALT_M
  EVADE_CYCLES: 10,           // MANEUVER_DURATION_S = 2.0
  EVADE_YAW_RATE: 15,         // EVADIR_*: +-15 grados/s
  VERT_CYCLES: 8,             // GANAR/PERDER_ALTURA 1.6 s
  TURN_CYCLES: 5,             // GIRAR_90 1.0 s
  // propios de la simulacion
  BLOCK_D: 12,                // distancia a la que una celda del flujo se marca ocupada
  MAX_T: 240,
  DRONE_R: 0.7,
};

const FLOW_AZ = [-30, 0, 30];      // tercios de un HFOV de 90 grados
const FLOW_EL = [20, 0, -20];
const STRAT_AZ = [-24, 0, 24];     // grilla del recorte cuadrado (+-24 grados)
const STRAT_EL = [24, 0, -24];
const COLS = ['A', 'B', 'C'];

const wrap = (a) => { while (a > Math.PI) a -= 2 * Math.PI; while (a < -Math.PI) a += 2 * Math.PI; return a; };
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const snap90 = (a) => wrap(Math.round(a / (Math.PI / 2)) * (Math.PI / 2));
const hyp = (x, y) => Math.sqrt(x * x + y * y);
const fmt = (v, d = 1) => (Number.isFinite(v) ? v.toFixed(d) : '∞');
const deg = (r) => Math.round(r / DEG);

function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------------------------------------------------------------------
// Mundo: cajas alineadas a los ejes. x = norte, y = este, z = arriba (metros).
// ---------------------------------------------------------------------------

const B = (x0, x1, y0, y1, h) => ({ kind: 'building', x0, x1, y0, y1, h, flow: true });
const M = (x, y0, y1, h) => ({ kind: 'mesh', x0: x - 0.2, x1: x + 0.2, y0, y1, h, flow: false });
const T = (cx, cy, h = 14, r = 2.2) => ({ kind: 'tree', x0: cx - r, x1: cx + r, y0: cy - r, y1: cy + r, h, flow: true, cx, cy, r });

function cityBlocks(rng, xs, ys, hmin, hmax) {
  const out = [];
  for (const [x0, x1] of xs) for (const [y0, y1] of ys) out.push(B(x0, x1, y0, y1, Math.round(hmin + rng() * (hmax - hmin))));
  return out;
}

const SCENARIOS = {
  libre: {
    name: 'Ruta libre (control)',
    blurb: 'Calles despejadas con un giro: la ruta fija de base, sin obstrucción.',
    wps: [[30, 0, 12], [110, 0, 12], [110, 75, 14]],
    build(rng) {
      return [
        ...cityBlocks(rng, [[-25, 20], [26, 60], [66, 98]], [[-48, -12], [12, 42]], 16, 44),
        ...cityBlocks(rng, [[122, 160]], [[-48, -12], [-6, 40], [50, 95]], 18, 40),
        ...cityBlocks(rng, [[66, 98]], [[48, 95]], 18, 36),
      ];
    },
  },
  torre: {
    name: 'Torre en la ruta (obstrucción)',
    blurb: 'Una torre angosta sobre la línea recta entre WP_1 y WP_2, en una plaza abierta.',
    wps: [[18, 0, 12], [112, 0, 12]],
    build() {
      return [
        B(55, 63, -4, 4, 38),
        B(20, 44, -46, -26, 14), B(72, 100, 26, 46, 18), B(-12, 14, 24, 42, 12), B(88, 116, -42, -24, 20),
      ];
    },
  },
  malla: {
    name: 'Malla sobre la calle (punto ciego)',
    blurb: 'Una malla que el flujo óptico no ve: el dron la descubre por contacto.',
    wps: [[18, 0, 12], [122, 0, 12]],
    build() {
      return [
        M(62, -12, 12, 28),
        B(-12, 50, -62, -30, 22), B(72, 132, -62, -30, 26), B(-12, 50, 30, 62, 18), B(72, 132, 30, 62, 30),
      ];
    },
  },
  arboles: {
    name: 'Corredor arbolado (obstrucción)',
    blurb: 'Copas más altas que la altitud de vuelo sobre la calzada.',
    wps: [[14, 0, 12], [156, 0, 12]],
    build(rng) {
      const trees = [];
      const ys = [-6, 5, 0, -7, 6, -2, 7];
      for (let i = 0; i < ys.length; i++) trees.push(T(34 + i * 17 + rng() * 3, ys[i], 13 + rng() * 4, 2.0 + rng() * 0.5));
      return [
        ...trees,
        ...cityBlocks(rng, [[-20, 30], [36, 84], [90, 140], [146, 180]], [[-50, -16], [16, 50]], 14, 34),
      ];
    },
  },
  sandbox: {
    name: 'Plaza vacía (agregá obstáculos)',
    blurb: 'Sin obstáculos: usá “+ Obstáculo” y hacé clic en el suelo.',
    wps: [[18, 0, 12], [104, 0, 12]],
    build() { return []; },
  },
};

function rayBox(ox, oy, oz, dx, dy, dz, b) {
  let tmin = 0, tmax = Infinity;
  const ax = [[ox, dx, b.x0, b.x1], [oy, dy, b.y0, b.y1], [oz, dz, -1, b.h]];
  for (const [o, d, lo, hi] of ax) {
    if (Math.abs(d) < 1e-9) { if (o < lo || o > hi) return Infinity; continue; }
    let t1 = (lo - o) / d, t2 = (hi - o) / d;
    if (t1 > t2) [t1, t2] = [t2, t1];
    tmin = Math.max(tmin, t1); tmax = Math.min(tmax, t2);
    if (tmin > tmax) return Infinity;
  }
  return tmin;
}

function dirOf(yaw, az, el) {
  const c = Math.cos(el);
  return [Math.cos(yaw + az) * c, Math.sin(yaw + az) * c, Math.sin(el)];
}

function raycast(world, p, d, maxD, flowOnly) {
  let best = Infinity;
  if (d[2] < -1e-6) best = -p.z / d[2];
  for (const b of world) {
    if (flowOnly && !b.flow) continue;
    const t = rayBox(p.x, p.y, p.z, d[0], d[1], d[2], b);
    if (t < best) best = t;
  }
  return best <= maxD ? best : Infinity;
}

function pointBoxDist(p, b) {
  const dx = Math.max(b.x0 - p.x, 0, p.x - b.x1);
  const dy = Math.max(b.y0 - p.y, 0, p.y - b.y1);
  const dz = Math.max(0, p.z - b.h);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// ---------------------------------------------------------------------------
// Simulacion
// ---------------------------------------------------------------------------

const RULES = [
  ['1', 'Barrido panorámico en curso', 'Continuar el barrido'],
  ['2', 'stopped_prolonged o wp_no_progress', 'Resolución de deadlock'],
  ['3', 'Maniobra comprometida', 'Continuarla (anti flip-flop)'],
  ['4', 'imu_contact o blind_wall', 'evasive_node'],
  ['5', 'Altitud < 4.5 m', 'reactive_node (piso óptico)'],
  ['6', 'z_path_blocked y dz > 1 m', 'PERDER_ALTURA'],
  ['7', 'TTC centro ≤ 3.2 s, o centro bloqueado y TTC ≤ 4.6 s', 'FOV > 60 %: GIRAR_90 + consulta; si no, evasive_node'],
  ['7b', 'Centro bloqueado o TTC mínimo ≤ 4.6 s', 'evasive_node'],
  ['8', '—', 'reactive_node (guiado nominal)'],
];

class Sim {
  constructor() {
    this.opts = { arm: 'slm', source: 'depth', deadlock: 'depth' };
    this.extra = [];
    this.listeners = [];
  }

  load(key, seed = 7) {
    this.key = key;
    this.sc = SCENARIOS[key];
    this.seed = seed;
    this.base = this.sc.build(mulberry32(seed));
    this.extra = [];
    this.reset();
  }

  get world() { return this.base.concat(this.extra); }

  reset() {
    this.rng = mulberry32(this.seed * 31 + 3);
    this.wps = this.sc.wps.map(([x, y, z], i) => ({ x, y, z, label: `WP_${i + 1}`, kind: 'wp' }));
    this.idx = 0;
    this.pos = { x: 0, y: 0, z: 0 };
    this.yaw = 0;
    this.v = { x: 0, y: 0, z: 0 };
    this.prev = { pos: { ...this.pos }, yaw: 0 };
    this.cycle = 0; this.t = 0;
    this.status = 'flying'; this.statusMsg = '';
    this.takeoff = true;
    this.maneuver = null;
    this.scan = null;
    this.stall = { stopped: 0, noprog: 0, best: Infinity, key: '', contact: 0, blind: 0, imuContact: false, blindWall: false, measured: 0 };
    this.gov = 1.2;
    this.degradedLeft = 0;
    this.strat = { last: -99, pending: null, expedite: false, resp: null, nextId: 1, sent: 0, applied: 0, discarded: 0 };
    this.anchorAlt = 0;
    this.contactNow = false;
    this.lastCmd = { vx: 0, vz: 0, action: 'FRENAR' };
    this.tried = [];
    this.deadlocks = 0; this.subgoals = 0; this.contacts = 0;
    this.dist = 0; this.distMin = Infinity;
    this.field = null;
    this.dec = { rule: '—', action: 'FRENAR', path: [], behaviour: '—', events: [] };
    this.trace = [];
    this.trail = [{ ...this.pos }];
    this.scanViz = [];
    this.lastPulse = null;
    this.field = this.computeField();
  }

  // -- percepcion: ObstacleField 3x3 (rayos en lugar de flujo; sin traslacion no hay evidencia)
  computeField() {
    const p = this.pos, world = this.world;
    const vF = this.v.x * Math.cos(this.yaw) + this.v.y * Math.sin(this.yaw);
    const evidence = vF > 0.3;
    const cells = [];
    let blockedRays = 0;
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
      let dmin = Infinity, hits = 0;
      for (const oa of [-10, 0, 10]) for (const oe of [-8, 0, 8]) {
        const az = (FLOW_AZ[c] + oa) * DEG, el = (FLOW_EL[r] + oe) * DEG;
        const d = raycast(world, p, dirOf(this.yaw, az, el), 45, true);
        if (d < dmin) dmin = d;
        if (d < CFG.BLOCK_D) hits++;
      }
      const fwd = dmin * Math.cos(FLOW_AZ[c] * DEG) * Math.cos(FLOW_EL[r] * DEG);
      const ttc = evidence ? fwd / vF : Infinity;
      const occ = evidence ? hits / 9 : 0;
      if (evidence) blockedRays += hits;
      cells.push({ r, c, d: dmin, ttc, occ, blocked: occ > 0.011 });
    }
    const center = cells[4];
    const minTTC = Math.min(...cells.map((x) => x.ttc));
    return { cells, center, minTTC, evidence, vF, fovBlocked: blockedRays / 81 };
  }

  // juicio de profundidad estimada: percentil 5 del sector ~ minimo de sus rayos
  depthSectors(pose) {
    const out = [];
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) {
      let dmin = Infinity;
      for (const oa of [-8, 0, 8]) for (const oe of [-8, 0, 8]) {
        const d = raycast(this.world, pose, dirOf(pose.yaw, (STRAT_AZ[c] + oa) * DEG, (STRAT_EL[r] + oe) * DEG), 60, false);
        dmin = Math.min(dmin, d);
      }
      out.push({ r, c, d: dmin, free: dmin >= CFG.DEPTH_FREE_M });
    }
    return out;
  }

  realWpIndex() {
    for (let i = this.idx; i < this.wps.length; i++) if (this.wps[i].kind === 'wp') return i;
    return -1;
  }

  guidance() {
    const tg = this.wps[this.idx];
    const dx = tg.x - this.pos.x, dy = tg.y - this.pos.y;
    return { tg, dx, dy, dist: hyp(dx, dy), bearing: Math.atan2(dy, dx), dz: tg.z - this.pos.z };
  }

  insertSubgoal(sub, ev, origin) {
    const ri = this.realWpIndex();
    const cur = this.wps[this.idx];
    if (cur.kind === 'sub' && hyp(cur.x - sub.x, cur.y - sub.y) < CFG.DEDUP && origin === 'estratégica') {
      ev.push('sub-meta a < 10 m de la pendiente: se ignora');
      return false;
    }
    this.wps.splice(this.idx, ri - this.idx, { ...sub, label: 'SUB', kind: 'sub', origin });
    this.subgoals++;
    this.stall.key = '';
    ev.push(`inject_corner: sub-meta ${origin} en (${fmt(sub.x, 0)}, ${fmt(sub.y, 0)}, ${fmt(sub.z, 0)} m)`);
    return true;
  }

  trackerUpdate(ev) {
    const ri = this.realWpIndex();
    const d3 = (w) => Math.sqrt((w.x - this.pos.x) ** 2 + (w.y - this.pos.y) ** 2 + (w.z - this.pos.z) ** 2);
    if (ri >= 0 && d3(this.wps[ri]) < CFG.ACCEPT) {
      ev.push(`${this.wps[ri].label} alcanzado`);
      this.idx = ri + 1;
      if (this.strat.pending) { this.strat.pending = null; }
    } else if (this.wps[this.idx] && this.wps[this.idx].kind === 'sub' && d3(this.wps[this.idx]) < CFG.ACCEPT) {
      ev.push('sub-meta alcanzada');
      this.idx++;
    }
    if (this.idx >= this.wps.length) {
      this.status = 'done';
      this.statusMsg = `misión completada en ${fmt(this.t, 1)} s`;
      return false;
    }
    return true;
  }

  updateStall(g) {
    const s = this.stall;
    const measured = hyp(this.pos.x - this.prev.pos.x, this.pos.y - this.prev.pos.y) / CFG.DT;
    s.measured = measured;
    if (this.takeoff || this.scan || this.pos.z < CFG.OPTICAL_MIN_ALT) {
      s.stopped = 0; s.contact = 0; s.blind = 0; s.imuContact = false; s.blindWall = false;
      if (this.takeoff) { s.noprog = 0; s.best = g.dist; }
      return;
    }
    const cmd = this.lastCmd.vx;
    s.stopped = cmd >= CFG.STOP_MIN_CMD && measured < 0.10 ? s.stopped + 1 : 0;
    s.contact = this.contactNow && cmd > 0.3 ? s.contact + 1 : 0;
    s.imuContact = s.contact >= 2;
    const fb = this.field ? this.field.fovBlocked : 0;
    s.blind = cmd >= 0.45 && measured < 0.30 && fb < 0.25 ? s.blind + 1 : 0;
    s.blindWall = s.blind >= 2;
    const key = `${g.tg.label}@${fmt(g.tg.x, 0)},${fmt(g.tg.y, 0)}`;
    if (key !== s.key) { s.key = key; s.best = g.dist; s.noprog = 0; }
    else if (g.dist < s.best - CFG.NOPROG_MIN_M) { s.best = g.dist; s.noprog = 0; }
    else s.noprog++;
  }

  resetStall() {
    Object.assign(this.stall, { stopped: 0, noprog: 0, contact: 0, blind: 0, imuContact: false, blindWall: false, key: '' });
    this.gov = 1.2;
  }

  // -- capa estrategica: hilo asincrono, ancla a la pose del fotograma
  stratTick(g, ev) {
    const st = this.strat;
    const depth = this.opts.source === 'depth';
    if (st.pending && this.t >= st.pending.readyT) this.stratProcess(st.pending, ev);
    if (st.pending || this.scan || this.takeoff) return;
    const ri = this.realWpIndex();
    if (ri < 0) return;
    const wp = this.wps[ri];
    const dWp = hyp(wp.x - this.pos.x, wp.y - this.pos.y);
    const goalAz = wrap(Math.atan2(wp.y - this.pos.y, wp.x - this.pos.x) - this.yaw);
    const period = depth ? CFG.DEPTH_PERIOD : CFG.VLM_PERIOD;
    const due = st.expedite || this.t - st.last >= period - 1e-6;
    if (!due || this.pos.z < CFG.SLM_MIN_ALT || dWp <= CFG.NEAR_WP || Math.abs(goalAz) > CFG.GOAL_CROP_DEG * DEG) return;
    const anchor = { x: this.pos.x, y: this.pos.y, z: this.pos.z, yaw: this.yaw, wp: wp.label, t: this.t };
    const latency = depth ? 0.11 : 0.6 + this.rng() * 0.5;
    let sectors;
    if (depth) sectors = this.depthSectors(anchor);
    else sectors = [...Array(9)].map((_, k) => ({ r: Math.floor(k / 3), c: k % 3, d: NaN, free: this.rng() < 0.9 }));
    st.pending = { id: st.nextId++, anchor, readyT: this.t + latency, latency, sectors, expedited: st.expedite };
    st.expedite = false;
    st.last = this.t;
    st.sent++;
    this.lastPulse = 'req';
    ev.push(`consulta estratégica #${st.pending.id} (${depth ? 'depth' : 'vlm'}${st.pending.expedited ? ', adelantada' : ''})`);
  }

  stratProcess(q, ev) {
    const st = this.strat;
    st.pending = null;
    const a = q.anchor;
    const ri = this.realWpIndex();
    const resp = { id: q.id, sectors: q.sectors, latency: q.latency, anchor: a, goal: null, chosen: null, outcome: '', sub: null, t: this.t };
    st.resp = resp;
    this.lastPulse = 'resp';
    const discard = (why) => { resp.outcome = `descartada: ${why}`; st.discarded++; ev.push(`respuesta #${q.id} ${resp.outcome}`); };
    if (this.t - a.t > CFG.MAX_AGE) return discard('más de 10 s');
    if (ri < 0 || this.wps[ri].label !== a.wp) return discard('cambió el waypoint');
    const wp = this.wps[ri];
    const dA = hyp(wp.x - a.x, wp.y - a.y);
    const az = wrap(Math.atan2(wp.y - a.y, wp.x - a.x) - a.yaw) / DEG;
    const el = Math.atan2(wp.z - a.z, dA) / DEG;
    const gc = az < -12 ? 0 : az > 12 ? 2 : 1;
    const gr = el > 12 ? 0 : el < -12 ? 2 : 1;
    resp.goal = gr * 3 + gc;
    if (q.sectors[resp.goal].free) {
      resp.outcome = 'sector de la meta libre: sin desvío';
      const cur = this.wps[this.idx];
      if (cur.kind === 'sub' && cur.origin === 'estratégica') { this.wps.splice(this.idx, 1); this.stall.key = ''; resp.outcome += ' (se descarta el pendiente)'; }
      ev.push(`respuesta #${q.id}: ${resp.outcome}`);
      return;
    }
    const free = q.sectors.map((s, k) => ({ s, k })).filter((o) => o.s.free);
    if (!free.length) { resp.outcome = 'ningún sector libre: sin sub-meta'; ev.push(`respuesta #${q.id}: ${resp.outcome}`); return; }
    const sd = (k) => hyp(STRAT_AZ[k % 3] - STRAT_AZ[gc], STRAT_EL[Math.floor(k / 3)] - STRAT_EL[gr]) + (Math.floor(k / 3) === gr ? 0 : 0.5);
    free.sort((p, q2) => sd(p.k) - sd(q2.k));
    const k = free[0].k;
    resp.chosen = k;
    const azC = STRAT_AZ[k % 3] * DEG, elC = STRAT_EL[Math.floor(k / 3)] * DEG;
    const dist = Math.min(CFG.SUBGOAL_DIST, dA);
    const sub = {
      x: a.x + Math.cos(a.yaw + azC) * dist,
      y: a.y + Math.sin(a.yaw + azC) * dist,
      z: Math.max(CFG.MIN_SUB_ALT, clamp(a.z + dist * Math.tan(elC), a.z - CFG.MAX_DZ, a.z + CFG.MAX_DZ)),
    };
    resp.sub = sub;
    const ahead = (sub.x - this.pos.x) * Math.cos(this.yaw) + (sub.y - this.pos.y) * Math.sin(this.yaw);
    if (ahead < CFG.MIN_AHEAD) return discard('ya superada (< 4 m por delante)');
    resp.outcome = `sub-meta hacia ${COLS[k % 3]}${Math.floor(k / 3) + 1}`;
    if (this.insertSubgoal(sub, ev, 'estratégica')) st.applied++;
    else resp.outcome += ' (duplicada, ignorada)';
  }

  startDeadlock(why, g, ev) {
    this.deadlocks++;
    ev.push(`deadlock: ${why}`);
    if (this.strat.pending) { ev.push(`consulta #${this.strat.pending.id} cancelada (el barrido es más reciente)`); this.strat.pending = null; }
    if (this.opts.deadlock === 'depth') {
      const h = [0, 90, 180, -90].map((d) => wrap(this.yaw + d * DEG));
      this.scan = { headings: h, i: 0, phase: 'rotate', rot: 0, settle: 0, frames: [], failed: g.bearing, startT: this.t };
      this.scanViz = [];
      return this.scanStep(g, ev);
    }
    return this.blindEscape(g, ev, 'estrategia blind');
  }

  blindEscape(g, ev, why) {
    this.resetStall();
    if (this.pos.z > CFG.MAX_ESCAPE_ALT) {
      const side = wrap(g.bearing - this.yaw) >= 0 ? 1 : -1;
      this.maneuver = { action: 'GIRAR_90', left: CFG.TURN_CYCLES, targetYaw: snap90(this.yaw + side * 90 * DEG), rate: 90 };
      ev.push(`${why}: escape GIRAR_90 (sobre 30 m)`);
    } else {
      this.maneuver = { action: 'GANAR_ALTURA', left: CFG.VERT_CYCLES };
      this.anchorAlt = this.pos.z + 2.4;
      ev.push(`${why}: escape GANAR_ALTURA 1.6 s`);
    }
    return this.continueManeuver('2');
  }

  scanStep(g, ev) {
    const s = this.scan;
    const target = s.headings[s.i];
    if (s.phase === 'rotate') {
      if (Math.abs(wrap(target - this.yaw)) < 4 * DEG) { s.phase = 'settle'; s.settle = CFG.SCAN_SETTLE; }
      else if (++s.rot > CFG.SCAN_ROT_TIMEOUT) {
        this.scan = null;
        return this.blindEscape(g, ev, 'rotación imposible');
      }
      if (s.phase === 'rotate') return { rule: '1', action: 'BARRIDO', behaviour: 'deep_scan · rotar', targetYaw: target, rate: 90, vx: 0 };
    }
    if (--s.settle > 0) return { rule: '1', action: 'BARRIDO', behaviour: 'deep_scan · asentar', targetYaw: target, rate: 90, vx: 0 };
    // captura y juicio con la profundidad estimada (p5 del sector central B2)
    const pose = { x: this.pos.x, y: this.pos.y, z: this.pos.z, yaw: this.yaw };
    const sec = this.depthSectors(pose)[4];
    const name = ['frente', 'derecha', 'atrás', 'izquierda'][s.i];
    s.frames.push({ yaw: this.yaw, free: sec.free, d: sec.d, name });
    this.scanViz.push({ pose, free: sec.free, d: sec.d });
    ev.push(`barrido ${name}: ${sec.free ? 'transitable' : 'bloqueado'} (p5 ${fmt(sec.d, 0)} m)`);
    s.i++; s.phase = 'rotate'; s.rot = 0;
    if (s.i < CFG.SCAN_HEADINGS) return { rule: '1', action: 'BARRIDO', behaviour: 'deep_scan · captura', targetYaw: s.headings[s.i], rate: 90, vx: 0 };
    return this.finishScan(g, ev);
  }

  finishScan(g, ev) {
    const s = this.scan;
    this.scan = null;
    const goalB = g.bearing;
    const near = this.tried.filter((t) => hyp(t.x - this.pos.x, t.y - this.pos.y) < 10);
    const free = s.frames.filter((f) => f.free && Math.abs(wrap(f.yaw - s.failed)) >= 45 * DEG);
    const ok = free.filter((f) => !near.some((t) => Math.abs(wrap(t.yaw - f.yaw)) < 45 * DEG));
    let f;
    if (ok.length) {
      ok.sort((a, b) => Math.abs(wrap(a.yaw - goalB)) - Math.abs(wrap(b.yaw - goalB)));
      f = ok[0];
    } else if (free.length) {
      // deadlocks repetidos: el rumbo libre mas distinto de lo ya probado
      const gap = (x) => Math.min(...near.map((t) => Math.abs(wrap(t.yaw - x.yaw))));
      free.sort((a, b) => gap(b) - gap(a));
      f = free[0];
      ev.push('deadlock repetido: rumbo libre más distinto de lo probado');
    } else return this.blindEscape(g, ev, 'sin rumbo transitable');
    const ri = this.realWpIndex();
    const wp = this.wps[ri];
    const dist = Math.min(CFG.SUBGOAL_DIST, hyp(wp.x - this.pos.x, wp.y - this.pos.y));
    const sub = { x: this.pos.x + Math.cos(f.yaw) * dist, y: this.pos.y + Math.sin(f.yaw) * dist, z: this.pos.z };
    this.tried.push({ x: this.pos.x, y: this.pos.y, yaw: f.yaw });
    ev.push(`barrido resuelto: rumbo ${f.name} (más cercano a la meta)`);
    this.insertSubgoal(sub, ev, 'barrido');
    this.resetStall();
    this.anchorAlt = this.pos.z;
    return { rule: '1', action: 'FRENAR', behaviour: 'deep_scan · sub-meta', vx: 0 };
  }

  continueManeuver(rule) {
    const m = this.maneuver;
    m.left--;
    if (m.left <= 0) this.maneuver = null;
    return { rule, action: m.action, behaviour: `maniobra (${Math.max(0, m.left)} ciclos)`, targetYaw: m.targetYaw, rate: m.rate, yawRate: m.yawRate };
  }

  evasive(rule, ev) {
    const f = this.field;
    const score = (c) => {
      const mid = f.cells[3 + c];
      return (Number.isFinite(mid.ttc) ? Math.min(mid.ttc, 20) : 20) - mid.occ * 10 + (Number.isFinite(mid.d) ? Math.min(mid.d, 40) / 4 : 10);
    };
    let side = score(0) > score(2) ? -1 : score(2) > score(0) ? 1 : 0;
    if (side === 0) {
      const g = this.guidance();
      side = wrap(g.bearing - this.yaw) >= 0 ? 1 : -1;
    }
    const action = side < 0 ? 'EVADIR_IZQUIERDA' : 'EVADIR_DERECHA';
    this.maneuver = { action, left: CFG.EVADE_CYCLES, yawRate: side * CFG.EVADE_YAW_RATE * DEG };
    this.gov = 1.2;
    ev.push(`evasive_node: ${action}`);
    return this.continueManeuver(rule);
  }

  navigate(g, ev) {
    const arm = this.opts.arm;
    this.updateStall(g);
    if (arm === 'slm' && this.opts.source !== 'off') this.stratTick(g, ev);
    if (this.takeoff) return { rule: 'despegue', action: 'MANTENER_RUMBO', behaviour: 'reactive_node · despegue vertical' };
    if (arm === 'reactive') return { rule: '8', action: 'MANTENER_RUMBO', behaviour: 'reactive_node' };

    const f = this.field, s = this.stall;
    if (this.scan) return this.scanStep(g, ev);                                        // 1
    if (s.stopped >= CFG.STOP_CYCLES) return this.startDeadlock('stopped_prolonged', g, ev); // 2
    if (s.noprog >= CFG.NOPROG_CYCLES) return this.startDeadlock('wp_no_progress', g, ev);
    if (this.maneuver) return this.continueManeuver('3');                             // 3
    if (s.imuContact || s.blindWall) {                                                 // 4
      ev.push(s.imuContact ? 'imu_contact' : 'blind_wall');
      return this.evasive('4', ev);
    }
    if (this.pos.z < CFG.OPTICAL_MIN_ALT) return { rule: '5', action: 'MANTENER_RUMBO', behaviour: 'reactive_node · piso óptico' };
    // 6: z_path_blocked no se da en estas escenas (sin techos)
    const c = f.center;
    if (c.ttc <= CFG.TTC_EVASION || (c.blocked && c.ttc <= CFG.TTC_SAFE)) {           // 7
      if (f.fovBlocked > CFG.FOV_BLOCKED) {
        const side = wrap(g.bearing - this.yaw) >= 0 ? 1 : -1;
        this.maneuver = { action: 'GIRAR_90', left: CFG.TURN_CYCLES, targetYaw: snap90(this.yaw + side * 90 * DEG), rate: 90 };
        if (arm === 'slm') { this.strat.expedite = true; ev.push('GIRAR_90: consulta estratégica adelantada'); }
        this.gov = 1.2;
        return this.continueManeuver('7');
      }
      return this.evasive('7', ev);
    }
    if (c.blocked || f.minTTC <= CFG.TTC_SAFE) return this.evasive('7b', ev);         // 7b
    return { rule: '8', action: 'MANTENER_RUMBO', behaviour: 'reactive_node' };       // 8
  }

  // action_to_command(): body frame; aca vz positivo = sube (NED lo invierte)
  command(dec, g) {
    const f = this.field;
    const nearObstacle = f && f.cells.some((c) => c.blocked);
    const guidVz = clamp(g.dz * 0.8, -1.5, 1.5);
    let vx = 0, vz = 0, yawRate = dec.yawRate ?? 0, targetYaw = dec.targetYaw ?? null, rate = dec.rate ?? 0;
    switch (dec.action) {
      case 'MANTENER_RUMBO': {
        const err = wrap(g.bearing - this.yaw);
        const maxRate = (nearObstacle && !this.takeoff ? 5 : 40) * DEG;
        yawRate = clamp(err * 1.5, -maxRate, maxRate);
        if (this.takeoff) { vx = 0; vz = 1.5; }
        else {
          const capV = f && !f.evidence ? Math.min(this.gov, 1.5) : this.gov;
          vx = Math.min(CFG.CRUISE, capV) * clamp(Math.cos(err), 0, 1);
          vz = guidVz;
        }
        break;
      }
      case 'EVADIR_IZQUIERDA': case 'EVADIR_DERECHA':
        vx = f && f.center.d < 6 ? 0.3 : 0.8; vz = guidVz; break;
      case 'GIRAR_90': case 'BARRIDO': vx = 0; vz = 0; break;
      case 'GANAR_ALTURA': vx = 0; vz = 1.5; break;
      case 'PERDER_ALTURA': vx = 1.0; vz = -0.8; break;
      default: { // FRENAR: ancla de altitud del motor (zona muerta 0.3 m, Kp 0.35, tope 0.8 m/s)
        const e = this.anchorAlt - this.pos.z;
        vz = Math.abs(e) < 0.3 ? 0 : clamp(e * 0.35, -0.8, 0.8);
      }
    }
    if (dec.action !== 'FRENAR') this.anchorAlt = this.pos.z;
    return { vx, vz, yawRate, targetYaw, rate, action: dec.action };
  }

  collides(x, y, z) {
    const r = CFG.DRONE_R;
    for (const b of this.world) if (x > b.x0 - r && x < b.x1 + r && y > b.y0 - r && y < b.y1 + r && z < b.h + 0.3) return true;
    return false;
  }

  integrate(cmd) {
    const dt = CFG.DT;
    if (cmd.targetYaw !== null && cmd.targetYaw !== undefined) {
      const e = wrap(cmd.targetYaw - this.yaw), m = cmd.rate * DEG * dt;
      this.yaw = wrap(this.yaw + clamp(e, -m, m));
    } else this.yaw = wrap(this.yaw + cmd.yawRate * dt);
    const des = { x: cmd.vx * Math.cos(this.yaw), y: cmd.vx * Math.sin(this.yaw), z: cmd.vz };
    const k = Math.min(1, dt / 0.35);
    for (const a of ['x', 'y', 'z']) this.v[a] += (des[a] - this.v[a]) * k;
    const n = { x: this.pos.x + this.v.x * dt, y: this.pos.y + this.v.y * dt, z: Math.max(0, this.pos.z + this.v.z * dt) };
    this.contactNow = false;
    if (this.collides(n.x, n.y, n.z)) {
      // contacto: se desliza por la componente libre, como contra una pared en AirSim
      this.contactNow = true;
      const z = this.collides(this.pos.x, this.pos.y, n.z) ? this.pos.z : n.z;
      if (!this.collides(n.x, this.pos.y, z)) { this.dist += Math.abs(n.x - this.pos.x); this.pos = { x: n.x, y: this.pos.y, z }; this.v.y = 0; }
      else if (!this.collides(this.pos.x, n.y, z)) { this.dist += Math.abs(n.y - this.pos.y); this.pos = { x: this.pos.x, y: n.y, z }; this.v.x = 0; }
      else { this.pos.z = z; this.v.x = 0; this.v.y = 0; }
    } else {
      this.dist += hyp(n.x - this.pos.x, n.y - this.pos.y);
      this.pos = n;
    }
    // gobernador: libera vx en rampa tras un bloqueo
    this.gov = Math.min(CFG.CRUISE, this.gov + 0.3 * dt);
  }

  step() {
    if (this.status !== 'flying') return null;
    const ev = [];
    if (this.t >= CFG.MAX_T) { this.status = 'timeout'; this.statusMsg = `tiempo agotado (${CFG.MAX_T} s)`; return null; }
    if (!this.trackerUpdate(ev)) { this.pushTrace({ rule: '—', action: '—', path: [] }, ev); return null; }
    const g = this.guidance();
    if (this.takeoff && this.pos.z >= this.wps[0].z - CFG.TAKEOFF_TOL) {
      this.takeoff = false; ev.push('despegue vertical completo');
      this.stall.best = g.dist;
    }
    this.prevCycle = { pos: { ...this.prev.pos } };
    const path = ['capture'];
    let dec;
    const degraded = this.degradedLeft > 0;
    if (degraded) {
      this.degradedLeft--;
      path.push('degraded_router', 'degraded_hover', 'motor', 'END');
      dec = { rule: '—', action: 'FRENAR', behaviour: 'degraded_hover (sin imagen)' };
      ev.push('fotograma perdido: degraded = True');
    } else {
      path.push('degraded_router', 'perception', 'navigate', 'motor', 'END');
      this.field = this.computeField();
      dec = this.navigate(g, ev);
    }
    this.prev = { pos: { ...this.pos }, yaw: this.yaw };
    const cmd = this.command(dec, g);
    this.integrate(cmd);
    this.lastCmd = cmd;
    if (this.contactNow) this.contacts++;
    this.dec = { ...dec, path, cmd, degraded, events: ev };
    this.t += CFG.DT; this.cycle++;
    this.distMin = Math.min(this.distMin, ...this.world.map((b) => pointBoxDist(this.pos, b)));
    this.curDist = Math.min(Infinity, ...this.world.map((b) => pointBoxDist(this.pos, b)));
    const last = this.trail[this.trail.length - 1];
    if (hyp(last.x - this.pos.x, last.y - this.pos.y) + Math.abs(last.z - this.pos.z) > 0.4) this.trail.push({ ...this.pos });
    this.pushTrace({ ...dec, path, degraded }, ev);
    return this.dec;
  }

  pushTrace(dec, ev) {
    this.trace.push({
      cycle: this.cycle, t: this.t, path: dec.path || [], rule: dec.rule, action: dec.action,
      ttc: this.field && !dec.degraded ? this.field.center.ttc : NaN, ev: ev.join(' · '),
    });
    if (this.trace.length > 400) this.trace.shift();
  }
}

// ---------------------------------------------------------------------------
// Escena 3D
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const isDark = () => matchMedia('(prefers-color-scheme: dark)').matches && document.documentElement.dataset.theme !== 'light'
  || document.documentElement.dataset.theme === 'dark';

// sim (x norte, y este, z arriba) -> three (X = x, Y = z, Z = y)
const V3 = (p, dz = 0) => new THREE.Vector3(p.x, p.z + dz, p.y);

const GRAPH_NODES = {
  capture:         { u: 0,  w: 0,   label: 'capture',         kind: 'node' },
  degraded_router: { u: 13, w: 0,   label: 'degraded_router', kind: 'router' },
  perception:      { u: 27, w: -7,  label: 'perception',      kind: 'node' },
  navigate:        { u: 43, w: -7,  label: 'navigate',        kind: 'node' },
  degraded_hover:  { u: 35, w: 9,   label: 'degraded_hover',  kind: 'node' },
  motor:           { u: 58, w: 0,   label: 'motor',           kind: 'node' },
  END:             { u: 70, w: 0,   label: 'END',             kind: 'end' },
  strategic:       { u: 43, w: -24, label: 'capa estratégica', kind: 'teal' },
  tracker:         { u: 14, w: -24, label: 'WaypointTracker', kind: 'outer' },
};
const GRAPH_EDGES = [
  ['capture', 'degraded_router'], ['degraded_router', 'perception'], ['degraded_router', 'degraded_hover'],
  ['perception', 'navigate'], ['navigate', 'motor'], ['degraded_hover', 'motor'], ['motor', 'END'],
  ['navigate', 'strategic', 'async'], ['strategic', 'tracker', 'async'], ['tracker', 'capture', 'outer'],
];

class Scene3D {
  constructor(host, sim, onPick) {
    this.host = host; this.sim = sim; this.onPick = onPick;
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = 'labels';
    host.appendChild(this.labels.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -2000, 4000);
    this.camera.position.set(-140, 160, 170);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = 1.45;
    this.controls.minZoom = 0.3; this.controls.maxZoom = 12;

    this.hemi = new THREE.HemisphereLight(0xffffff, 0x8899aa, 1.6);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(0xffffff, 1.6);
    this.sun.position.set(-80, 160, 60);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    this.sun.shadow.bias = -0.0005;
    this.scene.add(this.sun, this.sun.target);

    this.city = new THREE.Group(); this.scene.add(this.city);
    this.dyn = new THREE.Group(); this.scene.add(this.dyn);
    this.graph = new THREE.Group(); this.scene.add(this.graph);
    this.pickables = [];
    this.view = 'system';
    this.tween = null;
    this.follow = false;
    this.showRays = true;
    this.pulses = [];
    this.nodeGlow = {};

    this.buildDrone();
    this.buildDynamic();
    this.resize();
    new ResizeObserver(() => this.resize()).observe(host);
    this.bindPick();
  }

  palette() {
    const dark = isDark();
    return {
      bg: new THREE.Color(css('--surface-2') || (dark ? '#1F252E' : '#F6F8FA')),
      ground: new THREE.Color(dark ? '#1A2028' : '#E7EBF0'),
      street: new THREE.Color(dark ? '#232A33' : '#DCE2E9'),
      building: new THREE.Color(dark ? '#2C3540' : '#FFFFFF'),
      buildingTop: new THREE.Color(dark ? '#36414E' : '#F1F4F8'),
      edge: new THREE.Color(dark ? '#4B5765' : '#AEB8C5'),
      tree: new THREE.Color(dark ? '#2F7A55' : '#79C49A'),
      trunk: new THREE.Color(dark ? '#5B4636' : '#9C7B5E'),
      mesh: new THREE.Color(css('--warn') || '#D97706'),
      accent: new THREE.Color(css('--accent') || '#0066CC'),
      teal: new THREE.Color(css('--teal') || '#0F9488'),
      crit: new THREE.Color(css('--crit') || '#DC2626'),
      warn: new THREE.Color(css('--warn') || '#D97706'),
      safe: new THREE.Color(css('--safe') || '#259E5F'),
      muted: new THREE.Color(css('--muted') || '#718096'),
      platform: new THREE.Color(dark ? '#222932' : '#FFFFFF'),
      block: new THREE.Color(dark ? '#2E3742' : '#F3F6FA'),
      dark,
    };
  }

  clearGroup(g) {
    while (g.children.length) {
      const o = g.children.pop();
      o.traverse((c) => {
        if (c.isCSS2DObject) c.element.remove();
        if (c.geometry) c.geometry.dispose();
        if (c.material) (Array.isArray(c.material) ? c.material : [c.material]).forEach((m) => m.dispose());
      });
    }
  }

  bounds() {
    const s = this.sim;
    let x0 = -10, x1 = 10, y0 = -10, y1 = 10;
    for (const b of s.world) { x0 = Math.min(x0, b.x0); x1 = Math.max(x1, b.x1); y0 = Math.min(y0, b.y0); y1 = Math.max(y1, b.y1); }
    for (const w of s.sc.wps) { x0 = Math.min(x0, w[0]); x1 = Math.max(x1, w[0]); y0 = Math.min(y0, w[1]); y1 = Math.max(y1, w[1]); }
    return { x0: x0 - 8, x1: x1 + 8, y0: y0 - 8, y1: y1 + 8 };
  }

  buildWorld() {
    const P = this.pal = this.palette();
    this.scene.background = P.bg;
    this.clearGroup(this.city);
    this.pickables = this.pickables.filter((o) => o.userData.keep);
    const bd = this.bd = this.bounds();
    const w = bd.x1 - bd.x0, d = bd.y1 - bd.y0;

    const ground = new THREE.Mesh(new THREE.PlaneGeometry(w + 60, d + 60), new THREE.MeshStandardMaterial({ color: P.ground, roughness: 1 }));
    ground.rotation.x = -Math.PI / 2;
    ground.position.set((bd.x0 + bd.x1) / 2, 0, (bd.y0 + bd.y1) / 2);
    ground.receiveShadow = true;
    ground.userData.ground = true;
    this.ground = ground;
    this.city.add(ground);

    const grid = new THREE.GridHelper(Math.max(w, d) + 60, Math.round((Math.max(w, d) + 60) / 10), P.edge, P.edge);
    grid.material.opacity = P.dark ? 0.18 : 0.25; grid.material.transparent = true;
    grid.position.copy(ground.position).setY(0.02);
    this.city.add(grid);

    const edgeMat = new THREE.LineBasicMaterial({ color: P.edge, transparent: true, opacity: 0.9 });
    for (const b of this.sim.world) {
      const cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
      if (b.kind === 'building') {
        const geo = new THREE.BoxGeometry(b.x1 - b.x0, b.h, b.y1 - b.y0);
        const m = new THREE.Mesh(geo, [
          new THREE.MeshStandardMaterial({ color: P.building, roughness: 0.9 }),
          new THREE.MeshStandardMaterial({ color: P.building, roughness: 0.9 }),
          new THREE.MeshStandardMaterial({ color: P.buildingTop, roughness: 0.9 }),
          new THREE.MeshStandardMaterial({ color: P.building, roughness: 0.9 }),
          new THREE.MeshStandardMaterial({ color: P.building, roughness: 0.9 }),
          new THREE.MeshStandardMaterial({ color: P.building, roughness: 0.9 }),
        ]);
        m.position.set(cx, b.h / 2, cy);
        m.castShadow = true; m.receiveShadow = true;
        const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat);
        m.add(e);
        this.city.add(m);
      } else if (b.kind === 'tree') {
        const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.45, b.h * 0.45, 8), new THREE.MeshStandardMaterial({ color: P.trunk }));
        trunk.position.set(b.cx, b.h * 0.22, b.cy); trunk.castShadow = true;
        const crown = new THREE.Mesh(new THREE.IcosahedronGeometry(b.r * 1.15, 1), new THREE.MeshStandardMaterial({ color: P.tree, flatShading: true, roughness: 0.8 }));
        crown.scale.set(1, (b.h * 0.62) / (b.r * 2.3), 1);
        crown.position.set(b.cx, b.h * 0.66, b.cy); crown.castShadow = true;
        this.city.add(trunk, crown);
      } else if (b.kind === 'mesh') {
        const len = b.y1 - b.y0;
        const geo = new THREE.PlaneGeometry(len, b.h, Math.round(len / 1.5), Math.round(b.h / 1.5));
        const mat = new THREE.MeshBasicMaterial({ color: P.mesh, wireframe: true, transparent: true, opacity: 0.55 });
        const m = new THREE.Mesh(geo, mat);
        m.rotation.y = Math.PI / 2;
        m.position.set(cx, b.h / 2, cy);
        const posts = new THREE.Mesh(new THREE.BoxGeometry(0.4, b.h, 0.4), new THREE.MeshStandardMaterial({ color: P.mesh }));
        posts.position.set(cx, b.h / 2, b.y0);
        const posts2 = posts.clone(); posts2.position.z = b.y1;
        this.city.add(m, posts, posts2);
        this.city.add(this.label('malla · invisible al flujo', 'plain', new THREE.Vector3(cx, b.h + 3, cy)));
      }
    }

    const span = Math.max(w, d);
    const sc = this.sun.shadow.camera;
    sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.near = 1; sc.far = 800;
    sc.updateProjectionMatrix();
    this.sun.target.position.copy(ground.position);
    this.sun.position.copy(ground.position).add(new THREE.Vector3(-90, 200, 70));

    this.buildGraph();
  }

  label(text, cls, pos, onClick) {
    const el = document.createElement('div');
    el.className = `lbl3d ${cls}`;
    el.textContent = text;
    if (onClick) el.addEventListener('pointerdown', (e) => { e.stopPropagation(); onClick(); });
    const o = new CSS2DObject(el);
    if (pos) o.position.copy(pos);
    return o;
  }

  buildDrone() {
    const g = new THREE.Group();
    const s = 1.6;
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.9 * s, 0.32 * s, 0.6 * s), new THREE.MeshStandardMaterial({ color: 0x2f7fe0, roughness: 0.5 }));
    body.castShadow = true;
    const nose = new THREE.Mesh(new THREE.BoxGeometry(0.25 * s, 0.2 * s, 0.4 * s), new THREE.MeshStandardMaterial({ color: 0xdc2626 }));
    nose.position.x = 0.55 * s;
    const cam = new THREE.Mesh(new THREE.CylinderGeometry(0.09 * s, 0.09 * s, 0.12 * s, 12), new THREE.MeshStandardMaterial({ color: 0x111111 }));
    cam.rotation.z = Math.PI / 2; cam.position.set(0.7 * s, 0, 0);
    g.add(body, nose, cam);
    this.props = [];
    for (const [ax, az] of [[1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.9 * s, 0.07 * s, 0.07 * s), new THREE.MeshStandardMaterial({ color: 0x6b7a8f }));
      arm.position.set(ax * 0.32 * s, 0.05 * s, az * 0.32 * s);
      arm.rotation.y = ax * az > 0 ? -Math.PI / 4 : Math.PI / 4;
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.1 * s, 0.1 * s, 0.14 * s, 10), new THREE.MeshStandardMaterial({ color: 0x1f2630 }));
      motor.position.set(ax * 0.62 * s, 0.1 * s, az * 0.62 * s);
      const prop = new THREE.Mesh(new THREE.CylinderGeometry(0.42 * s, 0.42 * s, 0.02 * s, 20),
        new THREE.MeshStandardMaterial({ color: 0x8fa3b8, transparent: true, opacity: 0.45 }));
      prop.position.set(ax * 0.62 * s, 0.19 * s, az * 0.62 * s);
      this.props.push(prop);
      g.add(arm, motor, prop);
    }
    const hit = new THREE.Mesh(new THREE.SphereGeometry(2.4, 8, 8), new THREE.MeshBasicMaterial({ visible: false }));
    hit.userData = { inspect: 'drone', keep: true };
    g.add(hit);
    this.pickables.push(hit);
    this.drone = g;
    this.scene.add(g);
    const shadow = new THREE.Mesh(new THREE.CircleGeometry(1.4, 24), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.18, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2;
    this.droneShadow = shadow;
    this.scene.add(shadow);
    this.droneLabel = this.label('dron', 'node', null, () => this.onPick('drone'));
    this.droneLabel.position.set(0, 3.2, 0);
    g.add(this.droneLabel);
  }

  buildDynamic() {
    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3 * 6000), 3));
    this.trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0x0066cc }));
    this.trail.frustumCulled = false;
    this.scene.add(this.trail);
    const rayGeo = new THREE.BufferGeometry();
    rayGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3 * 2 * 40), 3));
    rayGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(3 * 2 * 40), 3));
    this.rays = new THREE.LineSegments(rayGeo, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95 }));
    this.rays.frustumCulled = false;
    this.scene.add(this.rays);
    this.routeLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0xdc2626, dashSize: 2, gapSize: 1.5 }));
    this.routeLine.frustumCulled = false;
    this.scene.add(this.routeLine);
  }

  buildGraph() {
    this.clearGroup(this.graph);
    this.graphLabelsOn = undefined;
    this.pickables = this.pickables.filter((o) => o.userData.keep);
    const P = this.pal, bd = this.bd;
    const origin = new THREE.Vector3(bd.x0 - 4, 46, bd.y0 - 52);
    this.graphOrigin = origin;
    const platform = new THREE.Mesh(new THREE.BoxGeometry(86, 1.2, 50), new THREE.MeshStandardMaterial({ color: P.platform, roughness: 0.9 }));
    platform.position.copy(origin).add(new THREE.Vector3(35, -1.6, -6));
    platform.receiveShadow = true;
    platform.add(new THREE.LineSegments(new THREE.EdgesGeometry(platform.geometry), new THREE.LineBasicMaterial({ color: P.edge })));
    this.graph.add(platform);
    for (const [txt, off] of [['grafo LangGraph · 5 Hz', [-4, 1, 16]], ['lazo lento · asíncrono', [28, 1, -32]]]) {
      const l = this.label(txt, 'plain', origin.clone().add(new THREE.Vector3(...off)));
      l.userData.lod = true;
      this.graph.add(l);
    }

    this.nodePos = {};
    this.nodeMesh = {};
    this.nodeLabel = {};
    for (const [key, n] of Object.entries(GRAPH_NODES)) {
      const p = origin.clone().add(new THREE.Vector3(n.u, 0, n.w));
      this.nodePos[key] = p;
      let geo, color = P.block;
      if (n.kind === 'router') { geo = new THREE.OctahedronGeometry(2.6); }
      else if (n.kind === 'end') { geo = new THREE.CylinderGeometry(2.2, 2.2, 1.6, 24); }
      else geo = new THREE.BoxGeometry(9, 3, 6);
      if (n.kind === 'teal') color = P.teal.clone().lerp(P.block, 0.65);
      if (n.kind === 'outer') color = P.block;
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.7, emissive: P.accent, emissiveIntensity: 0 });
      const m = new THREE.Mesh(geo, mat);
      m.position.copy(p).setY(p.y + (n.kind === 'router' ? 2.4 : 1.5));
      m.castShadow = true;
      m.userData = { inspect: key };
      m.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: n.kind === 'teal' ? P.teal : P.edge })));
      this.graph.add(m);
      this.pickables.push(m);
      this.nodeMesh[key] = m;
      const lab = this.label(n.label, `node${n.kind === 'teal' ? ' teal' : ''}`, p.clone().setY(p.y + 6), () => this.onPick(key));
      lab.userData.lod = true;
      this.graph.add(lab);
      this.nodeLabel[key] = lab;
      this.nodeGlow[key] = 0;
    }
    this.edgeCurves = {};
    for (const [a, b, kind] of GRAPH_EDGES) {
      const pa = this.nodePos[a].clone().setY(this.nodePos[a].y + 1.5), pb = this.nodePos[b].clone().setY(this.nodePos[b].y + 1.5);
      const mid = pa.clone().lerp(pb, 0.5).setY(pa.y + (kind ? 5 : 2.5));
      const curve = new THREE.QuadraticBezierCurve3(pa, mid, pb);
      this.edgeCurves[`${a}>${b}`] = curve;
      const pts = curve.getPoints(30);
      const color = kind === 'async' ? P.teal : kind === 'outer' ? P.muted : P.accent;
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts),
        kind ? new THREE.LineDashedMaterial({ color, dashSize: 1.2, gapSize: 0.8 }) : new THREE.LineBasicMaterial({ color }));
      if (kind) line.computeLineDistances();
      this.graph.add(line);
      const head = new THREE.Mesh(new THREE.ConeGeometry(0.6, 1.6, 10), new THREE.MeshBasicMaterial({ color }));
      const tan = curve.getTangent(0.92);
      head.position.copy(curve.getPoint(0.92));
      head.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tan);
      this.graph.add(head);
    }
    const lk = (a, b, t, txt) => {
      const l = this.label(txt, 'plain', this.edgeCurves[`${a}>${b}`].getPoint(t).add(new THREE.Vector3(0, 1.4, 0)));
      l.userData.lod = true;
      this.graph.add(l);
    };
    lk('degraded_router', 'perception', 0.5, 'ok');
    lk('degraded_router', 'degraded_hover', 0.55, 'degradado');
    lk('navigate', 'strategic', 0.5, 'frame + pose');
    lk('strategic', 'tracker', 0.5, 'sub-meta → inject_corner');
  }

  firePath(path, dur) {
    for (let i = 0; i < path.length - 1; i++) {
      const c = this.edgeCurves[`${path[i]}>${path[i + 1]}`];
      if (!c) continue;
      this.spawnPulse(c, dur * i / (path.length - 1), dur / (path.length - 1), this.pal.accent);
    }
    for (const n of path) this.nodeGlow[n] = 1;
  }

  fireAsync(kind, dur) {
    const P = this.pal;
    if (kind === 'req') { this.spawnPulse(this.edgeCurves['navigate>strategic'], 0, Math.max(dur, 0.25), P.teal); this.nodeGlow.strategic = 1; }
    if (kind === 'resp') { this.spawnPulse(this.edgeCurves['strategic>tracker'], 0, Math.max(dur, 0.25), P.teal); this.nodeGlow.tracker = 1; this.nodeGlow.strategic = 1; }
  }

  spawnPulse(curve, delay, dur, color) {
    let m = this.pulsePool?.pop();
    if (!m) m = new THREE.Mesh(new THREE.SphereGeometry(0.75, 12, 12), new THREE.MeshBasicMaterial());
    m.material.color.copy(color);
    m.visible = false;
    this.scene.add(m);
    this.pulses.push({ m, curve, t: -delay, dur });
  }

  setView(v, instant) {
    this.view = v;
    const s = this.sim, bd = this.bd;
    const city = new THREE.Vector3((bd.x0 + bd.x1) / 2, 0, (bd.y0 + bd.y1) / 2);
    const span = Math.max(bd.x1 - bd.x0, bd.y1 - bd.y0);
    const g = this.graphOrigin.clone().add(new THREE.Vector3(35, 0, -8));
    const drone = V3(s.pos);
    const iso = new THREE.Vector3(-1, 1.05, 1.15).normalize();
    let target, dir = iso, ext;
    switch (v) {
      case 'mission': target = city; ext = span * 1.0; break;
      case 'graph': target = g; ext = 92; dir = new THREE.Vector3(-0.15, 1.1, 1).normalize(); break;
      case 'perception': {
        // detras del dron y algo a su izquierda, mirando hacia adonde vuela
        const hx = Math.cos(s.yaw), hy = Math.sin(s.yaw);
        target = drone.clone().add(new THREE.Vector3(hx * 10, 0, hy * 10));
        ext = 46;
        dir = new THREE.Vector3(-hx + hy * 0.6, 0.75, -hy - hx * 0.6).normalize();
        break;
      }
      case 'strategic': target = drone; ext = 60; dir = new THREE.Vector3(-0.35, 1.6, 0.6).normalize(); break;
      default: target = city.clone().lerp(g, 0.35); ext = span * 1.25 + 30;
    }
    const pos = target.clone().add(dir.clone().multiplyScalar(300));
    const zoom = this.zoomFor(ext);
    if (instant) {
      this.camera.position.copy(pos); this.controls.target.copy(target); this.camera.zoom = zoom; this.camera.updateProjectionMatrix();
      this.tween = null;
    } else {
      this.tween = { t: 0, p0: this.camera.position.clone(), p1: pos, t0: this.controls.target.clone(), t1: target, z0: this.camera.zoom, z1: zoom };
    }
  }

  zoomFor(ext) {
    const w = this.host.clientWidth || 800, h = this.host.clientHeight || 500;
    const aspect = w / h;
    const halfH = 60;
    const need = ext / 2;
    return Math.min(halfH * aspect, halfH) / need;
  }

  resize() {
    const w = this.host.clientWidth, h = this.host.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h);
    this.labels.setSize(w, h);
    const aspect = w / h, H = 60;
    Object.assign(this.camera, { left: -H * aspect, right: H * aspect, top: H, bottom: -H });
    this.camera.updateProjectionMatrix();
  }

  bindPick() {
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
    let down = null;
    const el = this.renderer.domElement;
    el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
    el.addEventListener('pointerup', (e) => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const r = el.getBoundingClientRect();
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      if (this.placing) {
        const hit = ray.intersectObject(this.ground)[0];
        if (hit) this.onPlace(hit.point.x, hit.point.z);
        return;
      }
      const hit = ray.intersectObjects(this.pickables, false)[0];
      if (hit) this.onPick(hit.object.userData.inspect);
    });
  }

  update(alpha, dtReal) {
    const s = this.sim, P = this.pal;
    // pose interpolada entre ciclos
    const a = s.status === 'flying' ? clamp(alpha, 0, 1) : 1;
    const p = { x: s.prev.pos.x + (s.pos.x - s.prev.pos.x) * a, y: s.prev.pos.y + (s.pos.y - s.prev.pos.y) * a, z: s.prev.pos.z + (s.pos.z - s.prev.pos.z) * a };
    const yaw = s.prev.yaw + wrap(s.yaw - s.prev.yaw) * a;
    const before = this.drone.position.clone();
    this.drone.position.copy(V3(p, 0.4));
    this.drone.rotation.y = -yaw;
    this.droneShadow.position.set(p.x, 0.05, p.y);
    const spin = p.z > 0.2 ? 40 : 0;
    for (const pr of this.props) pr.rotation.y += spin * dtReal;
    if (this.follow || this.view === 'perception' || this.view === 'strategic') {
      if (!this.tween) {
        const d = this.drone.position.clone().sub(before);
        this.camera.position.add(d); this.controls.target.add(d);
      }
    }

    // estela
    const tp = this.trail.geometry.attributes.position;
    const n = Math.min(s.trail.length, 5999);
    for (let i = 0; i < n; i++) { const q = s.trail[s.trail.length - n + i]; tp.setXYZ(i, q.x, q.z + 0.4, q.y); }
    tp.setXYZ(n, p.x, p.z + 0.4, p.y);
    tp.needsUpdate = true;
    this.trail.geometry.setDrawRange(0, n + 1);
    this.trail.material.color.copy(P.accent);

    // ruta pendiente
    const pts = [V3(p, 0.4), ...s.wps.slice(s.idx).map((w) => V3(w))];
    this.routeLine.geometry.dispose();
    this.routeLine.geometry = new THREE.BufferGeometry().setFromPoints(pts);
    this.routeLine.computeLineDistances();
    this.routeLine.material.color.copy(P.crit);

    // rayos: ObstacleField (9) + barrido / estrategica
    const rp = this.rays.geometry.attributes.position, rc = this.rays.geometry.attributes.color;
    let k = 0;
    const seg = (o, d, len, col) => {
      if (k >= 40) return;
      rp.setXYZ(2 * k, o.x, o.z + 0.4, o.y);
      rp.setXYZ(2 * k + 1, o.x + d[0] * len, o.z + 0.4 + d[2] * len, o.y + d[1] * len);
      rc.setXYZ(2 * k, col.r, col.g, col.b); rc.setXYZ(2 * k + 1, col.r, col.g, col.b);
      k++;
    };
    if (this.showRays && s.field) {
      for (const c of s.field.cells) {
        const d = dirOf(yaw, FLOW_AZ[c.c] * DEG, FLOW_EL[c.r] * DEG);
        const col = !s.field.evidence ? P.muted : c.ttc <= CFG.TTC_EVASION ? P.crit : (c.ttc <= CFG.TTC_SAFE || c.blocked) ? P.warn : P.safe;
        seg(p, d, Math.min(Number.isFinite(c.d) ? c.d : 30, 30), col);
      }
      const r = s.strat.resp;
      if (r && s.t - r.t < 4 && (this.view === 'strategic' || this.view === 'system' || this.view === 'mission')) {
        for (const sct of r.sectors) {
          const d = dirOf(r.anchor.yaw, STRAT_AZ[sct.c] * DEG, STRAT_EL[sct.r] * DEG);
          seg(r.anchor, d, sct.free ? 15 : Math.min(Number.isFinite(sct.d) ? sct.d : 15, 15), sct.free ? P.teal : P.muted);
        }
      }
      for (const f of s.scanViz) {
        if (s.t - (s.scan?.startT ?? s.t) > 30) break;
        const d = dirOf(f.pose.yaw, 0, 0);
        seg(f.pose, d, Math.min(Number.isFinite(f.d) ? f.d : 20, 20), f.free ? P.teal : P.crit);
      }
    }
    rp.needsUpdate = true; rc.needsUpdate = true;
    this.rays.geometry.setDrawRange(0, 2 * k);

    // waypoints y sub-metas
    this.syncMarkers();

    // pulsos y brillo de nodos
    for (let i = this.pulses.length - 1; i >= 0; i--) {
      const pu = this.pulses[i];
      pu.t += dtReal;
      if (pu.t < 0) continue;
      const u = pu.t / pu.dur;
      if (u >= 1) { pu.m.visible = false; this.scene.remove(pu.m); (this.pulsePool ||= []).push(pu.m); this.pulses.splice(i, 1); continue; }
      pu.m.visible = true;
      pu.m.position.copy(pu.curve.getPoint(u));
    }
    for (const [key, m] of Object.entries(this.nodeMesh || {})) {
      const gl = this.nodeGlow[key] = Math.max(0, (this.nodeGlow[key] || 0) - dtReal * 4);
      m.material.emissive.copy(key === 'strategic' || key === 'tracker' ? P.teal : P.accent);
      m.material.emissiveIntensity = gl * 0.7;
      this.nodeLabel[key].element.classList.toggle('hot', gl > 0.3 && key !== 'strategic');
    }

    if (this.tween) {
      const tw = this.tween;
      tw.t = Math.min(1, tw.t + dtReal / 0.8);
      const e = tw.t < 0.5 ? 2 * tw.t * tw.t : 1 - Math.pow(-2 * tw.t + 2, 2) / 2;
      this.camera.position.lerpVectors(tw.p0, tw.p1, e);
      this.controls.target.lerpVectors(tw.t0, tw.t1, e);
      this.camera.zoom = tw.z0 + (tw.z1 - tw.z0) * e;
      this.camera.updateProjectionMatrix();
      if (tw.t >= 1) this.tween = null;
    }
    this.controls.update();
    // nivel de detalle: las etiquetas del grafo solo cuando un bloque mide mas de ~60 px
    const ppm = (this.host.clientHeight / 120) * this.camera.zoom;
    const showGraph = ppm * 9 > 60;
    if (showGraph !== this.graphLabelsOn) {
      this.graphLabelsOn = showGraph;
      for (const o of this.graph.children) if (o.userData.lod) o.visible = showGraph;
    }
    this.renderer.render(this.scene, this.camera);
    this.labels.render(this.scene, this.camera);
  }

  syncMarkers() {
    const s = this.sim, P = this.pal;
    const sig = s.wps.slice(s.idx).map((w) => `${w.label}${fmt(w.x, 1)}${fmt(w.y, 1)}`).join('|') + s.idx;
    if (sig === this.markerSig) return;
    this.markerSig = sig;
    if (this.markers) this.clearGroup(this.markers); else { this.markers = new THREE.Group(); this.scene.add(this.markers); }
    s.wps.forEach((w, i) => {
      const passed = i < s.idx;
      if (w.kind === 'sub' && passed) return;
      const col = w.kind === 'sub' ? P.teal : passed ? P.muted : P.crit;
      const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, w.z, 6), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.5 }));
      pole.position.set(w.x, w.z / 2, w.y);
      const mk = w.kind === 'sub'
        ? new THREE.Mesh(new THREE.OctahedronGeometry(1.2), new THREE.MeshStandardMaterial({ color: col, emissive: col, emissiveIntensity: 0.4 }))
        : new THREE.Mesh(new THREE.TorusGeometry(CFG.ACCEPT, 0.18, 8, 40), new THREE.MeshBasicMaterial({ color: col }));
      if (w.kind !== 'sub') mk.rotation.x = Math.PI / 2;
      mk.position.set(w.x, w.z, w.y);
      mk.userData = { inspect: 'tracker' };
      this.markers.add(pole, mk);
      if (!passed) this.markers.add(this.label(w.kind === 'sub' ? `SUB · ${w.origin}` : w.label, w.kind === 'sub' ? 'sub' : 'wp', new THREE.Vector3(w.x, w.z + 3, w.y)));
    });
  }
}

// ---------------------------------------------------------------------------
// Inspector
// ---------------------------------------------------------------------------

const kv = (rows) => `<table class="kv">${rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('')}</table>`;

const INSPECT = {
  drone: (s) => ({
    kicker: 'vehículo', title: 'Dron (cuadricóptero)',
    body: `<p>Una sola cámara RGB frontal (HFOV 90°) y la telemetría del simulador. Ningún nodo lee el canal de profundidad de AirSim: la distancia al obstáculo más cercano solo la mide un hilo de auditoría aparte (DistMin).</p>`,
    live: kv([
      ['posición (N, E)', `${fmt(s.pos.x)} , ${fmt(s.pos.y)} m`],
      ['altitud', `${fmt(s.pos.z)} m`],
      ['rumbo', `${deg(s.yaw)}°`],
      ['velocidad horizontal', `${fmt(hyp(s.v.x, s.v.y), 2)} m/s`],
      ['distancia recorrida', `${fmt(s.dist, 0)} m`],
      ['DistMin (auditoría)', `${fmt(s.distMin, 1)} m`],
      ['contactos', s.contacts],
    ]),
    src: 'airsim-loop/main.py · experiments/runner.py',
  }),
  capture: (s) => ({
    kicker: 'nodo', title: 'capture',
    body: '<p>Guarda el fotograma y la telemetría anteriores, captura RGB + telemetría y marca <code>degraded = True</code> si no hay imagen. No captura profundidad.</p>',
    live: kv([['ciclo', s.cycle], ['degraded', s.dec.degraded ? 'True' : 'False'], ['fotogramas a perder', s.degradedLeft]]),
    src: 'src/agents/graph.py · capture_node',
  }),
  degraded_router: (s) => ({
    kicker: 'arista condicional', title: 'degraded_router',
    body: '<p>El único punto de decisión de la topología: con datos va a <code>perception</code>, sin datos a <code>degraded_hover</code>. Toda la política vive dentro de <code>navigate</code>.</p>',
    live: kv([['último camino', s.dec.degraded ? 'degraded_hover' : 'perception']]),
    src: 'src/agents/graph.py · degraded_router',
  }),
  degraded_hover: (s) => ({
    kicker: 'nodo', title: 'degraded_hover',
    body: '<p>Sin datos no se mueve: emite <code>FRENAR</code> y no consulta a la capa estratégica. El motor mantiene la altitud con su ancla.</p><p>Probá «Perder fotogramas» en la barra de controles.</p>',
    live: kv([['fotogramas a perder', s.degradedLeft]]),
    src: 'src/agents/graph.py · degraded_hover_node',
  }),
  perception: (s) => {
    const f = s.field;
    return {
      kicker: 'nodo', title: 'perception → ObstacleField',
      body: '<p>Flujo óptico denso (DIS) derotado con la actitud, foco de expansión y TTC por celda en una grilla 3×3. Es la única percepción del lazo rápido. Sin traslación no hay flujo: girar en el lugar o frenar deja al dron <em>sin evidencia</em>.</p><p class="muted">Acá el TTC sale de rayos sobre la geometría; el umbral es el del sistema (Youden, AUC 0.97 y 0.96).</p>',
      live: f ? kv([
        ['evidencia (traslación)', f.evidence ? `sí · ${fmt(f.vF, 2)} m/s` : 'no'],
        ['TTC centro (B2)', `${fmt(f.center.ttc)} s`],
        ['TTC mínimo', `${fmt(f.minTTC)} s`],
        ['centro bloqueado', f.center.blocked ? 'sí' : 'no'],
        ['FOV bloqueado', `${Math.round(f.fovBlocked * 100)} %`],
      ]) : '',
      src: 'src/perception/flow_ttc.py · FlowTTCEstimator',
    };
  },
  navigate: (s) => ({
    kicker: 'nodo · política', title: `navigate (brazo ${s.opts.arm})`,
    body: s.opts.arm === 'reactive'
      ? '<p>El brazo <code>reactive</code> solo guía hacia el objetivo (<code>MANTENER_RUMBO</code>), con la tasa de guiñada acotada cerca de un obstáculo. No evade ni detecta atascos: es la línea de base.</p>'
      : `<p>Antes de la cascada: <code>StallDetector.update()</code>${s.opts.arm === 'slm' ? ' y <code>StrategicLayer.tick()</code>' : ''}. Luego gana la primera regla que aplica:</p>
         <ul class="rules">${RULES.map(([n, c, a]) => `<li class="${s.dec.rule === n ? 'hit' : ''}${n === '6' ? ' na' : ''}"><b>${n}</b><span>${c} → ${a}</span></li>`).join('')}</ul>`,
    live: kv([['regla', s.dec.rule], ['comportamiento', s.dec.behaviour || '—'], ['macro-acción', s.dec.action]]),
    src: 'src/agents/graph.py · navigate_node',
  }),
  motor: (s) => {
    const c = s.dec.cmd || s.lastCmd;
    return {
      kicker: 'nodo', title: 'motor',
      body: '<p><code>action_to_command()</code> traduce la macro-acción a velocidades en body frame; exactamente un comando por ciclo. El gobernador limita <code>vx</code> tras un bloqueo y lo libera en rampa; en <code>FRENAR</code> corrige la deriva hacia la altitud de anclaje.</p>',
      live: kv([
        ['macro-acción', c.action],
        ['vx', `${fmt(c.vx, 2)} m/s`],
        ['vz (NED)', `${fmt(-c.vz, 2)} m/s`],
        ['yaw', c.targetYaw != null ? `→ ${deg(c.targetYaw)}° a ${c.rate}°/s` : `${fmt(c.yawRate / DEG, 1)} °/s`],
        ['gobernador', `${fmt(s.gov, 2)} m/s`],
      ]),
      src: 'src/agents/graph.py · motor_node · action_to_command',
    };
  },
  END: (s) => ({
    kicker: 'fin de ciclo', title: 'END',
    body: '<p>Termina el ciclo del grafo. El lazo externo inserta la sub-meta pendiente (<code>inject_corner</code>), registra la traza y duerme hasta completar los 200 ms.</p>',
    live: kv([['ciclos', s.cycle], ['tiempo', `${fmt(s.t)} s`]]),
    src: 'airsim-loop/main.py',
  }),
  strategic: (s) => {
    const st = s.strat, r = st.resp;
    const src = s.opts.source;
    return {
      kicker: 'lazo lento · hilo aparte', title: 'Capa estratégica',
      body: `<p>Juzga qué sectores de una grilla 3×3 del fotograma son volables y convierte la respuesta en una <b>sub-meta en coordenadas del mundo</b>, calculada con la pose del momento de la captura (el ancla). El dron nunca frena a esperarla.</p>
        <p>Fuente: <code>${src}</code>${src === 'depth' ? ' · Depth Anything V2, ~110 ms, cada 1 s, libre si p5 ≥ 15 m (AUC 0.83–0.87).' : src === 'vlm' ? ' · LFM2.5-VL-1.6B local, ~0.8 s, cada 3 s. En el banco de prueba no separó libres de bloqueados (AUC 0.53).' : ' · apagada.'}</p>
        <p>Se descarta si tiene más de 10 s, si cambió el waypoint o si la sub-meta ya quedó atrás.</p>`,
      live: kv([
        ['consultas', st.sent], ['sub-metas aplicadas', st.applied], ['descartadas', st.discarded],
        ['en vuelo', st.pending ? `#${st.pending.id} (${fmt(st.pending.latency * 1000, 0)} ms)` : '—'],
        ['última', r ? `#${r.id}: ${r.outcome}` : '—'],
      ]),
      src: 'src/agents/vlm_strategic.py · depth_client.py',
    };
  },
  tracker: (s) => ({
    kicker: 'lazo externo', title: 'WaypointTracker',
    body: '<p>Persigue el objetivo activo con el guiado normal y lo da por alcanzado a 3.5 m. Las sub-metas se insertan delante del waypoint real, reemplazando la pendiente; el waypoint real se acepta aunque haya una sub-meta activa.</p>',
    live: kv([
      ['objetivo activo', s.wps[s.idx] ? `${s.wps[s.idx].label}${s.wps[s.idx].origin ? ` (${s.wps[s.idx].origin})` : ''}` : '—'],
      ['distancia', s.wps[s.idx] ? `${fmt(hyp(s.wps[s.idx].x - s.pos.x, s.wps[s.idx].y - s.pos.y))} m` : '—'],
      ['pendientes', s.wps.slice(s.idx).map((w) => w.label).join(' → ') || '—'],
      ['sub-metas insertadas', s.subgoals],
    ]),
    src: 'src/navigation/waypoint_tracker.py',
  }),
  stall: (s) => ({
    kicker: 'navigate · detector', title: 'StallDetector',
    body: '<p><b>stopped_prolonged</b>: se ordenó avanzar ≥ 0.3 m/s y el dron no se movió durante 10 ciclos. <b>wp_no_progress</b>: 50 ciclos (10 s) sin acercarse 2 m al objetivo. Cualquiera de las dos dispara el barrido de deadlock (regla 2). <b>imu_contact</b> y <b>blind_wall</b> detectan el contacto que el flujo no ve (regla 4).</p>',
    live: kv([['deadlocks', s.deadlocks], ['barrido', s.scan ? `rumbo ${s.scan.i + 1}/4` : '—']]),
    src: 'src/agents/stall_detector.py · deep_scan.py',
  }),
};

// ---------------------------------------------------------------------------
// Recorrido guiado
// ---------------------------------------------------------------------------

function buildLessons(app) {
  return [
    {
      title: 'El problema',
      html: `<p>Un cuadricóptero tiene que recorrer waypoints entre edificios. En un cañón urbano el LiDAR es caro y la profundidad del simulador no existiría en un dron real: el sistema solo tiene <b>una cámara RGB</b> y la telemetría.</p>
        <p>Tiene que reaccionar en fracciones de segundo y, a la vez, decidir rodeos que requieren «mirar» la escena. Un modelo de lenguaje en la misma GPU tarda casi un segundo en contestar.</p>`,
      setup: () => app.apply({ scenario: 'libre', arm: 'slm', source: 'depth', deadlock: 'depth', view: 'system', inspect: 'drone', run: true }),
      tries: [['Ver el grafo de cerca', () => app.setView('graph')], ['Seguir al dron', () => app.setView('perception')]],
    },
    {
      title: 'Ver con flujo óptico',
      html: `<p>Entre dos fotogramas, los píxeles de un obstáculo que se acerca se expanden desde el foco de expansión. De esa divergencia sale el <b>tiempo a colisión</b> (TTC) de cada celda de una grilla 3×3: el <code>ObstacleField</code>.</p>
        <ul><li>TTC ≤ 3.2 s en el centro: peligro frontal.</li><li>TTC ≤ 4.6 s: ventana de advertencia.</li></ul>
        <p>Los umbrales salen del índice de Youden contra profundidad de referencia (AUC 0.97 y 0.96). Mirá los rayos del dron y la grilla de la izquierda mientras se acerca a la torre.</p>`,
      setup: () => app.apply({ scenario: 'torre', arm: 'slm', source: 'depth', deadlock: 'depth', view: 'perception', inspect: 'perception', run: true }),
      tries: [['Perder 3 fotogramas', () => app.dropFrames()], ['Sin evasión (reactive)', () => app.apply({ arm: 'reactive', reset: true, run: true, inspect: 'navigate' })]],
    },
    {
      title: 'Decidir a 5 Hz',
      html: `<p>Cada 200 ms corre un ciclo de un grafo LangGraph de cuatro nodos: <code>capture → perception → navigate → motor</code>, con un desvío a <code>degraded_hover</code> si no hay imagen.</p>
        <p><code>navigate</code> evalúa ocho reglas en orden fijo y gana la primera que aplica. El lazo rápido es el <b>único</b> que comanda velocidades: un comando por ciclo.</p>
        <p>Pausá y avanzá de a un ciclo para ver qué regla dispara.</p>`,
      setup: () => app.apply({ scenario: 'torre', view: 'graph', inspect: 'navigate', run: true }),
      tries: [['Pausar y avanzar un ciclo', () => { app.setRunning(false); app.stepOnce(); }], ['Inspeccionar motor', () => app.inspect('motor')]],
    },
    {
      title: 'Pensar despacio, sin frenar',
      html: `<p>En paralelo, la <b>capa estratégica</b> mira el fotograma con una grilla 3×3 y dice qué sectores son volables. Cada pedido guarda la <b>pose del fotograma</b>: la respuesta llega varios ciclos después y se traduce con esa pose a una sub-meta en el mundo, válida aunque el dron haya girado.</p>
        <p>La configuración final usa profundidad monocular estimada (Depth Anything V2, ~110 ms). El VLM a bordo no distinguió sectores volables de bloqueados (AUC 0.53 contra 0.83–0.87) y quedó para el plan de ruta sobre el mapa.</p>`,
      setup: () => app.apply({ scenario: 'torre', arm: 'slm', source: 'depth', view: 'strategic', inspect: 'strategic', run: true }),
      tries: [['Cambiar a VLM', () => app.apply({ source: 'vlm', reset: true, run: true })], ['Apagar la capa', () => app.apply({ source: 'off', reset: true, run: true })]],
    },
    {
      title: 'Destrabarse',
      html: `<p>El flujo óptico tiene un punto ciego: un obstáculo centrado en la trayectoria, o una malla fina, casi no genera divergencia. El dron lo descubre por contacto (<code>blind_wall</code>, <code>imu_contact</code>) y, si no progresa, el <code>StallDetector</code> declara <b>deadlock</b>.</p>
        <p>Entonces gira a 4 rumbos, la profundidad estimada juzga cada uno (p5 ≥ 15 m) y sale una sub-meta a 15 m por el rumbo transitable más cercano a la meta. Sin ninguno, sube.</p>
        <p>Con <code>blind</code> el dron solo sube 1.6 s por deadlock: no supera la malla de 28 m y el guiado lo vuelve a bajar a la altitud del waypoint.</p>`,
      setup: () => app.apply({ scenario: 'malla', arm: 'slm', source: 'depth', deadlock: 'depth', view: 'mission', inspect: 'stall', run: true }),
      tries: [['Escape a ciegas (blind)', () => app.apply({ deadlock: 'blind', reset: true, run: true })], ['Ver la percepción', () => app.setView('perception')]],
    },
    {
      title: 'Lo que mostró la evaluación',
      html: `<p>Corrida productiva v4: seis escenarios en MiniSim, TownSim y CitySim, 10 semillas por celda.</p>
        <div class="stat-row">
          <div class="stat"><b>210</b><span>corridas</span></div>
          <div class="stat"><b>0</b><span>colisiones</span></div>
          <div class="stat"><b>0 / 20</b><span>reactive con obstrucción</span></div>
          <div class="stat"><b>5–9 / 10</b><span>brazos con evasión y barrido</span></div>
        </div>
        <p>En ruta libre la capa deliberativa solo cuesta: <code>reactive &lt; slm &lt; fsm</code> en tiempo, con una razón slm/reactive de 1.95, 1.49 y 1.39 según la longitud. Con obstrucción, la evasión y el barrido con profundidad deciden. Detalle en los capítulos <a href="informe/11-RESULTADOS.html">11</a> y <a href="informe/12-CONCLUSIONES.html">12</a>.</p>`,
      setup: () => app.apply({ scenario: 'arboles', arm: 'slm', source: 'depth', deadlock: 'depth', view: 'system', inspect: 'drone', run: true, speed: 2 }),
      tries: [['Probar reactive', () => app.apply({ arm: 'reactive', reset: true, run: true })], ['Probar fsm', () => app.apply({ arm: 'fsm', reset: true, run: true })], ['Volver a slm', () => app.apply({ arm: 'slm', reset: true, run: true })]],
    },
  ];
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

class App {
  constructor() {
    this.sim = new Sim();
    this.running = false;
    this.speed = 1;
    this.acc = 0;
    this.selected = 'drone';
    this.lessonIdx = 0;
    this.lastTraceCycle = -1;

    const selSc = $('sel-scenario');
    for (const [k, sc] of Object.entries(SCENARIOS)) selSc.add(new Option(sc.name, k));
    this.sim.load('libre');
    this.scene = new Scene3D($('viewport'), this.sim, (k) => this.inspect(k));
    this.scene.onPlace = (x, y) => this.place(x, y);
    this.scene.buildWorld();
    this.scene.setView('system', true);

    this.bind();
    this.lessons = buildLessons(this);
    this.renderLessonNav();
    this.showLesson(0, false);
    this.renderAll();
    this.last = performance.now();
    requestAnimationFrame((t) => this.frame(t));
  }

  bind() {
    $('btn-run').onclick = () => this.setRunning(!this.running);
    $('btn-step').onclick = () => { this.setRunning(false); this.stepOnce(); };
    $('btn-reset').onclick = () => { this.sim.reset(); this.afterReset(); };
    $('sel-speed').onchange = (e) => { this.speed = +e.target.value; };
    $('sel-scenario').onchange = (e) => this.apply({ scenario: e.target.value });
    $('sel-arm').onchange = (e) => this.apply({ arm: e.target.value, reset: true });
    $('sel-source').onchange = (e) => this.apply({ source: e.target.value, reset: true });
    $('sel-deadlock').onchange = (e) => this.apply({ deadlock: e.target.value, reset: true });
    $('btn-drop').onclick = () => this.dropFrames();
    $('btn-place').onclick = () => this.setPlacing(!this.scene.placing);
    $('chk-rays').onchange = (e) => { this.scene.showRays = e.target.checked; };
    $('chk-follow').onchange = (e) => { this.scene.follow = e.target.checked; };
    $('btn-tour').onclick = () => { this.showLesson(0, true); $('lesson').scrollIntoView({ behavior: 'smooth', block: 'center' }); };
    $('lesson-prev').onclick = () => this.showLesson(Math.max(0, this.lessonIdx - 1), true);
    $('lesson-next').onclick = () => this.showLesson(Math.min(this.lessons.length - 1, this.lessonIdx + 1), true);
    document.querySelectorAll('.view-tabs [data-view]').forEach((b) => { b.onclick = () => this.setView(b.dataset.view); });
    addEventListener('keydown', (e) => {
      if (e.key === 'Escape') this.setPlacing(false);
      if (e.target.closest('select, input')) return;
      if (e.key === ' ') { e.preventDefault(); this.setRunning(!this.running); }
      if (e.key === 'ArrowRight') { this.setRunning(false); this.stepOnce(); }
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { this.scene.markerSig = ''; this.scene.buildWorld(); });
  }

  apply(o) {
    const s = this.sim;
    if (o.arm) { s.opts.arm = o.arm; $('sel-arm').value = o.arm; }
    if (o.source) { s.opts.source = o.source; $('sel-source').value = o.source; }
    if (o.deadlock) { s.opts.deadlock = o.deadlock; $('sel-deadlock').value = o.deadlock; }
    $('sel-source').disabled = s.opts.arm !== 'slm';
    $('sel-deadlock').disabled = s.opts.arm === 'reactive';
    if (o.scenario && (o.scenario !== s.key || o.reset !== false)) {
      s.load(o.scenario);
      $('sel-scenario').value = o.scenario;
      this.scene.markerSig = '';
      this.scene.buildWorld();
      this.afterReset();
      this.setView(o.view || this.scene.view, true);
    } else if (o.reset) { s.reset(); this.afterReset(); }
    if (o.view && !o.scenario) this.setView(o.view);
    if (o.inspect) this.inspect(o.inspect);
    if (o.speed) { this.speed = o.speed; $('sel-speed').value = String(o.speed); }
    if (o.run !== undefined) this.setRunning(o.run);
    this.renderAll();
  }

  afterReset() {
    this.acc = 0;
    this.lastTraceCycle = -1;
    this.scene.markerSig = '';
    $('trace-body').innerHTML = '';
    this.renderAll();
  }

  setView(v, instant) {
    this.scene.setView(v, instant);
    document.querySelectorAll('.view-tabs [data-view]').forEach((b) => b.classList.toggle('active', b.dataset.view === v));
  }

  setRunning(r) {
    if (r && this.sim.status !== 'flying') { this.sim.reset(); this.afterReset(); }
    this.running = r;
    $('btn-run').querySelector('.ico').textContent = r ? '❚❚' : '▶';
    $('btn-run').querySelector('.lbl').textContent = r ? 'Pausar' : 'Volar';
  }

  setPlacing(p) {
    this.scene.placing = p;
    $('btn-place').setAttribute('aria-pressed', String(p));
    $('place-hint').hidden = !p;
  }

  place(x, y) {
    const s = this.sim, kind = $('sel-place').value;
    if (hyp(x - s.pos.x, y - s.pos.y) < 6) return;
    if (kind === 'building') s.extra.push(B(x - 6, x + 6, y - 6, y + 6, 30));
    else if (kind === 'tree') s.extra.push(T(x, y, 15, 2.4));
    else {
      // malla perpendicular al rumbo dominante (eje norte en estas escenas)
      s.extra.push(M(x, y - 10, y + 10, 26));
    }
    this.scene.buildWorld();
    this.renderAll();
  }

  dropFrames() { this.sim.degradedLeft = 3; this.inspect('degraded_hover'); if (!this.running) this.setRunning(true); }

  inspect(k) { this.selected = k; this.renderInspector(); }

  stepOnce() {
    const d = this.sim.step();
    if (d) this.onCycle(d, 0.18);
    this.renderAll();
  }

  onCycle(d, dur) {
    if (d.path?.length) this.scene.firePath(d.path, dur);
    if (this.sim.lastPulse) { this.scene.fireAsync(this.sim.lastPulse, dur * 2); this.sim.lastPulse = null; }
  }

  frame(now) {
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    if (this.running) {
      this.acc += dt * this.speed;
      let n = 0, stepped = false;
      while (this.acc >= CFG.DT && n < 8) {
        this.acc -= CFG.DT; n++;
        const d = this.sim.step();
        if (!d) { this.setRunning(false); break; }
        this.onCycle(d, CFG.DT / this.speed * 0.9);
        stepped = true;
      }
      if (stepped) this.renderAll();
    }
    this.scene.update(this.running ? this.acc / CFG.DT : 1, dt);
    requestAnimationFrame((t) => this.frame(t));
  }

  // ---- render de paneles
  renderAll() {
    this.renderStatus();
    this.renderField();
    this.renderStall();
    this.renderStrat();
    this.renderInspector();
    this.renderTrace();
  }

  renderStatus() {
    const s = this.sim;
    const st = s.status === 'flying' ? (this.running ? ['en vuelo', 'act'] : ['en pausa', '']) : s.status === 'done' ? [s.statusMsg, 'ok'] : [s.statusMsg, 'bad'];
    const chips = [
      [st[0], st[1]],
      [`t ${fmt(s.t, 1)} s · ciclo ${s.cycle}`, ''],
      [`${s.dec.action}`, s.dec.action === 'FRENAR' ? 'bad' : 'act'],
      [`regla ${s.dec.rule}`, ''],
      [`alt ${fmt(s.pos.z, 1)} m`, ''],
      [`DistMin ${fmt(s.distMin, 1)} m`, ''],
      [`sub-metas ${s.subgoals}`, 'teal'],
      [`deadlocks ${s.deadlocks}`, s.deadlocks ? 'bad' : ''],
    ];
    $('status-strip').innerHTML = chips.map(([t, c]) => `<span class="chip ${c}">${t}</span>`).join('');
  }

  renderField() {
    const f = this.sim.field;
    if (!f) return;
    $('hud-field').innerHTML = f.cells.map((c) => {
      const cls = !f.evidence ? '' : c.ttc <= CFG.TTC_EVASION ? 'crit' : (c.ttc <= CFG.TTC_SAFE || c.blocked) ? 'warn' : 'safe';
      return `<div class="cell ${cls}">${f.evidence ? `${fmt(c.ttc)} s` : '—'}<small>${COLS[c.c]}${c.r + 1} · occ ${Math.round(c.occ * 100)}%</small></div>`;
    }).join('');
  }

  renderStall() {
    const s = this.sim.stall;
    const meter = (name, v, max) => `<div><div class="meter-top"><span><code>${name}</code></span><span>${v} / ${max}</span></div>
      <div class="bar"><i class="${v >= max * 0.7 ? 'hot' : ''}" style="width:${Math.min(100, (v / max) * 100)}%"></i></div></div>`;
    $('hud-stall').innerHTML = this.sim.opts.arm === 'reactive'
      ? '<p class="small-note">El brazo reactive no detecta atascos.</p>'
      : meter('stopped_prolonged', s.stopped, CFG.STOP_CYCLES) + meter('wp_no_progress', s.noprog, CFG.NOPROG_CYCLES) +
        `<div class="flags"><span class="flag ${s.imuContact ? 'on' : ''}">imu_contact</span><span class="flag ${s.blindWall ? 'on' : ''}">blind_wall</span><span class="flag ${this.sim.scan ? 'on' : ''}">barrido ${this.sim.scan ? `${this.sim.scan.i + 1}/4` : ''}</span></div>`;
  }

  renderStrat() {
    const s = this.sim, r = s.strat.resp;
    $('strat-hint').textContent = s.opts.arm !== 'slm' ? `sin capa (brazo ${s.opts.arm})` : `fuente: ${s.opts.source}`;
    if (!r) {
      $('hud-strat').innerHTML = [...Array(9)].map((_, k) => `<div class="cell"><small>${COLS[k % 3]}${Math.floor(k / 3) + 1}</small></div>`).join('');
      $('strat-note').textContent = s.opts.arm === 'slm' && s.opts.source !== 'off' ? (s.strat.pending ? `Consulta #${s.strat.pending.id} en vuelo…` : 'Todavía no hubo consultas (requiere ≥ 8 m de altura y la meta en el recorte).') : 'La capa estratégica no corre en esta configuración.';
      return;
    }
    $('hud-strat').innerHTML = r.sectors.map((c, k) => `<div class="cell ${c.free ? 'free' : 'blocked'} ${k === r.goal ? 'goal' : ''} ${k === r.chosen ? 'chosen' : ''}">${c.free ? 'libre' : 'bloq.'}<small>${COLS[k % 3]}${Math.floor(k / 3) + 1}${Number.isFinite(c.d) ? ` · ${fmt(c.d, 0)} m` : ''}</small></div>`).join('');
    $('strat-note').innerHTML = `#${r.id} · ${fmt(r.latency * 1000, 0)} ms · ${r.outcome}. <span class="muted">Borde punteado: sector de la meta; borde lleno: elegido.</span>`;
  }

  renderInspector() {
    const fn = INSPECT[this.selected] || INSPECT.drone;
    const d = fn(this.sim);
    const picks = ['drone', 'capture', 'perception', 'navigate', 'motor', 'strategic', 'tracker', 'stall'];
    $('inspector').innerHTML = `<div class="kicker">${d.kicker}</div><h2>${d.title}</h2>${d.body}
      <h3>Valores actuales</h3>${d.live || ''}<div class="src">${d.src}</div>
      <div class="pick-list">${picks.map((p) => `<button data-pick="${p}" class="${p === this.selected ? 'on' : ''}">${p === 'drone' ? 'dron' : p === 'strategic' ? 'estratégica' : p === 'stall' ? 'atasco' : p}</button>`).join('')}</div>`;
    $('inspector').querySelectorAll('[data-pick]').forEach((b) => { b.onclick = () => this.inspect(b.dataset.pick); });
  }

  renderTrace() {
    const s = this.sim, body = $('trace-body');
    const rows = s.trace.filter((r) => r.cycle > this.lastTraceCycle);
    if (!rows.length) return;
    this.lastTraceCycle = rows[rows.length - 1].cycle;
    body.querySelectorAll('tr.new').forEach((tr) => tr.classList.remove('new'));
    const html = rows.reverse().map((r) => `<tr class="new"><td>${r.cycle}</td><td>${fmt(r.t, 1)}</td><td>${r.path.filter((n) => n !== 'degraded_router' && n !== 'END').join(' → ')}</td>
      <td>${r.rule}</td><td><span class="act-tag ${r.action}">${r.action}</span></td><td>${Number.isNaN(r.ttc) ? '—' : fmt(r.ttc)}</td><td class="ev">${r.ev}</td></tr>`).join('');
    body.insertAdjacentHTML('afterbegin', html);
    while (body.children.length > 200) body.lastElementChild.remove();
  }

  // ---- recorrido
  renderLessonNav() {
    $('lesson-steps').innerHTML = this.lessons.map((l, i) => `<button role="tab" title="${l.title}" data-i="${i}"></button>`).join('');
    $('lesson-steps').querySelectorAll('button').forEach((b) => { b.onclick = () => this.showLesson(+b.dataset.i, true); });
  }

  showLesson(i, run) {
    this.lessonIdx = i;
    const l = this.lessons[i];
    $('lesson-count').textContent = `${i + 1} / ${this.lessons.length}`;
    $('lesson-steps').querySelectorAll('button').forEach((b, k) => { b.className = k === i ? 'active' : k < i ? 'done' : ''; });
    $('lesson-body').innerHTML = `<h3>${l.title}</h3>${l.html}<div class="try"><strong>Probá</strong>${l.tries.map(([t], k) => `<button data-k="${k}">${t}</button>`).join('')}</div>`;
    $('lesson-body').querySelectorAll('.try button').forEach((b) => { b.onclick = () => l.tries[+b.dataset.k][1](); });
    $('lesson-prev').disabled = i === 0;
    $('lesson-next').disabled = i === this.lessons.length - 1;
    if (run) l.setup();
  }
}

try {
  window.app = new App();
} catch (err) {
  console.error(err);
  $('viewport').innerHTML = `<p style="padding:20px">No se pudo iniciar la escena 3D (${err.message}). El explorador necesita WebGL.</p>`;
}
