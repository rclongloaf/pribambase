local source = app.params["source"]
local output = app.params["output"]
local channelsPath = app.params["channels"]
if source == nil or output == nil or channelsPath == nil then
    error("Expected source, output, and channels script parameters")
end

local Channels = dofile(channelsPath)
local sprite = Sprite{fromFile=source}
app.activeSprite = sprite
Channels.initialize(sprite)
sprite:saveAs(output)
sprite:close()

print("Generated Pribambase Aseprite sample: " .. output)
