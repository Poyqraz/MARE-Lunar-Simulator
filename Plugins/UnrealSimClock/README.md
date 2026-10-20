# UnrealSimClock

One simulation clock for Unreal sensor plugins, streamed to ROS as `/clock`.
It follows Unreal's game time (pauses with Play, follows time dilation) and
never runs backwards across Play sessions.

Part of [MARE](https://github.com/raulcastar/MARE-Lunar-Simulator), an open-source lunar rover
simulation suite. In its ROS 2 stack,
[GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator), the `component_sim_clock` node publishes `/clock` (port 3008).

## Requirements

Unreal Engine 5.7 on Windows (the version it is developed and tested with).
Building from source also needs Visual Studio 2022 with the *Game development
with C++* workload.

On the ROS side: ROS 2 Jazzy (Ubuntu 24.04), with the
`component_sim_clock` node of GNC-Moon-Simulator receiving the stream. The plugin itself has no ROS
dependency: any program that reads the [wire format](docs/sim-time.md) can use it.

## Install

- **Prebuilt (UE 5.7, Win64):** download `UnrealSimClock-<version>-UE5.7-Win64.zip`
  from [Releases](https://github.com/raulcastar/UnrealSimClock/releases) and extract it
  into `<YourProject>/Plugins/`.
- **From source:** clone this repository into `<YourProject>/Plugins/UnrealSimClock`,
  open the project and answer **Yes** to rebuild the module.

Then check it is enabled under *Edit → Plugins → Project → Other*.

## Use

Nothing to add: it is a world subsystem. Press Play and it streams the time to
`127.0.0.1:3008`.

It also gives Blueprints **Get Sim Time Ns String** / **Get Sim Time Seconds**,
and **GNC Bytes To String** / **GNC String To Bytes** for TCP links.

## Dependencies

None: only engine modules. No other plugin needs it to build or run (each
carries its own copy of `GncSimTime.h`), but ROS nodes running on simulation
time need its `/clock`, and GNC's rover Blueprint uses its Blueprint nodes.

## Docs

| | |
|---|---|
| [Simulation time](docs/sim-time.md) | The shared clock, the `/clock` stream, console variables, Blueprint nodes |
| [Making a release](docs/release.md) | Building the prebuilt zip for GitHub releases |

## License

[MIT](LICENSE), © 2026 Raul Castilla Arquillo.
