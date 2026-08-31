-- Typed material-channel groups and deterministic ORME composition.
local Channels = {}

local pluginKey = "lampysprites/pribambase"
local sendKeys = {
    base_color="sendBaseColor",
    ao="sendAO",
    roughness="sendRoughness",
    metallic="sendMetallic",
    emission="sendEmission"
}

Channels.baseColorDefault = 204

Channels.definitions = {
    {
        id="ao",
        name="Ambient Occlusion",
        default=255,
        previewOpacity=96,
        presets={
            {name="Full", value=255},
            {name="Soft", value=192},
            {name="Half", value=128},
            {name="Dark", value=64}
        }
    },
    {
        id="roughness",
        name="Roughness",
        default=128,
        previewOpacity=96,
        presets={
            {name="Polished", value=38},
            {name="Glossy", value=89},
            {name="Matte", value=166},
            {name="Rough", value=230}
        }
    },
    {
        id="metallic",
        name="Metallic",
        default=0,
        previewOpacity=96,
        presets={
            {name="Non-metal", value=0},
            {name="Metal", value=255}
        }
    },
    {
        id="emission",
        name="Emission",
        default=0,
        previewOpacity=96,
        presets={
            {name="Off", value=0},
            {name="Low", value=64},
            {name="Medium", value=128},
            {name="Full", value=255}
        }
    }
}

local function properties(object)
    return object.properties(pluginKey)
end


local function tag(object, role, channel)
    local values = {role=role, schema=1}
    if channel ~= nil then values.channel = channel end
    object.properties(pluginKey, values)
end


local function matches(layer, role, channel)
    local values = properties(layer)
    return values.role == role and (channel == nil or values.channel == channel)
end


local function visit(layers, callback)
    for _,layer in ipairs(layers) do
        if callback(layer) then return layer end
        if layer.isGroup then
            local found = visit(layer.layers, callback)
            if found ~= nil then return found end
        end
    end
    return nil
end


local function find(sprite, role, channel)
    return visit(sprite.layers, function(layer)
        return matches(layer, role, channel)
    end)
end


local function definition(channel)
    for _,item in ipairs(Channels.definitions) do
        if item.id == channel or item.name == channel then return item end
    end
    return nil
end


local function createGroup(sprite, parent, name, role, channel)
    local group = sprite:newGroup()
    group.name = name
    group.parent = parent
    group.isExpanded = true
    tag(group, role, channel)
    return group
end


local function createLayer(sprite, parent, name, role, channel)
    local layer = sprite:newLayer()
    layer.name = name
    layer.parent = parent
    tag(layer, role, channel)
    return layer
end


local function channelPreviewOpacity(sprite, channel)
    local item = definition(channel)
    local group = item and find(sprite, "channel", item.id) or nil
    local stored = group and tonumber(properties(group).previewOpacity) or nil
    return math.max(0, math.min(255, math.floor(stored or (item and item.previewOpacity) or 96)))
end


local function setChannelPreviewOpacity(sprite, channel, value)
    local item = assert(definition(channel), "Unknown Pribambase channel: " .. tostring(channel))
    local group = find(sprite, "channel", item.id)
    if group == nil then return end
    value = math.max(0, math.min(255, math.floor(value)))
    properties(group).previewOpacity = value
    visit(group.layers, function(layer)
        if layer.isImage then layer.opacity = value end
        return false
    end)
end


local function backingPaintLayer(sprite, channel, createMissing)
    local item = assert(definition(channel), "Unknown Pribambase channel: " .. tostring(channel))
    local group = find(sprite, "channel", item.id)
    if group == nil then return nil end
    local fallback = nil
    for _,layer in ipairs(group.layers) do
        if matches(layer, "channel-paint", item.id) then
            if properties(layer).backing then return layer end
            if fallback == nil then fallback = layer end
        end
    end
    local layer = fallback
    if layer == nil and createMissing then
        layer = createLayer(sprite, group, "Paint", "channel-paint", item.id)
    end
    if layer ~= nil then
        properties(layer).backing = true
        layer.opacity = channelPreviewOpacity(sprite, item.id)
    end
    return layer
end


local function fillPaintDefaults(sprite, channel, everyFrame)
    local item = assert(definition(channel), "Unknown Pribambase channel: " .. tostring(channel))
    local layer = backingPaintLayer(sprite, item.id, true)
    local first = everyFrame and 1 or app.activeFrame.frameNumber
    local last = everyFrame and #sprite.frames or first
    for frame=first,last do
        local image = Image(sprite.width, sprite.height, ColorMode.RGB)
        image:clear(app.pixelColor.rgba(item.default, item.default, item.default, 255))
        local cel = layer:cel(frame)
        if cel == nil then
            sprite:newCel(layer, frame, image, Point(0, 0))
        else
            image:drawImage(cel.image, cel.position)
            cel.image = image
            cel.position = Point(0, 0)
        end
    end
    return layer
end


local function removeDefaultLayers(sprite)
    for _,item in ipairs(Channels.definitions) do
        while true do
            local layer = find(sprite, "channel-default", item.id)
            if layer == nil then break end
            sprite:deleteLayer(layer)
        end
    end
end


function Channels.definition(channel)
    return definition(channel)
end


function Channels.previewOpacity(sprite, channel)
    return channelPreviewOpacity(sprite, channel)
end


function Channels.setPreviewOpacity(sprite, channel, value)
    setChannelPreviewOpacity(sprite, channel, value)
end


function Channels.ensurePaintDefaults(sprite, everyFrame)
    if not Channels.hasStructure(sprite) then return end
    for _,item in ipairs(Channels.definitions) do
        fillPaintDefaults(sprite, item.id, everyFrame)
    end
end


function Channels.hasStructure(sprite)
    return sprite ~= nil and find(sprite, "channels-root") ~= nil
end


function Channels.needsMigration(sprite)
    if not Channels.hasStructure(sprite) then return false end
    return (tonumber(properties(sprite).channelSchema) or 1) < 5
end


function Channels.group(sprite, channel)
    if channel == "base_color" then return find(sprite, "base-color") end
    if channel == "normal" then return find(sprite, "world-normal") end
    return find(sprite, "channel", channel)
end


function Channels.basePreviewOpacity(sprite)
    local group = Channels.group(sprite, "base_color")
    local stored = group and tonumber(properties(group).basePreviewOpacity) or nil
    return math.max(0, math.min(255, math.floor(stored or 255)))
end


function Channels.setBasePreviewOpacity(sprite, value)
    local group = Channels.group(sprite, "base_color")
    if group == nil then return end
    value = math.max(0, math.min(255, math.floor(value)))
    visit(group.layers, function(layer)
        if layer.isImage then
            local values = properties(layer)
            local sourceOpacity = tonumber(values.baseSourceOpacity)
            if sourceOpacity == nil then
                sourceOpacity = layer.opacity or 255
                values.baseSourceOpacity = sourceOpacity
            end
            layer.opacity = math.floor(sourceOpacity * value / 255 + 0.5)
            if value == 255 then values.baseSourceOpacity = nil end
        end
        return false
    end)
    properties(group).basePreviewOpacity = value
end


function Channels.sendEnabled(sprite, channel)
    local key = sendKeys[channel]
    if sprite == nil or key == nil then return false end
    local value = properties(sprite)[key]
    return value ~= false and value ~= 0
end


function Channels.setSendEnabled(sprite, channel, enabled)
    local key = assert(sendKeys[channel], "Unknown Pribambase send channel: " .. tostring(channel))
    -- Aseprite extension properties persist numeric values reliably, while a
    -- false boolean can disappear after the current UI event and become nil.
    properties(sprite)[key] = enabled == true and 1 or 0
end


function Channels.toggleSendEnabled(sprite, channel)
    local enabled = not Channels.sendEnabled(sprite, channel)
    Channels.setSendEnabled(sprite, channel, enabled)
    return enabled
end


function Channels.initialize(sprite)
    if sprite == nil then error("Open a sprite before initializing material channels") end
    if sprite.colorMode ~= ColorMode.RGB then
        error("Pribambase material channels currently require an RGB sprite")
    end

    local root = find(sprite, "channels-root")
    if root ~= nil then
        local spriteProperties = properties(sprite)
        local schema = tonumber(spriteProperties.channelSchema) or 1
        if schema < 3 then
            for _,item in ipairs(Channels.definitions) do
                setChannelPreviewOpacity(sprite, item.id, item.previewOpacity)
            end
            local normal = find(sprite, "world-normal")
            local generated = normal and find(sprite, "normal-generated", "normal") or nil
            if generated ~= nil then generated.opacity = 96 end
        end
        if schema < 5 then
            Channels.ensurePaintDefaults(sprite, true)
            removeDefaultLayers(sprite)
        end
        if spriteProperties.channelSchema ~= 5 then spriteProperties.channelSchema = 5 end
        return root, false
    end

    local existing = {}
    for _,layer in ipairs(sprite.layers) do
        if not layer.isReference then table.insert(existing, layer) end
    end

    root = createGroup(sprite, sprite, "Pribambase", "channels-root")
    root.color = Color{r=92, g=154, b=255, a=255}
    local base = createGroup(sprite, root, "Base Color", "base-color")
    base.color = Color{r=92, g=190, b=120, a=255}
    for _,layer in ipairs(existing) do layer.parent = base end

    local material = createGroup(sprite, root, "Material Channels", "material-root")
    material.color = Color{r=255, g=174, b=72, a=255}
    for _,item in ipairs(Channels.definitions) do
        local group = createGroup(sprite, material, item.name, "channel", item.id)
        group.color = Color{r=item.default, g=item.default, b=item.default, a=255}
        local paint = createLayer(sprite, group, "Paint", "channel-paint", item.id)
        paint.opacity = item.previewOpacity
        properties(paint).backing = true
        properties(group).previewOpacity = item.previewOpacity
    end

    local normal = createGroup(sprite, root, "World Normal", "world-normal")
    normal.color = Color{r=128, g=160, b=255, a=255}
    local generated = createLayer(sprite, normal, "Generated from Blender", "normal-generated", "normal")
    generated.isEditable = false
    generated.opacity = 96

    Channels.ensurePaintDefaults(sprite, true)
    properties(sprite).channelSchema = 5
    return root, true
end


function Channels.paintLayer(sprite, channel, createNew)
    local group = Channels.group(sprite, channel)
    if group == nil then return nil end
    if not createNew then
        return backingPaintLayer(sprite, channel, true)
    end
    local count = 0
    for _,layer in ipairs(group.layers) do
        if matches(layer, "channel-paint", channel) then count = count + 1 end
    end
    local name = count == 0 and "Paint" or "Paint " .. tostring(count + 1)
    local layer = createLayer(sprite, group, name, "channel-paint", channel)
    layer.opacity = channelPreviewOpacity(sprite, channel)
    return layer
end


local function drawLayer(destination, layer, frame, ignoreOwnVisibility, useSourceOpacity)
    if not ignoreOwnVisibility and not layer.isVisible then return end
    if layer.isGroup then
        for _,child in ipairs(layer.layers) do
            drawLayer(destination, child, frame, false, useSourceOpacity)
        end
        return
    end
    if not layer.isImage then return end
    local cel = layer:cel(frame)
    if cel == nil then
        local heldFrame = -1
        for _,candidate in ipairs(layer.cels) do
            local candidateFrame = candidate.frame.frameNumber
            if candidateFrame <= frame and candidateFrame > heldFrame then
                cel = candidate
                heldFrame = candidateFrame
            end
        end
    end
    if cel == nil then return end
    local values = properties(layer)
    local previewOnly = values.role == "channel-paint"
    local sourceOpacity = useSourceOpacity and tonumber(values.baseSourceOpacity) or nil
    local layerOpacity = previewOnly and 255 or sourceOpacity or (layer.opacity or 255)
    local opacity = math.floor(layerOpacity * (cel.opacity or 255) / 255)
    destination:drawImage(cel.image, cel.position, opacity, layer.blendMode)
end


local function renderGroup(sprite, group, frame, defaultValue, useSourceOpacity)
    local result = Image(sprite.width, sprite.height, ColorMode.RGB)
    if defaultValue == nil then
        result:clear()
    else
        result:clear(app.pixelColor.rgba(defaultValue, defaultValue, defaultValue, 255))
    end
    if group ~= nil then drawLayer(result, group, frame, true, useSourceOpacity) end
    return result
end


function Channels.renderBaseColor(sprite, frame)
    if not Channels.sendEnabled(sprite, "base_color") then
        local result = Image(sprite.width, sprite.height, ColorMode.RGB)
        local value = Channels.baseColorDefault
        result:clear(app.pixelColor.rgba(value, value, value, 255))
        return result
    end
    local group = Channels.group(sprite, "base_color")
    if group == nil then
        local result = Image(sprite.width, sprite.height, ColorMode.RGB)
        result:drawSprite(sprite, frame)
        return result
    end
    return renderGroup(sprite, group, frame, nil, true)
end


local function grayscale(pixel)
    local red = app.pixelColor.rgbaR(pixel)
    local green = app.pixelColor.rgbaG(pixel)
    local blue = app.pixelColor.rgbaB(pixel)
    return math.floor(red * 0.2126 + green * 0.7152 + blue * 0.0722 + 0.5)
end


function Channels.renderChannel(sprite, channel, frame)
    local item = assert(definition(channel), "Unknown Pribambase channel: " .. tostring(channel))
    if not Channels.sendEnabled(sprite, item.id) then
        return renderGroup(sprite, nil, frame, item.default)
    end
    return renderGroup(sprite, Channels.group(sprite, item.id), frame, item.default)
end


function Channels.packORME(sprite, frame)
    if not Channels.hasStructure(sprite) then return nil end
    local ao = Channels.renderChannel(sprite, "ao", frame)
    local roughness = Channels.renderChannel(sprite, "roughness", frame)
    local metallic = Channels.renderChannel(sprite, "metallic", frame)
    local emission = Channels.renderChannel(sprite, "emission", frame)
    local result = Image(sprite.width, sprite.height, ColorMode.RGB)

    for y=0,sprite.height-1 do
        for x=0,sprite.width-1 do
            result:drawPixel(x, y, app.pixelColor.rgba(
                grayscale(ao:getPixel(x, y)),
                grayscale(roughness:getPixel(x, y)),
                grayscale(metallic:getPixel(x, y)),
                grayscale(emission:getPixel(x, y))
            ))
        end
    end
    return result
end


function Channels.activate(sprite, channel, value)
    Channels.initialize(sprite)
    local root = find(sprite, "channels-root")
    local base = find(sprite, "base-color")
    local material = find(sprite, "material-root")
    local normal = find(sprite, "world-normal")
    local scalar = definition(channel)

    root.isVisible = true
    -- Scalar channels are translucent editing overlays. Base Color stays
    -- visible for context; group opacity is intentionally ignored by the
    -- deterministic channel compositor below.
    material.isVisible = scalar ~= nil
    normal.isVisible = channel == "normal"
    for _,item in ipairs(Channels.definitions) do
        Channels.group(sprite, item.id).isVisible = scalar ~= nil and item.id == scalar.id
    end

    if scalar ~= nil then
        app.activeLayer = Channels.paintLayer(sprite, scalar.id, false)
        local gray = math.max(0, math.min(255, math.floor(value or scalar.default)))
        app.fgColor = Color{r=gray, g=gray, b=gray, a=255}
    elseif channel == "base_color" and #base.layers > 0 then
        app.activeLayer = base.layers[#base.layers]
    elseif channel == "normal" then
        app.activeLayer = find(sprite, "normal-generated", "normal")
    end
    app.refresh()
end


function Channels.showPacked(sprite, frame)
    local packed = Channels.packORME(sprite, frame)
    if packed == nil then error("Initialize material channels first") end
    local preview = Sprite(sprite.width, sprite.height, ColorMode.RGB)
    preview.filename = ""
    preview.layers[1].name = "Generated ORME — do not edit"
    preview.cels[1].image = packed
    preview.properties(pluginKey, {role="orme-preview", source=sprite.filename})
    app.activeSprite = preview
    return preview
end


return Channels
