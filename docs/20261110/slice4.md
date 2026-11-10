# Slice 4 — Game loop, 2026-11-10

Result: **PASS**. A person can go menu → racer intro → countdown → race → results → menu (or rematch, or the next
track), and the loop runs unattended. Report with the screens beside Unity's: `SCREENSHOTS/slice4_ui_report.html`.

## What is on screen

| Screen | Content |
|---|---|
| Menu (`L_Menu`) | Track list (built ones selectable, the others "later build"), racer chips (ready ones pickable; not ready or not eligible greyed with the reason), laps for a lap track, START (off until a racer that may race on the track is picked, with the reason under it). One panel that scales to fit: nothing scrolls. Build stamp bottom right. |
| Racer intro | 2.5 s per racer before the countdown: name, kind, height, mass, brain, this race's cruise speed; the camera frames that racer. |
| Race | Top left the track, lap and standings ("DOWN" while a racer is getting up or limp), the clock; top centre the frame and physics rates; top right the pause button; centre the countdown and GO; bottom right the build stamp. |
| Pause sheet | RESUME, RESTART, MENU. Pausing stops the physics clock: the race resumes exactly where it was. |
| Results card | The classified order (a called race shows DNF with the distance), then MENU, REMATCH, NEXT TRACK. |

Keys: Enter = START / back to the menu from the results; Esc = pause. Touch works as the mouse (`bUseMouseForTouch`).

## Checks (`-RaceUiTest`)

| Check | Result |
|---|---|
| Registry: 4 tracks listed, 2 built; 4 racers listed, 2 ready | OK |
| Grandma and G1 listed as not ready, each with its reason | OK |
| Matt refused on Banked Oval ("flat tracks only") | OK |
| START refused with nobody picked; allowed with Blue | OK |
| Menu layout: panel and stamp on screen, no overlap — 1280x720, 540x1170 (portrait), 1680x720 (21:9) | OK at all three |
| Race layout: top left, top centre, top right, bottom right on screen, no overlap — same three sizes | OK at all three |
| Marker and no-Chaos checks in races opened from the menu | OK |
| 10 unattended races (`-AutoStart=1 -AutoOk=2 -AutoLoops=10 -RaceLimit=8`) | 10/10, no stall, 0 check failures |

Races are unchanged by the new rules (intro, finish window and limit are off in race tests): Planar Sprint seeds 1–2 and
Flat Oval seed 1 give the same lines as Slice 3, identical to Python.

## New race rules (Python and Unreal)

- **Racer intro**: racers stand on the grid (Matt holding his heading) for the intro, then the countdown. Its length is
  fixed (2.5 s per racer), not skippable: skipping would change when the race starts and so its outcome (PRD R-13).
- **Finish window**: an interactive race is called 60 s after the winner; the rest are DNF at their distance. Off in tests.
- **Race limit**: a race is called after N seconds (`-RaceLimit`, `race.py --limit`); 600 s by default. The loop test uses 8 s.
- A called race reports `CALLED` (someone finished) or `DNF` (nobody did).

## Found and fixed

1. **URLab froze every body after a level travel.** The first frame after `OpenLevel` was drawn before the physics thread
   had published a snapshot; each `UMjBody` saw an empty snapshot, called it out of range and turned its updates off for
   good. Blue stayed at the parking spot (Matt's skin reads the snapshot itself, so he showed). URLab patch 11: an empty
   snapshot skips the frame. Races opened from the command line never hit it.
2. **Timers from the first drawn frame.** The editor binary can take a minute between BeginPlay and its first frame;
   the UI checks and screenshots now wait for 30 drawn frames at a steady screen size.
3. **Measuring Slate widgets.** UE 5.8 keeps no cached geometry for widgets that do not tick. `SRaceProbe` records the
   geometry it is painted with; the layout check measures with it.
4. **The results card never showed.** A scale box around a collapsed card kept the zero size it measured. The scale box
   now carries the visibility.
5. **Phone screens.** Slate scales with the short side (1.0 at 540 px, 2.0 at 1080 px) so text stays readable on a
   phone; the race camera fills any screen shape and keeps its vertical field of view (no letterbox); the virtual
   joysticks the touch-as-mouse setting adds are off.
6. **The build stamp was hidden on the menu** (Canvas draws under the menu's opaque backdrop); it is drawn in Slate there.

## Open

- **Memory over the loop**: +315 MB after 10 short races (about 30 MB a race), while an earlier run dropped 500 MB at
  race 9 when garbage collection ran. Ten races cannot tell a leak from caches; Slice 10's 2-hour soak decides.
- The creature registry reads the JSON cards from `training/`; packaged builds need them staged (Slice 12).
- The HUD text on a portrait phone is small (Canvas sizes follow the short side with a floor of 0.75); the broadcast
  layout pass is Slice 7/8.
