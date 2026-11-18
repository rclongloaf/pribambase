# Pribambase

Pribambase connects an animated Blender asset with its artist-authored Aseprite textures.

## Language

**Geometry Normal / Эталонная нормаль**:
A world-space geometric reference against which an artist compares painted directions. Flat follows polygon faces; Smooth follows the smoothed surface, and both references coexist for the same frame.
_Avoid_: edited normal, artist normal

**World Normal / Карта нормалей художника**:
The world-space normal texture composed of artist-painted directions over the geometric reference. An untouched pixel retains its geometric direction.
_Avoid_: tangent-space normal, height map

**Normal Palette / Палитра нормалей**:
A set of camera-facing world-space directions offered at a chosen angular step. Alternative rotation grids share the same visible hemisphere, world axes and diagonal landmarks. Each direction has a corresponding RGB brush color.

**Visible Hemisphere / Видимая полусфера**:
Normal directions pointing toward the render camera, including the tangent boundary. It belongs to the shared render projection, independently of the artist's viewport navigation.

**Source Pair / Пара исходников**:
The Blender scene and Aseprite sprite belonging to the same asset, including their animation and shared projection canvas.
