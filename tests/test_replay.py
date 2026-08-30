import json
import os
import subprocess
import sys
from copy import deepcopy

import deal
import pytest

from Wesen.objects import food as food_module
from Wesen.objects import wesen as wesen_module
from Wesen.replay.hash import GENESIS_HASH, replay_event_hash
from Wesen.replay.recorder import ReplayRecorder
from Wesen.replay.replayer import Replayer, ReplayError
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


def write_events(path, events, *, rebuild_chain=False):
    previous_hash = GENESIS_HASH
    lines = []
    for source_event in events:
        event = deepcopy(source_event)
        if rebuild_chain:
            event.pop("chain_hash", None)
            event["chain_hash"] = replay_event_hash(previous_hash, event)
        previous_hash = event["chain_hash"]
        lines.append(json.dumps(event, separators=(",", ":"), sort_keys=True))
    path.write_text("\n".join(lines) + "\n")


def record_world(path, turns=3, checkpoint_interval=100):
    world = World(world_info())
    recorder = ReplayRecorder(
        path,
        run_id="test-run",
        checkpoint_interval=checkpoint_interval,
    )
    world.setRecorder(recorder)
    recorder.start(world)
    states = []
    for _ in range(turns):
        world.main()
        states.append(world.persist())
    recorder.close()
    return world, states


def start_manual_replay(path, *, checkpoint_interval=100, wesen=1, food=1):
    world = World(world_info(wesen_count=wesen, food_count=food))
    recorder = ReplayRecorder(
        path,
        run_id="manual-run",
        checkpoint_interval=checkpoint_interval,
    )
    world.setRecorder(recorder)
    recorder.start(world)
    return world, recorder


def finish_manual_turn(world, recorder):
    world.turns += 1
    recorder.record_turn(world)


def test_initial_checkpoint_restores_independently(tmp_path):
    replay_path = tmp_path / "initial.jsonl"
    world, recorder = start_manual_replay(replay_path)
    expected = world.persist()
    recorder.close()

    events = read_events(replay_path)
    assert [event["event"] for event in events] == [
        "replay_header",
        "checkpoint",
        "replay_end",
    ]
    assert events[0]["schema"] == 2
    assert events[0]["mode"] == "checkpoint_delta"
    assert events[1]["turn"] == 0
    assert Replayer(replay_path).create_world().persist() == expected


def test_simple_and_multiple_object_field_changes_are_compact(tmp_path):
    replay_path = tmp_path / "changes.jsonl"
    world, recorder = start_manual_replay(replay_path)
    sim_id = min(world.objects)
    obj = world.objects[sim_id]
    obj.energy -= 17
    obj.age = 4
    obj.time = 9
    finish_manual_turn(world, recorder)
    expected = world.persist()
    recorder.close()

    delta = read_events(replay_path)[2]
    assert delta["event"] == "turn_delta"
    assert delta["changed"][str(sim_id)] == {
        "age": 4,
        "energy": obj.energy,
        "time": 9,
    }
    assert "state" not in delta

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert replay_world.persist() == expected


def test_object_creation_and_removal_round_trip(tmp_path):
    replay_path = tmp_path / "lifecycle.jsonl"
    world, recorder = start_manual_replay(replay_path, wesen=0, food=1)
    removed_id = min(world.objects)
    removed_position = list(world.objects[removed_id].position)
    world.DeleteObject(removed_id)
    info = world.infoAllWorld["food"].copy()
    info.update({"position": [3, 4], "energy": 23})
    created = world.AddObject(info)
    finish_manual_turn(world, recorder)
    expected = world.persist()
    recorder.close()

    delta = read_events(replay_path)[2]
    assert delta["removed"] == [removed_id]
    assert [state["sim_id"] for state in delta["created"]] == [created.sim_id]

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert replay_world.persist() == expected
    assert removed_id not in replay_world.objects
    assert created.sim_id in replay_world.objects
    assert (
        removed_id not in replay_world.map[removed_position[0]][removed_position[1]]
    )
    created_position = replay_world.objects[created.sim_id].position
    assert (
        replay_world.map[created_position[0]][created_position[1]][created.sim_id]
        is replay_world.objects[created.sim_id]
    )


def test_position_delta_updates_map_index_and_callbacks(tmp_path):
    replay_path = tmp_path / "move.jsonl"
    world, recorder = start_manual_replay(replay_path, wesen=1, food=0)
    sim_id = min(world.objects)
    obj = world.objects[sim_id]
    old_position = list(obj.position)
    new_position = [(old_position[0] + 2) % 12, (old_position[1] + 3) % 12]
    obj.position = new_position
    world.UpdatePos(sim_id, old_position, obj.getDescriptor())
    finish_manual_turn(world, recorder)
    recorder.close()

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    calls = []
    replay_world.setCallbacks(
        {
            "UpdatePos": lambda moved_id, descriptor: calls.append(
                (moved_id, descriptor["position"])
            )
        }
    )
    assert replayer.step(replay_world)
    replay_obj = replay_world.objects[sim_id]
    assert replay_obj.position == new_position
    assert sim_id not in replay_world.map[old_position[0]][old_position[1]]
    assert replay_world.map[new_position[0]][new_position[1]][sim_id] is replay_obj
    assert new_position[1] in replay_world._occupied_y[new_position[0]]
    assert calls == [(sim_id, new_position)]


def test_multiple_sequential_deltas_restore_each_original_state(tmp_path):
    replay_path = tmp_path / "sequential.jsonl"
    _world, original_states = record_world(replay_path, turns=8)
    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    replayed_states = []
    while replayer.step(replay_world):
        replayed_states.append(replay_world.persist())

    assert replayed_states == original_states
    assert replayer.verify().ok
    assert replayer.verify().frames == 8


def test_periodic_checkpoint_restores_exact_state(tmp_path):
    replay_path = tmp_path / "checkpoints.jsonl"
    _world, states = record_world(replay_path, turns=5, checkpoint_interval=2)
    events = read_events(replay_path)
    checkpoints = [event for event in events if event["event"] == "checkpoint"]
    deltas = [event for event in events if event["event"] == "turn_delta"]
    assert [event["turn"] for event in checkpoints] == [0, 2, 4]
    assert [event["turn"] for event in deltas] == [1, 3, 5]

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    for expected in states:
        assert replayer.step(replay_world)
        assert replay_world.persist() == expected
    verification = Replayer(replay_path).verify()
    assert verification.ok
    assert "3 checkpoints" in verification.message


def test_world_level_state_is_recorded_in_delta(tmp_path):
    replay_path = tmp_path / "world.jsonl"
    world, recorder = start_manual_replay(replay_path)
    world.stats["global"] = {"count": 99, "energy": 1234}
    world.infoAllWorld["food"]["growrate"] = 0.75
    world.infoAllWorld["range"]["look"] = 5
    finish_manual_turn(world, recorder)
    expected = world.persist()
    recorder.close()

    delta = read_events(replay_path)[2]
    assert delta["world"]["turns"] == 1
    assert delta["world"]["stats"]["global"]["count"] == 99
    assert delta["world"]["food"]["growrate"] == 0.75
    assert delta["world"]["range"]["look"] == 5
    replayer = Replayer(replay_path)
    initial_state = deepcopy(replayer.initial_checkpoint["state"])
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert replay_world.persist() == expected
    assert replayer.initial_checkpoint["state"] == initial_state


def test_source_ownership_and_wesen_configuration_changes_restore(tmp_path):
    replay_path = tmp_path / "ownership.jsonl"
    world, recorder = start_manual_replay(replay_path, wesen=1, food=0)
    sim_id = min(world.objects)
    obj = world.objects[sim_id]
    obj.source = "RecordedSource"
    obj.infoObject["maxage"] = 4321
    finish_manual_turn(world, recorder)
    expected = world.persist()
    recorder.close()

    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert replay_world.objects[sim_id].source == "RecordedSource"
    assert replay_world.persist() == expected


def test_replay_integrity_chain_rejects_modified_delta(tmp_path):
    replay_path = tmp_path / "corrupt.jsonl"
    record_world(replay_path, turns=2)
    events = read_events(replay_path)
    delta = next(event for event in events if event["event"] == "turn_delta")
    first_patch = next(iter(delta["changed"].values()))
    first_patch["energy"] = 999999
    write_events(replay_path, events)

    with pytest.raises(ReplayError, match="integrity failed"):
        Replayer(replay_path)


def test_replay_requires_terminal_event_to_detect_truncation(tmp_path):
    replay_path = tmp_path / "truncated.jsonl"
    record_world(replay_path, turns=2)
    events = read_events(replay_path)
    write_events(replay_path, events[:-1])

    with pytest.raises(ReplayError, match="last replay event must be replay_end"):
        Replayer(replay_path)


def test_checkpoint_state_hash_is_verified_separately(tmp_path):
    replay_path = tmp_path / "checkpoint-corrupt.jsonl"
    record_world(replay_path, turns=1)
    events = read_events(replay_path)
    events[1]["state"]["next_sim_id"] += 1
    write_events(replay_path, events, rebuild_chain=True)

    with pytest.raises(ReplayError, match="state hash failed"):
        Replayer(replay_path)


@pytest.mark.parametrize("sequence", [None, 7])
def test_missing_or_invalid_sequence_is_rejected(tmp_path, sequence):
    replay_path = tmp_path / "sequence.jsonl"
    record_world(replay_path, turns=1)
    events = read_events(replay_path)
    if sequence is None:
        events[1].pop("seq")
    else:
        events[1]["seq"] = sequence
    write_events(replay_path, events)

    with pytest.raises(ReplayError, match="sequence is not contiguous"):
        Replayer(replay_path)


def test_malformed_json_and_delta_are_rejected(tmp_path):
    malformed_path = tmp_path / "bad-json.jsonl"
    malformed_path.write_text("{not json}\n")
    with pytest.raises(ReplayError, match="invalid JSON"):
        Replayer(malformed_path)

    delta_path = tmp_path / "bad-delta.jsonl"
    record_world(delta_path, turns=1)
    events = read_events(delta_path)
    events[2]["changed"] = {"not-an-id": {"energy": 1}}
    write_events(delta_path, events, rebuild_chain=True)
    with pytest.raises(ReplayError, match="invalid object ID"):
        Replayer(delta_path)


def test_delta_cannot_change_or_remove_unknown_object(tmp_path):
    replay_path = tmp_path / "unknown.jsonl"
    record_world(replay_path, turns=1)
    events = read_events(replay_path)
    events[2]["changed"] = {"99999": {"energy": 1}}
    write_events(replay_path, events, rebuild_chain=True)
    replayer = Replayer(replay_path)
    world = replayer.create_world()
    with pytest.raises(ReplayError, match="does not exist"):
        replayer.step(world)


def test_unsupported_snapshot_schema_has_clear_migration_boundary(tmp_path):
    replay_path = tmp_path / "old.jsonl"
    record_world(replay_path, turns=1)
    events = read_events(replay_path)
    events[0]["schema"] = 1
    write_events(replay_path, events)

    with pytest.raises(ReplayError, match="unsupported replay schema: 1"):
        Replayer(replay_path)


def test_replay_reaches_eof_without_repeating_last_delta(tmp_path):
    replay_path = tmp_path / "eof.jsonl"
    record_world(replay_path, turns=1)
    replayer = Replayer(replay_path)
    world = replayer.create_world()
    assert replayer.step(world)
    final_state = world.persist()
    assert not replayer.step(world)
    assert not replayer.step(world)
    assert world.persist() == final_state


def test_replay_does_not_execute_ai_food_or_source_imports(tmp_path, monkeypatch):
    replay_path = tmp_path / "inert.jsonl"
    world, recorder = start_manual_replay(replay_path, wesen=0, food=0)
    info = world.infoAllWorld["wesen"].copy()
    info.update({"source": "WindlePoons", "position": [1, 1]})
    world.AddObject(info)
    finish_manual_turn(world, recorder)
    recorder.close()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("simulation behavior executed during replay")

    monkeypatch.setattr(wesen_module.importlib, "import_module", forbidden)
    monkeypatch.setattr(wesen_module.Wesen, "main", forbidden)
    monkeypatch.setattr(food_module.Food, "main", forbidden)
    replayer = Replayer(replay_path)
    replay_world = replayer.create_world()
    assert replayer.step(replay_world)
    assert len(replay_world.objects) == 1


def test_recording_assembles_checkpoints_without_full_world_persist(
    tmp_path, monkeypatch
):
    replay_path = tmp_path / "persist-count.jsonl"
    calls = 0
    original = World.persist

    def counted(world):
        nonlocal calls
        calls += 1
        return original(world)

    monkeypatch.setattr(World, "persist", counted)
    world, recorder = start_manual_replay(
        replay_path, checkpoint_interval=2, wesen=2, food=3
    )
    for _ in range(5):
        finish_manual_turn(world, recorder)
    recorder.close()

    assert calls == 0
    assert [
        event["turn"]
        for event in read_events(replay_path)
        if event["event"] == "checkpoint"
    ] == [0, 2, 4]


def test_checkpoint_interval_contract_requires_positive_value(tmp_path):
    with pytest.raises(deal.PreContractError):
        ReplayRecorder(tmp_path / "invalid.jsonl", checkpoint_interval=0)


def test_semantic_events_use_a_separate_optional_sink(tmp_path):
    class Sink:
        def __init__(self):
            self.events = []

        def event(self, event_type, **data):
            self.events.append((event_type, data))

    sink = Sink()
    replay_path = tmp_path / "separate.jsonl"
    world = World(world_info(wesen_count=0, food_count=0))
    recorder = ReplayRecorder(replay_path, semantic_sink=sink)
    world.setRecorder(recorder)
    recorder.start(world)
    recorder.semantic_event("future_metric", turn=0, value=3)
    recorder.close()

    assert sink.events == [("future_metric", {"turn": 0, "value": 3})]
    assert "future_metric" not in replay_path.read_text()


def test_wesend_record_and_playback_options_use_state_transitions(tmp_path):
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

    assert [event["event"] for event in read_events(replay_path)] == [
        "replay_header",
        "checkpoint",
        "turn_delta",
        "turn_delta",
        "replay_end",
    ]
    playback_config = world_info(wesen_count=0, food_count=0)
    playback_config.update(
        {
            "resume": False,
            "record_replay": None,
            "replay": str(replay_path),
            "verify_replay": None,
        }
    )
    playback = Wesend(playback_config)
    assert playback.mainLoop()
    assert playback.mainLoop()
    assert playback.replayer is not None
    assert not playback.replayer.step(playback.world)


def test_verify_cli_succeeds_for_delta_replay(tmp_path):
    replay_path = tmp_path / "cli.jsonl"
    record_world(replay_path, turns=2)
    config_path = tmp_path / "conf"
    env = os.environ.copy()
    env["HOME"] = str(tmp_path)
    wesen_cli = os.path.join(os.path.dirname(sys.executable), "wesen")
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

    events = read_events(replay_path)
    events[2]["world"]["turns"] = 999
    write_events(replay_path, events)
    corrupt = subprocess.run(command, capture_output=True, text=True, env=env)
    assert corrupt.returncode == 1
    assert "replay error: replay integrity failed" in corrupt.stdout
    assert "Traceback" not in corrupt.stderr
