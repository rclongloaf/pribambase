-- Shared animation-canvas helpers for the global Blender projection.
local Canvas = {}
local pluginKey = "lampysprites/pribambase"


function Canvas.needsUpdate(sprite, width, height, originX, originY)
    local properties = sprite.properties(pluginKey)
    return sprite.width ~= width
        or sprite.height ~= height
        or properties.originX ~= originX
        or properties.originY ~= originY
        or properties.profile ~= "global_iso_v1"
end


function Canvas.ensure(sprite, width, height, originX, originY)
    local properties = sprite.properties(pluginKey)
    local oldWidth = sprite.width
    local oldHeight = sprite.height
    local oldOriginX = properties.originX
    local oldOriginY = properties.originY

    if oldOriginX == nil then oldOriginX = math.floor(oldWidth / 2) end
    if oldOriginY == nil then oldOriginY = math.floor(oldHeight / 2) end

    if width < oldWidth or height < oldHeight then
        error("Pribambase refuses to shrink the Aseprite canvas automatically")
    end

    local left = originX - oldOriginX
    local bottom = originY - oldOriginY
    local right = width - oldWidth - left
    local top = height - oldHeight - bottom
    if left < 0 or top < 0 or right < 0 or bottom < 0 then
        error("The requested Pribambase canvas would crop existing pixels")
    end

    if width ~= oldWidth or height ~= oldHeight then
        app.activeSprite = sprite
        app.command.CanvasSize{
            ui=false,
            left=left,
            top=top,
            right=right,
            bottom=bottom,
            trimOutside=false
        }
    end

    -- Preserve material-channel flags and any future extension metadata. The
    -- bulk properties(pluginKey, table) setter replaces the complete map.
    if properties.originX ~= originX then properties.originX = originX end
    if properties.originY ~= originY then properties.originY = originY end
    if properties.profile ~= "global_iso_v1" then properties.profile = "global_iso_v1" end
    return width ~= oldWidth or height ~= oldHeight
end


return Canvas
