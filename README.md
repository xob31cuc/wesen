wesen
=====

Wesen - little game where players have to program the behavior of their Wesens to defeat the other players (like CoreWars)


History
=====
  * 2003 version 0.1 for Python 2
  * 2013 version 0.6 for Python 3
  * 2026 version 0.7 for Python > 3.7
  * 2026/08 extension 0.8 for Python 3.12-3.14

Run/Install/Build
=====

First you need freeglut (external non-python dependency for OpenGL), e.g.
```sh
sudo apt install freeglut3-dev
```

Using `uv`:
```sh
git clone https://github.com/xob31cuc/wesen.git
cd wesen
uv venv
uv sync
uv run wesen
```

Reproducible wesen-lab demonstration
=====

The example experiment uses `wesen_lab_example.conf`; it does not
change Wesen's default configuration. Its fixed random seed makes the
simulation result reproducible.

Run the experiment from a graphical session:

```sh
rm -rf -- runs/wesen-lab-example
uv run wesen-lab run experiment_example.yaml
```

Show the persisted raw inputs and semantic events without reconstructing replay
states:

```sh
head -n 4 runs/wesen-lab-example/metrics.jsonl
head -n 12 runs/wesen-lab-example/events.jsonl
```

Produce the analysis report:

```sh
uv run wesen-lab summary runs/wesen-lab-example
```

Finally, verify the replay hash chain and replay the saved event log directly.
The headless playback completes without executing source AI or recalculating
the simulation:

```sh
uv run wesen --configfile wesen_lab_example.conf \
  --verify-replay runs/wesen-lab-example/replay.jsonl
uv run wesen --configfile wesen_lab_example.conf \
  --replay runs/wesen-lab-example/replay.jsonl --disablegui
```
