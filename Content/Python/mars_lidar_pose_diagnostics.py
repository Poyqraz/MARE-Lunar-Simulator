"""Toggle opt-in LiDAR request-pose logging on the current PIE rover only."""

TAG = "MarsLidarPoseProbe"


def _rover(unreal):
    worlds = unreal.EditorLevelLibrary.get_pie_worlds(False)
    if len(worlds) != 1:
        raise ValueError("Start exactly one local Unreal Play session")
    world = worlds[0]
    pawns = unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Pawn)
    candidates = [p for p in pawns if p.get_class().get_name().startswith("Leo_Raph")]
    if len(candidates) != 1:
        raise ValueError("Expected exactly one Leo_Raph rover in the Play world")
    return world, candidates[0]


def _toggle(enabled, *, unreal_module=None):
    if unreal_module is None:
        import unreal as unreal_module
    unreal = unreal_module
    world, rover = _rover(unreal)
    tags = list(rover.get_editor_property("tags"))
    kept = [tag for tag in tags if str(tag).lower() != TAG.lower()]
    if enabled:
        kept.append(unreal.Name(TAG))
    rover.set_editor_property("tags", kept)
    result = {"world": world.get_path_name(), "rover": rover.get_name(), "enabled": enabled,
              "scope": "current Play actor only", "tag": TAG}
    print("MARS_LIDAR_POSE_LOG:", result)
    return result


def enable(*, unreal_module=None):
    return _toggle(True, unreal_module=unreal_module)


def disable(*, unreal_module=None):
    return _toggle(False, unreal_module=unreal_module)
