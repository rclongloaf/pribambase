local client = app.params["client"]
if client == nil or client == "" then
    error("Expected --script-param client=<built client directory>")
end

local files = {
    "Commands.lua",
    "Settings.lua",
    "Sync.lua"
}

for _, name in ipairs(files) do
    local path = app.fs.joinPath(client, name)
    local chunk, loadError = loadfile(path)
    if chunk == nil then
        error("Could not load " .. name .. ": " .. tostring(loadError))
    end
end

dofile(app.fs.joinPath(client, "Commands.lua"))
assert(type(init) == "function", "Commands.lua must define init(plugin)")
assert(type(pribambase_default_settings) == "table", "Default settings are missing")
assert(pribambase_default_settings.port == "34613", "Unexpected default port")

local result = app.params["result"]
if result == nil or result == "" then
    error("Expected --script-param result=<success marker path>")
end
local marker, openError = io.open(result, "w")
if marker == nil then
    error("Could not write smoke-test result: " .. tostring(openError))
end
marker:write("ok\n")
marker:close()

print("Pribambase Aseprite client smoke test passed")
