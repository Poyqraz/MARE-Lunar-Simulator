/* Run the real adapter with a minimal fetch/event harness, without a browser. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const requests = [], timers = [], overlays = [], missions = [];
let mission = null, state = 'idle';
const response = (data, stamp = null) => ({
  ok: true,
  json: async () => data,
  arrayBuffer: async () => new Uint8Array([1]).buffer,
  headers: {get: name => name === 'X-Capture-Stamp-Ns' ? stamp : null},
});
async function fetch(url) {
  requests.push(url);
  if (url === '/mission/snapshot') return response({session_id: 's', state, mission, pose_fresh: true,
    capture_clock_advancing: true, live_pose: {position_m: [5, 5, 0], heading_rad: 0}});
  if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true,
    feeds: {cam_central: {stamp_ns: '100', age_s: 0}}});
  if (url === '/dashboard/camera/cam_central.jpg') return response(null, '100');
  if (url === '/dashboard/viewport') return response({linked: false});
  if (url === '/dashboard/map') return response({data: []});
  if (url === '/mission/events') return response({events: []});
  if (url.startsWith('/mission/trail?')) return response({points: []});
  if (url.startsWith('/dashboard/path-overlay?')) return response({stamp_ns: '100'});
  throw Error('Unexpected request: ' + url);
}
const sandbox = {window: {}, fetch, console, setTimeout: f => timers.push(f)};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../mars_rover/dashboard_assets/mars-adapter.js'), 'utf8'),
                   sandbox);
const socket = sandbox.window.io();
socket.on('path_overlay', value => overlays.push(value));
socket.on('mission', value => missions.push(value));

(async () => {
  await timers.shift()();
  assert.equal(requests.filter(x => x.startsWith('/dashboard/path-overlay?')).length, 0);
  assert.equal(overlays.at(-1), null);
  mission = {mission_id: 'm', closed: false, active_plan: [[5, 5], [6, 5]], initial_plan: [], plan_revision: 1};
  state = 'following';
  await timers.shift()();
  assert.equal(requests.filter(x => x.startsWith('/dashboard/path-overlay?')).length, 1);
  assert.equal(overlays.at(-1).stamp_ns, '100');
  mission.closed = true;
  state = 'arrived';
  await timers.shift()();
  assert.equal(requests.filter(x => x.startsWith('/dashboard/path-overlay?')).length, 1);
  assert.equal(overlays.at(-1), null);
  state = 'blocked';
  mission.error = 'No connected traversable route to the requested goal';
  await timers.shift()();
  assert.equal(missions.at(-1).state, 'aborted');
  assert.equal(missions.at(-1).reason, mission.error);
})().catch(e => { console.error(e); process.exitCode = 1; });
