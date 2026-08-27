wesen
=====

Wesen - little game where players have to program the behavior of their Wesens to defeat the other players (like CoreWars)


History
=====
  * 2003 version 0.1 for Python 2
  * 2013 version 0.6 for Python 3
  * 2026 version 0.7 for Python > 3.7

Run/Install/Build
=====

First you need freeglut (external non-python dependency for OpenGL), e.g.
```sh
sudo apt install freeglut3-dev
```

Using `uv`:
```sh
git clone https://github.com/konradvoelkel/wesen.git
cd wesen
uv venv
uv sync
uv run wesen
```

Replay
=====

Wesen can record a normal run as human-readable JSON Lines. The replay stores
the initial state, detailed action/effect events, and a complete state frame
plus verification hash after every turn.

```sh
uv run wesen --record-replay run.jsonl
uv run wesen --replay run.jsonl
uv run wesen --replay run.jsonl --disablegui
uv run wesen --verify-replay run.jsonl
```

Playback restores recorded snapshots and never runs Wesen source AI logic.
Verification is non-GUI and exits unsuccessfully on the first corrupt frame,
printing its turn and expected/actual hashes.
