/* Dashboard audit fixes in the real adapter: trail errors, empty trails, attitude, rover chip.
 * Usage: node dashboard_adapter_audit.js trail_error|empty_trail|attitude|stale_telemetry */
'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const source = fs.readFileSync(path.resolve(__dirname, '../../mars_rover/dashboard_assets/mars-adapter.js'), 'utf8');
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data,
                                           arrayBuffer: async () => new Uint8Array([1]).buffer,
                                           headers: {get: () => null}});

function start(snapshot, trail) {
  const t = {timers: [], events: []};
  const fetch = async url => {
    if (url === '/mission/snapshot') return response(snapshot);
    if (url.startsWith('/mission/trail')) return trail;
    if (url === '/dashboard/feeds') return response({center_id_source: 'measured', image_encoder_available: true, feeds: {}});
    if (url === '/dashboard/viewport') return response({linked: false});
    if (url === '/dashboard/map') return response({data: []});
    if (url === '/dashboard/occupancy') return response({}, 404);
    if (url === '/mission/events') return response({events: []});
    throw Error('Unexpected request: ' + url);
  };
  const sandbox = {window: {}, fetch, console, setTimeout: f => t.timers.push(f),
    AbortSignal: {timeout: () => new AbortController().signal}};
  vm.runInNewContext(source, sandbox);
  t.socket = sandbox.window.io();
  for (const name of ['connect', 'disconnect', 'rover', 'log', 'odom_update', 'trajectory_update', 'mission'])
    t.socket.on(name, value => t.events.push([name, value]));
  t.named = name => t.events.filter(e => e[0] === name).map(e => e[1]);
  return t;
}
const base = (extra = {}) => ({session_id: 's', state: 'following', pose_fresh: true, capture_clock_advancing: true,
  map_revision: 0, live_pose: {position_m: [5, 6, 1], heading_rad: 0},
  mission: {mission_id: 'm', goal: [9, 9], active_plan: [[5, 6], [9, 9]], initial_plan: [[5, 6], [9, 9]],
            plan_revision: 1, closed: false}, ...extra});

const scenarios = {
  async trail_error() {
    // A trail 404 (mission no longer retained) must not be reported as an unreachable API.
    const t = start(base(), response({error: 'Mission is not retained in bounded history'}, 404));
    await t.timers.shift()();
    assert.equal(t.named('disconnect').length, 0);
    assert.ok(!t.named('log').some(l => /unreachable/.test(l.text)), 'trail error treated as unreachable API');
    assert.equal(t.named('mission').at(-1).state, 'driving');
  },
  async empty_trail() {
    // An empty trail on a mission's first poll must not look like the session reset (empty path).
    const t = start(base(), response({points: []}));
    await t.timers.shift()();
    assert.equal(t.named('trajectory_update').length, 0);
  },
  async attitude() {
    const t = start(base({attitude_deg: {roll: -1.5, pitch: 2.25, tilt: 2.7}, tilt_limit_deg: 15}),
                    response({points: [{position_m: [5, 6, 1], break_before: true}]}));
    await t.timers.shift()();
    const odom = t.named('odom_update').at(-1);
    assert.deepEqual([odom.roll, odom.pitch, odom.tilt, odom.tilt_limit], [-1.5, 2.25, 2.7, 15]);
    assert.equal(t.named('trajectory_update').at(-1).path.length, 1);
  },
  async stale_telemetry() {
    // Bridge connected but telemetry not fresh (paused): linked, not playing; never "not linked".
    const t = start(base({state: 'idle', pose_fresh: false, capture_clock_advancing: false, mission: null}),
                    response({points: []}));
    await t.timers.shift()();
    const rover = t.named('rover').at(-1);
    assert.equal(rover.unreal_linked, true);
    assert.equal(rover.unreal, null);
    assert.equal(t.named('odom_update').length, 0);
  },
};

const scenario = scenarios[process.argv[2]];
if (!scenario) throw Error('Unknown scenario ' + process.argv[2]);
scenario().catch(e => { console.error(e); process.exit(1); });
