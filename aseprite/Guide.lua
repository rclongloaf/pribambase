-- Reference-cel helpers shared by live sync and smoke tests.
local Guide = {}
local pluginKey = "lampysprites/pribambase"


function Guide.markRenderLayer(layer)
    if layer == nil or not layer.isReference then return false end
    local values = layer.properties(pluginKey)
    if values.role == "render-guide" and values.schema == 1 then return false end
    values.role = "render-guide"
    values.schema = 1
    return true
end


function Guide.placeAtBottom(layer)
    if layer ~= nil and layer.stackIndex ~= 1 then
        layer.stackIndex = 1
        return true
    end
    return false
end


function Guide.isRenderLayer(layer)
    return layer ~= nil
        and layer.isReference
        and layer.properties(pluginKey).role == "render-guide"
end


function Guide.findRenderLayer(sprite)
    if sprite == nil then return nil end

    local onlyReference = nil
    local referenceCount = 0
    for _,layer in ipairs(sprite.layers) do
        if layer.isReference then
            referenceCount = referenceCount + 1
            onlyReference = layer
            if layer.properties(pluginKey).role == "render-guide" then
                Guide.placeAtBottom(layer)
                return layer
            end
        end
    end

    for _,layer in ipairs(sprite.layers) do
        if layer.isReference and (
            layer.name == "Pribambase Render"
            or string.match(layer.name, "^Pribambase Render %(Guide%)") ~= nil
        ) then
            Guide.markRenderLayer(layer)
            Guide.placeAtBottom(layer)
            return layer
        end
    end

    if referenceCount == 1 then
        Guide.markRenderLayer(onlyReference)
        Guide.placeAtBottom(onlyReference)
        return onlyReference
    end
    return nil
end


function Guide.ensureCel(sprite, layer, frame, image)
    local existing = layer:cel(frame)
    if existing ~= nil then return existing, false end
    return sprite:newCel(layer, frame, image, Point(0, 0)), true
end


function Guide.imageMatches(cel, image)
    if cel == nil or image == nil then return false end
    local current = cel.image
    return current.width == image.width
        and current.height == image.height
        and current.colorMode == image.colorMode
end


function Guide.updateCelPixels(cel, image)
    if not Guide.imageMatches(cel, image) then
        error("Render guide image layout does not match its cel")
    end
    -- Image.bytes mutates the existing image without creating undo data. This
    -- keeps an externally refreshed render guide out of the artist's history.
    cel.image.bytes = image.bytes
end


return Guide
