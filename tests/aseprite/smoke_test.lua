local extension = app.params["extension"]
if extension == nil or extension == "" then
    error("Expected --script-param extension=<built extension directory>")
end

local result = app.params["result"]
if result == nil or result == "" then
    error("Expected --script-param result=<success marker path>")
end

local files = {
    "Canvas.lua",
    "ChannelEditor.lua",
    "Channels.lua",
    "Commands.lua",
    "Guide.lua",
    "PayloadCache.lua",
    "Settings.lua",
    "Sync.lua"
}

for _, name in ipairs(files) do
    local path = app.fs.joinPath(extension, name)
    local chunk, loadError = loadfile(path)
    if chunk == nil then
        error("Could not load " .. name .. ": " .. tostring(loadError))
    end
end

dofile(app.fs.joinPath(extension, "Commands.lua"))
assert(type(init) == "function", "Commands.lua must define init(plugin)")
assert(type(pribambase_default_settings) == "table", "Default settings are missing")
assert(pribambase_default_settings.port == "34613", "Unexpected default port")

local apiSprite = Sprite(2, 2, ColorMode.RGB)
app.activeSprite = apiSprite
apiSprite.cels[1].image:drawPixel(0, 0, app.pixelColor.rgba(255, 0, 0, 255))
app.command.NewLayer{ reference=true }
local referenceLayer = app.activeLayer
assert(referenceLayer.isReference, "Aseprite reference layers are unavailable")
local referenceCel = apiSprite:newCel(referenceLayer, 1)
referenceCel.image:drawPixel(0, 0, app.pixelColor.rgba(0, 255, 0, 255))
local composite = Image(2, 2, ColorMode.RGB)
composite:drawSprite(apiSprite, 1)
local compositePixel = composite:getPixel(0, 0)
assert(
    app.pixelColor.rgbaR(compositePixel) == 255 and app.pixelColor.rgbaG(compositePixel) == 0,
    "Image:drawSprite unexpectedly includes reference layers"
)
referenceLayer.isVisible = false
assert(not referenceLayer.isVisible, "Reference layer visibility cannot be changed")
referenceLayer.isVisible = true
referenceLayer.isEditable = false
assert(not referenceLayer.isEditable, "Reference layers cannot be locked")
apiSprite:newEmptyFrame()
assert(#apiSprite.frames == 2, "Aseprite frames cannot be appended")
local Guide = dofile(app.fs.joinPath(extension, "Guide.lua"))
Guide.markRenderLayer(referenceLayer)
Guide.placeAtBottom(referenceLayer)
assert(
    Guide.findRenderLayer(apiSprite) == referenceLayer,
    "Render guide layer metadata cannot be resolved"
)
assert(referenceLayer.stackIndex == 1, "Render guide must stay at the bottom of the layer stack")
assert(referenceLayer:cel(2) == nil, "Reference layer should start without a cel on frame 2")
local ensuredCel, createdCel = Guide.ensureCel(apiSprite, referenceLayer, 2)
assert(createdCel, "Missing guide cel was not reported as created")
assert(referenceLayer:cel(2) ~= nil, "Guide cel was not created on a previously empty frame")
local reusedCel, createdAgain = Guide.ensureCel(apiSprite, referenceLayer, 2)
assert(not createdAgain and reusedCel == ensuredCel, "Existing guide cel was not reused")
assert(referenceLayer:cel(2) ~= nil, "Existing guide cel was not replaced")
local guidePixels = Image(2, 2, ColorMode.RGB)
guidePixels:clear(app.pixelColor.rgba(12, 34, 56, 255))
app.transaction("Artist action before guide refresh", function()
    referenceLayer.opacity = 127
end)
Guide.updateCelPixels(referenceLayer:cel(1), guidePixels)
app.undo()
assert(
    referenceLayer.opacity == 255,
    "External render-guide pixels hid the preceding artist action from Undo"
)
assert(
    app.pixelColor.rgbaR(referenceLayer:cel(1).image:getPixel(0, 0)) == 12,
    "Undo unexpectedly reverted non-undoable external render-guide pixels"
)

local canvasSprite = Sprite(2, 2, ColorMode.RGB)
app.activeSprite = canvasSprite
canvasSprite.cels[1].image:drawPixel(0, 0, app.pixelColor.rgba(255, 0, 0, 255))
local Canvas = dofile(app.fs.joinPath(extension, "Canvas.lua"))
assert(Canvas.ensure(canvasSprite, 4, 4, 2, 2), "Canvas expansion was not reported")
assert(canvasSprite.width == 4 and canvasSprite.height == 4, "Canvas was not expanded")
local expandedComposite = Image(4, 4, ColorMode.RGB)
expandedComposite:drawSprite(canvasSprite, 1)
local shiftedPixel = expandedComposite:getPixel(1, 1)
assert(app.pixelColor.rgbaR(shiftedPixel) == 255, "Canvas expansion lost world-origin alignment")
assert(not Canvas.ensure(canvasSprite, 4, 4, 2, 2), "Idempotent canvas update changed the sprite")
app.transaction("Artist action before canvas refresh", function()
    canvasSprite.layers[1].opacity = 127
end)
assert(
    not Canvas.needsUpdate(canvasSprite, 4, 4, 2, 2),
    "Unchanged canvas metadata requested an external transaction"
)
app.undo()
assert(
    canvasSprite.layers[1].opacity == 255,
    "Idempotent external canvas metadata hid the preceding artist action from Undo"
)

local asymmetricSprite = Sprite(2, 3, ColorMode.RGB)
app.activeSprite = asymmetricSprite
asymmetricSprite.cels[1].image:drawPixel(0, 0, app.pixelColor.rgba(255, 0, 0, 255))
assert(Canvas.ensure(asymmetricSprite, 5, 7, 3, 4), "Asymmetric expansion was not reported")
local asymmetricComposite = Image(5, 7, ColorMode.RGB)
asymmetricComposite:drawSprite(asymmetricSprite, 1)
local asymmetricPixel = asymmetricComposite:getPixel(2, 1)
assert(
    app.pixelColor.rgbaR(asymmetricPixel) == 255,
    "Asymmetric canvas expansion changed the global projection origin"
)

local Channels = dofile(app.fs.joinPath(extension, "Channels.lua"))
local PayloadCache = dofile(app.fs.joinPath(extension, "PayloadCache.lua"))
local payloadCache = PayloadCache.new()
local payloadSpriteId = 1
local payloadImage = Image(2, 1, ColorMode.RGB)
payloadImage:clear(app.pixelColor.rgba(20, 40, 60, 255))
assert(
    payloadCache:changed(payloadSpriteId, "sprite.aseprite", 1, "base", payloadImage, false),
    "First texture payload must be sent"
)
assert(
    not payloadCache:changed(payloadSpriteId, "sprite.aseprite", 1, "base", payloadImage, false),
    "Identical guide-triggered texture payload must be suppressed"
)
payloadImage:clear(app.pixelColor.rgba(204, 204, 204, 255))
assert(
    payloadCache:changed(payloadSpriteId, "sprite.aseprite", 1, "base", payloadImage, false),
    "Disabled-channel defaults must be sent"
)
payloadImage:clear(app.pixelColor.rgba(20, 40, 60, 255))
assert(
    payloadCache:changed(payloadSpriteId, "sprite.aseprite", 1, "base", payloadImage, false),
    "Re-enabled artist texture must be sent"
)
payloadCache:clear()
assert(
    payloadCache:changed(payloadSpriteId, "sprite.aseprite", 1, "base", payloadImage, false),
    "Reconnect must invalidate the texture payload cache"
)
local channelSprite = Sprite(3, 2, ColorMode.RGB)
app.activeSprite = channelSprite
channelSprite.layers[1].name = "Artist Color"
channelSprite.cels[1].image:drawPixel(1, 0, app.pixelColor.rgba(230, 20, 10, 255))
local _root, created = Channels.initialize(channelSprite)
assert(created, "Material channel structure was not created")
assert(Channels.hasStructure(channelSprite), "Material channel metadata is missing")
for _,channel in ipairs({"ao", "roughness", "metallic", "emission"}) do
    assert(
        Channels.previewOpacity(channelSprite, channel) == 96,
        "Material channel is missing its translucent preview opacity: "
            .. channel .. "=" .. tostring(Channels.previewOpacity(channelSprite, channel))
    )
    assert(
        Channels.paintLayer(channelSprite, channel, false).opacity == 96,
        "Channel paint layer is not translucent: " .. channel
    )
    local paintPixel = Channels.paintLayer(channelSprite, channel, false):cel(1).image:getPixel(0, 0)
    local item = Channels.definition(channel)
    assert(app.pixelColor.rgbaA(paintPixel) == 255, "Channel backing must be opaque: " .. channel)
    assert(
        app.pixelColor.rgbaR(paintPixel) == item.default,
        "Channel backing has the wrong default value: " .. channel
    )
end

local base = Channels.renderBaseColor(channelSprite, 1)
local basePixel = base:getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(basePixel) == 230
        and app.pixelColor.rgbaG(basePixel) == 20
        and app.pixelColor.rgbaB(basePixel) == 10,
    "Initializing material channels changed the existing Base Color art"
)
Channels.setBasePreviewOpacity(channelSprite, 96)
assert(
    Channels.group(channelSprite, "base_color").layers[1].opacity == 96,
    "Base Color preview opacity was not applied"
)
local fadedBaseSource = Channels.renderBaseColor(channelSprite, 1):getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(fadedBaseSource) == 230
        and app.pixelColor.rgbaG(fadedBaseSource) == 20
        and app.pixelColor.rgbaB(fadedBaseSource) == 10,
    "Base Color preview opacity changed the texture sent to Blender"
)
Channels.setBasePreviewOpacity(channelSprite, 255)
assert(
    Channels.group(channelSprite, "base_color").layers[1].opacity == 255,
    "Resetting Base Color preview opacity did not restore layer opacity"
)

local defaults = Channels.packORME(channelSprite, 1):getPixel(0, 0)
assert(app.pixelColor.rgbaR(defaults) == 255, "Default AO must be 1.0")
assert(app.pixelColor.rgbaG(defaults) == 128, "Default Roughness must be 128/255")
assert(app.pixelColor.rgbaB(defaults) == 0, "Default Metallic must be 0.0")
assert(app.pixelColor.rgbaA(defaults) == 0, "Default Emission must be 0.0")

local expected = {ao=180, roughness=90, metallic=255, emission=70}
for channel,value in pairs(expected) do
    local paint = Channels.paintLayer(channelSprite, channel, false)
    paint:cel(1).image:drawPixel(2, 1, app.pixelColor.rgba(value, value, value, 255))
end
local packedPixel = Channels.packORME(channelSprite, 1):getPixel(2, 1)
assert(app.pixelColor.rgbaR(packedPixel) == expected.ao, "AO was not packed into R")
assert(app.pixelColor.rgbaG(packedPixel) == expected.roughness, "Roughness was not packed into G")
assert(app.pixelColor.rgbaB(packedPixel) == expected.metallic, "Metallic was not packed into B")
assert(app.pixelColor.rgbaA(packedPixel) == expected.emission, "Emission was not packed into A")

for _,channel in ipairs({"base_color", "ao", "roughness", "metallic", "emission"}) do
    assert(Channels.sendEnabled(channelSprite, channel), "Channel must be sent by default: " .. channel)
end
assert(
    Channels.toggleSendEnabled(channelSprite, "base_color") == false,
    "First channel toggle must disable sending"
)
assert(not Channels.sendEnabled(channelSprite, "base_color"), "Disabled send state was not stored")
Channels.setSendEnabled(channelSprite, "ao", false)
assert(
    not Channels.sendEnabled(channelSprite, "base_color"),
    "Changing a neighboring channel restored disabled Base Color"
)
Channels.setSendEnabled(channelSprite, "ao", true)
Canvas.ensure(
    channelSprite,
    channelSprite.width,
    channelSprite.height,
    math.floor(channelSprite.width / 2),
    math.floor(channelSprite.height / 2)
)
assert(
    not Channels.sendEnabled(channelSprite, "base_color"),
    "A Blender canvas update erased the disabled Base Color flag"
)
local defaultBase = Channels.renderBaseColor(channelSprite, 1):getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(defaultBase) == Channels.baseColorDefault
        and app.pixelColor.rgbaG(defaultBase) == Channels.baseColorDefault
        and app.pixelColor.rgbaB(defaultBase) == Channels.baseColorDefault,
    "Disabled Base Color must send the default gray"
)
assert(
    Channels.toggleSendEnabled(channelSprite, "base_color") == true,
    "Second channel toggle must enable sending"
)
local restoredBase = Channels.renderBaseColor(channelSprite, 1):getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(restoredBase) == 230
        and app.pixelColor.rgbaG(restoredBase) == 20
        and app.pixelColor.rgbaB(restoredBase) == 10,
    "Re-enabled Base Color did not restore the artist texture"
)
Channels.setSendEnabled(channelSprite, "roughness", false)
local channelDefaults = Channels.packORME(channelSprite, 1):getPixel(2, 1)
assert(app.pixelColor.rgbaR(channelDefaults) == expected.ao, "Disabling Roughness changed AO")
assert(app.pixelColor.rgbaG(channelDefaults) == 128, "Disabled Roughness did not send its default")
assert(
    app.pixelColor.rgbaB(channelDefaults) == expected.metallic,
    "Disabling Roughness changed Metallic"
)
assert(
    app.pixelColor.rgbaA(channelDefaults) == expected.emission,
    "Disabling Roughness changed Emission"
)
Channels.setSendEnabled(channelSprite, "roughness", true)
local restoredChannels = Channels.packORME(channelSprite, 1):getPixel(2, 1)
assert(
    app.pixelColor.rgbaG(restoredChannels) == expected.roughness,
    "Re-enabled Roughness did not restore the artist channel"
)

channelSprite:newEmptyFrame()
local heldBasePixel = Channels.renderBaseColor(channelSprite, 2):getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(heldBasePixel) == 230
        and app.pixelColor.rgbaG(heldBasePixel) == 20
        and app.pixelColor.rgbaB(heldBasePixel) == 10,
    "An empty animation frame must hold the previous Base Color cel"
)
local heldPackedPixel = Channels.packORME(channelSprite, 2):getPixel(2, 1)
assert(app.pixelColor.rgbaR(heldPackedPixel) == expected.ao, "Empty frame lost held AO")
assert(
    app.pixelColor.rgbaG(heldPackedPixel) == expected.roughness,
    "Empty frame lost held Roughness"
)
assert(
    app.pixelColor.rgbaB(heldPackedPixel) == expected.metallic,
    "Empty frame lost held Metallic"
)
assert(
    app.pixelColor.rgbaA(heldPackedPixel) == expected.emission,
    "Empty frame lost held Emission"
)

Channels.activate(channelSprite, "roughness", 128)
assert(Channels.group(channelSprite, "base_color").isVisible, "Base Color must stay visible under a channel")
assert(Channels.group(channelSprite, "roughness").isVisible, "Selected channel must be visible")
local overlayComposite = Image(channelSprite.width, channelSprite.height, ColorMode.RGB)
overlayComposite:drawSprite(channelSprite, 1)
local overlayPixel = overlayComposite:getPixel(1, 0)
assert(
    app.pixelColor.rgbaR(overlayPixel) ~= 230
        and app.pixelColor.rgbaR(overlayPixel) ~= 128,
    "The default-filled channel must be a translucent Base Color overlay"
)
local packedAfterPreview = Channels.packORME(channelSprite, 1):getPixel(2, 1)
assert(
    app.pixelColor.rgbaG(packedAfterPreview) == expected.roughness,
    "Preview opacity must not change packed channel values"
)
Channels.setPreviewOpacity(channelSprite, "roughness", 64)
assert(Channels.previewOpacity(channelSprite, "roughness") == 64, "Preview opacity was not updated")
assert(
    Channels.paintLayer(channelSprite, "roughness", false).opacity == 64,
    "Preview opacity was not applied to the paint layer"
)
assert(
    app.pixelColor.rgbaG(Channels.packORME(channelSprite, 1):getPixel(2, 1)) == expected.roughness,
    "Changing preview opacity changed the packed Roughness value"
)

local legacyDefault = channelSprite:newLayer()
legacyDefault.name = "Default 128"
legacyDefault.parent = Channels.group(channelSprite, "roughness")
legacyDefault.properties("lampysprites/pribambase", {
    role="channel-default",
    channel="roughness",
    schema=1
})
local legacyBacking = Channels.paintLayer(channelSprite, "roughness", false)
local legacyImage = Image(channelSprite.width, channelSprite.height, ColorMode.RGB)
legacyImage:clear()
legacyImage:drawPixel(2, 1, app.pixelColor.rgba(expected.roughness, expected.roughness, expected.roughness, 255))
legacyBacking:cel(1).image = legacyImage
channelSprite.properties("lampysprites/pribambase").channelSchema = 3
Channels.initialize(channelSprite)
for _,layer in ipairs(Channels.group(channelSprite, "roughness").layers) do
    assert(
        layer.properties("lampysprites/pribambase").role ~= "channel-default",
        "Legacy Default layers must be removed by migration"
    )
end
local migratedPixel = Channels.paintLayer(channelSprite, "roughness", false):cel(1).image:getPixel(0, 0)
assert(app.pixelColor.rgbaA(migratedPixel) == 255, "Migrated channel backing must be opaque")
assert(app.pixelColor.rgbaG(migratedPixel) == 128, "Migration did not fill Roughness with its default")
local preservedPixel = Channels.paintLayer(channelSprite, "roughness", false):cel(1).image:getPixel(2, 1)
assert(app.pixelColor.rgbaG(preservedPixel) == expected.roughness, "Migration lost painted channel pixels")

local roughnessGroup = Channels.group(channelSprite, "roughness")
roughnessGroup.name = "Artist renamed this group"
assert(
    Channels.group(channelSprite, "roughness") == roughnessGroup,
    "Material channels must be identified by extension properties, not layer names"
)
local preview = Channels.showPacked(channelSprite, 1)
assert(preview.width == channelSprite.width, "ORME preview has the wrong width")
preview:close()

local persistenceSprite = Sprite(2, 2, ColorMode.RGB)
app.activeSprite = persistenceSprite
Channels.initialize(persistenceSprite)
Channels.setSendEnabled(persistenceSprite, "base_color", false)
Channels.setSendEnabled(persistenceSprite, "ao", false)
local persistencePath = result .. ".channel-flags.aseprite"
assert(persistenceSprite:saveAs(persistencePath), "Could not save channel flag persistence test")
persistenceSprite:close()
local reopenedPersistence = Sprite{fromFile=persistencePath}
assert(
    not Channels.sendEnabled(reopenedPersistence, "base_color"),
    "Disabled Base Color did not survive saving and reopening the sprite"
)
assert(
    not Channels.sendEnabled(reopenedPersistence, "ao"),
    "Disabled AO did not survive saving and reopening the sprite"
)
reopenedPersistence:close()

local marker, openError = io.open(result, "w")
if marker == nil then
    error("Could not write smoke-test result: " .. tostring(openError))
end
marker:write("ok\n")
marker:close()

print("Pribambase Aseprite extension smoke test passed")
