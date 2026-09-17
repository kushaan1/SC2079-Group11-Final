# STM questions: pivot / turn on the spot

Paste into `docs/algorithms-todo.md` under "STM owner" when convenient. Written 2026-09-11.

The manoeuvre we mean is a **shuffle turn**, not a true zero-radius pivot: full lock forward,
full lock back the other way, repeated. `FORWARD_RIGHT` + `BACKWARD_LEFT` both swing the nose
clockwise, so the translations largely cancel and the car rotates with a few cm of residual.
The planner models it as one composite move.

The unit is **45 degrees**, at a working figure of **2 seconds** (your number, 2026-09-11).

## What the planner needs

**Capability**

1. Confirm the car can do full-lock forward and full-lock backward strokes back to back, and
   how quickly it can reverse direction between them. The reversal overhead is likely to
   dominate the cost, not the driving.
2. Smallest arc you can command and stop accurately. The default plan is **2 strokes per 45
   degrees, i.e. 22.5 degrees per stroke**. If 22.5 is not reliable, tell us what is — the
   planner reads the stroke count from config and re-derives everything.
3. Can you expose the whole sequence as one canned command, or must the planner emit the
   individual strokes? One token is much easier for us; the choice is one enum edit either way.

**Geometry** — same tape-mark form as question 1 in the existing list

4. Run "pivot 45 degrees left" ten times from a tape mark. Report the endpoint scatter: final
   heading, and (dx, dy) of the footprint centre. That single measurement gives us the net
   displacement AND the repeatability together.
5. Same for 90 degrees.
6. **Largest distance from the robot's centre to any point of it, including the camera mount,
   wheel bulge and any overhang.** This sets the clearance disc. The planner currently assumes
   a 31 cm square, circumscribed radius ~22 cm.

**Time**

7. Seconds for a 45 degree pivot, command to full stop. Confirm or correct our 2.0.
8. Is 90 degrees exactly twice 45, or is there a fixed per-command overhead that makes it less?
9. Any settle time before a straight can be commanded after a pivot?

**Accuracy**

10. Does heading error accumulate across consecutive pivots? Wheel scrub on a 4-wheel chassis
    drifts harder than an arc does.
11. Measured on the competition floor surface — pivot behaviour is almost entirely a friction
    property, and carpet vs vinyl will give different answers.

## Why it matters

Our model says the drift is **systematic, not noise**: it is driven almost entirely by
`R_forward != R_backward` (currently 40 vs 37 cm, another team's numbers). If you can trim
forward and backward lock to match, the drift mostly disappears. At the current placeholder
radii a 45 degree pivot drifts ~3.5 cm and sweeps a 51 x 58 cm box, against a 90 degree arc
that displaces the car by (52, 28) cm.

The prize is **reachability, not speed**. A pivot costs more than the equivalent arc (2.0 s vs
1.5 s at 45 degrees) and gains zero ground, so the planner will only choose it where the arc's
displacement is unwanted — which is exactly the case in section 6 where an obstacle facing a
wall within ~45 cm currently comes back unreachable at legal competition spacing.
