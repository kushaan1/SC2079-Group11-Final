# Testing the algorithm server

Two parts: test it **on the laptop** first (proves the server works), then **from the RPi** (proves
the network works). Doing it in that order means a failure tells you which half is broken.

Every command is deliberately short — long lines get split by terminal paste and then fail in
confusing ways.

---

# Part 1 — on the laptop

## 1.1 Start the server

From `algorithm/`:

```
./.venv/bin/python app.py
```

Leave it running. It prints the address to give the RPi:

```
[INFO] Listening on 0.0.0.0:5000 (stub=no)
[INFO] RPi should POST to http://192.168.16.11:5000/pathfinding/
[INFO] Swagger UI: http://127.0.0.1:5000/openapi/swagger
```

Add `--stub` for canned responses with no planning, so the RPi can integrate before the planner is
trusted. Stub replies carry an `X-MDP-Stub: true` header.

## 1.2 Test it locally

Open a second terminal, also in `algorithm/`:

```
curl -s -X POST http://127.0.0.1:5000/pathfinding/ -H 'Content-Type: application/json' -d @testdata/01-single-obstacle.json
```

`127.0.0.1` means "this same laptop". Three arenas are available:

| File | Expect |
|---|---|
| `testdata/01-single-obstacle.json` | 1 segment |
| `testdata/02-four-obstacles.json` | 4 segments, visit order 12, 11, 14, 13 |
| `testdata/03-unreachable.json` | 1 segment **and** 1 unreachable — correct, not a bug |

Readable output:

```
curl -s -X POST http://127.0.0.1:5000/pathfinding/ -H 'Content-Type: application/json' -d @testdata/02-four-obstacles.json | python3 -m json.tool
```

There is also a clickable version at **`http://127.0.0.1:5000/openapi/swagger`** — no JSON typing.

**If Part 1 works, the server is fine.** Anything that fails after this is network or the RPi side.

## 1.3 Copy a test arena to the RPi

Saves pasting JSON over there. From `algorithm/`, replace `RPI_IP` (and `pi` if the username
differs):

```
scp testdata/01-single-obstacle.json pi@RPI_IP:~/arena.json
```

---

# Part 2 — on the RPi

Replace `192.168.16.11` with whatever the laptop's startup log printed.
**That address changes every time the laptop reconnects to WiFi. Never hardcode it.**

## 2.1 Set the base URL

```
U=http://192.168.16.11:5000
```

## 2.2 Check the laptop is reachable

```
curl -s -o /dev/null -w '%{http_code}\n' $U/openapi/openapi.json
```

Expect **`200`**. Anything else is a network problem — fix it before step 2.4.

## 2.3 If you skipped the scp, create the arena here

One line:

```
printf '%s' '{"robot":{"direction":"NORTH","south_west":{"x":0,"y":0},"north_east":{"x":30,"y":30}},"obstacles":[{"image_id":11,"direction":"SOUTH","south_west":{"x":50,"y":90},"north_east":{"x":59,"y":99}}]}' > arena.json
```

Check it landed intact:

```
wc -c arena.json
```

Expect **`195`**. A different number means the paste broke and step 2.4 will return 400.

## 2.4 Request a plan

```
curl -s $U/pathfinding/ -H 'Content-Type: application/json' -d @arena.json
```

Expect one segment for image 11, ending in `CAPTURE_IMAGE`.

**Also watch the laptop's terminal** — it should log the request arriving. That proves it reached the
algorithm server and not something else on the network.

Readable:

```
curl -s $U/pathfinding/ -H 'Content-Type: application/json' -d @arena.json | python3 -m json.tool
```

---

## What comes back

| Field | Meaning |
|---|---|
| `segments` | One per obstacle to visit, **in visit order**. Each ends in `CAPTURE_IMAGE` |
| `segments[].instructions` | Mixed list: `{"move":"FORWARD","amount":<cm>}` objects, bare turn strings, and `"CAPTURE_IMAGE"` |
| `segments[].cost` | Path length in cm |
| `segments[].path` | Every cell passed through, in driving order. Straight cells are the robot centre; turn arcs are the path of a point 12 cm behind the centre, with the end pose last. Draw it; drive from `instructions` |
| `unreachable` | Obstacles the robot will **not** visit, with a reason |

`len(segments) + len(unreachable)` always equals the number of obstacles sent.

Add `"verbose":false` to the arena JSON to drop `path` and shrink the response.

Full contract: [`protocols/algorithm-service.md`](protocols/algorithm-service.md).

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `curl: (7) Failed to connect` | Laptop not on the same WiFi, wrong IP, or the server isn't running |
| Hangs, then times out | Firewall on the laptop. macOS may have prompted to allow incoming connections — it must be allowed |
| `curl: (2) no URL specified` | The paste split the command across lines. Use the `$U` variable form |
| `zsh: command not found: {"robot"...` | Same cause — `-d` got separated from its argument |
| Works on `127.0.0.1` but not from the RPi | Purely network. The server binds `0.0.0.0`, so it is listening on all interfaces |
| **`200` on 2.2 but `400` on 2.4** | `arena.json` is malformed. `wc -c arena.json` must say 195 |
| `422`, `"loc":["obstacles",0,"image_id"]` | image_id outside 1–40. Only 1–40 are valid |
| `422`, `"image_id must be unique"` | Two obstacles share an image_id |
| `200` but `segments` empty, `unreachable` populated | **Not a bug.** No reachable camera pose for that obstacle — usually too close to the wall it faces, or crowded by a neighbour. Space obstacles 50 cm+ apart for now |
| Response has header `X-MDP-Stub: true` | Laptop is running `--stub`, so instructions are **fabricated**. Ask for the real planner |

## Two things to confirm with the algorithms owner

1. **Does your generated client tolerate the `unreachable` response field?** It is not in the old
   Group 14 `openapi.json`, and some OpenAPI generators reject unknown fields — which would break
   responses that used to work.
2. **Is port 5000 right?** It is a placeholder. Override on the laptop with `MDP_PORT=5001`, no code
   change needed.
