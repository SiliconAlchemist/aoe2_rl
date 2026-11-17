-- CONTROL 1.0 documented API. Live execution is unverified on this machine.
local cfg = require("config")
local adapter = require("adapter")
function Load() adapter.load(cfg) end
function Init() adapter.init() end
function Update() adapter.update() end
function End(hasWon) adapter.finish(hasWon) end
function Unload() IPC.StopServer() end
