-- Copyright (c) 2021 lampysprites
--
-- Permission is hereby granted, free of charge, to any person obtaining a copy
-- of this software and associated documentation files (the "Software"), to deal
-- in the Software without restriction, including without limitation the rights
-- to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
-- copies of the Software, and to permit persons to whom the Software is
-- furnished to do so, subject to the following conditions:
--
-- The above copyright notice and this permission notice shall be included in all
-- copies or substantial portions of the Software.
--
-- THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
-- IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
-- FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
-- AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
-- LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
-- OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
-- SOFTWARE.

-- Live source-pair synchronization for Aseprite.
local function showChannelEditor()
    if app.isUIAvailable then
        pcall(function() app.command.SbMaterialChannels() end)
    end
end


if pribambase_dlg then
    -- when everything's already running, only need to pop up the dialog again
    pribambase_dlg:show{ wait = false }
    showChannelEditor()

else
    -- start a websocket and change observers

    local Guide = dofile(app.fs.joinPath(
        app.fs.userConfigPath,
        "extensions",
        "pribambase",
        "Guide.lua"
    ))
    local Canvas = dofile(app.fs.joinPath(
        app.fs.userConfigPath,
        "extensions",
        "pribambase",
        "Canvas.lua"
    ))
    local Channels = dofile(app.fs.joinPath(
        app.fs.userConfigPath,
        "extensions",
        "pribambase",
        "Channels.lua"
    ))
    local PayloadCache = dofile(app.fs.joinPath(
        app.fs.userConfigPath,
        "extensions",
        "pribambase",
        "PayloadCache.lua"
    ))
    local settings = pribambase_settings
    local ws
    local connected = false
    local stopping = false
    local reconnectTimer
    -- the list of texures open in blender
    local syncList = {}
    -- map MessageID to handler callback
    local handlers = {}
    -- main dialog
    local dlg = app.isUIAvailable and Dialog{ title="Pribambase Sync" }
    -- command dialog
    local menu = Dialog()
    -- used to track the change of active sprite
    local spr = app.activeSprite
    -- used to track saving the image under a different name
    local sprfile = spr and spr.filename
    -- used to track frame changes
    local frame = -1
    -- used to pause the app from processing updates
    local pause_app_change = false
    -- portable pair identity; local paths may differ between collaborators
    local pairedAsset = ""
    local pairedRemoteSource = ""
    local pairedFileName = ""
    local pairedSprite = nil
    -- Last artist texture payload sent for each sprite/frame/channel. Blender
    -- guide updates modify the sprite but reference layers are excluded from
    -- these payloads, so identical bytes must not feed back into Blender.
    local sentTexturePayloads = PayloadCache.new()


    -- Set up an image buffer for two reasons:
    -- a) the active cel might not be the same size as the sprite
    -- b) the sprite might not be in RGBA mode, and it's easier to use ase
    --    than do conversions on the other side.
    local buf = Image(1, 1, ColorMode.RGB)


    --[[
        State-independent messsage packing functions.
        May have multiple returns, WebSocket:send() concatenates its arguments
    ]]

    local function messageImage(opts)
        local sprite = opts.sprite
        local name = opts.name or ""
        local id = string.byte(opts.new and 'N' or 'I')
        local image = opts.image

        if image == nil then
            if buf.width ~= sprite.width or buf.height ~= sprite.height then
                buf:resize(sprite.width, sprite.height)
            end

            buf:clear()
            buf:drawSprite(sprite, opts.frame)
            image = buf
        end

        return string.pack(
            "<BHHs4I4",
            id,
            image.width,
            image.height,
            name,
            image.rowStride * image.height
        ), image.bytes
    end


    local function messageChannel(opts)
        local image = opts.image
        return string.pack(
            "<BHHI4s4s4I4",
            string.byte('P'),
            image.width,
            image.height,
            opts.frame,
            opts.channel,
            opts.source,
            image.rowStride * image.height
        ), image.bytes
    end


    local function messageChangeName(opts)
        return string.pack("<Bs4s4", string.byte('C'), opts.from, opts.to)
    end

    local function messageFrame(number)
        return string.pack("<BI4", string.byte('A'), number)
    end

    local function _messageBatchImpl(msg, ...)
        -- FIXME this is not lisp
        if msg then
            return string.pack("<I4", #msg), msg, _messageBatchImpl(...)
        end
    end

    local function messageBatch(count, ...)
        return string.pack("<BH", string.byte('['), count), _messageBatchImpl(...)
    end


    --[[ Messaging logic ]]

    local function sendSpriteFrame(sprite, name, frameNumber, new)
        if not connected or sprite == nil then return end
        if math.max(sprite.width, sprite.height) > tonumber(pribambase_settings.maxsize) then return end

        if Channels.hasStructure(sprite) then
            local base = Channels.renderBaseColor(sprite, frameNumber)
            local baseChanged = sentTexturePayloads:changed(
                sprite.id, name, frameNumber, "base", base, new
            )
            if baseChanged then
                ws:sendBinary(messageImage{
                    sprite=sprite,
                    image=base,
                    name=name,
                    frame=frameNumber,
                    new=new
                })
            end
            local orme = Channels.packORME(sprite, frameNumber)
            local ormeChanged = sentTexturePayloads:changed(
                sprite.id, name, frameNumber, "orme", orme, new
            )
            if ormeChanged then
                ws:sendBinary(messageChannel{
                    image=orme,
                    frame=frameNumber,
                    channel="orme",
                    source=name
                })
            end
        else
            ws:sendBinary(messageImage{
                sprite=sprite,
                name=name,
                frame=frameNumber,
                new=new
            })
        end
    end


    local function sendImage(name, new)
        if spr == nil then return end
        local frameNumber = app.activeFrame and app.activeFrame.frameNumber or 1
        sendSpriteFrame(spr, name, frameNumber, new)
    end


    -- Creates the reference layer/cel once, then refreshes only its pixel bytes.
    -- Direct Image.bytes updates intentionally stay outside transactions so
    -- Blender guide refreshes do not become artist-visible undo actions.
    local function show_uv(w, h, opacity, name, data)
        local refLayer
        local refCel

        local frame = app.activeFrame

        -- Reuse reference layers only. A paint layer with the same name belongs
        -- to the artist and must never be cleared by a Blender projection.
        -- in this case opacity is kept (it's convenient to change)
        for _,l in ipairs(spr.layers) do
            if l.name == name and l.isReference then
                refLayer = l
                refCel = refLayer:cel(frame)
                break
            end
        end

        if refLayer == nil then
            for _,l in ipairs(spr.layers) do
                if l.name == name and not l.isReference then
                    name = name .. " (Guide)"
                    break
                end
            end
        end

        if refLayer == nil then
            for _,l in ipairs(spr.layers) do
                if l.name == name and l.isReference then
                    refLayer = l
                    refCel = refLayer:cel(frame)
                    break
                end
            end
        end

        local renderImage
        if spr.colorMode == ColorMode.RGB then
            renderImage = Image(w, h, ColorMode.RGB)
            renderImage.bytes = data
            if w ~= spr.width or h ~= spr.height then
                renderImage:resize(spr.width, spr.height)
            end
        else
            -- can't seem to find a way to convert between rgb and indexed in the API rn, so we'll have to do manually
            local idx = -1
            local bestDist = math.maxinteger -- squared distance; looking for best match color to draw the UVs with
            local threshold = 64 -- TODO global const

            local rimg = Image(w, h, ColorMode.INDEXED)

            for i=1,#data//4 do
                local a, b, g, r = string.byte(data, 4 * i, 4 * i + 3)

                if a > threshold then
                    if idx == -1 then
                        -- let's find the best color in the palette that we can use
                        local pal = spr.palettes[1]
                        for n=0,#pal-1 do
                            local col = pal:getColor(n)
                            -- euclidean is dumb af but does something at all
                            local dist = (col.red - r) ^ 2 + (col.green - g) ^ 2 + (col.blue - b) ^ 2
                            if dist < bestDist and n ~= spr.transparentColor then
                                bestDist = dist
                                idx = n
                            end
                        end

                        if idx == -1 then
                            -- indexed mode alsways has at least one color in the palette so just in case
                            idx = 0
                        end
                    end

                    rimg:drawPixel(i % w, i // w, idx)
                end
            end

            if w ~= spr.width or h ~= spr.height then
                rimg:resize(spr.width, spr.height)
            end
            renderImage = rimg
        end

        local needsSetup = refLayer == nil
            or refCel == nil
            or not Guide.imageMatches(refCel, renderImage)
            or not Guide.isRenderLayer(refLayer)
            or refLayer.stackIndex ~= 1
            or refLayer.isEditable
            or refCel.position.x ~= 0
            or refCel.position.y ~= 0

        if needsSetup then
            app.transaction("Prepare Pribambase Render Guide", function()
                if refLayer == nil then
                    local active = app.activeLayer
                    app.command.NewLayer{reference=true}
                    refLayer = app.activeLayer
                    refLayer.name = name
                    refLayer.opacity = opacity
                    app.activeLayer = active
                end

                refCel = Guide.ensureCel(spr, refLayer, frame, renderImage)
                if not Guide.imageMatches(refCel, renderImage) then
                    refCel.image = renderImage
                end
                Guide.markRenderLayer(refLayer)
                Guide.placeAtBottom(refLayer)
                if refCel.position.x ~= 0 or refCel.position.y ~= 0 then
                    refCel.position = Point(0, 0)
                end
                if refLayer.isEditable then refLayer.isEditable = false end
            end)
        end

        Guide.updateCelPixels(refCel, renderImage)
        app.refresh()
    end


    local function portableFileName(path)
        return string.match(path or "", "[^/\\]+$") or path or ""
    end


    local function matchesPairedSprite(candidate)
        if candidate == nil or pairedRemoteSource == "" then return false end
        return candidate == pairedSprite
            or candidate.filename == pairedRemoteSource
            or (pairedFileName ~= "" and portableFileName(candidate.filename) == pairedFileName)
    end


    local function outboundSpriteName(candidate)
        if matchesPairedSprite(candidate) then return pairedRemoteSource end
        return candidate.filename
    end


    -- check if the file got renamed
    local function checkFilename()
        local paired = matchesPairedSprite(spr)
        if spr and spr == app.activeSprite and (syncList[sprfile] or paired) and spr.filename ~= sprfile then
            -- renamed
            if sprfile ~= "" and not paired then
                ws:sendBinary(messageChangeName{ from=sprfile, to=spr.filename })
            end
            sprfile = spr.filename
        elseif spr then
            sprfile = spr.filename
        end
    end


    local function syncSprite()
        if spr == nil or pause_app_change or pribambase_channel_mutating then return end

        checkFilename()

        local s = outboundSpriteName(spr)
        if syncList[s] or matchesPairedSprite(spr) then
            sendImage(s)
        end
    end


    local function updateSourceLabel()
        if dlg ~= nil then
            local source = spr and portableFileName(spr.filename) or "No sprite"
            if pairedAsset ~= "" then source = pairedAsset .. " · " .. source end
            pcall(function() dlg:modify{ id="source", text=source } end)
        end
    end


    -- close connection and ui if the sprite is closed
    local function onAppChange()
        if pause_app_change then return end

        checkFilename()

        if app.activeSprite ~= spr then
            -- stop watching the hidden sprite
            if spr and connected then
                spr.events:off(syncSprite)
            end

            -- start watching the active sprite
            -- nil when it's the startpage or empty window
            if app.activeSprite then
                spr = app.activeSprite
                if matchesPairedSprite(spr) then pairedSprite = spr end
                sprfile = app.activeSprite.filename
                frame = app.activeFrame.frameNumber
                if connected then
                    spr.events:on("change", syncSprite)
                    syncSprite()
                end
            end

            -- hopefully this will prevent the closed sprite error
            spr = app.activeSprite
            sprfile = ""

        elseif spr and connected and app.activeFrame.frameNumber ~= frame then
            frame = app.activeFrame.frameNumber
            ws:sendBinary(messageFrame(frame))
            syncSprite()
        end

        updateSourceLabel()
    end


    -- clean up and exit
    local function cleanup()
        stopping = true
        if reconnectTimer ~= nil then reconnectTimer:stop() end
        if ws ~= nil then ws:close() end
        if dlg ~= nil then dlg:close() dlg = nil end
        pribambase_dlg = nil
        pribambase_channel_refresh = nil
        if spr~=nil then spr.events:off(syncSprite) end
        app.events:off(onAppChange)
    end


    local function createTexture()
        sendImage(spr.filename or "Sprite", true)
    end


    --[[ Message handlers  ]]

    local function handleUVMap(msg)
        local _id, opacity, w, h, layer, sprite, pixels = string.unpack("<BBHHs4s4s4", msg)

        if sprite ~= "" then
            local found = false

            for _,s in ipairs(app.sprites) do
                if s.filename == sprite or (sprite == pairedRemoteSource and matchesPairedSprite(s)) then
                    if sprite == pairedRemoteSource then pairedSprite = s end
                    app.activeSprite = s
                    found = true
                    break
                end
            end

            if not found then
                return
            end
            onAppChange()
        elseif spr == nil then
            return
        end

        pause_app_change = true
        local ok, errorMessage = pcall(function()
            show_uv(w, h, opacity, layer, pixels)
        end)
        pause_app_change = false
        if not ok then error(errorMessage) end
    end


    local function handleTextureList(msg)
        local _id = string.unpack("<BH", msg)
        local offset = 2
        local ml = #msg
        local synced = spr and (syncList[outboundSpriteName(spr)] or matchesPairedSprite(spr))

        syncList = {}

        while offset < ml do
            local len = string.unpack("<I4", msg, offset)
            local name = string.unpack("<s4", msg, offset)
            syncList[name] = true
            offset = offset + 4 + len
        end

        if not synced then
            syncSprite()
        end
    end


    local function handleFocus(msg)
        local _id, path = string.unpack("<Bs4", msg)

        for _,sprite in ipairs(app.sprites) do
            if sprite.filename == path or (path == pairedRemoteSource and matchesPairedSprite(sprite)) then
                if path == pairedRemoteSource then pairedSprite = sprite end
                app.activeSprite = sprite
                onAppChange()
                break
            end
        end
    end


    local function handleOpenSprite(msg)
        local _id, path = string.unpack("<Bs4", msg)

        syncList[path] = true

        local opened
        for _,sprite in ipairs(app.sprites) do
            if sprite.filename == path or (path == pairedRemoteSource and matchesPairedSprite(sprite)) then
                opened = sprite
                if path == pairedRemoteSource then pairedSprite = sprite end
                break
            end
        end

        if opened then
            if app.activeSprite ~= opened then
                app.activeSprite = opened
            end
            onAppChange()
            syncSprite()
        elseif app.fs.filePath(path) and app.fs.isFile(path) then -- check if absolute path; message can't contain rel path, so getting one mean it's a datablock name, and we don't need to open it if it isn't
            Sprite{ fromFile = path }
        end
    end


    local function handleCanvas(msg)
        local _id, width, height, originX, originY, source = string.unpack("<BHHi4i4s4", msg)
        local target = nil
        for _,candidate in ipairs(app.sprites) do
            if candidate.filename == source or (source == pairedRemoteSource and matchesPairedSprite(candidate)) then
                target = candidate
                break
            end
        end
        if target == nil then return end

        pause_app_change = true
        local changed = false
        local ok, errorMessage = pcall(function()
            local needsCanvas = Canvas.needsUpdate(target, width, height, originX, originY)
            local needsChannels = Channels.needsMigration(target)
            if needsCanvas or needsChannels then
                app.transaction("Update Pribambase Canvas", function()
                    changed = Canvas.ensure(target, width, height, originX, originY)
                    if Channels.hasStructure(target) then
                        Channels.initialize(target)
                        if changed then Channels.ensurePaintDefaults(target, true) end
                    end
                end)
            end
        end)
        pause_app_change = false
        if not ok then error(errorMessage) end

        pairedSprite = target
        spr = target
        app.activeSprite = target
        frame = app.activeFrame.frameNumber
        if changed then syncSprite() end
        updateSourceLabel()
    end


    local function handleWorkspace(msg)
        local _id, asset, source = string.unpack("<Bs4s4", msg)

        pairedAsset = asset
        pairedRemoteSource = source
        pairedFileName = portableFileName(source)
        pairedSprite = nil
        syncList[source] = true

        for _,candidate in ipairs(app.sprites) do
            if candidate.filename == source or portableFileName(candidate.filename) == pairedFileName then
                pairedSprite = candidate
                break
            end
        end

        if pairedSprite ~= nil then
            app.activeSprite = pairedSprite
            onAppChange()
        end
        updateSourceLabel()
    end


    local function activateFrame(number, createMissing, sendTexture)
        local target = pairedSprite or spr
        if target == nil or number < 1 then
            return
        end

        pause_app_change = true
        if createMissing then
            local addedFrames = false
            while #target.frames < number do
                target:newEmptyFrame()
                addedFrames = true
            end
            if addedFrames and Channels.hasStructure(target) then
                app.transaction("Fill Pribambase channel frames", function()
                    Channels.ensurePaintDefaults(target, true)
                end)
            end
        elseif number > #target.frames then
            pause_app_change = false
            return
        end

        app.activeSprite = target
        spr = target
        app.activeFrame = target.frames[number]
        frame = number
        pause_app_change = false
        app.refresh()
        if sendTexture then syncSprite() end
    end


    local function handleFrame(msg)
        local _id, number = string.unpack("<BI4", msg)
        activateFrame(number, false, true)
    end


    local function handleGuideFrame(msg)
        local _id, number = string.unpack("<BI4", msg)
        activateFrame(number, true, false)
    end


    local function handleBatch(msg)
        local count = string.unpack("<BH", msg, 2)
        local offset = 4
        for _=1,count do
            -- peek the data length and id inside the batched command
            local len, id = string.unpack("<I4B", msg, offset)
            -- the command as if it arrived alone
            local message = string.unpack("<s4", msg, offset)
            handlers[id](message)
            -- pcall(handlers[id], message) TODO uncomment
            offset = offset + 4 + len
        end
    end


    handlers = {
        [string.byte('[')] = handleBatch,
        [string.byte('M')] = handleUVMap,
        [string.byte('V')] = handleCanvas,
        [string.byte('L')] = handleTextureList,
        [string.byte('O')] = handleOpenSprite,
        [string.byte('F')] = handleFocus,
        [string.byte('A')] = handleFrame,
        [string.byte('G')] = handleGuideFrame,
        [string.byte('W')] = handleWorkspace,
    }


    --[[ UI callbacks ]]

    -- t is for type, there's already a lua function
    local function receive(t, message)
        if t == WebSocketMessageType.BINARY then
            local id = string.unpack("<B", message)
            handlers[id](message)
            -- pcall(handlers[id], message) TODO uncommet

        elseif t == WebSocketMessageType.OPEN then
            connected = true
            sentTexturePayloads:clear()
            reconnectTimer:stop()
            dlg:modify{ id="status", text="Sync active" }

            if spr ~= nil then
                spr.events:on("change", syncSprite)
            end

        elseif t == WebSocketMessageType.CLOSE and dlg ~= nil then
            connected = false
            sentTexturePayloads:clear()
            dlg:modify{ id="status", text="Waiting for Blender..." }
            if spr ~= nil then
                spr.events:off(syncSprite)
            end
            if not stopping then reconnectTimer:start() end
        end

        checkFilename()
    end


    -- set up a websocket
    ws = WebSocket{
        url=table.concat{"http://", settings.host, ":", settings.port},
        onreceive=receive,
        deflate=false
    }


    -- Channel Editor calls this after explicit rebuild actions. Normal brush
    -- edits are already covered by the sprite change observer.
    pribambase_channel_refresh = function(allFrames, requestedSprite)
        local target = requestedSprite or pairedSprite or spr
        if target == nil or not Channels.hasStructure(target) then return end
        local source = outboundSpriteName(target)
        if allFrames then
            for frameNumber=1,#target.frames do
                sendSpriteFrame(target, source, frameNumber, false)
            end
        else
            local frameNumber = app.activeFrame and app.activeFrame.frameNumber or 1
            sendSpriteFrame(target, source, frameNumber, false)
        end
    end

    reconnectTimer = Timer{
        interval=2.0,
        ontick=function()
            if not connected and not stopping then
                pcall(function() ws:connect() end)
            end
        end
    }

    --[[ global ]] pribambase_dlg = dlg
    app.events:on("sitechange", onAppChange)

    -- create an UI

    local function showMenu()
        local ready = (connected and spr ~= nil)
        -- temporarily disabled TODO see below
        -- menu:modify{ id="texture", enabled=ready }
        menu:modify{ id="update", enabled=ready }
        menu:show()
    end

    menu:newrow{ always=true }
    menu:separator{ text="Actions" }
    -- disabled since it gets a bit upredictable in some cases -- TODO enable after temp images get blendfile reference
    -- menu:button{ id="texture", text="Create Texture", onclick=function() createTexture() menu:close() end }
    menu:button{ id="update", text="Force Refresh", onclick=function() syncSprite() menu:close() end }
    menu:button{ id="channels", text="Material Channels...", onclick=function()
        menu:close()
        app.command.SbMaterialChannels()
    end }
    menu:button{ id="reconnect", text="Reconnect", onclick=function() menu:close() ws:close() ws:connect() end }
    menu:separator()
    menu:button{ id="settings", text="* Settings", onclick=function() menu:close() app.command.SbSyncSettings() end }
    menu:button{ id="back", text="< Back", focus=true}

    dlg:label{ id="status", label="Status", text="Connecting..." }
    dlg:label{ id="source", label="Source", text=spr and app.fs.fileName(spr.filename) or "No sprite" }
    dlg:button{ id="actions", text="> Menu", onclick=showMenu, focus=true }
    dlg:newrow()
    dlg:button{ text="X Stop", onclick=cleanup }
    dlg:button{ text="_ Hide" }

    -- GO

    if --[[ global ]]pribambase_start then
        -- plugin is loading now
        -- FIXME remove this condition, it's not needed
        if pribambase_settings.autostart then
            ws:connect()
            showChannelEditor()

            if pribambase_settings.autoshow then
                dlg:show{ wait=false }
            end
        end
    else
        -- launched from the menu
        ws:connect()
        dlg:show{ wait=false }
        showChannelEditor()
    end
end
