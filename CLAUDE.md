# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Running the Simulation
```bash
python main.py                              # Run with default params
python main.py --config config_eink.json   # Run with e-ink evolution display config
python main.py --config biosim4.ini        # Run with a C++ biosim4 INI config
```

### Installation
```bash
pip install -r requirements.txt   # Install dependencies
pip install -e .                  # Install in development mode
```

### Running Tests
```bash
python -m pytest tests/                             # Run all tests
python -m pytest tests/test_neural_network.py       # Run a single test file
python -m pytest tests/test_deterministic.py -v     # Run with verbose output
```

Tests use `unittest`. 5 tests are pre-existing failures (4 deterministic + 1 responsiveness_curve); 8 should pass.

## Architecture

### Two Operating Modes

The simulation has two selection modes controlled by `environment_system` in config:

1. **Classic challenge mode** (`environment_system: false`): Uses `challenge` param (0-19) for positional survival criteria (e.g., right half, circle, corners). Selection happens via `SurvivalCriteria.check_criterion()`.

2. **Environment pressure mode** (`environment_system: true`): Ignores challenge system entirely. Selection is **energy-based** — creatures in hazard zones lose energy and die, creatures in safe zones gain energy. Survivors are scored by remaining energy. Six pressure types rotate automatically (Wall, Corridor, Bloom, Drought, Wave, Partition).

### Module Overview

- **`main.py`** — Entry point. Creates Grid, Signals, ZoneManager, BarrierManager, EventLog, EnvironmentManager, DisplayDriver, and wires them into `InteractiveSimulator`.
- **`core/`** — Simulation engine:
  - `params.py` — `DEFAULT_PARAMS` dict + `load_parameters()`. JSON/INI config merges over defaults.
  - `grid.py` — 2D grid; `data[x, y, 0]` = creature ID, `data[x, y, 2]` = zone type (0=none, 1=safe, 2=hazard).
  - `simulator.py` — `Simulator` base class with generation loop.
  - `survival_criteria.py` — `CHALLENGE_*` constants + `SurvivalCriteria` class. `CHALLENGE_NONE = 20` passes all alive creatures (used with environment_system).
  - `event_log.py` — `EventType` enum, `Event` dataclass, `EventLog` class for tracking simulation events.
  - `types.py` — `Sensor` enum (24 sensors, indices 0–23) and `Action` enum (17 actions, indices 0–16).
- **`agents/`** — Creature logic:
  - `creature.py` — `Creature` class with `species_id`, energy system (starts at 500, metabolism 0.1/step), zone sensors (ZONE_HERE, ZONE_FWD, ENERGY).
  - `population.py` — Selection logic splits by mode: environment_system uses energy-based selection, classic uses challenge criteria. Species-aware selection when `num_species >= 2`. Has `environment_manager` attribute for applying survival modifiers.
  - `genome.py` / `neural_network.py` — Gene encoding and neural network from genome.
- **`environment/`** — Environmental systems:
  - `environment_manager.py` — `EnvironmentManager` orchestrates pressure lifecycle. Six `EnvironmentPressure` subclasses: WallPressure, CorridorPressure, BloomPressure, DroughtPressure, WavePressure, PartitionPressure. Has 70% hazard coverage cap.
  - `zones.py` — `ZoneManager`; `create_zone()` (circular), `create_directional_zone()` (edge-based), `clear_zones()`.
  - `barriers.py` / `radiation.py` — Barriers and radioactive walls.
- **`visualization/`** — Rendering:
  - `interactive_simulator.py` — `InteractiveSimulator` extends `Simulator`; pygame event loop, sidebar rendering, environment manager integration.
  - `renderer.py` — `GridRenderer` (zones with fills + borders, e-ink compatible colors) and `CreatureRenderer` (3px dots, species colors).
  - `display_driver.py` — `DisplayDriver` ABC, `SidebarData` / `DisplayFrame` dataclasses.
  - `pygame_driver.py` — `PyGameDriver` sidebar with word-wrapping events, survivors %, species stats.
  - `eink_driver.py` — `EInkDriver` stub for Waveshare 7.3" 6-color e-ink (updates every 50 gens).
  - `logger.py` — CSV logging with per-species columns when `num_species >= 2`.

### Data Flow

1. `load_parameters()` → flat params dict (see `DEFAULT_PARAMS` in `core/params.py`).
2. `Grid` + `Signals` constructed; all components share same `grid` and `params` refs.
3. Each step: creature reads sensors → neural network fires → actions applied → grid updates → energy adjusted by zone type.
4. At generation end: `EnvironmentManager.step_generation()` updates pressure → `Population.natural_selection_tournament()` selects survivors → offspring bred to fill population back to `population_size`.

### Key Design Decisions

- **biosim4 compatibility**: Sensor indices 0–20 and Action indices 0–16 match C++ biosim4 exactly. Python extensions (ZONE_HERE=21, ZONE_FWD=22, ENERGY=23) are appended after C++ range. Do not change existing enum indices.
- **Global RNG**: All randomness should go through `utils/random_generator.py`'s `random_generator` singleton for deterministic mode. (Note: some code still uses `random` directly — this is a known inconsistency.)
- **Energy system**: Creatures start at 500 energy. Safe zones add `safe_zone_bonus` (3.0)/step. Hazard zones subtract `hazard_zone_penalty` (5.0)/step. Metabolism costs 0.1/step. Death at energy ≤ 0.
- **Zone rendering**: Hazard zones fill with pale yellow (e-ink: yellow), safe zones with pale green (e-ink: green). Borders are orange/green respectively. All zone colors are from the 6-color e-ink palette (black, white, red, green, blue, yellow).
- **Two-species system**: `species_id` on creatures (0 or 1). Each species breeds independently to `population_size // 2`. Extinct species respawn if `species_respawn_on_extinction` is true.
- **Pressure lifecycle**: Each pressure lasts 300-800 gens, then 50-gen transition to next. Pressures selected by weighted random, no back-to-back repeats. Hazard coverage capped at 70% of map.
- **Config files**: `config_eink.json` is the primary config for the e-ink evolution display project. Default `config.json` (if present) is for classic biosim4-style runs.

### Known Issues

- `creature.py` historically had duplicated class definitions — has been cleaned up but watch for regressions.
- 5 tests are pre-existing failures unrelated to recent changes.
- `DroughtPressure` sets entire grid to hazard via `grid.data[:,:,2] = 2` then stamps safe refuge on top — this is intentional, not a bug.
