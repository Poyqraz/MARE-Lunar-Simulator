/* Hung requests, API reachability vs rover link, and uncertain command results in the real adapter.
 * Usage: node dashboard_adapter_link.js hung_status|rover_disconnected|goal_timeout */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const source = fs.readFileSync(path.resolve(__dirname, '../../mars_rover/dashboard_assets/mars-adapter.js'), 'utf8');
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data,
                                           arrayBuffer: async () => new Uint8Array([1]).buffer,
                                           headers: {get: () => null}});
const tick = () => new Promise(resolve => setImmediate(resolve));

function start(route) {
  const t = {requests: [], timers: [], signals: [], events: []};
  // Requests that never answer reject only when their timeout signal fires, like a real fetch.
  t.hang = opts => new Promise((_, reject) => {
    if (!opts || !opts.signal) return; // Without a client timeout this request hangs forever.
    opts.signal.addEventListener('abort', () => reject(opts.signal.reason));
  });
  t.expire = () => {
    for (const c of t.signals.splice(0)) c.abort(new DOMException('The operation timed out.', 'TimeoutError'));
  };
  const fetch = async (url, opts) => { t.requests.push(url); return route(url, opts, t); };
  const sandbox = {window: {}, fetch, console, setTimeout: f => t.timers.push(f),
    AbortSignal: {timeout: () => { const c = new AbortController(); t.signals.push(c); return c.signal; }}};
  vm.runInNewContext(source, sandbox);
  t.socket = sandbox.window.io();
  for (const name of ['connect', 'disconnect', 'feed_lost', 'rover', 'log', 'command_error'])
    t.socket.on(name, value => t.events.push([name, value]));
  t.named = name => t.events.filter(e => e[0] === name).map(e => e[1]);
  return t;
}
const snapshot = state => response({session_id: 's', state, mission: null, pose_fresh: state !== 'disconnected',
  capture_clock_advancing: state !== 'disconnected', live_pose: {position_m: [5, 5, 0], heading_rad: 0}});
function common(url) {
  if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true,
    feeds: {cam_rear: {stamp_ns: '100', age_s: 0}}});
  if (url === '/dashboard/camera/cam_rear.jpg') return {...response(null), headers: {get: () => '100'}};
  if (url === '/dashboard/viewport') return response({linked: false});
  if (url === '/dashboard/map') return response({data: []});
  if (url === '/mission/events') return response({events: []});
  throw Error('Unexpected request: ' + url);
}

const scenarios = {
  async hung_status() {
    let hung = false;
    const t = start((url, opts, t) => {
      if (url === '/mission/snapshot') return hung ? t.hang(opts) : snapshot('idle');
      if (url === '/stop') return response({ok: true});
      return common(url);
    });
    await t.timers.shift()();
    assert.deepEqual(t.named('connect').length, 1);
    assert.deepEqual(t.named('disconnect').length, 0);

    hung = true;
    const polling = t.timers.shift()();
    await tick();
    assert.equal(t.timers.length, 0, 'the poll is waiting on the hung status request');
    t.socket.emit('stop_rover', {});
    await tick();
    assert.equal(t.requests.at(-1), '/stop', 'a STOP is sent while the status request hangs');
    assert.ok(t.named('log').some(m => m.text === 'Stop accepted.'));

    t.expire();
    await polling;
    assert.equal(t.named('disconnect').length, 1);
    assert.equal(t.socket.connected, false);
    assert.deepEqual(t.named('feed_lost'), ['cam_rear']);
    assert.equal(t.named('rover').at(-1).unknown, true);
    assert.ok(t.named('log').some(m => m.level === 'ERROR' && /Dashboard API unreachable/.test(m.text)));
    assert.equal(t.timers.length, 1, 'polling continues after the timeout');

    hung = false;
    await t.timers.shift()();
    assert.equal(t.named('connect').length, 2);
    assert.ok(t.named('log').some(m => m.text === 'Dashboard API reachable again.'));
  },
  async rover_disconnected() {
    let state = 'disconnected';
    const t = start(url => url === '/mission/snapshot' ? snapshot(state) : common(url));
    await t.timers.shift()();
    assert.equal(t.socket.connected, false, 'a reachable API alone is not a rover link');
    assert.equal(t.named('connect').length, 0);
    assert.equal(t.named('rover').at(-1).unreal_linked, false);
    assert.ok(!t.named('log').some(m => /unreachable/.test(m.text)));
    state = 'idle';
    await t.timers.shift()();
    assert.equal(t.named('connect').length, 1);
    state = 'disconnected';
    await t.timers.shift()();
    assert.equal(t.named('disconnect').length, 1);
    assert.equal(t.timers.length, 1);
  },
  async goal_timeout() {
    let goalReply = null;
    const t = start((url, opts, t) => {
      if (url === '/mission/snapshot') return snapshot('idle');
      if (url === '/goal') return goalReply || t.hang(opts);
      return common(url);
    });
    await t.timers.shift()();
    t.signals.length = 0;
    t.socket.emit('send_goal', {x: 1, y: 2});
    await tick();
    t.expire();
    await tick(); await tick();
    assert.deepEqual(t.named('command_error'), [], 'a timed-out goal is not reported as rejected');
    assert.ok(t.named('log').some(m => m.level === 'WARN' && /Goal command result unknown/.test(m.text)));
    assert.equal(t.requests.filter(u => u === '/goal').length, 1, 'goals are not retried');

    goalReply = response({error: 'Goal is outside the map'}, 400); // A real reply is still a definite rejection.
    t.socket.emit('send_goal', {x: 1, y: 2});
    await tick(); await tick();
    assert.deepEqual(t.named('command_error'), ['Goal is outside the map']);
  },
};

let finished = false;
process.on('exit', () => { if (!finished) { console.error('Scenario never finished (a request hung).'); process.exitCode = 1; } });
scenarios[process.argv[2]]().then(() => { finished = true; })
  .catch(e => { finished = true; console.error(e); process.exitCode = 1; });
