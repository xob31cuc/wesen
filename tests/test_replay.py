import json
import os
import subprocess
import sys

from Wesen.objects import wesen as wesen_module
from Wesen.replay.hash import world_hash
from Wesen.replay.recorder import ReplayRecorder
from Wesen.replay.replayer import Replayer
from Wesen.wesend import Wesend
from Wesen.world import World


def world_info(wesen_count=1, food_count=2):
    return {
        "gui": {
            "enable": False,
            "source": "gui",
            "size": 100,
            "pos": "0,0",
        },
        "world": {"length": 12},
        "wesen": {
            "sources": ["WindlePoons"],
            "count": wesen_count,
            "energy": 200,
            "maxage": 1000,
        },
        "food": {
            "count": food_count,
            "energy": 10,
            "maxamount": 1000,
            "maxage": 1000,
            "growrate": 0.2,
            "seedrate": 0.002,
        },
        "range": {
            "seed": 3,
            "look": 12,
            "closer_look": 12,
            "talk": 12,
        },
        "time": {
            "init": 25,
            "max": 100,
            "look": 1,
            "closerlook": 2,
            "talk": 1,
            "broadcast": 1,
            "move": 1,
            "eat": 1,
            "vomit": 1,
            "donate": 1,
            "attack": 1,
            "reproduce": 1,
        },
    }


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def record_world(path, turns=3):
    world = World(world_info())
    recorder = ReplayRecorder(path, run_id="test-run")
    world.setRecorder(recorder)
    recorder.start(world)
    hashes = []
    for _ in range(turns):
        world.main()
        hashes.append(world_hash(world))
    recorder.close()
    return world, hashes


def test_records_header_frames_and_hashes(tmp_path):
    replay_path = tmp_path / "run.jsonl"
    _world, hashes = record_world(replay_path, turns=4)
    events = read_events(replay_path)

    assert events[0]["event"] == "replay_header"
    assert events[0]["schema"] == 1
    assert events[0]["mode"] == "snapshot"
    assert "initial_state" in events[0]
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))

    frames = [event for event in events if event["event"] == "frame"]
    turn_ends = [event for event in events if event["event"] == "turn_end"]
    assert len(frames) == len(turn_ends) == 4
    assert [frame["world_hash"] for frame in frames] == hashes
    assert [event["world_hash"] for event in turn_ends] == hashes


def test_wesend_record_option_writes_replay(tmp_path):
    replay_path = tmp_path / "wesend.jsonl"
    config = world_info(wesen_count=1, food_count=1)
    config["wesen"]["sources"] = "WindlePoons"
    config.update(
        {
            "resume": False,
            "record_replay": str(replay_path),
            "replay": None,
            "verify_replay": None,
        }
    )
    wesend = Wesend(config)
    wesend.mainLoop()
    wesend.mainLoop()
    wesend.close()

    events = read_events(replay_path)
    assert events[0]["event"] == "replay_header"
    frames = [event for event in events if event["event"] == "frame"]
    assert len(frames) == 2


def test_frames_restore_and_verify(tmp_path):
    replay_path = tmp_path / "run.jsonl"
    _world, hashes = record_world(replay_path, turns=3)

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    restored_hashes = []
    while replayer.step(replay_world):
        restored_hashes.append(world_hash(replay_world))

    assert restored_hashes == hashes
    verification = Replayer(replay_path).verify()
    assert verification.ok
    assert verification.frames == 3


def test_stable_ids_survive_restore_and_continue_monotonically():
    world = World(world_info(wesen_count=1, food_count=1))
    state = world.persist()
    original_ids = sorted(world.objects)

    restored = World(state, createObjects=False)
    restored.restore(state)
    assert sorted(restored.objects) == original_ids
    restored_ids = [obj.sim_id for obj in restored.objects.values()]
    assert restored_ids == original_ids
    assert all(
        obj.getDescriptor()["id"] == obj.sim_id for obj in restored.objects.values()
    )

    expected_id = state["next_sim_id"]
    new_food = restored.AddObject(restored.infoAllWorld["food"])
    assert new_food.sim_id == expected_id
    assert new_food.sim_id > max(original_ids)


def test_replay_does_not_run_source_ai(tmp_path, monkeypatch):
    replay_path = tmp_path / "run.jsonl"
    record_world(replay_path, turns=2)

    def forbidden_import(*_args, **_kwargs):
        raise AssertionError("source module imported during replay")

    monkeypatch.setattr(wesen_module.importlib, "import_module", forbidden_import)
    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert replayer.step(replay_world)
    assert not replayer.step(replay_world)


def test_actions_and_autonomous_food_effects_have_stable_ids(tmp_path):
    replay_path = tmp_path / "effects.jsonl"
    world = World(world_info(wesen_count=0, food_count=0))
    recorder = ReplayRecorder(replay_path, run_id="effects-run")
    world.setRecorder(recorder)
    recorder.start(world)

    wesen_info = world.infoAllWorld["wesen"].copy()
    wesen_info.update({"source": "WindlePoons", "position": [1, 1]})
    actor = world.AddObject(wesen_info)
    target_info = wesen_info.copy()
    target_info.update({"position": [2, 1], "energy": 40})
    target = world.AddObject(target_info)
    food_info = world.infoAllWorld["food"].copy()
    food_info.update({"position": [2, 1], "energy": 20})
    food = world.AddObject(food_info)
    actor.time = 100

    assert actor.wesenSource.Move([1, 0])
    assert actor.wesenSource.Eat(food.sim_id)
    child_id = actor.wesenSource.Reproduce()
    assert isinstance(child_id, int)
    assert actor.wesenSource.Donate(5, target.sim_id)
    assert actor.wesenSource.Attack(target.sim_id)
    assert actor.wesenSource.Vomit(5)

    seeder_info = world.infoAllWorld["food"].copy()
    seeder_info.update(
        {
            "position": [8, 8],
            "energy": 5,
            "seedrate": 1.0,
            "growrate": 1.0,
        }
    )
    seeder = world.AddObject(seeder_info)
    seeder.age = 11
    ids_before_seed = set(world.objects)
    seeder.main()
    assert set(world.objects) - ids_before_seed

    world.turns = 1
    recorder.record_turn(world)
    recorder.close()
    events = read_events(replay_path)

    action_names = {
        event["name"] for event in events if event["event"] == "source_action"
    }
    assert {"Move", "Eat", "Reproduce", "Donate", "Attack", "Vomit"} <= (
        action_names
    )
    known_ids = {
        obj["sim_id"]
        for event in events
        if event["event"] in {"replay_header", "frame"}
        for obj in (
            event["initial_state"]["objects"]
            if event["event"] == "replay_header"
            else event["state"]["objects"]
        )
    }
    known_ids.update(
        event["object_id"] for event in events if event["event"] == "object_created"
    )
    for event in events:
        for key in ("actor", "object_id"):
            if key in event:
                assert isinstance(event[key], int)
                assert event[key] in known_ids


def test_snapshot_callbacks_remain_gui_compatible(tmp_path):
    replay_path = tmp_path / "run.jsonl"
    record_world(replay_path, turns=1)
    replayer = Replayer(replay_path)
    world = replayer.create_world()
    calls = []
    world.setCallbacks(
        {
            "AddObject": lambda sim_id, obj: calls.append(
                ("add", sim_id, obj["id"])
            ),
            "DeleteObject": lambda sim_id: calls.append(("delete", sim_id)),
            "UpdatePos": lambda sim_id, obj: calls.append(
                ("move", sim_id, obj["id"])
            ),
        }
    )

    assert replayer.step(world)
    assert world.getDescriptor()
    assert any(call[0] == "delete" for call in calls)
    assert any(call[0] == "add" and call[1] == call[2] for call in calls)


def test_verify_cli_succeeds_and_reports_corruption(tmp_path):
    replay_path = tmp_path / "run.jsonl"
    record_world(replay_path, turns=2)
    config_path = tmp_path / "conf"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    wesen_cli = os.path.join(os.path.dirname(sys.executable), "wesen")
    assert os.path.exists(wesen_cli)
    command = [
        wesen_cli,
        "--configfile",
        str(config_path),
        "--verify-replay",
        str(replay_path),
    ]

    valid = subprocess.run(command, capture_output=True, text=True, env=env)
    assert valid.returncode == 0, valid.stderr
    assert "verified successfully" in valid.stdout

    playback = subprocess.run(
        [
            wesen_cli,
            "--configfile",
            str(config_path),
            "--replay",
            str(replay_path),
            "--disablegui",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert playback.returncode == 0, playback.stderr
    assert "replay completed: 2 frames" in playback.stdout

    events = read_events(replay_path)
    frame = next(event for event in events if event["event"] == "frame")
    frame["state"]["objects"][0]["energy"] += 1
    replay_path.write_text("".join(json.dumps(event) + "\n" for event in events))
    corrupt = subprocess.run(command, capture_output=True, text=True, env=env)
    assert corrupt.returncode == 1
    assert f"failed at turn {frame['turn']}" in corrupt.stdout
    assert "expected:" in corrupt.stdout
    assert "actual:" in corrupt.stdout
