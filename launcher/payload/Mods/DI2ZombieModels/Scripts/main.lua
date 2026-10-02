-- DI2 Zombie Models (UE4SS mod).
--
-- 1. Loads di2swap.dll from this mod's folder: it does the model swap from inside the game (see
--    tools/di2swap/di2swap.c) using swaps.txt, written by the mod launcher.
-- 2. Safety net: a zombie that still spawns with the engine's fallback "mannequin" model (possibly
--    invisible, and able to block "kill them all" objectives) gets one of the chosen models with the
--    engine's own SetSkeletalMesh, and is made visible.
-- 3. F3 = unstick quest: removes the zombies within 60 m (last resort when an objective waits for
--    zombies that never became active).
--
-- Notes for this game + UE4SS 3.0.1: characters are tracked with NotifyOnNewObject (FindAllOf on every
-- check stutters: 20-90 ms); the model given to a mannequin is taken from a live zombie that already
-- uses it (StaticFindObject can return a model being unloaded and crash); IsValid relies on the
-- engine's delete notifications, so zombies destroyed in bulk on area changes are simply dropped.

local cfg = require("config")

local TAG = "[DI2ZombieModels] "
local function log(fmt, ...) print(TAG .. string.format(fmt, ...) .. "\n") end

-- di2swap.dll sits next to the game's exe and is loaded by name only: Windows looks in the exe's
-- folder first, so no path goes through Lua (whose loader is ANSI: a game folder with non-latin
-- characters would break a full path). Loading it starts its worker thread; again = no-op.
do
    local ok, err = package.loadlib("di2swap.dll", "*")
    log("di2swap.dll: %s", ok and "loaded" or ("not loaded: " .. tostring(err)))
end

local FALLBACK = { SK_BaseZombiePreview = true, SK_BaseHumanPreview = true, SK_MaleStandard = true }
-- special zombies keep their look (it signals a danger)
local SPECIAL = { "Burning", "Fireman", "Electric", "Shocking", "Caustic", "Corrosive", "Hazmat", "FuelTank",
                  "GrenadeVest", "RiotGear", "Spiky", "Vicious", "Loot", "Satchel", "Boss", "Apex", "Crusher",
                  "Butcher", "Screamer", "Slobber", "Thug", "Burster", "Mutator", "Crawler" }
-- a new zombie shows the fallback model until the game gives it its own: it counts as a mannequin
-- only if it stays so for GRACE_S seconds
local GRACE_S = 3

local tracked = {}         -- characters being followed
local done = {}            -- actor address -> model we gave it
local fallback_since = {}  -- actor address -> since when it shows the fallback model
local kind_of = {}         -- blueprint class -> zombie type (false = not handled)
local meshes = {}          -- model name -> SkeletalMesh used by a live zombie (current check only)
local stats = { repaired = 0 }

local function short_name(obj)
    if obj and obj:IsValid() then return obj:GetFName():ToString() end
    return nil
end

local function class_kind(cls)
    local k = kind_of[cls]
    if k ~= nil then return k end
    k = false
    for _, s in ipairs(SPECIAL) do
        if cls:find(s, 1, true) then kind_of[cls] = false; return false end
    end
    if cls:find("InsectSwarm", 1, true) then k = "insect"
    elseif cls:match("^BP_Walker") then k = "walker"
    elseif cls:match("^BP_Shambler") then k = "shambler"
    elseif cls:match("^BP_Runner") then k = "runner" end
    kind_of[cls] = k
    return k
end

-- same model for the same actor
local function pick(list, addr)
    if #list == 1 then return list[1] end
    return list[(addr // 16) % #list + 1]
end

-- only the Mesh component: propagating would also show hidden helper shapes
local function make_visible(actor, comp)
    pcall(function() actor:SetActorHiddenInGame(false) end)
    pcall(function() comp:SetHiddenInGame(false, false) end)
    pcall(function() comp:SetVisibility(true, false) end)
end

local function check(actor)
    local comp = actor.Mesh
    if not (comp and comp:IsValid()) then return end
    local cur = short_name(comp.SkeletalMesh) or "none"
    local addr = actor:GetAddress()
    if done[addr] == cur then return end
    if not (FALLBACK[cur] or cur == "none") then fallback_since[addr] = nil; return end
    local since = fallback_since[addr]
    if not since then fallback_since[addr] = os.clock(); return end
    if os.clock() - since < GRACE_S then return end

    local cls = actor:GetClass():GetFName():ToString()
    local kind = class_kind(cls)
    if not kind then return end
    local list = (cfg.classes and cfg.classes[cls:lower()]) or cfg[kind]
    if not list or #list == 0 then return end
    local target = pick(list, addr)
    local mesh = meshes[target]
    if not mesh then return end   -- no live zombie uses it right now: next check
    comp:SetSkeletalMesh(mesh, true)
    if short_name(comp.SkeletalMesh) == target then
        done[addr] = target
        make_visible(actor, comp)
        stats.repaired = stats.repaired + 1
        log("mannequin repaired: %s -> %s", cls, target)
    end
end

-- the PlayerController is looked up again only when the kept one is gone (at most every 5 s)
local pc_cached, pc_next = nil, 0
local function player_pawn()
    if not (pc_cached and pc_cached:IsValid()) then
        if os.clock() < pc_next then return nil end
        pc_next = os.clock() + 5
        pc_cached = FindFirstOf("PlayerController")
        if not (pc_cached and pc_cached:IsValid()) then pc_cached = nil; return nil end
    end
    local pawn = pc_cached.Pawn
    if pawn and pawn:IsValid() then return pawn end
    return nil
end

local wanted = {}   -- models chosen in the launcher
for _, kind in ipairs({ "walker", "shambler", "runner", "insect" }) do
    for _, n in ipairs(cfg[kind] or {}) do wanted[n] = true end
end
for _, ms in pairs(cfg.classes or {}) do
    for _, n in ipairs(ms) do wanted[n] = true end
end

local function track(obj)
    if obj:GetFName():ToString():sub(1, 9) ~= "Default__" then table.insert(tracked, obj) end
end
for _, c in ipairs(FindAllOf("Character") or {}) do track(c) end
NotifyOnNewObject("/Script/Engine.Character", track)

local function sweep()
    meshes = {}
    if not player_pawn() then return end   -- menu, loading screens
    local alive = {}
    for _, a in ipairs(tracked) do
        if a:IsValid() then
            table.insert(alive, a)
            local comp = a.Mesh
            if comp and comp:IsValid() then
                local sk = comp.SkeletalMesh
                local n = short_name(sk)
                if n and wanted[n] and not meshes[n] then meshes[n] = sk end
            end
        end
    end
    tracked = alive
    local seen, since = {}, {}
    for _, a in ipairs(alive) do
        local addr = a:GetAddress()
        local ok, err = pcall(check, a)
        if not ok then log("error: %s", tostring(err)) end
        seen[addr], since[addr] = done[addr], fallback_since[addr]
    end
    done, fallback_since = seen, since
end

local busy = false
LoopAsync(cfg.interval_ms or 500, function()
    if not busy then
        busy = true
        ExecuteInGameThread(function()
            local ok, err = pcall(sweep)
            if not ok then log("check error: %s", tostring(err)) end
            busy = false
        end)
    end
    return false
end)

-- F3: unstick quest - removes the zombies within 60 m of the player
RegisterKeyBind(Key.F3, function()
    ExecuteInGameThread(function()
        local ok, err = pcall(function()
            local pawn = player_pawn()
            if not pawn then return end
            local p, me, n = pawn:K2_GetActorLocation(), pawn:GetAddress(), 0
            for _, a in ipairs(tracked) do
                if a:IsValid() and a:GetAddress() ~= me then
                    local cls = a:GetClass():GetFName():ToString()
                    if cls:match("^BP_") and not cls:match("Player") then
                        local l = a:K2_GetActorLocation()
                        if (l.X - p.X) ^ 2 + (l.Y - p.Y) ^ 2 + (l.Z - p.Z) ^ 2 <= 6000 * 6000 then
                            a:K2_DestroyActor()
                            n = n + 1
                        end
                    end
                end
            end
            log("F3 (unstick quest): %d zombies removed within 60 m", n)
        end)
        if not ok then log("F3 error: %s", tostring(err)) end
    end)
end)

if (cfg.summary_s or 0) > 0 then
    LoopAsync(cfg.summary_s * 1000, function()
        log("tracked %d, mannequins repaired %d", #tracked, stats.repaired)
        return false
    end)
end

log("active")
