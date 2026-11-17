"""Create actual DE scenario files; never rename them to saved games."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import numpy as np


def generate(output, count=4, first_seed=0, version="1.55"):
    from AoE2ScenarioParser.scenarios.aoe2_de_scenario import AoE2DEScenario
    from AoE2ScenarioParser.datasets.units import UnitInfo
    from AoE2ScenarioParser.datasets.object_support import StartingAge, Civilization
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for seed in range(first_seed, first_seed+count):
        for side in (0, 1):
            rng = np.random.default_rng(seed)
            with contextlib.redirect_stdout(io.StringIO()):
                scenario = AoE2DEScenario.from_default(version)
                scenario.map_manager.map_size = 32
                scenario.player_manager.active_players = 2
                for tile in scenario.map_manager.terrain:
                    tile.terrain_id, tile.elevation = 0, 0
                for p in range(1, 9):
                    player = scenario.player_manager.players[p]
                    player.human = p == 1
                    player.civilization = Civilization.BYZANTINES
                    player.starting_age = StartingAge.FEUDAL_AGE
                    player.food = player.wood = player.gold = player.stone = 0
                    player.population_cap = 200
                    player.allied_victory = False
                # Mirror the same randomized geometry exactly when swapping sides.
                for p in (1, 2):
                    x = 10 if p == 1 else 20
                    for i in range(5):
                        ux, uy = x+float(rng.uniform(-1, 1)), 13+i+float(rng.uniform(-.3, .3))
                        if side:
                            ux, uy = 32-ux, 32-uy
                        scenario.unit_manager.add_unit(player=p, unit_const=UnitInfo.ARCHER.ID, x=ux, y=uy)
                    trigger = scenario.trigger_manager.add_trigger(f"Player {p} eliminated")
                    trigger.new_condition.own_fewer_objects(quantity=1, object_list=UnitInfo.ARCHER.ID, source_player=p)
                    trigger.new_effect.declare_victory(source_player=3-p, enabled=1)
                name = f"aoe2rl_{seed}_{side}.aoe2scenario"
                path = out/name
                scenario.write_to_file(str(path))
                # Parse the written result to catch structural corruption before delivery.
                loaded = AoE2DEScenario.from_file(str(path))
                assert len(loaded.unit_manager.get_all_units()) == 10
            manifest.append(dict(seed=seed, side=side, scenario=name,
                                 sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 save_game=None, live_verified=False))
    (out/"manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"scenarios": len(manifest), "directory": str(out), "live_verified": False}
