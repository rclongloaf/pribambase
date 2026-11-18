-- Normal math, migration, editable composition, comparison and persistence.
local directory = app.params.extension
local Math = dofile(app.fs.joinPath(directory, "NormalMath.lua"))
local Normals = dofile(app.fs.joinPath(directory, "Normals.lua"))
local Channels = dofile(app.fs.joinPath(directory, "Channels.lua"))
local Guide = dofile(app.fs.joinPath(directory, "Guide.lua"))
local pc = app.pixelColor

-- Projection matches the canonical Blender render, rather than world -Y.
assert(Math.angle(Math.fromDisk(0,0), {x=0,y=-math.sqrt(3)/2,z=0.5}) < 1e-6)
assert(Math.angle(Math.fromDisk(0,1), {x=0,y=0.5,z=math.sqrt(3)/2}) < 1e-6)
assert(Math.fromDisk(1.1,0) == nil)
assert(Math.visible({x=1,y=0,z=0}) and Math.visible({x=-1,y=0,z=0}))
assert(not Math.visible({x=0,y=1,z=0}) and not Math.visible({x=0,y=0,z=-1}))
assert(Math.paintable(Math.decode(Math.color({x=1,y=0,z=0}).rgbaPixel)),
    "RGB8 rounding rejected a valid tangent normal")
assert(Math.decode(pc.rgba(128,128,255,0)) == nil)
assert(math.abs(Math.angle({x=1,y=0,z=0}, {x=0,y=0,z=1})-90) < 1e-6)

-- Known noncommuting active world rotations from -Y.
local zx = Math.ordered(math.pi/4,math.pi/4,"ZX")
local xz = Math.ordered(math.pi/4,math.pi/4,"XZ")
assert(Math.angle(zx,{x=math.sqrt(0.5),y=-0.5,z=-0.5}) < 1e-6)
assert(Math.angle(xz,{x=0.5,y=-0.5,z=-math.sqrt(0.5)}) < 1e-6)
assert(Math.angle(zx,xz) > 15)
assert(Math.angle(zx,Math.quantize(zx,2,"ZX")) < 1e-5)
assert(Math.angle(xz,Math.quantize(xz,2,"XZ")) < 1e-5)
assert(Math.angle(zx,Math.quantize(zx,2,"XZ")) > 1)
for _,order in ipairs({"ZX","XZ"}) do
    assert(math.abs(Math.angle(Math.front,Math.quantize(Math.front,2,order))-15) < 1e-5,
        "45-degree grid offers an off-grid camera-center direction")
    assert(Math.angle(Math.front,Math.quantize(Math.front,3,order)) < 1e-5,
        "30-degree grid lost its legitimate camera-center direction")
    assert(Math.angle(Math.front,Math.quantize(Math.front,0,order)) < 1e-5,
        "Free mode lost the camera-center direction")
end

for divisions=1,12 do
    for _,order in ipairs({"ZX","XZ"}) do
        local palette,seen = Math.palette(divisions,order),{}
        for _,n in ipairs(palette) do
            assert(Math.visible(n), "Palette offers a hidden normal")
            assert(math.abs(Math.dot(n,n)-1) < 1e-6)
            assert(Math.angle(n,Math.decode(Math.color(n).rgbaPixel)) < 0.5)
            assert(Math.angle(n,Math.quantize(n,divisions,order)) < 1e-5)
            local u,v = Math.toDisk(n)
            assert(Math.angle(n,Math.fromDisk(u,v)) < 1e-5)
            local key = string.format("%.5f,%.5f,%.5f",n.x+0,n.y+0,n.z+0)
            assert(not seen[key],"Duplicate palette direction")
            seen[key]=true
        end
        for _,point in ipairs(Math.landmarks()) do
            assert(Math.angle(point.n,Math.quantize(point.n,divisions,order)) < 1e-5,
                "Coarse palette lost a world axis or diagonal")
        end
        for _,plane in ipairs({"XY","XZ","YZ"}) do
            local n = Math.quantize(Math.front,divisions,order,plane)
            assert(n and Math.visible(n) and Math.inPlane(n,plane))
        end
        for _,line in ipairs(Math.grid(divisions,order)) do
            for _,n in ipairs(line) do assert(Math.visible(n)) end
        end
    end
end
for _,plane in ipairs({"XY","XZ","YZ"}) do
    for _,line in ipairs(Math.planeCurve(plane)) do
        for _,n in ipairs(line) do assert(Math.visible(n) and Math.inPlane(n,plane)) end
    end
end
assert(Math.quantize({x=0,y=1,z=0},2,"ZX") == nil)
for tilt=0,90,15 do
    for bearing=-180,180,30 do
        local n = Math.fromCameraAngles(math.rad(bearing),math.rad(tilt))
        assert(Math.visible(n))
        assert(math.abs(Math.angle(n,Math.front)-tilt) < 1e-5)
        for _,plane in ipairs({"XY","XZ","YZ"}) do
            local constrained = Math.quantize(n,0,"ZX",plane)
            assert(constrained and Math.visible(constrained) and Math.inPlane(constrained,plane))
        end
    end
end

local sprite = Sprite(3,2,ColorMode.RGB)
app.activeSprite = sprite
sprite.layers[1].name = "Keep artist color"
sprite.cels[1].image:clear(pc.rgba(12,34,56,255))
Channels.initialize(sprite)
local before = Channels.renderBaseColor(sprite,1).bytes
-- Simulate v2.4's read-only generated normal.
app.command.NewLayer{reference=true}
local legacy = app.activeLayer
legacy.name = "Pribambase World Normal"
legacy.properties("lampysprites/pribambase", {role="world-normal-generated", schema=1})
sprite.properties("lampysprites/pribambase").channelSchema = 6
Channels.initialize(sprite)
assert(not Channels.needsMigration(sprite))
assert(Channels.renderBaseColor(sprite,1).bytes == before, "Normal migration changed Base Color")
for _,layer in ipairs(sprite.layers) do
    assert(layer.properties("lampysprites/pribambase").role ~= "world-normal-generated")
end
local group = Normals.group(sprite)
local paint = Normals.paintLayer(sprite, false)
assert(group and paint and paint.isEditable)
local reference = Image(3,2,ColorMode.RGB)
reference:clear(pc.rgba(128,128,255,255))
reference:drawPixel(0,1,pc.rgba(128,0,128,255))
app.activeLayer = paint
local referenceLayer = Normals.receiveDefault(sprite,1,reference)
assert(referenceLayer.isReference and not referenceLayer.isEditable)
assert(app.activeLayer == paint, "Receiving reference stole the artist's layer")
assert(Guide.findRenderLayer(sprite) == nil, "Geometry reference was mistaken for render guide")
assert(Normals.render(sprite,1).bytes == reference.bytes)
local smooth = Image(3,2,ColorMode.RGB)
smooth:clear(pc.rgba(128,0,128,255))
local smoothLayer = Normals.receiveDefault(sprite,1,smooth,"SMOOTH")
assert(smoothLayer ~= referenceLayer and smoothLayer.isReference and not smoothLayer.isEditable)
assert(Normals.defaultImage(sprite,1,"SMOOTH").bytes == smooth.bytes)
assert(Normals.render(sprite,1).bytes == reference.bytes, "Receiving Smooth changed the artist map")

assert(Normals.defaultImage(sprite,2) == nil, "Reference leaked into a different frame")

local ink = Image(1,1,ColorMode.RGB)
ink:clear(pc.rgba(255,128,128,255))
app.transaction("Paint a normal", function() sprite:newCel(paint,1,ink,Point(1,0)) end)
local edited = Normals.render(sprite,1)
assert(pc.rgbaR(edited:getPixel(1,0)) == 255)
assert(edited:getPixel(0,1) == reference:getPixel(0,1), "Untouched normal lost its geometry")
local sampled = Normals.inspect(sprite,1,1,0)
assert(Math.angle(Math.decode(sampled.painted), Math.decode(sampled.default)) > 89)
assert(Normals.inspect(sprite,1,-1,0) == nil)
Channels.activate(sprite,"normal")
assert(app.activeLayer == paint and group.isVisible and referenceLayer.isVisible)
assert(not Channels.group(sprite,"base_color").isVisible)
local sent = Channels.renderNormal(sprite,1).bytes
Normals.showDefault(sprite,true)
assert(not group.isVisible and referenceLayer.isVisible)
assert(Channels.renderNormal(sprite,1).bytes == sent, "Compare mode changed outbound artist normals")
Normals.showDefault(sprite,true,"SMOOTH")
assert(smoothLayer.isVisible and not referenceLayer.isVisible)
assert(Channels.renderNormal(sprite,1).bytes == sent, "Smooth preview changed outbound artist normals")
assert(Normals.inspect(sprite,1,1,0).smooth == smooth:getPixel(1,0))

Channels.setSendEnabled(sprite,"normal",false)
assert(Channels.renderNormal(sprite,1).bytes == reference.bytes)
Channels.setSendEnabled(sprite,"normal",true)
assert(Channels.renderNormal(sprite,1).bytes == sent)

local updated = Image(reference)
updated:clear(pc.rgba(128,0,128,255))
local artistBytes = paint:cel(1).image.bytes
app.transaction("Artist layer opacity", function() paint.opacity = 254 end)
Normals.receiveDefault(sprite,1,updated)
assert(paint:cel(1).image.bytes == artistBytes, "Reference refresh overwrote artist normals")
app.undo()
assert(paint.opacity == 255, "Reference refresh inserted an unwanted Undo step")
assert(Normals.defaultImage(sprite,1).bytes == updated.bytes)
assert(pc.rgbaR(Normals.render(sprite,1):getPixel(1,0)) == 255)
Channels.activate(sprite,"base_color")
assert(not group.isVisible and not referenceLayer.isVisible)
assert(Channels.group(sprite,"base_color").isVisible)
assert(Channels.renderBaseColor(sprite,1).bytes == before)
local count = #sprite.layers
Channels.initialize(sprite)
assert(#sprite.layers == count and paint:cel(1).image.bytes == artistBytes,
    "Repeated migration changed artist layers")

-- Both reference and artist pixels and the schema survive a save/reopen.
local path = app.params.result .. ".normals.aseprite"
assert(sprite:saveAs(path))
sprite:close()
local reopened = Sprite{fromFile=path}
assert(not Channels.needsMigration(reopened))
assert(Normals.defaultImage(reopened,1).bytes == updated.bytes)
assert(Normals.defaultImage(reopened,1,"SMOOTH").bytes == smooth.bytes)
assert(Normals.paintLayer(reopened,false):cel(1).image.bytes == artistBytes)
reopened:close()
print("Pribambase normal palette, migration and comparison tests passed")
