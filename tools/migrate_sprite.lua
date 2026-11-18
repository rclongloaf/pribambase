-- Aseprite-side saved-pair migration. The host restores backups on any failure.
local source, directory, extension, result = app.params.source, app.params.references,
    app.params.extension, app.params.result
assert(source and directory and extension and result, "Missing migration parameters")
local Channels = dofile(app.fs.joinPath(extension, "Channels.lua"))
local Normals = dofile(app.fs.joinPath(extension, "Normals.lua"))
local sprite = Sprite{fromFile=source}
app.activeSprite = sprite
local originalFrame = app.activeFrame.frameNumber
local frameDuration = sprite.frames[1].duration
local before = {}
for frame=1,#sprite.frames do before[frame] = Channels.renderBaseColor(sprite,frame).bytes end
Channels.initialize(sprite)
local stream = assert(io.open(app.fs.joinPath(directory, "references.json"), "r"))
local references = json.decode(stream:read("*a"))
stream:close()
for _,reference in ipairs(references) do
    local file = assert(io.open(app.fs.joinPath(directory, reference.file), "rb"))
    local image = Image(reference.width, reference.height, ColorMode.RGB)
    image.bytes = file:read("*a")
    file:close()
    local previousCount = #sprite.frames
    Normals.receiveDefault(sprite, reference.frame, image, reference.mode)
    for frame=previousCount+1,#sprite.frames do sprite.frames[frame].duration = frameDuration end
end
for frame,bytes in ipairs(before) do
    assert(Channels.renderBaseColor(sprite,frame).bytes == bytes, "Migration changed artist Base Color")
end
app.activeFrame = sprite.frames[originalFrame]
assert(sprite:saveAs(source), "Could not save migrated sprite")
sprite:close()
local marker = assert(io.open(result,"w"))
marker:write("ok\n") marker:close()
print("Aseprite source migrated; Flat and Smooth references stored separately")
