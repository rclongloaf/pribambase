-- Composite Pribambase paint layers at native size, using the extension's channel API.
local jobFile=assert(app.params.job)
local extension=app.fs.joinPath(app.fs.userConfigPath,"extensions","pribambase")
local channelsPath=app.fs.joinPath(extension,"Channels.lua")
assert(app.fs.isFile(channelsPath),"Install the Pribambase extension in Aseprite to export its channels.")
local Channels=dofile(channelsPath)
local Normals=dofile(app.fs.joinPath(extension,"Normals.lua"))
local rgba=app.pixelColor.rgba
local pixel=app.pixelColor
local ATLAS_EDGE=2048

local function write(path,data)
  local stream=assert(io.open(path,"wb"))
  assert(stream:write(data))
  stream:close()
end

local function read(path)
  local stream=assert(io.open(path,"rb"))
  local data=stream:read("*a")
  stream:close()
  return data
end

local function relative(root,...)
  return app.fs.joinPath(root,...)
end

local function save(image,path)
  image:saveAs(path)
  assert(app.fs.isFile(path),"Could not save "..path)
end

local function saveAtlas(channel,output)
  local width,height=channel.spec.width,channel.spec.height
  local cellWidth,cellHeight=width+2,height+2
  local maxCols=math.max(1,ATLAS_EDGE//cellWidth)
  local maxRows=math.max(1,ATLAS_EDGE//cellHeight)
  local capacity=maxCols*maxRows
  local tiles=channel.tiles
  local pages,regions={},{}
  local empty=string.rep("\0",cellWidth*4)

  for first=1,#tiles,capacity do
    local count=math.min(capacity,#tiles-first+1)
    local square=math.floor(math.sqrt(count*cellHeight/cellWidth)+0.5)
    local columns=math.min(maxCols,count,math.max(square,math.ceil(count/maxRows)))
    local rows=math.ceil(count/columns)
    local spec=ImageSpec(channel.spec)
    spec.width,spec.height=columns*cellWidth,rows*cellHeight
    local atlas=Image(spec)
    local stridePadding=string.rep("\0",atlas.rowStride-spec.width*4)
    local scanlines={}
    for row=0,rows-1 do
      for y=-1,height do
        local sourceRow=math.max(0,math.min(height-1,y))
        local start=sourceRow*channel.rowStride+1
        local strips={}
        for col=0,columns-1 do
          local index=first+row*columns+col
          if index<first+count then
            local line=tiles[index]:sub(start,start+width*4-1)
            -- Duplicate the edge pixels into a one-pixel gutter on each side.
            strips[#strips+1]=line:sub(1,4)..line..line:sub(-4)
          else
            strips[#strips+1]=empty
          end
        end
        scanlines[#scanlines+1]=table.concat(strips)..stridePadding
      end
    end
    atlas.bytes=table.concat(scanlines)
    local page=#pages
    local name=string.format("%s_atlas_%02d.png",channel.stem,page)
    save(atlas,relative(output,name))
    pages[#pages+1]=name
    for i=0,count-1 do
      regions[first+i]={page,(i%columns)*cellWidth+1,(i//columns)*cellHeight+1,width,height}
    end
  end
  local rects={}
  for i,index in ipairs(channel.frames) do rects[i]=regions[index] end
  return {pages=pages,rects=rects}
end

local function recenter(image,dx,dy)
  if dx==0 and dy==0 then return image end
  local shifted=Image(image.spec)
  -- Channel-packed ORME alpha is data. Move the raw RGBA bytes without compositing.
  for y=math.max(0,dy),math.min(image.height-1,image.height-1+dy) do
    for x=math.max(0,dx),math.min(image.width-1,image.width-1+dx) do
      shifted:drawPixel(x,y,image:getPixel(x-dx,y-dy))
    end
  end
  return shifted
end

local function linear(s)
  s=s/255
  return s<=0.04045 and s/12.92 or ((s+0.055)/1.055)^2.4
end

local function srgb(n)
  local s=n<=0.0031308 and n*12.92 or 1.055*n^(1/2.4)-0.055
  return math.max(0,math.min(255,math.floor(s*255+.5)))
end

local function emissionMap(base,orme)
  local result=Image(base.width,base.height,ColorMode.RGB)
  for y=0,base.height-1 do
    for x=0,base.width-1 do
      local p=base:getPixel(x,y)
      local power=pixel.rgbaA(orme:getPixel(x,y))/255
      result:drawPixel(x,y,rgba(srgb(linear(pixel.rgbaR(p))*power),
        srgb(linear(pixel.rgbaG(p))*power),srgb(linear(pixel.rgbaB(p))*power),255))
    end
  end
  return result
end

local function ormMap(orme)
  local result=Image(orme.width,orme.height,ColorMode.RGB)
  for it in result:pixels() do
    local p=orme:getPixel(it.x,it.y)
    it(rgba(pixel.rgbaR(p),pixel.rgbaG(p),pixel.rgbaB(p),255))
  end
  return result
end

local function normalMap(normal)
  local result=Image(normal.spec)
  for it in result:pixels() do
    local p=normal:getPixel(it.x,it.y)
    if pixel.rgbaA(p)>0 then
      it(rgba(pixel.rgbaR(p),pixel.rgbaG(p),pixel.rgbaB(p),255))
    else
      it(rgba(128,128,255,255))
    end
  end
  return result
end

local function missingNormalPixels(normal, reference)
  local missing=0
  for it in reference:pixels() do
    if pixel.rgbaA(it())>0 and pixel.rgbaA(normal:getPixel(it.x,it.y))<255 then
      missing=missing+1
    end
  end
  return missing
end

local function export_asset(job)
  local asset=job.asset
  local sprite=assert(app.open(asset.sprite),asset.sprite)
  assert(Channels.hasStructure(sprite),"Pribambase layers missing in "..asset.sprite)
  assert(sprite.colorMode==ColorMode.RGB and sprite.width==asset.width and sprite.height==asset.height,
    "Aseprite canvas no longer matches the UV canvas in "..asset.id)
  assert(#asset.poses==1 or #sprite.frames==#asset.poses,
    "Blender pose count must match the Aseprite frame count in "..asset.id)
  if #sprite.frames>1 then
    assert(#sprite.tags==1,"Expected one forward animation tag in "..asset.id)
    local tag=sprite.tags[1]
    assert(tag.name=="loop" and tag.aniDir==AniDir.FORWARD and tag.fromFrame.frameNumber==1
      and tag.toFrame.frameNumber==#sprite.frames,"The loop tag must cover all frames in "..asset.id)
  end
  local blank=Image(sprite.spec)
  local references={}

  local channels,durations={},{}
  local function record(name,stem,image,index)
    local channel=channels[name]
    if not channel then
      channel={stem=stem,spec=image.spec,rowStride=image.rowStride,tiles={},frames={},seen={}}
      channels[name]=channel
    end
    local bytes=image.bytes
    local tile=channel.seen[bytes]
    if not tile then
      tile=#channel.tiles+1
      channel.tiles[tile]=bytes
      channel.seen[bytes]=tile
    end
    channel.frames[index]=tile
  end

  for i,frame in ipairs(sprite.frames) do
    local pose=asset.poses[i] or asset.poses[1]
    local dx,dy=pose.shift[1],pose.shift[2]
    local normalReference=references[pose.normalReference]
    if not normalReference then
      local bytes=read(pose.normalReference)
      assert(#bytes==sprite.width*sprite.height*4,"Invalid normal reference size")
      normalReference=Image(sprite.spec)
      normalReference.bytes=bytes
      references[pose.normalReference]=normalReference
    end
    local poseReference=recenter(normalReference,dx,-dy)
    -- A transparent reference isolates the author's paint during strict validation.
    Normals.receiveDefault(sprite,i,job.normalFallback and poseReference or blank,"FLAT")
    local normal=assert(Channels.renderNormal(sprite,i),"Could not compose World Normal")
    if not job.normalFallback then
      local missing=missingNormalPixels(normal,poseReference)
      if missing>0 then
        sprite:close()
        return {error=string.format(
          "World Normal, кадр %d. Пикселей видимой геометрии без полной нормали — %d. " ..
          "Выбери --normal-fallback flat или --normal-fallback smooth, либо дорисуй World Normal в Aseprite и повтори экспорт.",
          i,missing)}
      end
    end

    local base=Channels.renderBaseColor(sprite,i)
    local orme=assert(Channels.packORME(sprite,i))
    durations[i]=math.floor(frame.duration*1000+.5)
    local restColor=recenter(base,-dx,dy)
    local restOrme=recenter(orme,-dx,dy)
    record("baseColor","base_color",restColor,i)
    record("orm","orm",ormMap(restOrme),i)
    record("worldNormal","world_normal",normalMap(recenter(normal,-dx,dy)),i)
    if asset.emissionStrength>0 then
      record("emission","emission",emissionMap(restColor,restOrme),i)
    end
    if job.packets then
      local width,height=sprite.width,sprite.height
      local prefix=relative(job.packets,asset.id.."."..i)
      local source=sprite.filename
      local ib=base.bytes
      local pb=orme.bytes
      write(prefix..".base",string.pack("<BHHs4s4",string.byte("I"),width,height,source,ib))
      write(prefix..".orme",string.pack("<BHHI4s4s4s4",string.byte("P"),width,height,i,"orme",source,pb))
      write(prefix..".rest-orme",restOrme.bytes)
    end
  end
  sprite:close()
  local result={durations=durations,channels={}}
  local output=relative(job.output,"textures")
  for name,channel in pairs(channels) do
    if #durations==1 then
      local image=Image(channel.spec)
      image.bytes=channel.tiles[1]
      local filename=channel.stem.."_00.png"
      save(image,relative(output,filename))
      result.channels[name]={file=filename}
    else
      result.channels[name]=saveAtlas(channel,output)
    end
  end
  return result
end

local job=json.decode(read(jobFile))
write(job.metadata,json.encode(export_asset(job)))
