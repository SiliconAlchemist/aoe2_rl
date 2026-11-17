import contextlib
import io
import json
from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario
from AoE2ScenarioParser.datasets.units import UnitInfo
from aoe2rl.scenarios import generate


def test_written_scenarios_have_balanced_mirrored_units(tmp_path):
    result = generate(tmp_path, count=1)
    assert result["scenarios"] == 2 and result["live_verified"] is False
    with contextlib.redirect_stdout(io.StringIO()):
        a = AoE2DEScenario.from_file(str(tmp_path/"aoe2rl_0_0.aoe2scenario"))
        b = AoE2DEScenario.from_file(str(tmp_path/"aoe2rl_0_1.aoe2scenario"))
    assert a.player_manager.active_players == 2
    assert a.map_manager.map_size == 32
    for ua, ub in zip(a.unit_manager.get_all_units(), b.unit_manager.get_all_units()):
        assert ua.unit_const == ub.unit_const == UnitInfo.ARCHER.ID
        assert abs(ua.x+ub.x-32) < .00001
        assert abs(ua.y+ub.y-32) < .00001
    manifest = json.loads((tmp_path/"manifest.json").read_text())
    assert all(x["save_game"] is None for x in manifest)
