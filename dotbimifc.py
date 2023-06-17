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

        mesh_name_dictionary = {}
        current_mesh_id = 0

        while True:
            shape = iterator.get()
            element = self.file.by_guid(shape.guid)

            if element.is_a("IfcAnnotation") or element.is_a("IfcOpeningElement"):
                iterator.next()
                continue

            mesh_name = shape.geometry.id
            if mesh_name not in mesh_name_dictionary:
                mesh_name_dictionary[mesh_name] = current_mesh_id
                current_mesh_id += 1

            mesh = self.meshes.get(mesh_name)
            if mesh is None:
                mesh = self.create_mesh(mesh_name, shape, mesh_name_dictionary[mesh_name])

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
                    mesh_id=mesh_name_dictionary[mesh_name],
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

    def create_mesh(self, name, shape, mesh_id):
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

        mesh = dotbimpy.Mesh(mesh_id=mesh_id, coordinates=list(verts), indices=list(faces))
        self.meshes[name] = mesh
        return mesh
