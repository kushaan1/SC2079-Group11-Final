# Test arenas

Ready-made request bodies for hitting the service by hand, so nobody has to type JSON during an
integration session.

```sh
# against your own laptop
curl -s -X POST http://127.0.0.1:5000/pathfinding/ \
  -H 'Content-Type: application/json' -d @testdata/02-four-obstacles.json

# from the RPi, pointed at your laptop (swap in the IP the server logs on startup)
curl -s -X POST http://192.168.50.12:5000/pathfinding/ \
  -H 'Content-Type: application/json' -d @02-four-obstacles.json
```

| File | Obstacles | Expect |
|---|---|---|
| `01-single-obstacle.json` | 1 | 1 segment, `unreachable` empty. The smallest thing that can work — use it first |
| `02-four-obstacles.json` | 4 | 4 segments in visit order `12, 11, 14, 13`, `unreachable` empty, ~2.5 s |
| `03-unreachable.json` | 2 | **1 segment (11) and 1 unreachable (13, `NO_OBJECTIVES`)** — this is correct, not a bug |

`image_id` in these files is the obstacle's identifier, not a real image ID; any value in 1–40 is
accepted and is echoed back unchanged.

`03` exists to exercise the `unreachable` path deliberately. Obstacle 13 faces north while sitting
at y ≤ 159, so every pose that would photograph it lands beyond the arena's free area. Use it to
check that the RPi and the tablet handle a skipped obstacle instead of silently showing one fewer.

All three use `"verbose": false` to keep responses small and readable. Set it to `true` when you
need the per-cell path for drawing.

Every request the server receives is written to `.replay/<timestamp>.json` regardless, so a real
arena that misbehaves can be replayed later with `-d @.replay/<file>`.
