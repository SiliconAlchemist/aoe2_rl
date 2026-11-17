from pathlib import Path
import pytest
from lupa import LuaRuntime


def runtime(audited=True):
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute('''
        now=0; queue={}; sent={}; count=0
        IPC={StartServer=function() end, GetMessages=function() local q=queue; queue={}; return q end,
             Send=function(data) sent[#sent+1]=data end}
        ParseJSON=function(x) return x end
        GetAssignedPlayerId=function() return 1 end
        GetGameTime=function() return now end
        GetMapWidth=function() return 32 end; GetMapHeight=GetMapWidth
        GetAvailableSaveFiles=function() return {"pilot.aoe2spgame"} end
        DispatchLoadGame=function() return true end
        Vector3=function(x,y,z) return {x=x,y=y,z=z} end
        UnitsMove=function() count=count+1; return true end
        UnitsTargetObject=UnitsMove
        GetVictoryPlayer=function() return nil end
        IsEnemyPlayer=function(p) return p:GetId()==2 end
        function unit(id,owner,visible)
            return {IsVisible=function() return visible end,
                GetId=function() return id end, IsAlive=function() return true end,
                GetPosition=function() if not visible then error("hidden position accessed") end return {x=12,y=12} end,
                GetOwningPlayer=function() if not visible then error("hidden owner accessed") end return {GetId=function() return owner end} end,
                GetHitpoints=function() if not visible then error("hidden hp accessed") end return 30 end,
                GetMaxHitpoints=function() return 30 end}
        end
        GetObjectsByType=function() return {unit(1,1,true),unit(2,2,false)} end
    ''')
    module = lua.execute(Path("bridge/aoe2rl/adapter.lua").read_text())
    module.load(lua.table_from(dict(audited=audited, interval=.5, map_size=32, pipe="test", build="test")))
    module.init()
    return lua, module


def send(lua, module, **payload):
    lua.globals().queue = lua.table_from([lua.table_from(payload)])
    module.update()


def test_lua_blocks_until_audited():
    lua, m = runtime(False)
    send(lua, m, op="reset", request_id="r", save_game="pilot.aoe2spgame")
    assert "not complete" in lua.globals().sent[1]["error"]


def test_lua_inspection_is_read_only_and_fog_filtered_before_audit():
    lua, m = runtime(False)
    lua.execute('DispatchLoadGame=function() error("inspection must not reset") end')
    send(lua, m, op="inspect", request_id="probe")
    result = lua.globals().sent[1]
    assert result["op"] == "inspection"
    assert result["audited"] is False
    assert len(result["visible_units"]) == 1
    assert result["saves"][1] == "pilot.aoe2spgame"
    assert lua.globals().count == 0


def test_lua_inspection_engine_failure_is_reported():
    lua, m = runtime(False)
    lua.execute('GetAvailableSaveFiles=function() error("not in match") end')
    send(lua, m, op="inspect", request_id="probe")
    assert "not in match" in lua.globals().sent[1]["error"]


def test_lua_reset_visibility_rate_and_manual_exit():
    lua, m = runtime()
    send(lua, m, op="reset", request_id="r", save_game="pilot.aoe2spgame")
    m.init(); m.update()
    assert len(lua.globals().sent[1]["units"]) == 1
    send(lua, m, op="step", request_id="a", episode="r", seq=1, action=1, interval=.1)
    assert "limit" in lua.globals().sent[2]["error"]
    assert lua.globals().count == 0
    send(lua, m, op="step", request_id="b", episode="r", seq=1, action=1, interval=.5)
    assert lua.globals().count == 1
    m.finish(False)
    assert "no outcome inferred" in lua.globals().sent[3]["error"]


def test_lua_successful_timed_transition_and_stale_requests():
    lua, m = runtime()
    send(lua, m, op="reset", request_id="r", save_game="pilot.aoe2spgame")
    m.init(); m.update()
    send(lua, m, op="step", request_id="a", episode="r", seq=1, action=1, interval=.5)
    lua.globals().now = .5
    m.update()
    assert lua.globals().sent[2]["game_time"] == .5
    send(lua, m, op="step", request_id="b", episode="r", seq=1, action=1, interval=.5)
    assert "Stale" in lua.globals().sent[3]["error"]
    assert lua.globals().count == 1
