-- Simple scripted baseline. Assign to the opposing player with native AI suppressed.
local next_time = 0
function Init() next_time = 0 end
function Update()
    local now = GetGameTime()
    if now < next_time then return end
    next_time = now+0.5
    local mine, targets = {}, {}
    local x, y = 0, 0
    for _, object in ipairs(GetObjectsByType(4)) do
        if object:IsVisible() and object:IsAlive() then
            if object:GetOwningPlayer():GetId() == GetAssignedPlayerId() then
                mine[#mine+1] = object
                local pos = object:GetPosition()
                x, y = x+pos.x, y+pos.y
            elseif IsEnemyPlayer(object:GetOwningPlayer()) then
                targets[#targets+1] = object
            end
        end
    end
    if #mine == 0 then return end
    x, y = x/#mine, y/#mine
    local target, best = nil, math.huge
    for _, enemy in ipairs(targets) do
        local pos = enemy:GetPosition()
        local distance = (pos.x-x)^2+(pos.y-y)^2
        if distance < best then target, best = enemy, distance end
    end
    if target then
        UnitsTargetObject(mine, target)
    else
        UnitsMove(mine, Vector3(GetMapWidth()/2, GetMapHeight()/2, 0))
    end
end
