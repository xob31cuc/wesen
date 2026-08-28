from copy import deepcopy

from Wesen.defaults import CONFIG_DEFAULTS
from Wesen.world import World


def _empty_world():
    config = deepcopy(CONFIG_DEFAULTS)
    config["wesen"]["sources"] = []
    return World(config, createObjects=False)


def _add_food(world, position):
    info = world.infoAllWorld["food"].copy()
    info["position"] = list(position)
    return world.AddObject(info)


def _naive_range(world, obj, radius, condition=None):
    x, y = obj.position
    length = world.infoAllWorld["world"]["length"]
    result = []
    for x1 in range(max(0, x - radius), min(length, x + radius + 1)):
        for y1 in range(max(0, y - radius), min(length, y + radius + 1)):
            result.extend(
                (object_id, candidate)
                for object_id, candidate in world.map[x1][y1].items()
                if condition is None or condition(candidate)
            )
    return result


def _assert_index_matches_map(world, obj):
    conditions = (None, lambda candidate: candidate.sim_id % 2 == 0)
    for radius in (0, 1, 10, 500):
        for condition in conditions:
            assert list(obj.getRangeIterator(radius, condition)) == _naive_range(
                world, obj, radius, condition
            )


def test_spatial_index_preserves_map_order_through_mutations_and_restore():
    world = _empty_world()
    anchor = _add_food(world, (250, 250))
    objects = [
        _add_food(world, position)
        for position in ((249, 251), (250, 250), (250, 250), (251, 249), (0, 0))
    ]
    _assert_index_matches_map(world, anchor)

    moved = objects[0]
    old_position = moved.position
    moved.position = [250, 250]
    world.UpdatePos(moved.sim_id, old_position, moved.getDescriptor())
    world.DeleteObject(objects[1].sim_id)
    _assert_index_matches_map(world, anchor)

    state = world.persist()
    restored = World(state, createObjects=False, load_sources=False)
    restored.restore(state)
    _assert_index_matches_map(restored, restored.objects[anchor.sim_id])
