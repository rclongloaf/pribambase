local source = app.params["sprite"]
local channelsPath = app.params["channels"]
if source == nil or channelsPath == nil then
    error("Expected sprite and channels script parameters")
end

local Channels = dofile(channelsPath)
local sprite = Sprite{fromFile=source}
app.activeSprite = sprite
assert(Channels.hasStructure(sprite), "Sample is missing typed material channel groups")
assert(Channels.group(sprite, "base_color") ~= nil, "Sample is missing Base Color")
for _,channel in ipairs({"ao", "roughness", "metallic", "emission"}) do
    assert(Channels.group(sprite, channel) ~= nil, "Sample is missing channel: " .. channel)
    assert(Channels.previewOpacity(sprite, channel) == 96, "Sample preview opacity is invalid: " .. channel)
    assert(
        Channels.paintLayer(sprite, channel, false).opacity == 96,
        "Sample paint layer is not translucent: " .. channel
    )
    local pixel = Channels.paintLayer(sprite, channel, false):cel(1).image:getPixel(0, 0)
    assert(app.pixelColor.rgbaA(pixel) == 255, "Sample channel backing is transparent: " .. channel)
    assert(
        app.pixelColor.rgbaR(pixel) == Channels.definition(channel).default,
        "Sample channel backing has the wrong default: " .. channel
    )
end
local packed = Channels.packORME(sprite, 1)
local pixel = packed:getPixel(0, 0)
assert(app.pixelColor.rgbaR(pixel) == 255, "Sample AO default is invalid")
assert(app.pixelColor.rgbaG(pixel) == 128, "Sample Roughness default is invalid")
assert(app.pixelColor.rgbaB(pixel) == 0, "Sample Metallic default is invalid")
assert(app.pixelColor.rgbaA(pixel) == 0, "Sample Emission default is invalid")
print("Pribambase Aseprite sample validation passed")
sprite:close()
