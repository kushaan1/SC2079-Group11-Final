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
| `02-four-obstacles.json` | 4 | 4 segments in visit order `12, 11, 14, 13`, `unreachable` empty: the default `"optimal"`, 22.26 s. `"greedy"` visits `12, 11, 13, 14` in 23.05 s. With four headings the two agree on `12, 11, 14, 13`, in 30.60 s |
| `03-unreachable.json` | 2 | **1 segment (11) and 1 unreachable (13, `NO_OBJECTIVES`)** — this is correct, not a bug |
| `04-five-obstacles.json` | 5 | 5 segments, `unreachable` empty. The arena that catches a route optimiser trusting its own lower bound (see below) |
| `05-greedy-loses.json` | 4 | 4 segments, `unreachable` empty. Both strategies visit `14, 13, 12, 11`: `"greedy"` in 22.38 s, the default `"optimal"` in **21.43 s**. With four headings `"greedy"` visits `14, 12, 11, 13` in 38.00 s and `"optimal"` visits `12, 14, 13, 11` in **34.80 s**. Synthetic: three obstacles sit 10 cm from a wall, tighter than the competition's 30 cm rule |

Orders and times in this file were re-measured 2026-09-25, after the per-command turn fit, with
the config as shipped (`DIAGONAL_HEADINGS` on, `PIVOT_TURNS` off), which is what a request to the
running service gets. "With four headings" means `DIAGONAL_HEADINGS` off, the planner the test
suite pins; it is quoted where an arena's purpose rests on it.

`image_id` in these files is the obstacle's identifier, not a real image ID; any value in 1–40 is
accepted and is echoed back unchanged.

`03` exists to exercise the `unreachable` path deliberately. Obstacle 13 faces north while sitting
at y ≤ 159, so every pose that would photograph it lands beyond the arena's free area. Use it to
check that the RPi and the tablet handle a skipped obstacle instead of silently showing one fewer.

`04` exists for the route optimiser. The leg-cost matrix prices a leg from anywhere in an
obstacle's goal-pose set while the robot drives it from the one pose it arrived at, so a cheaper
bound can be the slower route. The matrix's favourite order, `12, 11, 13, 15, 14` (21.81 s bound),
re-plans to 27.78 s, only 0.03 s better than greedy's own 27.81 s. The order that wins, `11, 12, 15, 14, 13`
in 26.93 s, ranks ninth by bound. That is the last candidate `MAX_REPLANS` (8) allows, so the
service logs the route as the best one tried, not a proven optimum. With four headings the
favourite is greedy's own order, `12, 11, 15, 14, 13` (39.80 s bound), and it re-plans to 50.80 s
against the 46.40 s greedy actually drives: an optimiser that picks the best matrix order and
stops is 9.5% slower than plain greedy there. Use it to check that `strategy: "optimal"` is never
slower than `strategy: "greedy"`.

`05` is the other half of that check: an arena where optimal is strictly *faster*, so a `strategy`
field that quietly did nothing would be caught. Obstacle 14 sits nearest the start, so greedy
photographs it first. As shipped, optimal keeps greedy's order and is faster only because it
re-plans every leg for time rather than distance. With four headings greedy then drives back
across the arena, and optimal takes 14 second instead: it saves 3.20 s despite 16 cm more path,
because it drives one turn fewer and the time model charges each turn a flat `TURN_TIME_S`. Both
strategies photograph all four obstacles — optimal never trades an obstacle for time.

Planning times, measured 2026-09-25: `"greedy"` about 0.03-0.3 s on any of these; `"optimal"`
about 0.1 s on one obstacle and 2-3.5 s on four or five. With four headings, greedy takes 0.01-0.1 s
and optimal 0.7-1.4 s on four or five. Both are small against the 6-minute Task 1 budget.

All five use `"verbose": false` to keep responses small and readable. Set it to `true` when you
need the per-cell path for drawing, or for the per-segment `seconds`. None of them sets
`strategy`, so all five plan the shortest-time order; add `"strategy": "greedy"` for the old
nearest-first one.

`responses/02-four-obstacles.verbose.json` is the service's answer to `02`, a 2026-09-25 snapshot
of the shipped config (eight headings, `verbose: true` forced), for the RPi owner's parser.
Regenerate it whenever the geometry or the config changes, with the Flask test client:
`create_app().test_client().post("/pathfinding/", json=body)` with `body["verbose"] = True`.

Every request the server receives is written to `.replay/<timestamp>.json` regardless, so a real
arena that misbehaves can be replayed later with `-d @.replay/<file>`.
