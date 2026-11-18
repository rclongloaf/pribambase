-- World-space unit directions. RGB is data: encode (n + 1) / 2 without gamma.
local M = {}
local palettes, grids = {}, {}
-- global_iso_v1 in blender/projection.py: orthographic, elevation 30 degrees.
M.right = {x=1, y=0, z=0}
M.up = {x=0, y=0.5, z=math.sqrt(3)/2}
M.front = {x=0, y=-math.sqrt(3)/2, z=0.5}

function M.normalize(v)
    if v == nil then return nil end
    local length = math.sqrt(v.x*v.x + v.y*v.y + v.z*v.z)
    if length < 1e-8 then return nil end
    return {x=v.x/length, y=v.y/length, z=v.z/length}
end

function M.dot(a, b)
    return a.x*b.x + a.y*b.y + a.z*b.z
end

function M.decode(pixel)
    if pixel == nil or app.pixelColor.rgbaA(pixel) == 0 then return nil end
    return M.normalize{
        x=app.pixelColor.rgbaR(pixel)/127.5-1,
        y=app.pixelColor.rgbaG(pixel)/127.5-1,
        z=app.pixelColor.rgbaB(pixel)/127.5-1
    }
end

function M.color(v)
    v = assert(M.normalize(v), "A normal direction must be nonzero")
    local function byte(n) return math.max(0, math.min(255, math.floor((n+1)*127.5+0.5))) end
    return Color{r=byte(v.x), g=byte(v.y), b=byte(v.z), a=255}
end

function M.angle(a, b)
    if a == nil or b == nil then return nil end
    return math.deg(math.acos(math.max(-1, math.min(1, M.dot(a, b)))))
end

function M.visible(n, tolerance)
    return n ~= nil and M.dot(n, M.front) >= -(tolerance or 1e-7)
end

-- An encoded tangent normal can round slightly behind the horizon in RGB8.
function M.paintable(n) return M.visible(n, 0.006) end

function M.inPlane(n, plane)
    local component = ({XY="z", XZ="y", YZ="x"})[plane]
    return not component or math.abs(n[component]) < 1e-7
end

function M.fromDisk(u, v)
    local length = u*u+v*v
    if length > 1+1e-9 then return nil end
    local depth = math.sqrt(math.max(0, 1-length))
    return M.normalize{x=u, y=M.up.y*v+M.front.y*depth, z=M.up.z*v+M.front.z*depth}
end

function M.toDisk(n) return M.dot(n, M.right), M.dot(n, M.up) end

function M.fromCameraAngles(bearing, tilt)
    return M.fromDisk(math.cos(bearing)*math.sin(tilt), math.sin(bearing)*math.sin(tilt))
end

-- Active rotations around fixed WORLD axes, starting from -Y.
-- Restrict the first angle to +/-90; the second sweeps a full turn.
function M.ordered(first, second, order)
    local s, c, t, d = math.sin(first), math.cos(first), math.sin(second), math.cos(second)
    if order == "XZ" then return {x=c*t, y=-c*d, z=-s} end
    return {x=s, y=-c*d, z=-c*t}
end

local landmarks
function M.landmarks()
    if landmarks then return landmarks end
    landmarks = {}
    for x=-1,1 do for y=-1,1 do for z=-1,1 do
        local n = M.normalize{x=x,y=y,z=z}
        if M.visible(n) then
            local count = math.abs(x)+math.abs(y)+math.abs(z)
            local name = string.format("[%d,%d,%d]", x,y,z)
            if count == 1 then
                name = (x+y+z > 0 and "+" or "-") .. (x ~= 0 and "X" or y ~= 0 and "Y" or "Z")
            end
            landmarks[#landmarks+1] = {n=n, name=name, axis=count == 1}
        end
    end end end
    return landmarks
end

function M.palette(divisions, order)
    divisions = math.max(1, math.min(12, math.floor(divisions)))
    order = order or "ZX"
    local key = divisions .. order
    if palettes[key] then return palettes[key] end
    local result, seen = {}, {}
    local function add(n)
        if not M.visible(n) then return end
        local identity = string.format("%d,%d,%d", math.floor(n.x*1e6+0.5),
            math.floor(n.y*1e6+0.5), math.floor(n.z*1e6+0.5))
        if not seen[identity] then seen[identity]=true result[#result+1]=n end
    end
    local step = math.pi/(2*divisions)
    for first=-divisions,divisions do
        for second=0,4*divisions-1 do add(M.ordered(first*step, second*step, order)) end
    end
    -- Shared exact anchors remain available even at coarse angular steps.
    for _,point in ipairs(M.landmarks()) do add(point.n) end
    palettes[key] = result
    return result
end

function M.quantize(v, divisions, order, plane)
    v = assert(M.normalize(v), "A normal direction must be nonzero")
    if not M.paintable(v) then return nil end
    if not divisions or divisions == 0 then
        if plane and plane ~= "Any" then
            local component = ({XY="z", XZ="y", YZ="x"})[plane]
            local projected = {x=v.x, y=v.y, z=v.z}
            if component then projected[component]=0 end
            projected = M.normalize(projected)
            if not projected then
                projected = {x=M.front.x,y=M.front.y,z=M.front.z}
                if component then projected[component]=0 end
                projected = M.normalize(projected)
            end
            if M.visible(projected) then return projected end
            -- Closest endpoint of the plane's visible semicircle. Keep Free continuous.
            local horizon = plane == "YZ" and {x=0,y=-M.front.z,z=M.front.y} or {x=1,y=0,z=0}
            if M.dot(v,horizon) < 0 then
                horizon = {x=-horizon.x,y=-horizon.y,z=-horizon.z}
            end
            return M.normalize(horizon)
        end
        return v
    end
    local best, score
    for _,candidate in ipairs(M.palette(divisions, order)) do
        if M.inPlane(candidate, plane) then
            local dot = M.dot(v, candidate)
            if score == nil or dot > score then best, score = candidate, dot end
        end
    end
    return best and {x=best.x, y=best.y, z=best.z} or nil
end

-- Clip sampled spherical curves to the camera horizon, including exact crossings.
function M.clipCurve(points)
    local segments, segment, previous = {}, {}, nil
    local function flush()
        if #segment > 1 then segments[#segments+1] = segment end
        segment = {}
    end
    for _,n in ipairs(points) do
        local visible = M.visible(n)
        if previous and visible ~= M.visible(previous) then
            local a, b = M.dot(previous,M.front), M.dot(n,M.front)
            local t = a/(a-b)
            segment[#segment+1] = M.normalize{x=previous.x+t*(n.x-previous.x),
                y=previous.y+t*(n.y-previous.y), z=previous.z+t*(n.z-previous.z)}
            if not visible then flush() end
        end
        if visible then segment[#segment+1] = n end
        previous = n
    end
    flush()
    return segments
end

function M.grid(divisions, order)
    if divisions == 0 then return {} end
    local key = divisions .. order
    if grids[key] then return grids[key] end
    local lines, step = {}, math.pi/(2*divisions)
    local function add(points)
        for _,segment in ipairs(M.clipCurve(points)) do lines[#lines+1]=segment end
    end
    for first=-divisions+1,divisions-1 do
        local points = {}
        for i=0,144 do points[#points+1]=M.ordered(first*step, -math.pi+i*math.pi/72, order) end
        add(points)
    end
    for second=0,4*divisions-1 do
        local points = {}
        for i=0,72 do points[#points+1]=M.ordered(-math.pi/2+i*math.pi/72, second*step, order) end
        add(points)
    end
    grids[key] = lines
    return lines
end

function M.planeCurve(plane)
    local points = {}
    for i=0,144 do
        local c,s = math.cos(i*math.pi/72), math.sin(i*math.pi/72)
        points[#points+1] = plane == "XY" and {x=c,y=s,z=0}
            or plane == "XZ" and {x=c,y=0,z=s} or {x=0,y=c,z=s}
    end
    return M.clipCurve(points)
end

return M
