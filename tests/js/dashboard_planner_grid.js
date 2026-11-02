'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = path.resolve(__dirname, '../..');
const requests = [], timers = [], grids = [], lost = [];
let revision = 0, session = 's1', badGrid = false;
const bytes = [2, 0, 0, 0, 6, 0, 0, 0, 3];
const response = data => ({ok: true, json: async () => data});
async function fetch(url) {
  requests.push(url);
  if (url === '/mission/snapshot') return response({session_id: session, map_revision: revision,
    state: 'idle', mission: null, pose_fresh: true, capture_clock_advancing: true,
    live_pose: {position_m: [1, 1, 0], heading_rad: 0}});
  if (url === '/dashboard/occupancy') return response({session_id: badGrid ? 'wrong' : session,
    revision, width: 3, height: 3, resolution: 1, classes_b64: Buffer.from(bytes).toString('base64')});
  if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true,
    feeds: {}});
  if (url === '/dashboard/viewport') return response({linked: false});
  if (url === '/dashboard/map') return response({data: [], width: 3, height: 3, resolution: 1});
  if (url === '/mission/events') return response({events: []});
  throw Error('Unexpected request: ' + url);
}
const sandbox = {window: {}, fetch, console, setTimeout: f => timers.push(f),
  atob: value => Buffer.from(value, 'base64').toString('binary')};
vm.runInNewContext(fs.readFileSync(path.join(root, 'mars_rover/dashboard_assets/mars-adapter.js'), 'utf8'), sandbox);
const socket = sandbox.window.io();
socket.on('planner_occupancy', value => grids.push(value));
socket.on('planner_occupancy_lost', () => lost.push(true));

// Exercise the renderer's actual event handlers with an in-memory canvas.
const html = fs.readFileSync(path.join(root, 'mars_rover/dashboard_assets/index.html'), 'utf8');
const start = html.indexOf("socket.on('planner_occupancy_lost'");
const end = html.indexOf('/* The canvases match', start);
assert(start >= 0 && end > start);
let image;
const handlers = {}, label = {textContent: ''}, canvas = {width: 0, height: 0};
const renderer = {socket: {on: (name, cb) => { handlers[name] = cb; }}, mapW: 3, mapH: 3, mapRes: 1,
  gridCanvas: canvas, gridVisible: false, drawOverlay: () => {}, $: () => label,
  gridCtx: {createImageData: (w, h) => ({data: new Uint8ClampedArray(w * h * 4)}),
            putImageData: value => { image = value; }}};
vm.runInNewContext(html.slice(start, end), renderer);

(async () => {
  await timers.shift()();
  assert.equal(grids.length, 1);
  assert.deepEqual(Array.from(grids[0].data), bytes);
  handlers.planner_occupancy(grids[0]);
  // South row zero is drawn at the bottom; north row two at the top.
  assert.deepEqual(Array.from(image.data.slice((2 * 3) * 4, (2 * 3) * 4 + 4)), [255, 209, 102, 220]);
  assert.deepEqual(Array.from(image.data.slice(2 * 4, 2 * 4 + 4)), [252, 129, 199, 220]);
  assert.equal(label.textContent, 'PLANNER GRID · REV 0');
  await timers.shift()();
  assert.equal(requests.filter(u => u === '/dashboard/occupancy').length, 1);
  revision = 1; badGrid = true;
  await timers.shift()();
  assert.equal(grids.length, 1);
  assert(lost.length >= 1);
  handlers.planner_occupancy_lost();
  assert.equal(label.textContent, 'PLANNER GRID UNAVAILABLE');
  badGrid = false;
  await timers.shift()();
  assert.equal(grids.length, 2);
  assert.equal(grids[1].revision, 1);
  session = 's2'; revision = 0;
  await timers.shift()();
  assert.equal(grids[2].session_id, 's2');
})().catch(e => { console.error(e); process.exitCode = 1; });
