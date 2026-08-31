local test = app.params["test"]
local result = app.params["result"]
if test == nil or result == nil then error("Expected test and result script parameters") end

local function report(message)
    print(message)
    local marker = io.open(result .. ".error", "w")
    if marker ~= nil then
        marker:write(message)
        marker:close()
    end
end

local chunk, loadError = loadfile(test)
if chunk == nil then
    report("Could not load Aseprite test: " .. tostring(loadError))
    error(loadError)
end

local ok, runtimeError = pcall(chunk)
if not ok then
    report("Aseprite test failed: " .. tostring(runtimeError))
    error(runtimeError)
end
