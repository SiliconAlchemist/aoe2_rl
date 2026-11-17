local M = {}
local cfg, player, pending, resetting, episode
local origin, seq, commands, last_command = 0, 0, 0, -1e9
local ready = false

local function reply(request, data)
    data.request_id = request.request_id
    IPC.Send(data)
end

local function fail(request, message)
    reply(request, {error = message})
end

local function snapshot(outcome)
    local units = {}
    for _, object in ipairs(GetObjectsByType(4)) do -- Archer, verified against ScenarioParser
        -- Visibility must be checked BEFORE any restricted object reads.
        if object:IsVisible() then
            local owner = object:GetOwningPlayer():GetId()
            if owner == 1 or owner == 2 then
                local pos = object:GetPosition()
                units[#units+1] = {id=object:GetId(), player=owner, x=pos.x, y=pos.y,
                    hp=object:GetHitpoints(), max_hp=object:GetMaxHitpoints(), visible=true}
            end
        end
    end
    return {schema=1, backend="de", build=cfg.build, episode=episode, seq=seq,
        game_time=GetGameTime()-origin, units=units, outcome=outcome, commands=commands,
        fairness="fog_limited", native_ai_suppressed=cfg.audited,
        shaping_potential=0} -- Sparse rewards until damage telemetry is live-validated.
end

local function dispatch(action)
    if action == 0 then return true end -- Continue current order; this is NOT a stop command.
    local owned, enemies = {}, {}
    local x, y = 0, 0
    for _, object in ipairs(GetObjectsByType(4)) do
        if object:IsVisible() and object:IsAlive() then
            if object:GetOwningPlayer():GetId() == player then
                owned[#owned+1] = object
                local pos = object:GetPosition()
                x, y = x+pos.x, y+pos.y
            elseif IsEnemyPlayer(object:GetOwningPlayer()) then
                enemies[#enemies+1] = object
            end
        end
    end
    if #owned == 0 then return false end
    x, y = x/#owned, y/#owned
    if action == 9 then
        local target, best = nil, math.huge
        for _, enemy in ipairs(enemies) do
            local pos = enemy:GetPosition()
            local distance = (pos.x-x)^2+(pos.y-y)^2
            if distance < best then target, best = enemy, distance end
        end
        return target ~= nil and UnitsTargetObject(owned, target)
    end
    local angle = (action-1)*math.pi/4
    local tx, ty = x+2*math.cos(angle), y+2*math.sin(angle)
    if tx < 0 or ty < 0 or tx >= GetMapWidth() or ty >= GetMapHeight() then return false end
    return UnitsMove(owned, Vector3(tx, ty, 0))
end

function M.load(config)
    cfg, player = config, GetAssignedPlayerId()
    IPC.StartServer(cfg.pipe)
end

function M.init()
    ready = false
    origin, seq, commands, last_command = GetGameTime(), 0, 0, -1e9
    if resetting then
        episode = resetting.request_id
        pending, resetting = resetting, nil
        pending.initial = true
    end
end

function M.update()
    if pending and pending.initial then
        if GetMapWidth() ~= cfg.map_size or GetMapHeight() ~= cfg.map_size then
            fail(pending, "Expected 32x32 pilot map; wrong saved game")
        else
            ready = true
            reply(pending, snapshot(nil))
        end
        pending = nil
    elseif pending and GetGameTime() >= pending.until_time then
        reply(pending, snapshot(nil))
        pending = nil
    end
    for _, raw in ipairs(IPC.GetMessages()) do
        local request = ParseJSON(raw)
        if request and request.request_id then
            if request.op == "ping" then
                reply(request, {op="pong", audited=cfg.audited, game_time=GetGameTime()})
            elseif request.op == "inspect" then
                -- Read-only diagnostics are allowed before the live audit. The build
                -- is a configuration label, not an engine compatibility measurement.
                local ok, data = pcall(function()
                    return {op="inspection", schema=1, configured_build=cfg.build,
                        audited=cfg.audited, player=player, game_time=GetGameTime(),
                        map_width=GetMapWidth(), map_height=GetMapHeight(),
                        visible_units=snapshot(nil).units, saves=GetAvailableSaveFiles()}
                end)
                if ok then reply(request, data)
                else fail(request, "Read-only inspection failed: "..tostring(data)) end
            elseif not cfg.audited then
                fail(request, "Live fog/suppression/reset audit is not complete; see LIVE_SETUP.md")
            elseif pending or resetting then
                fail(request, "An operation is already pending")
            elseif request.op == "reset" then
                local found = false
                for _, file in ipairs(GetAvailableSaveFiles()) do
                    if file == request.save_game and file:match("%.aoe2spgame$") then found = true end
                end
                if not found then
                    fail(request, "Requested verified save is not available in the DE load-game list")
                else
                    resetting, ready = request, false
                    if not DispatchLoadGame(request.save_game) then
                        resetting = nil
                        fail(request, "DE rejected saved-game load")
                    end
                end
            elseif request.op == "step" then
                local now = GetGameTime()
                if not ready or request.episode ~= episode or request.seq ~= seq+1 then
                    fail(request, "Stale episode or sequence")
                elseif type(request.interval) ~= "number" or request.interval < cfg.interval then
                    fail(request, "Action interval below configured limit")
                elseif type(request.action) ~= "number" or request.action%1 ~= 0 or request.action < 0 or request.action > 9 then
                    fail(request, "Unknown action")
                elseif now-last_command < cfg.interval then
                    fail(request, "Command rate exceeded")
                elseif not dispatch(request.action) then
                    -- Visibility may change between observation and command. Fail explicitly.
                    fail(request, "Command rejected or target no longer visible")
                else
                    seq = request.seq
                    if request.action ~= 0 then commands, last_command = commands+1, now end
                    pending = request
                    pending.until_time = now+request.interval
                end
            else
                fail(request, "Unsupported operation")
            end
        end
    end
end

function M.finish(hasWon)
    if resetting then return end -- Loading a new world is not a defeat.
    ready = false
    if not pending then return end
    local winner = GetVictoryPlayer()
    if not winner then
        fail(pending, "Game exited without a verified winner; no outcome inferred")
    else
        local outcome = winner:GetId() == player and "win" or "loss"
        reply(pending, snapshot(outcome))
    end
    pending = nil
end
return M
