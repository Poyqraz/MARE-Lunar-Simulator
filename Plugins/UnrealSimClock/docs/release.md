# Making a release

Each GitHub release carries the plugin prebuilt for one engine version and
platform, e.g. `UnrealSimClock-1.0-UE5.7-Win64.zip`, so projects can use it without
Visual Studio.

1. Set `VersionName` (and `Version`, an integer) in `UnrealSimClock.uplugin`, and
   `EngineVersion` if the engine changes.
2. Build the package (about 2 minutes):

   ```
   powershell -ExecutionPolicy Bypass -File Scripts\Package.ps1
   ```

   It compiles the plugin for Win64 with `RunUAT BuildPlugin` against
   `C:\Program Files\Epic Games\UE_5.7` (`-EngineDir` for another install) and
   writes `UnrealSimClock-<VersionName>-UE<engine>-Win64.zip` to `%TEMP%\UnrealPluginRelease`
   (`-OutDir` to change). The zip holds a `UnrealSimClock/` folder: the descriptor,
   `Source/`, the compiled `Binaries/`, the libraries packaged games link
   (`Intermediate/`), and the `LICENSE`, `README.md` and `docs/` listed in
   `Config/FilterPlugin.ini`.
3. Tag the commit (`v<VersionName>`) and create a GitHub release from the tag,
   attaching the zip.

The binaries load only in the engine version they were built for (5.7.x here);
other versions build from source.
