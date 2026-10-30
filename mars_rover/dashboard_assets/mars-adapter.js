/* Connect the original overview's event interface to the local Python API.
 * No ROS, Socket.IO server, second sensor connection, or fabricated feeds. */
(function () {
  'use strict';
  window.io = function () {
    const listeners = new Map(), seen = new Map();
    const socket = {connected: false, on, emit};
    const names = ['cam_central', 'cam_left', 'cam_right', 'depth_gt'];
    let snapshot = null, mapLoaded = false, previousSession = null, lastLidar = null;
    let busy = false, lastEvents = 0, centreWarned = false, encoderWarned = false;

    function on(name, fn) {
      if (!listeners.has(name)) listeners.set(name, []);
      listeners.get(name).push(fn);
      return socket;
    }
    function dispatch(name, value) {
      for (const fn of listeners.get(name) || []) {
        try { fn(value); } catch (e) { console.error('Dashboard event', name, e); }
      }
    }
    function log(level, text) {
      dispatch('log', {level, text, node: 'mars_python', stamp: Date.now() / 1000});
    }
    async function json(path) {
      const response = await fetch(path, {cache: 'no-store'});
      if (!response.ok) throw Error(`${path}: HTTP ${response.status}`);
      return response.json();
    }
    async function post(path, data) {
      const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                          body: JSON.stringify(data)});
      const result = await response.json();
      if (!response.ok) throw Error(result.error || `HTTP ${response.status}`);
      return result;
    }
    function emit(name, data) {
      if (name === 'refresh_map') { loadMap(); return; }
      if (name === 'viewport_camera') {
        post('/dashboard/viewport', {mode: data.mode})
          .then(v => dispatch('viewport_camera', v))
          .catch(e => dispatch('command_error', e.message));
        return;
      }
      if (name === 'send_goal' || name === 'stop_rover') {
        if (name === 'send_goal' && (!snapshot || !snapshot.pose_fresh || !snapshot.capture_clock_advancing)) {
          dispatch('command_error', 'Fresh Unreal telemetry is required before selecting a goal.'); return;
        }
        const path = name === 'send_goal' ? '/goal' : '/stop';
        const payload = name === 'send_goal' ? {x: data.x, y: data.y} : {};
        post(path, payload).then(() => log('INFO', name === 'send_goal' ? 'Goal accepted.' : 'Stop accepted.'))
          .catch(e => dispatch('command_error', e.message));
      }
    }
    async function loadMap() {
      try { dispatch('map_update', await json('/dashboard/map')); mapLoaded = true; }
      catch (e) { log('WARN', 'Map unavailable: ' + e.message); }
    }
    const route = a => (a || []).map(p => ({x: p[0], y: p[1]}));
    function missionState(s) {
      return ({following: 'driving', arrived: 'reached', replanning: 'planning',
               waiting_for_sensors: 'waiting', waiting_for_settle: 'waiting',
               waiting_for_pose: 'waiting', waiting_for_fresh_data: 'waiting',
               blocked: 'aborted', stalled_or_timed_out: 'aborted', disconnected: 'unknown'})[s] || s || 'unknown';
    }
    async function receiveState() {
      const s = await json('/mission/snapshot');
      snapshot = s;
      if (previousSession !== null && previousSession !== s.session_id) {
        for (const name of seen.keys()) dispatch('feed_lost', name);
        seen.clear(); lastLidar = null;
        dispatch('path_overlay', null); dispatch('local_dem_lost');
        dispatch('trajectory_update', {path: []});
      }
      previousSession = s.session_id;
      const fresh = !!(s.pose_fresh && s.capture_clock_advancing && s.live_pose);
      dispatch('rover', {label: 'Reference', unreal_linked: fresh, unreal: fresh ? 'reference' : null,
                         unreal_label: 'connected', match: true});
      if (fresh) {
        const p = s.live_pose.position_m;
        dispatch('odom_update', {x: p[0], y: p[1], z: p[2], yaw: s.live_pose.heading_rad * 180 / Math.PI,
                                 speed: s.speed_estimate_m_s});
      } else dispatch('odom_lost');
      const m = s.mission;
      dispatch('mission', {state: missionState(s.state), goal: m && m.goal,
                           reason: s.observer_error || s.sensor_observation_error || ''});
      dispatch('global_path_update', {path: route(m && m.active_plan), first: route(m && m.initial_plan),
                                      replans: m ? Math.max(0, m.plan_revision - 1) : 0});
      if (m && m.mission_id) {
        const trail = await json('/mission/trail?mission_id=' + encodeURIComponent(m.mission_id));
        dispatch('trajectory_update', {path: trail.points.map(p => ({x: p.position_m[0], y: p.position_m[1],
                                                                     break_before: p.break_before}))});
      }
      return s;
    }
    async function receiveFeeds(s) {
      const status = await json('/dashboard/feeds');
      if (!centreWarned && status.center_id_source === 'assumed_plugin_default') {
        centreWarned = true; log('WARN', 'Central camera ID 0 is assumed; the saved sensor config did not record it.');
      }
      if (!encoderWarned && !status.image_encoder_available) {
        encoderWarned = true; log('WARN', 'Pillow is missing; camera image encoding is unavailable.');
      }
      const health = {feeds: {}};
      if (s && s.pose_fresh) health.feeds.odom = {age: s.pose_age_s, hz: '—'};
      for (const [name, f] of Object.entries(status.feeds)) health.feeds[name] = {age: f.age_s, hz: '—'};
      dispatch('health', health);
      await Promise.all(names.map(async name => {
        const f = status.feeds[name];
        if (!f) {
          if (seen.has(name)) { seen.delete(name); dispatch('feed_lost', name); }
          return;
        }
        if (seen.get(name) === f.stamp_ns) return;
        try {
          const response = await fetch('/dashboard/camera/' + name + '.jpg', {cache: 'no-store'});
          if (!response.ok) return;
          const image = await response.arrayBuffer(), captured = response.headers.get('X-Capture-Stamp-Ns');
          if (!captured) return;
          seen.set(name, captured); dispatch('feed', {id: name, image});
        } catch (_) { /* A missing image does not disconnect the pose or command service. */ }
      }));
      if (seen.has('cam_central')) {
        try {
          const response = await fetch('/dashboard/path-overlay?stamp=' + encodeURIComponent(seen.get('cam_central')),
                                       {cache: 'no-store'});
          dispatch('path_overlay', response.ok ? await response.json() : null);
        } catch (_) { dispatch('path_overlay', null); }
      } else dispatch('path_overlay', null);
      if (seen.has('depth_gt')) {
        try {
          const response = await fetch('/dashboard/local-dem?stamp=' + encodeURIComponent(seen.get('depth_gt')),
                                       {cache: 'no-store'});
          if (response.ok) dispatch('local_dem', await response.json()); else dispatch('local_dem_lost');
        } catch (_) { dispatch('local_dem_lost'); }
      } else dispatch('local_dem_lost');
      if (status.feeds.lidar && status.feeds.lidar.stamp_ns !== lastLidar) {
        try {
          const scan = await json('/dashboard/lidar');
          lastLidar = scan.stamp_ns; dispatch('lidar', scan);
        } catch (_) { lastLidar = null; dispatch('lidar', {points: [], count: 0, frame: 'no fresh scan'}); }
      } else if (!status.feeds.lidar && lastLidar !== null) {
        lastLidar = null; dispatch('lidar', {points: [], count: 0, frame: 'no fresh scan'});
      }
    }
    async function receiveEvents() {
      const page = await json('/mission/events'), goals = new Map(), events = [];
      for (const e of page.events) {
        if (e.kind === 'goal_accepted') goals.set(e.mission_id, e.goal);
        const kind = e.kind === 'goal_accepted' ? 'planning' :
          e.kind === 'mission_finished' ? ({arrived: 'reached', blocked: 'aborted', stopped: 'cancelled',
                                           stalled_or_timed_out: 'aborted'})[e.status] :
          e.kind === 'state_changed' ? ({following: 'driving', replanning: 'replan',
              waiting_for_sensors: 'waiting', waiting_for_fresh_data: 'waiting'})[e.status] : null;
        if (kind && e.stamp_ns) events.push({kind, t: Number(e.stamp_ns) / 1e9,
                                             goal: goals.get(e.mission_id) || null, reason: e.error || ''});
      }
      dispatch('timeline', events);
    }
    async function poll() {
      if (busy) return;
      busy = true;
      try {
        const s = await receiveState();
        if (!socket.connected) {
          socket.connected = true; dispatch('connect'); dispatch('config', {depth_max_distance: 8});
        }
        await receiveFeeds(s);
        dispatch('viewport_camera', await json('/dashboard/viewport'));
        if (!mapLoaded) await loadMap();
        if (Date.now() - lastEvents >= 2000) { await receiveEvents(); lastEvents = Date.now(); }
      } catch (_) {
        if (socket.connected) { socket.connected = false; dispatch('disconnect'); }
        dispatch('odom_lost');
        for (const name of seen.keys()) dispatch('feed_lost', name);
        seen.clear(); dispatch('path_overlay', null); dispatch('local_dem_lost');
      } finally { busy = false; setTimeout(poll, 500); }
    }
    setTimeout(poll, 0); // Allow the original overview to register its listeners first.
    return socket;
  };
})();
