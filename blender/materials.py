import bpy


def enum(owner, field, desired):
    choices = [item.identifier for item in owner.bl_rna.properties[field].enum_items]
    if desired not in choices:
        raise ValueError(f"{field}: {desired} unavailable, choices={choices}")
    setattr(owner, field, choices[choices.index(desired)])


def function_enum(collection, function, field, desired):
    choices = [item.identifier for item in collection.bl_rna.functions[function].parameters[field].enum_items]
    return choices[choices.index(desired)]


def material(name, color, metallic=0, roughness=0.55, emission=0):
    name = "TR." + name
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color[:3], 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Emission Color"].default_value = (*color[:3], 1)
    shader.inputs["Emission Strength"].default_value = emission
    mat.diffuse_color = (*color[:3], 1)
    return mat
