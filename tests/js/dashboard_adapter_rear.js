/* Exercise the actual adapter with a small fetch/event harness. */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const requests = [], timers = [], received = [], lost = [];
let hasRear = true;
const response = (data, stamp = null) => ({
  ok: true,
  json: async () => data,
  arrayBuffer: async () => new Uint8Array([1]).buffer,
  headers: {get: name => name === 'X-Capture-Stamp-Ns' ? stamp : null},
});
async function fetch(url) {
  requests.push(url);
  if (url === '/mission/snapshot') return response({session_id: 's', state: 'idle', mission: null,
    pose_fresh: true, capture_clock_advancing: true, live_pose: {position_m: [5, 5, 0], heading_rad: 0}});
  if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true,
    feeds: hasRear ? {cam_rear: {stamp_ns: '100', age_s: 0}} : {}});
  if (url === '/dashboard/camera/cam_rear.jpg') return response(null, '100');
  if (url === '/dashboard/viewport') return response({linked: false});
  if (url === '/dashboard/map') return response({data: []});
  if (url === '/mission/events') return response({events: []});
  throw Error('Unexpected request: ' + url);
}
const sandbox = {window: {}, fetch, console, setTimeout: f => timers.push(f)};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../../mars_rover/dashboard_assets/mars-adapter.js'), 'utf8'),
                   sandbox);
const socket = sandbox.window.io();
socket.on('feed', value => received.push(value.id));
socket.on('feed_lost', value => lost.push(value));

(async () => {
  await timers.shift()();
  assert.deepEqual(received, ['cam_rear']);
  assert.equal(requests.filter(x => x === '/dashboard/camera/cam_rear.jpg').length, 1);
  hasRear = false;
  await timers.shift()();
  assert.deepEqual(lost, ['cam_rear']);
})().catch(e => { console.error(e); process.exitCode = 1; });
