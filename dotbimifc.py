import re
import math
import uuid
import numpy
import dotbimpy
import pyquaternion
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.util.element
import multiprocessing


class Ifc2Dotbim:
    def __init__(self, ifc):
        self.file = ifc
        self.meshes = {}
        self.mesh_colors = {}
        self.elements = []

    def execute(self):
        self.settings = ifcopenshell.geom.settings()
        self.filter_body_contexts()
        iterator = ifcopenshell.geom.iterator(self.settings, self.file, multiprocessing.cpu_count())

        if not iterator.initialize():
            return

        while True:
            shape = iterator.get()
            element = self.file.by_guid(shape.guid)

            if element.is_a("IfcAnnotation") or element.is_a("IfcOpeningElement"):
                iterator.next()
                continue

            mesh_name = shape.geometry.id
            mesh = self.meshes.get(mesh_name)
            if mesh is None:
                mesh = self.create_mesh(mesh_name, element, shape)

            rgba = self.mesh_colors.get(mesh_name, [255, 255, 255, 255])
            color = dotbimpy.Color(r=rgba[0], g=rgba[1], b=rgba[2], a=rgba[3])

            m = shape.transformation.matrix.data

            mat = numpy.array(
                ([m[0], m[3], m[6], m[9]], [m[1], m[4], m[7], m[10]], [m[2], m[5], m[8], m[11]], [0, 0, 0, 1])
            )

            qw, qx, qy, qz = pyquaternion.Quaternion(matrix=mat).elements

            rotation = dotbimpy.Rotation(qx=float(qx), qy=float(qy), qz=float(qz), qw=float(qw))
            vector = dotbimpy.Vector(x=m[9], y=m[10], z=m[11])
            info = {
                str(k): str(v) for k, v in element.get_info().items() if not isinstance(v, ifcopenshell.entity_instance)
            }

            for pset, properties in ifcopenshell.util.element.get_psets(element).items():
                for prop, value in properties.items():
                    info[f"{pset}-{prop}"] = str(value)

            element_type = ifcopenshell.util.element.get_type(element)
            if element_type:
                for pset, properties in ifcopenshell.util.element.get_psets(element_type).items():
                    for prop, value in properties.items():
                        info[f"{pset}-{prop}"] = str(value)

            self.elements.append(
                dotbimpy.Element(
                    mesh_id=mesh_name,
                    vector=vector,
                    guid=str(uuid.UUID(ifcopenshell.guid.expand(element.GlobalId))),
                    info=info,
                    rotation=rotation,
                    type=element.is_a(),
                    color=color,
                )
            )

            if not iterator.next():
                break

        file_info = {
            "Author": " ".join(self.file.header.file_name.author),
            "Date": self.file.header.file_name.time_stamp,
        }

        self.dotbim_file = dotbimpy.File(
            "1.0.0", meshes=list(self.meshes.values()), elements=self.elements, info=file_info
        )

    def write(self, output):
        self.dotbim_file.save(output)

    def filter_body_contexts(self):
        self.body_contexts = [
            c.id()
            for c in self.file.by_type("IfcGeometricRepresentationSubContext")
            if c.ContextIdentifier in ["Body", "Facetation"]
        ]
        # Ideally, all representations should be in a subcontext, but some BIM programs don't do this correctly
        self.body_contexts.extend(
            [
                c.id()
                for c in self.file.by_type("IfcGeometricRepresentationContext", include_subtypes=False)
                if c.ContextType == "Model"
            ]
        )
        if self.body_contexts:
            self.settings.set_context_ids(self.body_contexts)

    def create_mesh(self, name, element, shape):
        faces = shape.geometry.faces
        verts = shape.geometry.verts
        materials = shape.geometry.materials
        material_ids = shape.geometry.material_ids

        material_popularity_contest = {}
        material_rgbas = {}
        if materials:
            for material in materials:
                if material.has_diffuse:
                    alpha = 1.0
                    if material.has_transparency and material.transparency > 0:
                        alpha = 1.0 - material.transparency
                    rgba = material.diffuse + (alpha,)
                    rgba = [int(v * 255) for v in rgba]
                    material_rgbas[material.name] = rgba

            for material_id in material_ids:
                material_name = materials[material_id].name
                material_popularity_contest.setdefault(material_name, 0)
                material_popularity_contest[material_name] += 1

        if material_popularity_contest:
            flattened_contest = [(k, v) for k, v in material_popularity_contest.items()]
            most_popular_material = list(reversed(sorted(flattened_contest, key=lambda x: x[1])))[0][0]
            self.mesh_colors[name] = material_rgbas[most_popular_material]

        mesh = dotbimpy.Mesh(mesh_id=name, coordinates=list(verts), indices=list(faces))
        self.meshes[name] = mesh
        return mesh


class Dotbim2Ifc:
    def __init__(self, dotbim):
        self.dotbim = dotbim
        self.file = None
        self.meshes = {}
        self.mesh_colors = {}

    def execute(self):
        ifcopenshell.api.run("project.create_file")

        self.file = ifcopenshell.api.run("project.create_file", version="IFC4")
        project = ifcopenshell.api.run("root.create_entity", self.file, ifc_class="IfcProject", name="Project")
        ifcopenshell.api.run("unit.assign_unit", self.file, units=[ifcopenshell.api.run("unit.add_si_unit", self.file)])

        model = ifcopenshell.api.run("context.add_context", self.file, context_type="Model")
        self.body = ifcopenshell.api.run(
            "context.add_context",
            self.file,
            context_type="Model",
            context_identifier="Body",
            target_view="MODEL_VIEW",
            parent=model,
        )

        site = ifcopenshell.api.run("root.create_entity", self.file, ifc_class="IfcSite", name="Site")
        ifcopenshell.api.run("aggregate.assign_object", self.file, product=site, relating_object=project)

        for mesh in self.dotbim.meshes:
            self.create_mesh(mesh)

        for dotbim_element in self.dotbim.elements:
            ifc_class = "IfcBuildingElementProxy"
            name = dotbim_element.info.get("Name", dotbim_element.info.get("name", "Unnamed"))
            element = ifcopenshell.api.run("root.create_entity", self.file, ifc_class=ifc_class, name=name)
            ifcopenshell.api.run("spatial.assign_container", self.file, product=element, relating_structure=site)
            pset = ifcopenshell.api.run("pset.add_pset", self.file, product=element, name="Dotbim_Info")
            ifcopenshell.api.run("pset.edit_pset", self.file, pset=pset, properties=dotbim_element.info)

            representation = self.meshes[dotbim_element.mesh_id]

            # IFC stores colours per mesh. Dotbim stores colours per element.
            rgba = (dotbim_element.color.r, dotbim_element.color.g, dotbim_element.color.b, dotbim_element.color.a)
            rgba_key = ",".join(rgba)

            self.mesh_colors.setdefault(dotbim_element.mesh_id, {})
            mesh_rgba = self.mesh_colors[dotbim_element.mesh_id]
            if not mesh_rgba:
                self.assign_rgba(representation, rgba)
                self.mesh_colors[dotbim_element.mesh_id][rgba_key] = representation
            elif rgba_key in mesh_rgba:
                representation = mesh_rgba[rgba_key]
            else:
                representation = ifcopenshell.util.element.copy_deep(self.file, representation)
                self.assign_rgba(representation, rgba)
                self.mesh_colors[dotbim_element.mesh_id][rgba_key] = representation

            element.Representation = self.file.createIfcProductDefinitionShape(Representations=[representation])

            matrix = pyquaternion.Quaternion(
                a=dotbim_element.rotation.qw,
                b=dotbim_element.rotation.qx,
                c=dotbim_element.rotation.qy,
                d=dotbim_element.rotation.qz,
            ).transformation_matrix
            matrix[0][3] = dotbim_element.vector.x
            matrix[1][3] = dotbim_element.vector.y
            matrix[2][3] = dotbim_element.vector.z
            ifcopenshell.api.run("geometry.edit_object_placement", self.file, product=element, matrix=matrix)

    def write(self, output):
        self.file.write(output)

    def create_mesh(self, mesh):
        verts = mesh.coordinates
        faces = mesh.indices

        grouped_verts = [[verts[i], verts[i + 1], verts[i + 2]] for i in range(0, len(verts), 3)]
        grouped_faces = [[faces[i], faces[i + 1], faces[i + 2]] for i in range(0, len(faces), 3)]

        coordinates = self.file.createIfcCartesianPointList3D(grouped_verts)
        polygons = [self.file.createIfcIndexedPolygonalFace([v + 1 for v in gf]) for gf in grouped_faces]
        items = [self.file.createIfcPolygonalFaceSet(coordinates, None, polygons)]

        self.meshes[mesh.mesh_id] = self.file.createIfcShapeRepresentation(
            self.body,
            self.body.ContextIdentifier,
            "Tessellation",
            items,
        )

    def assign_rgba(self, representation, rgba):
        style = ifcopenshell.api.run("style.add_style", self.file)
        surface_style = ifcopenshell.api.run(
            "style.add_surface_style",
            self.file,
            style=style,
            ifc_class="IfcSurfaceStyleShading",
            attributes=self.get_rgba_attributes(rgba),
        )
        ifcopenshell.api.run(
            "style.assign_representation_styles", self.file, shape_representation=representation, styles=[style]
        )

    def get_rgba_attributes(self, rgba):
        return {
            "SurfaceColour": {
                "Red": rgba[0] / 255,
                "Green": rgba[1] / 255,
                "Blue": rgba[2] / 255,
            },
            "Transparency": 1 - (rgba[3] / 255),
        }
