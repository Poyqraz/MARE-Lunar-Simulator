'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.resolve(__dirname, '../..');
const timers = [], events = [], requests = [];
let enabled = true, available = true;
const response = data => ({ok: true, json: async () => data});
async function fetch(url) {
  requests.push(url);
  if (url === '/mission/snapshot') return response({session_id: 's', state: 'idle', mission: null,
    pose_fresh: true, capture_clock_advancing: true, live_pose: {position_m: [1, 1, 0], heading_rad: 0},
    fusion_shadow_enabled: enabled});
  if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true,
    feeds: {}});
  if (url === '/dashboard/fusion-shadow') {
    if (!available) throw Error('connection failure');
    return response({status: 'sampled_comparison', shared_bins: 42, lidar_hazard_depth_ground_like_bins: 3});
  }
  if (url === '/dashboard/viewport') return response({linked: false});
  if (url === '/dashboard/map') return response({data: []});
  if (url === '/mission/events') return response({events: []});
  throw Error('Unexpected request: ' + url);
}
const sandbox = {window: {}, fetch, console, setTimeout: f => timers.push(f)};
vm.runInNewContext(fs.readFileSync(path.join(root, 'mars_rover/dashboard_assets/mars-adapter.js'), 'utf8'), sandbox);
sandbox.window.io().on('fusion_shadow', value => events.push(value));

const html = fs.readFileSync(path.join(root, 'mars_rover/dashboard_assets/index.html'), 'utf8');
const start = html.indexOf("socket.on('fusion_shadow'");
const end = html.indexOf("socket.on('command_error'", start);
assert(start >= 0 && end > start);
const handlers = {}, label = {textContent: ''};
vm.runInNewContext(html.slice(start, end), {socket: {on: (name, cb) => { handlers[name] = cb; }}, $: () => label});

(async () => {
  await timers.shift()();
  assert.equal(events[0].status, 'sampled_comparison');
  handlers.fusion_shadow(events[0]);
  assert.equal(label.textContent, 'LiDAR hazard / depth ground: 3 of 42 bins');
  handlers.fusion_shadow({status: 'sampled_comparison', shared_bins: 0});
  assert.equal(label.textContent, 'NO SHARED SAMPLES');
  available = false;
  await timers.shift()();
  assert.equal(events[1].status, 'unavailable');
  handlers.fusion_shadow(events[1]);
  assert.equal(label.textContent, 'UNAVAILABLE');
  enabled = false;
  await timers.shift()();
  assert.equal(events[2].status, 'disabled');
  assert.equal(requests.filter(x => x === '/dashboard/fusion-shadow').length, 2);
})().catch(e => { console.error(e); process.exitCode = 1; });
