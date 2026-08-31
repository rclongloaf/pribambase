local PayloadCache = {}


function PayloadCache.new()
    local payloads = {}
    local cache = {}

    function cache:changed(spriteId, name, frameNumber, channel, image, force)
        local key = table.concat({
            tostring(spriteId),
            name,
            tostring(frameNumber),
            channel
        }, "\0")
        local signature = string.pack("<HH", image.width, image.height) .. image.bytes
        if not force and payloads[key] == signature then return false end
        payloads[key] = signature
        return true
    end

    function cache:clear()
        payloads = {}
    end

    return cache
end


return PayloadCache
