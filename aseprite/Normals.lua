-- Artist normal layers over a locked, frame-exact polygon-normal reference.
local N = {}
local key = "lampysprites/pribambase"
local DEFAULT_ROLES = {FLAT="geometry-normal-flat", SMOOTH="geometry-normal-smooth"}

local function visit(layers, predicate)
    for _,layer in ipairs(layers) do
        if predicate(layer) then return layer end
        if layer.isGroup then
            local found = visit(layer.layers, predicate)
            if found then return found end
        end
    end
end

function N.group(sprite)
    if sprite == nil then return nil end
    return visit(sprite.layers, function(layer)
        local p = layer.properties(key)
        return p.role == "channel" and p.channel == "normal"
    end)
end

function N.defaultLayer(sprite, mode)
    if sprite == nil then return nil end
    return visit(sprite.layers, function(layer)
        return layer.isReference and layer.properties(key).role == DEFAULT_ROLES[mode or "FLAT"]
    end)
end

function N.paintLayer(sprite, createNew)
    local group = N.group(sprite)
    if group == nil then return nil end
    if not createNew then
        local existing = visit(group.layers, function(layer) return layer.isImage and not layer.isReference end)
        if existing then return existing end
    end
    local layer = sprite:newLayer()
    layer.name = #group.layers == 0 and "Paint" or "Paint " .. tostring(#group.layers+1)
    layer.parent = group
    layer.properties(key, {role="normal-paint", channel="normal", schema=1})
    return layer
end

function N.ensure(sprite, root)
    local group = N.group(sprite)
    if group == nil then
        group = sprite:newGroup()
        group.name = "World Normal"
        group.parent = root
        group.isVisible = false
        group.properties(key, {role="channel", channel="normal", schema=1})
        group.color = Color{r=128, g=128, b=255}
    end
    N.paintLayer(sprite, false)
    return group
end

-- Legacy Blender-authored normals are deliberately not copied into artist layers.
function N.migrate(sprite)
    local remove = {}
    visit(sprite.layers, function(layer)
        local role = layer.properties(key).role
        if role == "world-normal" or role == "world-normal-generated"
            or (layer.isReference and (layer.name == "Pribambase World Normal"
                or layer.name == "Pribambase World Normal (Generated)")) then
            remove[#remove+1] = layer
        end
        return false
    end)
    for _,layer in ipairs(remove) do sprite:deleteLayer(layer) end
end

function N.defaultImage(sprite, frame, mode)
    local layer = N.defaultLayer(sprite, mode)
    local cel = layer and layer:cel(frame) or nil
    if cel == nil then return nil end
    local image = Image(sprite.width, sprite.height, ColorMode.RGB)
    image:clear()
    image:drawImage(cel.image, cel.position)
    return image
end

local function paint(destination, layer, frame, originX, originY)
    originX, originY = originX or 0, originY or 0
    if not layer.isVisible then return end
    if layer.isGroup then
        -- Composite the group separately to honor its opacity/blending.
        local groupImage = Image(destination.width, destination.height, ColorMode.RGB)
        groupImage:clear()
        for _,child in ipairs(layer.layers) do paint(groupImage, child, frame, originX, originY) end
        destination:drawImage(groupImage, Point(0, 0), layer.opacity, layer.blendMode)
    elseif layer.isImage and not layer.isReference then
        local cel = layer:cel(frame)
        if cel then destination:drawImage(cel.image, Point(cel.position.x-originX, cel.position.y-originY),
            math.floor(layer.opacity*cel.opacity/255), layer.blendMode) end
    end
end

function N.render(sprite, frame, defaultOnly)
    local result = N.defaultImage(sprite, frame)
    local group = N.group(sprite)
    if result == nil then
        result = Image(sprite.width, sprite.height, ColorMode.RGB)
        result:clear()
    end
    if not defaultOnly and group then
        -- The group's visibility is a preview switch, never a send switch.
        for _,layer in ipairs(group.layers) do paint(result, layer, frame) end
    end
    return result
end

function N.inspect(sprite, frame, x, y)
    if sprite == nil or x < 0 or y < 0 or x >= sprite.width or y >= sprite.height then return nil end
    local function referencePixel(mode)
        local layer = N.defaultLayer(sprite, mode)
        local cel = layer and layer:cel(frame) or nil
        if not cel then return nil end
        local px, py = x-cel.position.x, y-cel.position.y
        if px < 0 or py < 0 or px >= cel.image.width or py >= cel.image.height then return nil end
        return cel.image:getPixel(px, py)
    end
    local flat, smooth = referencePixel("FLAT"), referencePixel("SMOOTH")
    local result = Image(1,1,ColorMode.RGB)
    result:clear(flat or 0)
    local group = N.group(sprite)
    if group then
        for _,layer in ipairs(group.layers) do paint(result, layer, frame, x, y) end
    end
    return {painted=result:getPixel(0,0), default=flat, smooth=smooth}
end

function N.showDefault(sprite, selected, mode)
    local group = N.group(sprite)
    if group then group.isVisible = not selected end
    for _,basis in ipairs({"FLAT", "SMOOTH"}) do
        local reference = N.defaultLayer(sprite, basis)
        if reference then reference.isVisible = basis == (selected and (mode or "FLAT") or "FLAT") end
    end
    app.refresh()
end

function N.receiveDefault(sprite, frame, image, mode)
    mode = mode or "FLAT"
    assert(DEFAULT_ROLES[mode], "Unknown geometry normal reference")
    assert(sprite.colorMode == ColorMode.RGB, "Geometry Normal requires an RGB sprite")
    assert(image.width == sprite.width and image.height == sprite.height,
        "Geometry Normal must match the shared canvas")
    local activeSprite, activeLayer, activeFrame = app.activeSprite, app.activeLayer, app.activeFrame
    local reference = N.defaultLayer(sprite, mode)
    local cel = reference and reference:cel(frame) or nil
    local matches = cel and cel.image.width == image.width and cel.image.height == image.height
        and cel.position.x == 0 and cel.position.y == 0
    if not reference or not matches or frame > #sprite.frames then
        app.transaction("Prepare Geometry Normal reference", function()
            app.activeSprite = sprite
            while #sprite.frames < frame do sprite:newEmptyFrame() end
            if reference == nil then
                app.command.NewLayer{reference=true}
                reference = app.activeLayer
                reference.name = "Pribambase Geometry Normal (" .. (mode == "SMOOTH" and "Smooth" or "Flat") .. ")"
                reference.properties(key, {role=DEFAULT_ROLES[mode], schema=1})
                reference.isVisible = mode == "FLAT" and N.group(sprite) ~= nil and N.group(sprite).isVisible
                reference.stackIndex = 1
            end
            reference.isEditable = false
            cel = reference:cel(frame)
            if cel == nil then
                cel = sprite:newCel(reference, frame, image, Point(0, 0))
            elseif not matches then
                cel.image = image
                cel.position = Point(0, 0)
            end
            app.activeSprite = activeSprite
            if activeFrame then app.activeFrame = activeFrame end
            if activeLayer then app.activeLayer = activeLayer end
        end)
    end
    -- External refreshes do not overwrite artist paint or add repeated undo steps.
    cel.image.bytes = image.bytes
    reference.isEditable = false
    return reference
end

return N
