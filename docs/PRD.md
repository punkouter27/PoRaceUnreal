# PoRace — Product Requirements Document

Status: draft for approval, 2026-11-10. This document describes the product only. How it is built is in `SPEC.md`.

## 1. Executive summary and vision

**Problem.** Racing games show animation: a designer decided how each runner moves, so nothing about the race is in doubt. Robotics demos show real learned motion, but they are single clips with no stakes and no show around them.

**Solution.** PoRace is a watch-only racing simulation. Every racer is a physically realistic body driven by a brain that learned to move through trial and error. Nobody steers a racer and no motion is animated. The viewer picks a track and a field, then watches a race presented like a sports broadcast: cameras that find the action, replays, timing, commentary and standings.

**Value.**

- Every race is real: a stumble, a recovery or a pass happens because of the body, the brain and the track, not a script.
- Very different creatures (a robot dog, a tall man, a small older woman) race each other on the same track under the same physics.
- The show explains itself: a viewer with no background can follow who is ahead, who is struggling and why.
- The roster and the track list grow. Adding a racer or a track is a repeatable recipe, not a rebuild.

**This version.** A rebuild of the existing PoRace with a much higher visual standard on desktop, the same races on phones, and a lighter spectator version in the browser. It matches the existing game feature for feature, minus audience interference, and it is designed to take more racers and tracks afterwards.

## 2. Personas and target segments

| Persona | Who | Goals | Pain points | Motivation |
|---|---|---|---|---|
| **The Builder** (owner) | Creates racers and tracks, trains brains, runs the show | Add a racer or a track without touching the rest; trust that a racer behaves in the game exactly as it did in training | Motion that looks right in training and wrong in the game; one change quietly breaking an older racer | A growing stable of believable creatures |
| **The Spectator** | Casual viewer on a phone or in a browser | Understand the race within seconds; see the dramatic moments | Clutter, jargon, long waits between races | Entertainment, picking a favourite |
| **The Enthusiast** | Viewer curious about learned motion and robotics | See what a body is doing: effort, cadence, balance, recoveries | Polished shows that hide the interesting detail | Curiosity, comparing creatures |
| **The Unattended Screen** | A stream, kiosk or second monitor nobody is operating | Run race after race for hours with no input | Menus that wait forever, crashes, stuck racers | Always something worth watching |

## 3. Epics and prioritised user stories

Priority: **P0** = needed for the first complete version, **P1** = part of the full match, delivered after the core loop, **P2** = full match, last.

### Epic A — Racers

**A1 (P0).** As a Spectator, I want to pick which racers start, so that I can set up the matchup I want.
- The roster shows every racer with name, type, size and status.
- Only racers marked ready can be picked. Others are visible and labelled "not ready".
- At least one racer must be picked before a race can start.

**A2 (P0).** As a Builder, I want Blue the dog and Matt to move as they do in the existing game, so that the rebuild loses nothing.
- Blue walks, runs fast, takes banked turns, clears steeplechase obstacles and gets up after a fall.
- Matt walks and jogs, and goes limp when down.
- For each racer, the same starting state and the same race conditions produce the same motion as the reference simulation, within the tolerance in rule R-14.

**A3 (P0).** As a Spectator, I want each racer to be visibly its own character, so that I can tell them apart at a glance.
- Each racer has a distinct look and a colour used consistently on its body, in standings and in captions.
- Colours stay distinguishable for colour-blind viewers.

**A4 (P1).** As a Builder, I want Grandma and the G1 robot to appear as "not ready" until they pass their checks, so that an untrained racer never reaches a grid.
- A racer becomes ready only after its brain graduates and its motion is verified in the game.
- Tournament slots without a ready racer show as byes.

### Epic B — Tracks

**B1 (P0).** As a Spectator, I want to choose a track, so that I can watch different kinds of race.
- Four tracks at launch: Planar Sprint (100 m straight), Flat Oval (97.6 m lap), Banked Oval (15° banks), Steeplechase (34 obstacles).
- The menu shows each track's name, length and which racers may run on it.

**B2 (P0).** As a Spectator, I want to set the number of laps, so that I control how long a race lasts.
- Laps can be set from 1 to 5 on lapped tracks.

**B3 (P0).** As a Builder, I want a racer kept off tracks it was not trained for, so that races are not decided by guaranteed failures.
- Humans may be picked on flat tracks only. Blue may be picked on all four.
- Picking a track removes ineligible racers from the selection and says why.

### Epic C — The race

**C1 (P0).** As a Spectator, I want a clear start, so that I know when the race begins.
- A 3-second countdown; no racer moves forward before it ends.

**C2 (P0).** As a Spectator, I want live standings and timing, so that I always know who is ahead and by how much.
- Standings order by distance covered, updated continuously.
- Lap count, split times and the finish time are shown per racer.

**C3 (P0).** As a Spectator, I want races to vary, so that the same matchup is not the same race twice.
- Lane draw and a small speed spread (about 6 %) are drawn fresh each race.
- Any race can be repeated exactly from its race number (seed).

**C4 (P0).** As an Unattended Screen, I want a stuck or downed racer to be dealt with automatically, so that a race always finishes.
- A racer down for more than 5 s without recovering, stalled for more than 10 s, or out of bounds is put back at its last checkpoint.
- Once the winner is home, the race is called after a fixed window; anyone still running is classified by distance as "did not finish".

**C5 (P1).** As a Spectator, I want racers to race each other, so that the field is more than parallel time trials.
- Racers move to pass a slower or fallen racer and to block an attacker.
- No sideways manoeuvres on banked sections.

**C6 (P1).** As a Spectator, I want a yellow flag after a pile-up, so that the race stays close.
- When two or more racers are down, the leaders ease to 80 % pace for up to 5 s.

**C7 (P2).** As a Spectator, I want an optional head-start handicap, so that unequal racers finish close together.
- Head starts are sized so expected finish times are equal. A racer with a head start cannot set a track record.

### Epic D — Game flow

**D1 (P0).** As a Spectator, I want a simple path from menu to race to result, so that I can start watching in a few taps.
- Menu (track, racers, laps, start) → racer intro → countdown → race → results card → menu or next race.
- The results card shows place, time and best split for every racer.

**D2 (P1).** As an Unattended Screen, I want the game to play itself, so that it is never idle.
- After 30 s without input on the menu, demo races start and continue race after race.
- Any input returns to the menu.

**D3 (P1).** As a Spectator, I want a knockout tournament, so that there is a champion.
- A 16-slot bracket, 8 a side, meeting in the middle. Ready racers are placed at random; empty slots are byes.
- Each match runs on a randomly chosen eligible track. The bracket can play itself through to a champion.

**D4 (P1).** As a Spectator, I want a season, so that results add up over many races.
- A series over the eligible tracks; points per place 10 / 7 / 5 / 3 / 1.
- A racer that does not finish scores only if it covered more than half the distance.
- Season standings persist between sessions.

**D5 (P1).** As an Enthusiast, I want ratings, so that I can compare racers over time.
- Every racer starts at 1500. Ratings update after each race and persist between sessions.

### Epic E — Broadcast

**E1 (P0).** As a Spectator, I want the camera to find the action, so that I never have to hunt for it.
- Automatic cuts between the pack, the leader, a battle for position, a trackside view, an overhead view and an incident.
- The viewer can take over the camera at any time and hand it back.

**E2 (P1).** As a Spectator, I want incidents replayed, so that I see what I missed.
- The last 8 s can be replayed, paused and resumed without affecting the race outcome.
- Falls get a slow-motion look.

**E3 (P1).** As a Spectator, I want a warning before a fall, so that I see the stumble and not only the aftermath.
- A racer that is losing balance is flagged and the camera cuts to it before it goes down.

**E4 (P1).** As an Enthusiast, I want to see how hard each body is working, so that I can read the race beneath the standings.
- The racer on camera shows speed, cadence, stride length, effort and state.
- A racer near its physical limit glows and is marked in the standings.
- A racer that is down shows a countdown to its forced reset and the nearest chaser.

**E5 (P1).** As a Spectator, I want live timing against the record, so that every race has a target.
- A timing gate every 10 m compares the leader with the track record and the second racer with the first.
- A new best run replaces the record. The best run appears as a ghost on later races.

**E6 (P2).** As a Spectator, I want captions, a second picture and intent markers, so that the show explains itself.
- Short commentary captions on notable events.
- A picture-in-picture view during a close battle.
- Pass, avoid and block markers on racers.

**E7 (P1).** As a Spectator, I want sound and impact effects that match what happens, so that the race feels physical.
- Footsteps, motor noise, impacts and crowd reactions follow the real contacts and their strength.
- Dust, sparks and scuff marks appear where contacts occur.

### Epic F — Conditions

**F1 (P2).** As a Spectator, I want real weather from a real circuit, so that conditions change the race.
- The menu offers a list of circuits, or off.
- Rain lowers grip. Wind pushes on every racer. Both stay inside the range the racers were trained for.
- Conditions are shown on screen and can be set by hand for a repeatable race.

### Epic G — Records

**G1 (P1).** As an Enthusiast, I want a stats card after each race, so that I can compare performances.
- Per racer: time, falls, passes, peak effort, cadence and energy efficiency.
- Track records, fastest recoveries, season standings and ratings persist between sessions.

### Epic H — Devices and quality

**H1 (P0).** As a Spectator, I want the best visuals my desktop can deliver, so that the race looks like a broadcast.
- Desktop uses the full visual feature set and never drops below 30 frames per second; quality steps down automatically before that happens.

**H2 (P1).** As a Spectator, I want the same races on my phone, so that I can watch anywhere.
- Portrait layout with no scrolling; all controls reachable by thumb.
- The same race number gives the same result on phone and desktop.
- 60 frames per second on a recent flagship phone.

**H3 (P1).** As a Spectator, I want to watch in a browser with nothing to install, so that I can share a link.
- The browser version runs the same racers, tracks and rules with a simpler look.
- It covers menu, race, standings, timing and results. Tournament, season and replay may follow later.

**H4 (P0).** As a Builder, I want the build date on screen, so that I always know which version I am looking at.
- A date stamp sits in the bottom-right corner on every device.

### Epic I — Growth

**I1 (P0).** As a Builder, I want a racer to be a self-contained package, so that adding one changes nothing else.
- A racer is a look, a body, a character card and its own brain.
- A new racer appears in the roster automatically, as "not ready" until verified.

**I2 (P0).** As a Builder, I want a track to be data, so that adding one needs no new rules.
- A track is a centre line plus settings (width, banking, obstacles, laps, eligible racers). Rails, grid, checkpoints and timing gates follow from it.

**I3 (P1).** As a Builder, I want an automatic check that old racers still behave after any change, so that growth does not break what works.
- A standard set of unattended races runs for every ready racer and reports finishes, resets and falls against the previous version.

## 4. Core workflows and state machines

### 4.1 Session flow

```
Launch → Menu ──(30 s idle)──→ Attract ──(any input)──→ Menu
          │
        Start
          ↓
   Racer intro → Countdown (3 s) → Racing ⇄ Yellow flag
                                      ↓
                                   Winner home → Finish window → Race called
                                                                    ↓
                                                              Results card
                                                                    ↓
                                           Menu  |  Rematch  |  Next (tournament / season / attract)
```

Pause can be entered from Racing and returns to it. Replay can be entered from Racing or the Results card and returns to where it came from.

### 4.2 Racer state during a race

```
Gridded → Racing ⇄ Wobbling → Down → Recovering → Racing
                                │
                     (down > 5 s, stalled > 10 s, or out of bounds)
                                ↓
                       Reset to last checkpoint → Racing

Racing → Finished          (crossed the line on the final lap)
Racing → Did not finish    (race called first; classified by distance)
```

State is decided only by what the body is physically doing: contacts, tilt and progress.

### 4.3 Racer readiness

```
Body built → Body checked → Training → Graduated → Verified in game → Ready
```

A racer moves back to "Body checked" if its body changes, and back to "Graduated" if the game's physics changes.

### 4.4 Tournament

```
Draw (16 slots, byes for empty) → Round of 16 → Quarter-finals → Semi-finals → Final → Champion
```

A bye advances its opponent without a race. Two byes produce a bye in the next round.

### 4.5 Season

```
New season (race number fixed) → Next round (track + race number) → Race → Score → … → Season complete → New season
```

## 5. Scope

### In scope for this version

- Racers: Blue and Matt ready at launch; Grandma and G1 listed as not ready.
- The four tracks, with today's eligibility rules.
- Race rules: countdown, laps, splits, seeded variation, auto-reset, finish window, tactics, yellow flag, handicap.
- Flow: menu, intro, results, attract mode, tournament, season, ratings.
- Broadcast: director cameras, manual camera, replay, ghost, gate timing, wobble warning, strain and effort indicators, recovery countdown, captions, picture-in-picture, intent markers, sound and impact effects.
- Weather from real circuits.
- Stats card and persistent records.
- Desktop (full visuals), phone (same races, lighter look), browser (spectator version).
- Racer and track onboarding recipes and the regression check.

### Out of scope for this version

- Any audience interference: chat commands, cube drops, shoves, speed nudges, betting.
- Steering or controlling a racer.
- Network multiplayer, accounts, sign-in, purchases.
- New racers or tracks beyond those listed (the recipes are in scope; new content comes after).
- Training Grandma or G1 to readiness (they continue on their own schedule).
- Rough terrain, moving hazards, pit stops.
- Tournament, season and replay in the browser version.

### Later

More racers, more tracks, humans on banked and obstacle tracks, slalom track, force-arrow replays, racing-line heat maps, rival duel mode, voiced commentary.

## 6. Business rules and data invariants

**Motion**

- **R-1** Racer motion comes only from the physics simulation driven by the racer's brain. No animation clips, no pose snapping, no blending.
- **R-2** One brain per character. No racer uses another's brain, even with a similar body.
- **R-3** The simulation runs on a fixed step and never depends on the frame rate. A slow frame catches up; it never stretches a step.
- **R-4** Gravity is 9.81 m/s². Body masses, joint ranges, strength and speed limits are realistic for the creature.
- **R-5** Bodies do not pass through themselves, each other or the track.
- **R-6** A racer's state (racing, down, recovering) is read from the physics, never from the picture.

**Race**

- **R-7** A race needs 1 or more ready racers and exactly one track. Laps are 1–5.
- **R-8** A racer can only be placed on a track it is eligible for.
- **R-9** Same track, racers, laps, conditions and race number give the same result on desktop and phone.
- **R-10** Auto-reset returns a racer to its last checkpoint, never ahead of where it went down.
- **R-11** Tactics and yellow-flag changes stay inside each racer's trained speed range. Sideways moves are capped and banned on banked sections.
- **R-12** Weather keeps grip and wind inside the range the racers were trained for: grip never falls below 70 % of dry, steady wind never exceeds 10 N.
- **R-13** Nothing the viewer does (camera, pause, replay, quality setting) changes the race outcome.

**Readiness**

- **R-14** A racer is ready only when (a) its brain held its target score for 100 consecutive trials, and (b) the game reproduces the reference simulation: a recorded run replays with every body part within 1 mm, and a live 5-second run ends within 1 cm with the same fall / no-fall outcome.
- **R-15** A change to a body, the rules or the physics lists the racers it affects, and those racers are re-checked before they stay ready.

**Records**

- **R-16** Track records are per track and lap count. A racer with a head start is timed but cannot set a record.
- **R-17** Ratings start at 1500 and change only on completed races. Season points are 10 / 7 / 5 / 3 / 1; a non-finisher scores only past half distance.
- **R-18** Unattended test races never write records, ratings or season results.

**Presentation**

- **R-19** Desktop holds at least 30 frames per second by lowering quality automatically. Phones target 60.
- **R-20** Portrait layout on phones with no scrolling; the build date is always in the bottom-right corner.
- **R-21** Racer colours are consistent everywhere and distinguishable for colour-blind viewers.

**Edge cases**

- A single-racer race is a time trial against the record and the ghost.
- If every racer is down at once, no yellow flag applies (there are no leaders to slow).
- If no racer finishes inside the maximum race time, the race is called and all are classified by distance.
- A tournament with one ready racer crowns it by byes without racing.
- If weather cannot be fetched, the race runs dry and calm and says so.
- A track with no eligible ready racer cannot be started.
