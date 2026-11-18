-- Exercise the modeless dialog callbacks in batch, using the real Aseprite
-- color/image/event APIs and a small widget host instead of the unavailable GUI.
local directory = app.params.extension
local Channels = dofile(app.fs.joinPath(directory,"Channels.lua"))
local Normals = dofile(app.fs.joinPath(directory,"Normals.lua"))
local Math = dofile(app.fs.joinPath(directory,"NormalMath.lua"))
local sprite = Sprite(4,4,ColorMode.RGB)
app.activeSprite = sprite
Channels.initialize(sprite)
local flat, smooth = Image(4,4,ColorMode.RGB), Image(4,4,ColorMode.RGB)
flat:clear(app.pixelColor.rgba(128,128,255,255))
-- Deliberately non-unit RGB: sampling must retain bytes, not re-encode a normalized vector.
smooth:clear(app.pixelColor.rgba(150,37,140,255))
Normals.receiveDefault(sprite,1,flat,"FLAT")
Normals.receiveDefault(sprite,1,smooth,"SMOOTH")
local oldApp, oldDialog, oldTimer = app, Dialog, Timer
local dialog, callbacks, images = nil, {}, {}
local gc = setmetatable({}, {__index=function(_,name)
    if name == "drawImage" then return function(_,image) images[#images+1] = image end end
    return function() end
end})
local ok, message = pcall(function()
    app = setmetatable({isUIAvailable=true}, {
        __index=function(_,key) return oldApp[key] end,
        __newindex=function(_,key,value) oldApp[key]=value end
    })
    Timer = function(options)
        return {start=function() end, stop=function() end}
    end
    Dialog = function(options)
        local data, controls = {}, {}
        local d = {data=data, controls=controls, bounds=Rectangle(0,0,350,550)}
        dialog = d
        local function widget(self, values)
            if values.id then
                controls[values.id] = values
                if values.selected ~= nil then data[values.id]=values.selected
                else data[values.id]=values.option or values.value or values.color or values.text end
            end
            return self
        end
        for _,name in ipairs({"combobox","canvas","label","slider","color","check"}) do d[name]=widget end
        d.button = function(self,values) callbacks[values.text]=values.onclick return widget(self,values) end
        d.separator=widget
        d.newrow=function() end
        d.samerow=function() end
        d.modify=function(self,values)
            local control = assert(controls[values.id], "Unknown dialog control " .. tostring(values.id))
            for key,value in pairs(values) do control[key]=value end
            if values.value ~= nil then data[values.id]=values.value end
            if values.text ~= nil then data[values.id]=values.text end
            if values.selected ~= nil then data[values.id]=values.selected end
            if values.color ~= nil then data[values.id]=values.color end
        end
        d.repaint=function(self) if controls.balls then controls.balls.onpaint{context=gc} end end
        d.show=function(self) self:repaint() end
        d.close=function() options.onclose() end
        return d
    end
    pribambase_settings = {}
    dofile(app.fs.joinPath(directory,"NormalEditor.lua"))
    assert(pribambase_normals_dlg == dialog)
    assert(not dialog.controls.bearing.visible and not dialog.controls.rebuild.visible)
    dialog.data.options = true
    dialog.controls.options.onclick()
    assert(dialog.controls.bearing.visible and dialog.controls.rebuild.visible)
    dialog.data.options = false
    dialog.controls.options.onclick()
    assert(not dialog.controls.bearing.visible and not dialog.controls.rebuild.visible)
    assert(dialog.data.reference_mode == nil, "Inspector still requires choosing one reference")
    assert(dialog.controls.use_flat.enabled and dialog.controls.use_smooth.enabled)
    assert(dialog.data.flat_xyz:find("+1.000",1,true))
    assert(dialog.data.smooth_xyz ~= dialog.data.flat_xyz)
    assert(dialog.data.difference:find("Flat:",1,true) and dialog.data.difference:find("Smooth:",1,true))
    local before = Channels.renderNormal(sprite,1).bytes
    callbacks["Use Smooth"]()
    assert(app.fgColor.rgbaPixel == smooth:getPixel(2,2), "Reference picker changed the exact RGB")
    callbacks["Use Flat"]()
    assert(app.fgColor.rgbaPixel == flat:getPixel(2,2))
    dialog.data.step = "45°"
    local exactColor = app.fgColor.rgbaPixel
    dialog.controls.step.onchange()
    assert(app.fgColor.rgbaPixel == exactColor, "Grid change rounded the selected color")
    assert(not dialog.controls.axis_4.enabled and not dialog.controls.axis_5.enabled)
    assert(dialog.controls.axis_1.enabled and dialog.controls.axis_2.enabled)
    callbacks["+Y"]() -- Also guard callbacks independently of disabled widgets.
    assert(app.fgColor.rgbaPixel == exactColor, "Hidden world axis can be selected")

    -- The same pixel coordinate on either sphere represents the same continuous direction.
    dialog.data.step = "Free"
    dialog.controls.balls.onmousedown{button=MouseButton.LEFT,x=80,y=87}
    local centerColor = app.fgColor.rgbaPixel
    assert(Math.angle(Math.decode(centerColor), Math.front) < 0.5)
    dialog.controls.balls.onmousemove{x=240,y=87}
    assert(app.fgColor.rgbaPixel == centerColor, "Second ball shows a different hemisphere")
    dialog.controls.balls.onmouseup{}
    dialog.controls.balls.onmousemove{x=270,y=80}
    assert(app.fgColor.rgbaPixel == centerColor, "Released drag changed the brush")

    -- Both discrete grids select their own directions, not the most recently focused grid.
    dialog.data.step = "45°"
    for _,cx in ipairs({80,240}) do
        dialog.controls.balls.onmousedown{button=MouseButton.LEFT,x=cx,y=87}
        assert(Math.angle(Math.decode(app.fgColor.rgbaPixel),Math.front) > 14,
            "Center click bypassed the 45-degree rotation grid")
        dialog.controls.balls.onmouseup{}
    end
    local first = Math.ordered(math.pi/4,math.pi/4,"ZX")
    local u,v = Math.toDisk(first)
    dialog.controls.balls.onmousedown{button=MouseButton.LEFT,x=80+65*u,y=87-65*v}
    assert(Math.angle(Math.decode(app.fgColor.rgbaPixel),first) < 0.5)
    local leftColor = app.fgColor.rgbaPixel
    dialog.controls.balls.onmousedown{button=MouseButton.LEFT,x=240+65*u,y=87-65*v}
    assert(Math.angle(Math.decode(app.fgColor.rgbaPixel),first) > 1)
    assert(app.fgColor.rgbaPixel ~= leftColor)
    dialog.controls.balls.onmouseup{}
    dialog.data.plane = "XZ"
    dialog.controls.balls.onmousedown{button=MouseButton.LEFT,x=80,y=87}
    assert(math.abs(Math.decode(app.fgColor.rgbaPixel).y) < 0.01)
    dialog.controls.balls.onmouseup{}
    dialog.data.plane = "Any"

    callbacks["View Smooth"]()
    assert(Normals.defaultLayer(sprite,"SMOOTH").isVisible)
    assert(not Normals.group(sprite).isVisible)
    assert(Channels.renderNormal(sprite,1).bytes == before)
    callbacks["View Flat"]()
    assert(Normals.defaultLayer(sprite,"FLAT").isVisible and not Normals.group(sprite).isVisible)
    assert(Channels.renderNormal(sprite,1).bytes == before)
    callbacks["Paint Normals"]()
    assert(Normals.group(sprite).isVisible and Normals.defaultLayer(sprite,"FLAT").isVisible)
    assert(not Normals.defaultLayer(sprite,"SMOOTH").isVisible)

    -- Standard Aseprite foreground input cannot introduce a rear-facing brush on a normal layer.
    local brushBefore = app.fgColor.rgbaPixel
    app.fgColor = Color{r=128,g=255,b=128,a=255}
    assert(app.fgColor.rgbaPixel == brushBefore, "Native color picker bypassed hemisphere restriction")
    assert(dialog.data.brush_note:find("blocked",1,true))
    app.fgColor = Math.color({x=1,y=0,z=0})
    assert(app.fgColor.red == 255, "RGB8 tangent was incorrectly blocked")
    Channels.activate(sprite,"base_color")
    local rearColor = Color{r=128,g=255,b=128,a=255}
    app.fgColor = rearColor
    assert(app.fgColor.rgbaPixel == rearColor.rgbaPixel, "Normal picker restricted another artist channel")
    callbacks["Paint Normals"]()
    assert(Math.paintable(Math.decode(app.fgColor.rgbaPixel)), "Entering normal painting retained a hidden brush")

    -- A hidden reference remains inspectable, but cannot be copied into the brush.
    local hidden = Image(smooth)
    hidden:clear(app.pixelColor.rgba(128,255,128,255))
    Normals.receiveDefault(sprite,1,hidden,"SMOOTH")
    pribambase_normal_refresh()
    assert(dialog.data.smooth_xyz:find("HIDDEN",1,true))
    assert(not dialog.controls.use_smooth.enabled)
    local valid = app.fgColor.rgbaPixel
    callbacks["Use Smooth"]()
    assert(app.fgColor.rgbaPixel == valid)
    assert(dialog.controls.use_flat.enabled)
    assert(Channels.renderNormal(sprite,1).bytes == before)
    local requested
    pribambase_normal_request=function(frame) requested=frame return true end
    callbacks["Rebuild Both References"]()
    assert(requested == 1)
    pribambase_normal_request=nil

    assert(#images > 0 and images[1].width == 320)
    assert(images[1]:getPixel(80,87) == images[1]:getPixel(240,87))
    images[1]:saveAs(app.params.result .. ".picker-balls.png")
    dialog:close()
    assert(pribambase_normals_dlg == nil and pribambase_normal_refresh == nil)
end)
app, Dialog, Timer = oldApp, oldDialog, oldTimer
sprite:close()
if not ok then error(message) end
print("Pribambase normal picker dialog callbacks passed")
