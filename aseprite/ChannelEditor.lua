-- Material-channel editor for artist-friendly grayscale source layers.
local Channels = dofile(app.fs.joinPath(
    app.fs.userConfigPath,
    "extensions",
    "pribambase",
    "Channels.lua"
))
local Guide = dofile(app.fs.joinPath(
    app.fs.userConfigPath,
    "extensions",
    "pribambase",
    "Guide.lua"
))
if pribambase_channels_dlg then
    pribambase_channels_dlg:show{wait=false}
    return
end

local labels = {"Base Color", "Ambient Occlusion", "Roughness", "Metallic", "Emission", "World Normal"}
local ids = {
    ["Base Color"]="base_color",
    ["Ambient Occlusion"]="ao",
    ["Roughness"]="roughness",
    ["Metallic"]="metallic",
    ["Emission"]="emission",
    ["World Normal"]="normal"
}
local settings = pribambase_settings
local initialChannel = settings and settings.channelEditorChannel or "Base Color"
if ids[initialChannel] == nil then initialChannel = "Base Color" end
local initialTab = settings and settings.channelEditorTab or "paint_tab"
if initialTab ~= "paint_tab" and initialTab ~= "view_tab" and initialTab ~= "actions_tab" then
    initialTab = "paint_tab"
end
local dlg
local updatingOverlay = false
local updatingVisibility = false
local updatingSend = false
local updatingBaseOpacity = false
local onSiteChange
local siteChangeRegistered = false
local controlsSpriteId


local function saveDialogState()
    if settings ~= nil and dlg ~= nil then
        local bounds = dlg.bounds
        settings.channelEditorX = bounds.x
        settings.channelEditorY = bounds.y
        settings.channelEditorWidth = bounds.width
        settings.channelEditorHeight = bounds.height
        settings.channelEditorChannel = dlg.data.channel or initialChannel
        settings.channelEditorTab = dlg.data.channel_tabs or initialTab
    end
    if siteChangeRegistered and onSiteChange ~= nil then
        app.events:off(onSiteChange)
        siteChangeRegistered = false
    end
    pribambase_channels_dlg = nil
end


dlg = Dialog{
    title="Pribambase Channels",
    resizeable=false,
    onclose=saveDialogState
}

local function currentSprite()
    local sprite = app.activeSprite
    if sprite == nil then error("Open an Aseprite sprite first") end
    return sprite
end


local function notifySync(allFrames, sprite)
    if pribambase_channel_refresh then
        pribambase_channel_refresh(allFrames == true, sprite or app.activeSprite)
    end
end


local function mutate(label, callback, refresh)
    pribambase_channel_mutating = true
    local ok, message = pcall(function()
        app.transaction(label, callback)
    end)
    pribambase_channel_mutating = false
    if not ok then
        app.alert{title="Pribambase", text=tostring(message)}
        return false
    end
    app.refresh()
    if refresh then notifySync(false) end
    return true
end


local function selectedId()
    return ids[dlg.data.channel] or "base_color"
end


local function setBrushValue(value)
    value = math.max(0, math.min(255, math.floor(value)))
    dlg:modify{id="value", value=value}
    dlg:modify{id="value_label", text=string.format("%.3f · %d", value / 255, value)}
    app.fgColor = Color{r=value, g=value, b=value, a=255}
end


local function updateOverlayControls()
    local item = Channels.definition(selectedId())
    local sprite = app.activeSprite
    local opacity = item and sprite and Channels.previewOpacity(sprite, item.id)
        or (item and item.previewOpacity or 96)
    updatingOverlay = true
    dlg:modify{id="overlay", value=opacity, enabled=item ~= nil}
    dlg:modify{
        id="overlay_label",
        text=string.format("%d%% · preview only", math.floor(opacity * 100 / 255 + 0.5))
    }
    dlg:modify{id="overlay_default", enabled=item ~= nil}
    updatingOverlay = false
end


local function updateVisibilityControls()
    if dlg == nil then return end
    local sprite = app.activeSprite
    local base = sprite and Channels.group(sprite, "base_color") or nil
    local guide = Guide.findRenderLayer(sprite)
    updatingVisibility = true
    dlg:modify{
        id="base_visible",
        selected=base ~= nil and base.isVisible,
        enabled=base ~= nil
    }
    dlg:modify{
        id="guide_visible",
        selected=guide ~= nil and guide.isVisible,
        enabled=guide ~= nil
    }
    updatingVisibility = false
end


local function setBaseVisibility()
    if updatingVisibility then return end
    local sprite = app.activeSprite
    local base = sprite and Channels.group(sprite, "base_color") or nil
    if base ~= nil then base.isVisible = dlg.data.base_visible end
    app.refresh()
    updateVisibilityControls()
end


local function setGuideVisibility()
    if updatingVisibility then return end
    local guide = Guide.findRenderLayer(app.activeSprite)
    if guide ~= nil then guide.isVisible = dlg.data.guide_visible end
    app.refresh()
    updateVisibilityControls()
end


local function updateBaseOpacityControls()
    if dlg == nil or updatingBaseOpacity then return end
    local sprite = app.activeSprite
    local base = sprite and Channels.group(sprite, "base_color") or nil
    local opacity = base and Channels.basePreviewOpacity(sprite) or 255
    dlg:modify{id="base_opacity", value=opacity, enabled=base ~= nil}
    dlg:modify{
        id="base_opacity_label",
        text=string.format("%d%% · preview only", math.floor(opacity * 100 / 255 + 0.5))
    }
    dlg:modify{id="base_opacity_default", enabled=base ~= nil}
end


local function setBaseOpacity(value)
    if updatingBaseOpacity then return end
    local sprite = app.activeSprite
    if sprite == nil or Channels.group(sprite, "base_color") == nil then return end
    updatingBaseOpacity = true
    pribambase_channel_mutating = true
    local ok, message = pcall(function()
        app.transaction("Change Base Color preview opacity", function()
            Channels.setBasePreviewOpacity(sprite, value)
        end)
    end)
    pribambase_channel_mutating = false
    updatingBaseOpacity = false
    if not ok then
        app.alert{title="Pribambase", text=tostring(message)}
        return
    end
    app.refresh()
    updateBaseOpacityControls()
end


local sendControls = {
    {id="send_base_color", channel="base_color"},
    {id="send_ao", channel="ao"},
    {id="send_roughness", channel="roughness"},
    {id="send_metallic", channel="metallic"},
    {id="send_emission", channel="emission"}
}


local function updateSendControls()
    if dlg == nil then return end
    local sprite = app.activeSprite
    controlsSpriteId = sprite and sprite.id or nil
    local enabled = sprite ~= nil and Channels.hasStructure(sprite)
    updatingSend = true
    for _,control in ipairs(sendControls) do
        dlg:modify{
            id=control.id,
            selected=enabled and Channels.sendEnabled(sprite, control.channel) or true,
            enabled=enabled
        }
    end
    updatingSend = false
end


local function setSendEnabled(controlId, channel)
    if updatingSend or dlg == nil then return end
    local sprite = app.activeSprite
    if sprite == nil or not Channels.hasStructure(sprite) then return end
    if sprite.id ~= controlsSpriteId then
        updateSendControls()
        return
    end
    local selected = dlg.data[controlId] == true
    local before = Channels.sendEnabled(sprite, channel)
    if selected == before then return end
    local changed, message = pcall(function()
        Channels.setSendEnabled(sprite, channel, selected)
    end)
    if not changed then
        app.alert{title="Pribambase", text=tostring(message)}
        updateSendControls()
        return
    end
    app.refresh()
    if changed then notifySync(false, sprite) end
end


local function setOverlayOpacity(value)
    if updatingOverlay then return end
    local item = Channels.definition(selectedId())
    if item == nil then return end
    value = math.max(0, math.min(255, math.floor(value)))
    mutate("Change channel preview opacity", function()
        Channels.setPreviewOpacity(currentSprite(), item.id, value)
    end, false)
    updateOverlayControls()
end


local function updatePresets()
    local item = Channels.definition(selectedId())
    for index=1,4 do
        local preset = item and item.presets[index] or nil
        dlg:modify{
            id="preset" .. tostring(index),
            text=preset and preset.name or "—",
            enabled=preset ~= nil
        }
    end
    if item ~= nil then setBrushValue(item.default) end
    updateOverlayControls()
    updateVisibilityControls()
    updateBaseOpacityControls()
    updateSendControls()
end


local function activate()
    if settings ~= nil then settings.channelEditorChannel = dlg.data.channel end
    mutate("Select Pribambase channel", function()
        Channels.activate(currentSprite(), selectedId(), dlg.data.value)
    end, false)
    updatePresets()
end


local function initialize()
    mutate("Initialize Pribambase channels", function()
        Channels.initialize(currentSprite())
        Channels.activate(currentSprite(), selectedId(), dlg.data.value)
    end, true)
    updatePresets()
end


local function addPaintLayer()
    local channel = selectedId()
    if Channels.definition(channel) == nil then
        app.alert{title="Pribambase", text="Paint layers are available for scalar material channels."}
        return
    end
    mutate("Add Pribambase paint layer", function()
        Channels.initialize(currentSprite())
        app.activeLayer = Channels.paintLayer(currentSprite(), channel, true)
    end, false)
end


local function usePreset(index)
    local item = Channels.definition(selectedId())
    local preset = item and item.presets[index] or nil
    if preset ~= nil then setBrushValue(preset.value) end
end


dlg:combobox{id="channel", label="Channel", options=labels, option=initialChannel, onchange=activate}

dlg:tab{id="paint_tab", text="Paint"}
dlg:slider{
    id="value",
    label="Brush value",
    min=0,
    max=255,
    value=128,
    onchange=function() setBrushValue(dlg.data.value) end
}
dlg:label{id="value_label", label="Value", text="0.502 · 128"}
dlg:newrow()
for index=1,4 do
    local presetIndex = index
    dlg:button{
        id="preset" .. tostring(index),
        text="—",
        onclick=function() usePreset(presetIndex) end
    }
end
dlg:newrow()
dlg:button{id="add_layer", text="Add Paint Layer", onclick=addPaintLayer}

dlg:tab{id="view_tab", text="View"}
dlg:separator{text="Layer Visibility"}
dlg:check{id="base_visible", label="Base Color", selected=true, onclick=setBaseVisibility}
dlg:slider{
    id="base_opacity",
    label="Base opacity",
    min=0,
    max=255,
    value=255,
    onchange=function() setBaseOpacity(dlg.data.base_opacity) end
}
dlg:label{id="base_opacity_label", label="Preview", text="100% · preview only"}
dlg:button{id="base_opacity_default", text="Reset Base Opacity", onclick=function()
    setBaseOpacity(255)
end}
dlg:separator{text="Send to Blender"}
dlg:check{id="guide_visible", label="Show Render Guide", selected=true, onclick=setGuideVisibility}
dlg:check{id="send_base_color", label="Base Color", selected=true, onclick=function()
    setSendEnabled("send_base_color", "base_color")
end}
dlg:check{id="send_ao", label="Ambient Occlusion", selected=true, onclick=function()
    setSendEnabled("send_ao", "ao")
end}
dlg:check{id="send_roughness", label="Roughness", selected=true, onclick=function()
    setSendEnabled("send_roughness", "roughness")
end}
dlg:check{id="send_metallic", label="Metallic", selected=true, onclick=function()
    setSendEnabled("send_metallic", "metallic")
end}
dlg:check{id="send_emission", label="Emission", selected=true, onclick=function()
    setSendEnabled("send_emission", "emission")
end}
dlg:separator{text="Channel Overlay"}
dlg:slider{
    id="overlay",
    label="Overlay opacity",
    min=0,
    max=255,
    value=96,
    onchange=function() setOverlayOpacity(dlg.data.overlay) end
}
dlg:label{id="overlay_label", label="Preview", text="38% · preview only"}
dlg:button{id="overlay_default", text="Reset Overlay", onclick=function()
    local item = Channels.definition(selectedId())
    if item ~= nil then setOverlayOpacity(item.previewOpacity) end
end}

dlg:tab{id="actions_tab", text="Actions"}
dlg:button{id="initialize", text="Initialize / Migrate", onclick=initialize}
dlg:newrow()
dlg:button{id="rebuild", text="Refresh Blender", onclick=function() notifySync(false) end}
dlg:button{id="preview", text="Show Packed ORME", onclick=function()
    local sprite = currentSprite()
    Channels.showPacked(sprite, app.activeFrame.frameNumber)
end}
dlg:endtabs{
    id="channel_tabs",
    selected=initialTab,
    align=Align.CENTER | Align.TOP,
    onchange=function(ev)
        if settings ~= nil then settings.channelEditorTab = ev.tab end
    end
}

pribambase_channels_dlg = dlg
updatePresets()
onSiteChange = function()
    pcall(updateVisibilityControls)
    pcall(updateBaseOpacityControls)
    local sprite = app.activeSprite
    local spriteId = sprite and sprite.id or nil
    if spriteId ~= controlsSpriteId then pcall(updateSendControls) end
end
app.events:on("sitechange", onSiteChange)
siteChangeRegistered = true
local x = settings and tonumber(settings.channelEditorX) or nil
local y = settings and tonumber(settings.channelEditorY) or nil
local width = settings and tonumber(settings.channelEditorWidth) or nil
local height = settings and tonumber(settings.channelEditorHeight) or nil
if x ~= nil and y ~= nil and width ~= nil and height ~= nil and width > 0 and height > 0 then
    dlg:show{wait=false, bounds=Rectangle(x, y, width, height)}
else
    dlg:show{wait=false}
end
