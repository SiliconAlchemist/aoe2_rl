-- Session control only: this module never issues unit commands.
-- Assign ONLY to Player 1 in a disposable single-player training match.
local generation = 0
local cache, order = {}, {}

local function reply(request, data)
    data.request_id = request.request_id
    IPC.Send(data)
end

function Load(playerId)
    if playerId ~= 1 then error("opening_reset must be assigned to Player 1") end
    IPC.StartServer("AoE2RLOpeningReset")
end

function Init()
    generation = generation + 1
end

function Update()
    for _, raw in ipairs(IPC.GetMessages()) do
        local request = ParseJSON(raw)
        if type(request) == "table" and type(request.request_id) == "string" then
            if cache[request.request_id] then
                reply(request, cache[request.request_id])
            else
                local state = GetRandomMapStartStatus()
                local result = {generation=generation, game_time=GetGameTime()}
                if request.op == "ping" then
                    result.ready = state and state.sessionActive and not state.multiplayer and not state.replay
                    result.effective_seed = GetEffectiveRandomMapSeed()
                elseif request.op == "restart" then
                    if not state or not state.sessionActive or state.multiplayer or state.replay then
                        result.error = "Restart requires a running single-player match, not a replay"
                    elseif request.generation ~= generation then
                        result.error = "Stale restart generation; no restart sent"
                    else
                        result.accepted = DispatchRestartGame()
                        if not result.accepted then
                            result.error = "Restart rejected: check Multithreading and Tournament Mode are off"
                        end
                    end
                else
                    result.error = "Unknown reset-helper operation"
                end
                cache[request.request_id] = result
                order[#order+1] = request.request_id
                if #order > 64 then cache[table.remove(order, 1)] = nil end
                reply(request, result)
            end
        end
    end
end

function Unload()
    IPC.StopServer()
end
