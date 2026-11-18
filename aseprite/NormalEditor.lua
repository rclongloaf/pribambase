-- Modeless camera-facing picker. Painting uses Aseprite's native tools.
local directory = app.fs.filePath(debug.getinfo(1, "S").source:sub(2))
local Math = dofile(app.fs.joinPath(directory, "NormalMath.lua"))
local Normals = dofile(app.fs.joinPath(directory, "Normals.lua"))
local Channels = dofile(app.fs.joinPath(directory, "Channels.lua"))
if pribambase_normals_dlg then
    pribambase_normals_dlg:show{wait=false}
    return
end
if not app.isUIAvailable then return end

local settings = pribambase_settings or {}
local steps = {"Free", "90°", "45°", "30°", "22.5°", "15°", "7.5°"}
local divisions = {["Free"]=0, ["90°"]=1, ["45°"]=2, ["30°"]=3,
    ["22.5°"]=4, ["15°"]=6, ["7.5°"]=12}
local step = divisions[settings.normalPickerStep] and settings.normalPickerStep or "22.5°"
local selected, validColor = Math.front, Math.color(Math.front)
local painted, flat, smooth, sample
local pixelX, pixelY = app.activeSprite and math.floor(app.activeSprite.width/2) or 0,
    app.activeSprite and math.floor(app.activeSprite.height/2) or 0
local updating, settingColor, dragging, asking = false, false, false, false
local watchedSprite, revision, lastSample = nil, 0, nil
local dlg, timer, askEditor
local refresh, foregroundChanged
local activeOrder = settings.normalPickerOrder == "XZ" and "XZ" or "ZX"
local radius, cy, centers, width, height = 65, 87, {80, 240}, 320, 166
local orders = {"ZX", "XZ"}
local ballImage
local colors = {
    brush=Color{r=255,g=255,b=255}, painted=Color{r=50,g=230,b=255},
    flat=Color{r=255,g=188,b=65}, smooth=Color{r=215,g=140,b=255},
    XY=Color{r=90,g=140,b=255}, XZ=Color{r=85,g=235,b=110}, YZ=Color{r=255,g=95,b=95}
}
local planeCurves = {XY=Math.planeCurve("XY"), XZ=Math.planeCurve("XZ"), YZ=Math.planeCurve("YZ")}

local function currentFrame() return app.activeFrame and app.activeFrame.frameNumber or 1 end
local function orderLabel(order) return order == "XZ" and "X -> Z" or "Z -> X" end

local function normalLayerActive()
    local group = Normals.group(app.activeSprite)
    local layer = app.activeLayer
    while layer and layer ~= app.activeSprite do
        if group and layer == group then return true end
        layer = layer.parent
    end
    return false
end

local function makeBalls()
    local image = Image(width, height, ColorMode.RGB)
    image:clear()
    for _,cx in ipairs(centers) do
        for y=-radius,radius do for x=-radius,radius do
            local n = Math.fromDisk(x/radius, -y/radius)
            if n then image:drawPixel(cx+x, cy+y, Math.color(n).rgbaPixel) end
        end end
    end
    return image
end

local function pointOnBall(n, cx)
    local u,v = Math.toDisk(n)
    return cx+u*radius, cy-v*radius
end

local function curves(gc, lines, cx, color)
    gc.color, gc.strokeWidth = color, 1
    for _,line in ipairs(lines) do
        gc:beginPath()
        for i,n in ipairs(line) do
            local x,y = pointOnBall(n,cx)
            if i == 1 then gc:moveTo(x,y) else gc:lineTo(x,y) end
        end
        gc:stroke()
    end
end

local function marker(gc, n, kind)
    if not n then return end
    local hidden = not Math.paintable(n)
    local u,v = Math.toDisk(n)
    if hidden then
        local length = math.sqrt(u*u+v*v)
        if length < 1e-6 then u,v=0,-1 else u,v=u/length,v/length end
    end
    for _,cx in ipairs(centers) do
        local x,y = cx+u*radius, cy-v*radius
        gc.color, gc.strokeWidth = Color{r=12,g=14,b=20}, 3
        -- Dark under-stroke keeps all four shapes visible on RGB backgrounds.
        for pass=1,2 do
            if pass == 2 then gc.color, gc.strokeWidth = colors[kind], 1 end
            gc:beginPath()
            if kind == "flat" then
                gc:moveTo(x,y-7) gc:lineTo(x+7,y) gc:lineTo(x,y+7) gc:lineTo(x-7,y) gc:closePath()
            elseif kind == "smooth" then
                gc:moveTo(x,y-10) gc:lineTo(x+9,y+7) gc:lineTo(x-9,y+7) gc:closePath()
            elseif kind == "painted" then
                gc:oval(Rectangle(x-4,y-4,8,8))
            else
                gc:moveTo(x-3,y) gc:lineTo(x+3,y) gc:moveTo(x,y-3) gc:lineTo(x,y+3)
            end
            gc:stroke()
        end
        if hidden then
            gc.color = Color{r=255,g=70,b=70}
            gc:beginPath()
            gc:moveTo(x+7,y-6) gc:lineTo(x+12,y-1)
            gc:moveTo(x+12,y-6) gc:lineTo(x+7,y-1) gc:stroke()
        end
    end
end

local function paintBalls(ev)
    local gc = ev.context
    if not ballImage then ballImage = makeBalls() end
    gc:drawImage(ballImage,0,0)
    local count, plane = divisions[dlg.data.step] or 0, dlg.data.plane
    for side,cx in ipairs(centers) do
        gc.color = colors.brush
        gc:fillText(orderLabel(orders[side]) .. (activeOrder == orders[side] and " *" or ""),cx-24,0)
        curves(gc,Math.grid(count,orders[side]),cx,Color{r=20,g=24,b=36,a=115})
        if dlg.data.planes then
            for _,name in ipairs({"XY","XZ","YZ"}) do
                curves(gc,planeCurves[name],cx,colors[name])
            end
        end
        gc.color, gc.strokeWidth = Color{r=210,g=214,b=224}, 1
        gc:beginPath() gc:oval(Rectangle(cx-radius,cy-radius,2*radius,2*radius)) gc:stroke()
        if count > 0 then
            gc.color = Color{r=12,g=14,b=20,a=210}
            for _,n in ipairs(Math.palette(count,orders[side])) do
                if Math.inPlane(n,plane) then
                    local x,y = pointOnBall(n,cx)
                    gc:fillRect(Rectangle(x-1,y-1,2,2))
                end
            end
        end
        if dlg.data.planes and plane ~= "Any" then curves(gc,planeCurves[plane],cx,colors.brush) end
        for _,point in ipairs(Math.landmarks()) do
            if point.axis or dlg.data.diagonals then
                local x,y = pointOnBall(point.n,cx)
                gc.color = Math.inPlane(point.n,plane) and colors.brush or Color{r=80,g=80,b=80}
                gc:beginPath()
                gc:oval(Rectangle(x-2,y-2,4,4)) gc:stroke()
                if point.axis then gc:fillText(point.name,x-5,y+4) end
            end
        end
    end
    marker(gc,smooth,"smooth")
    marker(gc,flat,"flat")
    marker(gc,painted,"painted")
    marker(gc,selected,"brush")
    for i,item in ipairs({{"+ Brush","brush"},{"o Painted","painted"},{"<> Flat","flat"},{"^ Smooth","smooth"}}) do
        gc.color = colors[item[2]]
        gc:fillText(item[1],(i-1)*80+4,12)
    end
    if dlg.data.planes then
        for i,name in ipairs({"XY","XZ","YZ"}) do
            gc.color = colors[name]
            gc:fillText(name .. ": " .. ({XY="Z=0",XZ="Y=0",YZ="X=0"})[name],(i-1)*106+4,156)
        end
    end
end

local function describe(n)
    if not n then return "No covered pixel" end
    return string.format("%+.3f  %+.3f  %+.3f%s",n.x,n.y,n.z,
        Math.paintable(n) and "" or " · HIDDEN")
end

local function updateBrush(note)
    updating = true
    local color = app.fgColor
    dlg:modify{id="brush_color",color=color}
    dlg:modify{id="brush_xyz",text="XYZ " .. describe(selected)}
    dlg:modify{id="brush_rgb",text=string.format("RGB %d, %d, %d",color.red,color.green,color.blue)}
    local warning = note or (selected and not Math.paintable(selected)
        and "Behind camera · choose a visible direction" or "")
    dlg:modify{id="brush_note",text=warning,visible=warning ~= ""}
    if selected then
        local u,v = Math.toDisk(selected)
        if u*u+v*v > 1e-10 then
            dlg:modify{id="bearing",value=math.floor(math.deg(math.atan(v,u))+0.5)}
        end
        dlg:modify{id="tilt",value=math.floor(math.deg(math.acos(math.max(0,math.min(1,
            Math.dot(selected,Math.front)))))+0.5)}
    end
    updating = false
    dlg:repaint()
end

local function choose(n, snap, exactPixel)
    if not Math.paintable(n) then return false end
    local direction = snap and Math.quantize(n,divisions[dlg.data.step],activeOrder,dlg.data.plane)
        or Math.normalize(n)
    if not direction then return false end
    selected = direction
    settingColor = true
    app.fgColor = exactPixel and Color(exactPixel) or Math.color(selected)
    validColor = Color(app.fgColor)
    settingColor = false
    updateBrush()
    return true
end

local function directionAt(ev)
    local side = ev.x < width/2 and 1 or 2
    return Math.fromDisk((ev.x-centers[side])/radius,(cy-ev.y)/radius),side
end

local function hoverBall(ev)
    local n,side = directionAt(ev)
    if not n then return end
    local name, nearest, distance = "",nil,5/radius
    for _,point in ipairs(Math.landmarks()) do
        if point.axis or dlg.data.diagonals then
            local u,v = Math.toDisk(point.n)
            local x,y = (ev.x-centers[side])/radius,(cy-ev.y)/radius
            local d = math.sqrt((x-u)^2+(y-v)^2)
            if d < distance then name,nearest,distance=point.name,point.n,d end
        end
    end
    n = nearest or n
    local memberships = {}
    for _,plane in ipairs({"XY","XZ","YZ"}) do
        if Math.inPlane(n,plane) then memberships[#memberships+1]=plane end
    end
    dlg:modify{id="hover",text=string.format("%s  %.2f, %.2f, %.2f%s",name,n.x,n.y,n.z,
        #memberships > 0 and " · " .. table.concat(memberships," / ") or "")}
end

local function pickBall(ev)
    local n,side = directionAt(ev)
    if n then
        activeOrder = orders[side]
        settings.normalPickerOrder = activeOrder
        choose(n,true)
    end
end

local function brushFromAngles()
    if updating then return end
    choose(Math.fromCameraAngles(math.rad(dlg.data.bearing),math.rad(dlg.data.tilt)),true)
end

local function cancelInspect()
    if asking and askEditor then pcall(function() askEditor:cancel() end) end
    asking,askEditor = false,nil
end

local function spriteChanged() revision=revision+1 end
local function watchSprite()
    local sprite = app.activeSprite
    if watchedSprite ~= sprite then
        if watchedSprite then pcall(function() watchedSprite.events:off(spriteChanged) end) end
        watchedSprite = sprite
        if sprite then sprite.events:on("change",spriteChanged) end
        lastSample = nil
    end
end

refresh = function(force)
    watchSprite()
    local sprite,frame = app.activeSprite,currentFrame()
    local identity = string.format("%s:%d:%d:%d:%d",sprite and sprite.id or 0,frame,pixelX,pixelY,revision)
    if not force and identity == lastSample then return end
    lastSample = identity
    sample = sprite and Normals.inspect(sprite,frame,pixelX,pixelY) or nil
    painted = sample and Math.decode(sample.painted) or nil
    flat = sample and Math.decode(sample.default) or nil
    smooth = sample and Math.decode(sample.smooth) or nil
    dlg:modify{id="sample_site",text=string.format("Frame %d · pixel %d, %d",frame,pixelX,pixelY)}
    dlg:modify{id="painted_xyz",text=describe(painted)}
    dlg:modify{id="flat_xyz",text=describe(flat)}
    dlg:modify{id="smooth_xyz",text=describe(smooth)}
    local a,b = Math.angle(painted,flat),Math.angle(painted,smooth)
    dlg:modify{id="difference",text=string.format("Painted vs Flat: %s   vs Smooth: %s",
        a and string.format("%.2f°",a) or "—",b and string.format("%.2f°",b) or "—")}
    dlg:modify{id="use_painted",enabled=Math.paintable(painted)}
    dlg:modify{id="use_flat",enabled=Math.paintable(flat)}
    dlg:modify{id="use_smooth",enabled=Math.paintable(smooth)}
    if normalLayerActive() then foregroundChanged() end
    dlg:repaint()
end

local function activate(mode)
    local sprite = app.activeSprite
    if not sprite then app.alert("Open a sprite first") return end
    pribambase_channel_mutating = true
    local ok,message = pcall(function()
        app.transaction("Edit World Normal",function() Channels.activate(sprite,"normal") end)
        if mode then Normals.showDefault(sprite,true,mode) end
    end)
    pribambase_channel_mutating = false
    if not ok then app.alert(tostring(message)) return end
    dlg:modify{id="view_status",text=mode and (mode == "FLAT" and "Canvas · Flat preview" or "Canvas · Smooth preview")
        or "Canvas · painting World Normal"}
    foregroundChanged()
    refresh(true)
end

local function inspectPixel()
    local editor = app.editor
    if not editor then return end
    cancelInspect()
    dlg:modify{id="follow",selected=false}
    askEditor,asking = editor,true
    local sprite = app.activeSprite
    editor:askPoint{
        title="Inspect World Normal: click a pixel · Esc cancels",
        onclick=function(ev)
            if app.activeSprite == sprite then pixelX,pixelY=ev.point.x,ev.point.y refresh(true) end
            cancelInspect()
        end,
        onchange=function(ev)
            if app.activeSprite == sprite then pixelX,pixelY=ev.point.x,ev.point.y refresh(false) end
        end,
        oncancel=function() asking,askEditor=false,nil end
    }
end

local function siteChanged()
    if asking then cancelInspect() end
    refresh(true)
end

foregroundChanged = function()
    if settingColor then return end
    local c = app.fgColor
    local n = Math.decode(app.pixelColor.rgba(c.red,c.green,c.blue,c.alpha))
    if n and not Math.paintable(n) and normalLayerActive() then
        settingColor = true
        app.fgColor = Color(validColor)
        settingColor = false
        selected = Math.decode(validColor.rgbaPixel)
        updateBrush("Hidden direction blocked · previous brush kept")
        return
    end
    selected = n
    if Math.paintable(n) then validColor = Color(c) end
    updateBrush()
end

local function close()
    if timer then timer:stop() end
    cancelInspect()
    if watchedSprite then pcall(function() watchedSprite.events:off(spriteChanged) end) end
    app.events:off(siteChanged)
    app.events:off(foregroundChanged)
    settings.normalPickerX,settings.normalPickerY = dlg.bounds.x,dlg.bounds.y
    pribambase_normal_refresh,pribambase_normals_dlg = nil,nil
end

dlg = Dialog{title="Pribambase · World Normal",onclose=close}
dlg:separator{text="Direction · camera-facing"}
dlg:combobox{id="step",label="Step",options=steps,option=step,hexpand=false,onchange=function()
    settings.normalPickerStep=dlg.data.step
    dlg:repaint() -- Changing the grid never rounds an already selected color.
end}
dlg:samerow()
dlg:label{text="Plane"}
dlg:samerow()
dlg:combobox{id="plane",options={"Any","XY","XZ","YZ"},option="Any",hexpand=false,onchange=function() dlg:repaint() end}
dlg:canvas{id="balls",width=width,height=height,vexpand=false,autoscaling=true,onpaint=paintBalls,
    onmousedown=function(ev)
        dragging=ev.button == MouseButton.LEFT
        if dragging then pickBall(ev) end
    end,
    onmousemove=function(ev) hoverBall(ev) if dragging then pickBall(ev) end end,
    onmouseup=function() dragging=false end}
dlg:label{id="hover",text="World axes and diagonals · hover for XYZ / plane"}
dlg:newrow()
local axes = {
    {"-X",{x=-1,y=0,z=0}}, {"+X",{x=1,y=0,z=0}},
    {"-Y",{x=0,y=-1,z=0}}, {"+Y",{x=0,y=1,z=0}},
    {"-Z",{x=0,y=0,z=-1}}, {"+Z",{x=0,y=0,z=1}}
}
for i,axis in ipairs(axes) do
    local direction = axis[2]
    dlg:button{id="axis_"..i,text=axis[1],enabled=Math.visible(direction),onclick=function() choose(direction,false) end}
end

dlg:separator{text="Brush direction"}
dlg:color{id="brush_color",label="Brush",color=validColor,enabled=false}
dlg:samerow()
dlg:label{id="brush_rgb",text="RGB 128, 17, 191"}
dlg:samerow()
dlg:check{id="options",text="Options",selected=false,onclick=function()
    for _,id in ipairs({"brush_xyz","bearing","tilt","planes","diagonals","geometry","rebuild"}) do
        dlg:modify{id=id,visible=dlg.data.options}
    end
end}
dlg:newrow()
dlg:label{id="brush_xyz",text="XYZ 0.000  -0.866  +0.500",visible=false}
dlg:newrow()
dlg:label{id="brush_note",text="",visible=false}
dlg:slider{id="bearing",label="Screen angle",min=-180,max=180,value=0,visible=false,onchange=brushFromAngles}
dlg:slider{id="tilt",label="From camera",min=0,max=90,value=0,visible=false,onchange=brushFromAngles}
dlg:check{id="planes",text="XY / XZ / YZ",selected=true,visible=false,onclick=function() dlg:repaint() end}
dlg:check{id="diagonals",text="Diagonals",selected=true,visible=false,onclick=function() dlg:repaint() end}

dlg:separator{text="Inspect pixel · both references"}
dlg:button{text="Inspect Pixel",onclick=inspectPixel}
dlg:samerow()
dlg:check{id="follow",text="Follow cursor",selected=false}
dlg:label{id="sample_site",text="Frame 1 · pixel 0, 0"}
dlg:label{id="painted_xyz",label="Painted o",text="No covered pixel"}
dlg:samerow()
dlg:button{id="use_painted",text="Use Painted",enabled=false,onclick=function()
    if sample then choose(painted,false,sample.painted) end
end}
dlg:label{id="flat_xyz",label="Flat <>",text="No covered pixel"}
dlg:samerow()
dlg:button{id="use_flat",text="Use Flat",enabled=false,onclick=function()
    if sample then choose(flat,false,sample.default) end
end}
dlg:label{id="smooth_xyz",label="Smooth /\\",text="No covered pixel"}
dlg:samerow()
dlg:button{id="use_smooth",text="Use Smooth",enabled=false,onclick=function()
    if sample then choose(smooth,false,sample.smooth) end
end}
dlg:label{id="difference",text="Painted vs Flat: —   vs Smooth: —"}

dlg:separator{id="view_status",text="Canvas · paint / preview"}
dlg:button{text="Paint Normals",onclick=function() activate() end}
dlg:button{text="View Flat",onclick=function() activate("FLAT") end}
dlg:button{text="View Smooth",onclick=function() activate("SMOOTH") end}
dlg:separator{id="geometry",text="Geometry · Blender sync",visible=false}
dlg:button{id="rebuild",text="Rebuild Both References",visible=false,onclick=function()
    if not pribambase_normal_request or not pribambase_normal_request(currentFrame()) then
        app.alert("Start Sync in both applications to rebuild both references for this frame.")
    end
end}

pribambase_normals_dlg = dlg
pribambase_normal_refresh = function() revision=revision+1 refresh(true) end
app.events:on("sitechange",siteChanged)
app.events:on("fgcolorchange",foregroundChanged)
timer = Timer{interval=0.1,ontick=function()
    if dlg.data.follow and not asking then
        local editor = app.editor
        if editor and app.activeSprite and editor.sprite == app.activeSprite then
            local p = editor.spritePos
            if p and p.x >= 0 and p.y >= 0 and p.x < app.activeSprite.width and p.y < app.activeSprite.height then
                pixelX,pixelY=p.x,p.y
            end
        end
    end
    refresh(false)
end}
foregroundChanged()
refresh(true)
local x,y = tonumber(settings.normalPickerX),tonumber(settings.normalPickerY)
dlg:show{wait=false,autoscrollbars=true}
if x and y then
    local bounds=dlg.bounds
    bounds.x,bounds.y=x,y
    dlg.bounds=bounds
end
dlg:repaint()
timer:start()
