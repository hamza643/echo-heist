# ECHO HEIST

> **The guards remember every loop.**

A graphics-heavy, time-loop stealth heist game written in Python with **pygame**, in a single file. Each round you break into the bank, grab the loot and escape. Each time you retry, the guards remember everything you did before.

No AI/ML libraries and no external assets are needed. The guard "learning" is a simple path-frequency table plus a tile heat-map, and all sound effects are synthesised in code.

---

## Quick start

```bash
pip install pygame
python echo_heist.py
```

Requires Python 3.8+ and pygame 2.x.

---

## How to play

1. Sneak from the **EXIT pad** (bottom) to the **VAULT** (top) and pick up the loot.
2. Return to the **EXIT pad** before the 60-second timer runs out.
3. If you succeed, you bank the loot and score points. If you are caught or time runs out, the loop rewinds.
4. Either way, the guards learn from your run and the next loop is harder.

The map has three lanes (**LEFT**, **MIDDLE**, **RIGHT**) joined by two side connectors, so you can switch lanes mid-run.

### Controls

| Key | Action |
|---|---|
| `W A S D` / Arrow keys | Move |
| `SHIFT` (hold) | Sneak: slower, quieter, shorter detection range |
| `SPACE` / `ENTER` | Start loop / continue |
| `H` | Toggle heat-map overlay |
| `P` / `ESC` | Pause |
| `M` | Mute |
| `F` | Fullscreen |
| `R` | Memory wipe (new game, guards forget everything) |

---

## How the guards "remember"

### 1. Path frequency table
After every run, the game records which lane you spent the most time in and adds it to a table shown in the top-right **GUARD MEMORY** panel.

- A lane used **2 or more times** gets an **ambush guard** waiting there in the next loop.
- The more you reuse a lane, the longer that guard's vision range becomes.
- At **4 or more** uses, a second guard also covers the return path.
- The lane the guards expect you to take next is marked `<< PREDICTED`.

### 2. Heat-map
Every tile you step on is counted. From the third loop onward, a **Tracker** guard patrols your most-visited tiles. Press `H` at any time to see where you have been (the heat-map is also shown on the result screen).

### 3. Your echo
Your last two runs replay as **ECHO** ghosts. Guards that see an echo get distracted and chase it. If a guard touches an echo, it is **stunned for about 2 seconds**. Use your past self as a decoy, and plan around its faint path trail.

---

## Mechanics

- **Vision cones:** Cones are ray-cast and blocked by walls. A detection meter fills when you are in a cone and drains when you are not. Sneaking fills it slower.
- **Noise:** Running near a guard (about 3 tiles) makes it investigate, even without line of sight.
- **Alerts:** A spotted player triggers a chase and sends other guards to your last known position.
- **Cameras:** Three sweeping cameras raise an alarm if they fully detect you.
- **Lockdown:** After you grab the loot, patrol guards speed up and the alarm lighting pulses.
- **Scoring:** 1000 per successful heist, plus a time bonus, plus 100 for every guard your echo lured.

---

## Features

- Dynamic dark-lighting with light cut-outs and glowing entities
- Translucent vision cones, camera sweeps and alarm flashes
- Particles, screen shake, vignette and scanlines
- Glitch "rewind" transition and a briefing screen that shows where guards are deployed
- Animated title screen
- Procedurally synthesised sound effects (no audio files)
- Single file, around 900 lines, easy to hack on

---

## Tweaking the game

| What | Where in `echo_heist.py` |
|---|---|
| Loop time limit | `LOOP_TIME` |
| Ambush threshold (uses before a guard appears) | `Game.setup_guards()` (`c[i] >= 2`) |
| Guard vision range / FOV / speed | `Guard.__init__()` |
| Player speed | `Player.update()` |
| Map layout | `World.__init__()` (carved rectangles and pillars) |
| Camera positions | `Game.setup_cams()` |

---

## Troubleshooting

- **No sound:** Your system may lack an audio device. The game continues silently.
- **Low FPS:** Close other apps, or avoid fullscreen on very high-resolution displays. The window scales automatically.
- **Font looks different:** The game tries Consolas, DejaVu Sans Mono, Menlo and Courier New, then falls back to a system default.

---

## License

Free to use, modify and share. Add the license of your choice (MIT is a good default) before publishing.

---

Made by [@hamza643](https://github.com/hamza643)
