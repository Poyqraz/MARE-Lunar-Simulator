"""Editor-only Mars material graphs. No numerical Python dependencies."""


def connect_input(lib, source, target, input_name, output=""):
    """Resolve displayed UE pin names (TextureSample uses UVs, not Coordinates)."""
    available = [str(v) for v in lib.get_material_expression_input_names(target)]
    aliases = {"Coordinates": ("UVs", "Coordinates"), "Input": ("Input", "")}
    if available and input_name not in available:
        input_name = next((name for name in aliases.get(input_name, (input_name,)) if name in available), None)
        if input_name is None:
            raise RuntimeError(f"Material input not exposed; available pins: {available}")
    if not lib.connect_material_expressions(source, output, target, input_name):
        raise RuntimeError(f"Cannot connect material input {input_name}")


def create_material(unreal, folder, mode, manifest_path, manifest, scene):
    name = "M_JezeroOrbitalReference" if mode == "orbital_reference" else "M_MarsProcedural"
    asset_path = folder + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(asset_path):
        raise FileExistsError(asset_path)
    lib = unreal.MaterialEditingLibrary
    material = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, unreal.Material, unreal.MaterialFactoryNew())
    if material is None:
        raise RuntimeError("Could not create Mars material")

    def node(class_name, **properties):
        result = lib.create_material_expression(material, getattr(unreal, class_name))
        if result is None:
            raise RuntimeError(f"Cannot create material node {class_name}")
        for key, value in properties.items():
            result.set_editor_property(key, value)
        return result

    def link(source, target, input_name, output=""):
        connect_input(lib, source, target, input_name, output)

    def final(source, property_name):
        if not lib.connect_material_property(source, "", getattr(unreal.MaterialProperty, property_name)):
            raise RuntimeError(f"Cannot connect {property_name}; supply a project-compatible material_path")

    position = node("MaterialExpressionWorldPosition")
    if mode == "orbital_reference":
        material.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
        image = manifest["imagery"]
        task = unreal.AssetImportTask()
        task.set_editor_property("filename", str(manifest_path.parent / image["filename"]))
        task.set_editor_property("destination_path", folder)
        task.set_editor_property("destination_name", "T_JezeroOrbitalReference")
        task.set_editor_property("automated", True)
        task.set_editor_property("save", True)
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
        paths = task.get_editor_property("imported_object_paths")
        if len(paths) != 1:
            raise RuntimeError("Could not import the registered orbital reference texture")
        texture = unreal.load_asset(paths[0])
        texture.set_editor_property("address_x", unreal.TextureAddress.TA_CLAMP)
        texture.set_editor_property("address_y", unreal.TextureAddress.TA_CLAMP)
        unreal.EditorAssetLibrary.save_asset(paths[0])
        x = node("MaterialExpressionComponentMask", r=True, g=False, b=False, a=False)
        y = node("MaterialExpressionComponentMask", r=False, g=True, b=False, a=False)
        link(position, x, "Input")
        link(position, y, "Input")
        extent_x, extent_y = manifest["grid"]["extent_m"]
        u = node("MaterialExpressionMultiply", const_b=-1 / (extent_x * 100))
        vy = node("MaterialExpressionMultiply", const_b=-1 / (extent_y * 100))
        v = node("MaterialExpressionAdd", const_b=1.0)
        link(x, u, "A")
        link(y, vy, "A")
        link(vy, v, "A")
        uv = node("MaterialExpressionAppendVector")
        link(u, uv, "A")
        link(v, uv, "B")
        sample = node("MaterialExpressionTextureSampleParameter2D", texture=texture,
                      parameter_name="MeasuredOrbitalReference")
        link(uv, sample, "Coordinates")
        final(sample, "MP_EMISSIVE_COLOR")
    else:
        # Synthetic shading variation only: no displacement/collision fiction.
        noise = node("MaterialExpressionNoise", scale=0.002, levels=2, quality=1,
                     output_min=0.0, output_max=1.0)
        link(position, noise, "Position")
        a = node("MaterialExpressionConstant3Vector", constant=unreal.LinearColor(*scene["terrain_color_a_linear"], 1))
        b = node("MaterialExpressionConstant3Vector", constant=unreal.LinearColor(*scene["terrain_color_b_linear"], 1))
        blend = node("MaterialExpressionLinearInterpolate")
        link(a, blend, "A")
        link(b, blend, "B")
        link(noise, blend, "Alpha")
        final(blend, "MP_BASE_COLOR")
        roughness = node("MaterialExpressionConstant", r=scene["terrain_roughness"])
        final(roughness, "MP_ROUGHNESS")
    lib.recompile_material(material)
    if not unreal.EditorAssetLibrary.save_asset(asset_path):
        raise RuntimeError(f"Could not save {asset_path}")
    return material
