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
| `02-four-obstacles.json` | 4 | 4 segments in visit order `12, 11, 14, 13`, `unreachable` empty. Both strategies agree here — greedy's order is already the quickest |
| `03-unreachable.json` | 2 | **1 segment (11) and 1 unreachable (13, `NO_OBJECTIVES`)** — this is correct, not a bug |
| `04-five-obstacles.json` | 5 | 5 segments, `unreachable` empty. The arena that catches a route optimiser trusting its own lower bound (see below) |
| `05-greedy-loses.json` | 4 | 4 segments, `unreachable` empty. `"greedy"` visits `14, 12, 11, 13` in 35.17 s; the default `"optimal"` visits `12, 11, 14, 13` in **30.33 s**. Synthetic: three obstacles sit 10 cm from a wall, tighter than the competition's 30 cm rule |

`image_id` in these files is the obstacle's identifier, not a real image ID; any value in 1–40 is
accepted and is echoed back unchanged.

`03` exists to exercise the `unreachable` path deliberately. Obstacle 13 faces north while sitting
at y ≤ 159, so every pose that would photograph it lands beyond the arena's free area. Use it to
check that the RPi and the tablet handle a skipped obstacle instead of silently showing one fewer.

`04` exists for the route optimiser. Its leg-cost matrix prefers the visiting order
`12, 11, 14, 15, 13` (53.00 s) over `12, 11, 15, 14, 13` (54.00 s), but those orders re-plan to
66.83 s and 62.33 s respectively — the matrix prices a leg from anywhere in an obstacle's
goal-pose set while the robot drives it from the one pose it arrived at, so the cheaper bound is
the slower route. An optimiser that picks the best matrix order and stops is 7.2% slower than
plain greedy here. Use it to check that `strategy: "optimal"` is never slower than
`strategy: "greedy"`.

`05` is the other half of that check: an arena where optimal is strictly *faster*, so a `strategy`
field that quietly did nothing would be caught. Obstacle 14 sits nearest the start, so greedy
photographs it first and then drives back across the arena; taking it third instead saves 4.84 s
and 85 cm. Both strategies photograph all four obstacles — optimal never trades an obstacle for
time.

Planning times, measured 2026-09-04: `"greedy"` about 0.05-0.12 s on any of these; `"optimal"` about
0.5-0.9 s on four or five obstacles. Both are noise against the 6-minute Task 1 budget.

All five use `"verbose": false` to keep responses small and readable. Set it to `true` when you
need the per-cell path for drawing, or for the per-segment `seconds`. None of them sets
`strategy`, so all five plan the shortest-time order; add `"strategy": "greedy"` for the old
nearest-first one.

Every request the server receives is written to `.replay/<timestamp>.json` regardless, so a real
arena that misbehaves can be replayed later with `-d @.replay/<file>`.
