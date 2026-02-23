import math
import numpy as np
from utils.random_generator import random_generator
from core.event_log import EventType


class EnvironmentPressure:
    """Base class for all environment pressures."""

    def __init__(self, name, description, duration):
        self.name = name
        self.description = description
        self.duration = duration

    def apply(self, grid, zone_manager, barrier_manager, params):
        """Apply the pressure to the environment."""
        pass

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        """Update the pressure each generation."""
        pass

    def remove(self, grid, zone_manager, barrier_manager):
        """Remove the pressure from the environment."""
        zone_manager.clear_zones()

    def survival_modifier(self, creature, passed, score):
        """Modify survival check for a creature. Returns (passed, score)."""
        return passed, score

    def get_display_overlay(self):
        """Return display information dict."""
        return {'name': self.name, 'description': self.description}


class WallPressure(EnvironmentPressure):
    """Hazard zone on 1-4 sides."""

    def __init__(self, duration):
        super().__init__("Wall", "Hazard zones along arena edges", duration)
        sides = ['left', 'right', 'top', 'bottom']
        num_sides = random_generator.random_uint(1, 4)
        # Shuffle and pick
        indices = list(range(4))
        for i in range(len(indices) - 1, 0, -1):
            j = random_generator.random_uint(0, i)
            indices[i], indices[j] = indices[j], indices[i]
        self.sides = [sides[indices[i]] for i in range(num_sides)]
        self.width_pct = random_generator.random_float() * 22 + 3  # 3-25%
        self.lethality = random_generator.random_float() * 0.6 + 0.3  # 0.3-0.9

    def apply(self, grid, zone_manager, barrier_manager, params):
        zone_manager.clear_zones()
        for side in self.sides:
            zone_manager.create_directional_zone(side, self.width_pct, zone_type=2)

    def remove(self, grid, zone_manager, barrier_manager):
        zone_manager.clear_zones()

    def survival_modifier(self, creature, passed, score):
        if creature.in_safe_zone:
            return passed, score
        # Creature is in hazard zone - reduce score
        return passed, score * (1.0 - self.lethality)


class CorridorPressure(EnvironmentPressure):
    """Two hazard zones converging, leaving a safe band."""

    def __init__(self, duration):
        super().__init__("Corridor", "Converging hazard zones with safe corridor", duration)
        self.band_pct = random_generator.random_float() * 15 + 15  # 15-30%
        self.band_center = 50.0  # Start centered
        self.drift_speed = random_generator.random_float() * 0.5 + 0.1

    def apply(self, grid, zone_manager, barrier_manager, params):
        self._update_zones(zone_manager, 0.0)

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        self._update_zones(zone_manager, fraction_complete)

    def _update_zones(self, zone_manager, fraction):
        zone_manager.clear_zones()
        # Drift center on sine wave
        offset = math.sin(fraction * 2 * math.pi * 3) * 15
        center = 50.0 + offset
        half_band = self.band_pct / 2
        top_pct = max(1, center - half_band)
        bottom_pct = max(1, 100 - (center + half_band))
        if top_pct > 1:
            zone_manager.create_directional_zone('top', top_pct, zone_type=2)
        if bottom_pct > 1:
            zone_manager.create_directional_zone('bottom', bottom_pct, zone_type=2)

    def remove(self, grid, zone_manager, barrier_manager):
        zone_manager.clear_zones()


class BloomPressure(EnvironmentPressure):
    """Circular safe zone that drifts and pulses."""

    def __init__(self, duration):
        super().__init__("Bloom", "Drifting safe zone bloom", duration)
        self.center_x = random_generator.random_float() * 0.6 + 0.2  # 0.2-0.8 normalized
        self.center_y = random_generator.random_float() * 0.6 + 0.2
        self.base_radius_pct = random_generator.random_float() * 10 + 15  # 15-25% of map
        self.momentum_x = 0.0
        self.momentum_y = 0.0
        self.score_multiplier = random_generator.random_float() * 0.5 + 1.5  # 1.5-2.0

    def apply(self, grid, zone_manager, barrier_manager, params):
        self._place_bloom(zone_manager, params, 0.0)

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        # Random walk with momentum
        self.momentum_x += (random_generator.random_float() - 0.5) * 0.02
        self.momentum_y += (random_generator.random_float() - 0.5) * 0.02
        self.momentum_x *= 0.95  # Damping
        self.momentum_y *= 0.95
        self.center_x = max(0.15, min(0.85, self.center_x + self.momentum_x))
        self.center_y = max(0.15, min(0.85, self.center_y + self.momentum_y))
        self._place_bloom(zone_manager, params, fraction_complete)

    def _place_bloom(self, zone_manager, params, fraction):
        zone_manager.clear_zones()
        # Pulse radius on sine wave
        pulse = math.sin(fraction * 2 * math.pi * 5) * 5
        radius_pct = self.base_radius_pct + pulse
        world_w = params['world_size'][0]
        world_h = params['world_size'][1]
        cx = int(self.center_x * world_w)
        cy = int(self.center_y * world_h)
        radius = int(radius_pct / 100 * min(world_w, world_h))
        zone_manager.create_zone((cx, cy), radius * 2, zone_type=1)

    def remove(self, grid, zone_manager, barrier_manager):
        zone_manager.clear_zones()

    def survival_modifier(self, creature, passed, score):
        if creature.in_safe_zone:
            return passed, score * self.score_multiplier
        return passed, score * 0.8


class DroughtPressure(EnvironmentPressure):
    """80% hazard with small refuge zone."""

    def __init__(self, duration):
        super().__init__("Drought", "Harsh drought with small refuge", duration)
        self.lethality = random_generator.random_float() * 0.1 + 0.1  # 0.1-0.2
        self.refuge_x = random_generator.random_float() * 0.6 + 0.2
        self.refuge_y = random_generator.random_float() * 0.6 + 0.2
        self.refuge_pct = random_generator.random_float() * 10 + 15  # 15-25%
        self.shift_counter = 0

    def apply(self, grid, zone_manager, barrier_manager, params):
        self._place_refuge(zone_manager, params)

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        self.shift_counter += 1
        if self.shift_counter >= 100:
            self.shift_counter = 0
            self.refuge_x = random_generator.random_float() * 0.6 + 0.2
            self.refuge_y = random_generator.random_float() * 0.6 + 0.2
            self._place_refuge(zone_manager, params)

    def _place_refuge(self, zone_manager, params):
        zone_manager.clear_zones()
        # Set entire grid to hazard directly, then stamp safe refuge on top
        zone_manager.grid.data[:, :, 2] = 2
        world_w = params['world_size'][0]
        world_h = params['world_size'][1]
        cx = int(self.refuge_x * world_w)
        cy = int(self.refuge_y * world_h)
        radius = int(self.refuge_pct / 100 * min(world_w, world_h))
        zone_manager.create_zone((cx, cy), radius * 2, zone_type=1)

    def remove(self, grid, zone_manager, barrier_manager):
        zone_manager.clear_zones()

    def survival_modifier(self, creature, passed, score):
        if creature.in_safe_zone:
            return passed, score
        return passed, score * (1.0 - self.lethality)


class WavePressure(EnvironmentPressure):
    """Hazard band that sweeps across the map."""

    def __init__(self, duration):
        super().__init__("Wave", "Sweeping hazard wave", duration)
        self.band_width_pct = random_generator.random_float() * 10 + 10  # 10-20%
        self.speed = random_generator.random_float() + 1  # 1-2 cells/gen equivalent
        self.position = 0.0  # 0-100% position

    def apply(self, grid, zone_manager, barrier_manager, params):
        self._update_wave(zone_manager)

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        self.position += self.speed
        if self.position > 100:
            self.position = 0.0
        self._update_wave(zone_manager)

    def _update_wave(self, zone_manager):
        zone_manager.clear_zones()
        # Create hazard band at current position using left+right zones
        left_edge = max(0, self.position - self.band_width_pct / 2)
        right_edge = min(100, self.position + self.band_width_pct / 2)
        if left_edge > 0:
            # Safe zone on the left of the wave
            pass
        # Create the hazard band as a directional zone from left
        if right_edge > left_edge:
            zone_manager.create_directional_zone('left', right_edge, zone_type=2)
            if left_edge > 0:
                # Overwrite the left part back to neutral by creating safe zone
                zone_manager.create_directional_zone('left', left_edge, zone_type=0)

    def remove(self, grid, zone_manager, barrier_manager):
        zone_manager.clear_zones()


class PartitionPressure(EnvironmentPressure):
    """Barrier wall for first half, then removal."""

    def __init__(self, duration):
        super().__init__("Partition", "Barrier wall dividing arena", duration)
        self.barrier_active = True

    def apply(self, grid, zone_manager, barrier_manager, params):
        # Create a vertical barrier in center
        barrier_manager.create_barriers(1)
        self.barrier_active = True

    def update(self, generation, fraction_complete, grid, zone_manager, barrier_manager, params):
        if fraction_complete >= 0.5 and self.barrier_active:
            # Remove barrier at midpoint
            barrier_manager.create_barriers(0)
            self.barrier_active = False

    def remove(self, grid, zone_manager, barrier_manager):
        if self.barrier_active:
            barrier_manager.create_barriers(0)
            self.barrier_active = False


PRESSURE_CLASSES = {
    'wall': WallPressure,
    'corridor': CorridorPressure,
    'bloom': BloomPressure,
    'drought': DroughtPressure,
    'wave': WavePressure,
    'partition': PartitionPressure,
}


class EnvironmentManager:
    """Manages the lifecycle of environment pressures."""

    def __init__(self, grid, zone_manager, barrier_manager, radiation_manager, params, event_log):
        self.grid = grid
        self.zone_manager = zone_manager
        self.barrier_manager = barrier_manager
        self.radiation_manager = radiation_manager
        self.params = params
        self.event_log = event_log

        self.current_pressure = None
        self.next_pressure = None
        self.pressure_start_gen = 0
        self.pressure_duration = 0
        self.in_transition = False
        self.transition_start_gen = 0
        self.transition_duration = params.get('transition_duration', 50)
        self.outgoing_pressure = None
        self.last_pressure_name = None

    def step_generation(self, generation):
        """Manage pressure lifecycle. Returns list of events."""
        events = []

        if self.current_pressure is None:
            # Start first pressure
            self._start_new_pressure(generation)
            self._cap_hazard_coverage()
            if self.current_pressure:
                evt = self.event_log.log(
                    generation, EventType.PRESSURE_START,
                    f"Pressure started: {self.current_pressure.name}",
                    {'pressure': self.current_pressure.name}
                )
                events.append(evt)
            return events

        elapsed = generation - self.pressure_start_gen

        if self.in_transition:
            # We're transitioning between pressures
            trans_elapsed = generation - self.transition_start_gen
            if trans_elapsed >= self.transition_duration:
                # Transition complete
                self.in_transition = False
                if self.outgoing_pressure:
                    self.outgoing_pressure.remove(self.grid, self.zone_manager, self.barrier_manager)
                self.outgoing_pressure = None
                evt = self.event_log.log(
                    generation, EventType.TRANSITION_END,
                    f"Transition complete, now: {self.current_pressure.name}",
                    {'pressure': self.current_pressure.name}
                )
                events.append(evt)
                self.pressure_start_gen = generation
            else:
                # Update both pressures during transition
                trans_frac = trans_elapsed / self.transition_duration
                if self.current_pressure:
                    self.current_pressure.update(
                        generation, 0.0, self.grid,
                        self.zone_manager, self.barrier_manager, self.params
                    )
        elif elapsed >= self.pressure_duration:
            # Time to transition to next pressure
            self.outgoing_pressure = self.current_pressure
            evt = self.event_log.log(
                generation, EventType.PRESSURE_END,
                f"Pressure ending: {self.current_pressure.name}",
                {'pressure': self.current_pressure.name}
            )
            events.append(evt)

            self._start_new_pressure(generation)
            self.in_transition = True
            self.transition_start_gen = generation

            evt = self.event_log.log(
                generation, EventType.TRANSITION_START,
                f"Transitioning to: {self.current_pressure.name}",
                {'pressure': self.current_pressure.name}
            )
            events.append(evt)
        else:
            # Normal update
            fraction = elapsed / self.pressure_duration if self.pressure_duration > 0 else 0
            self.current_pressure.update(
                generation, fraction, self.grid,
                self.zone_manager, self.barrier_manager, self.params
            )

        self._cap_hazard_coverage()
        return events

    def apply_survival_modifiers(self, creature, passed, score):
        """Apply current pressure's survival modifier."""
        if self.in_transition and self.outgoing_pressure and self.current_pressure:
            trans_elapsed = 0
            if self.transition_start_gen > 0:
                # Can't easily get current gen here, use fraction approach
                pass
            # During transition, use current pressure only (simplified)
            return self.current_pressure.survival_modifier(creature, passed, score)
        elif self.current_pressure:
            return self.current_pressure.survival_modifier(creature, passed, score)
        return passed, score

    def get_current_pressure_name(self):
        if self.current_pressure:
            return self.current_pressure.name
        return "None"

    def get_pressure_progress(self):
        """Return 0.0-1.0 progress through current pressure."""
        if self.pressure_duration <= 0:
            return 0.0
        # We don't have current gen here, caller should compute
        return 0.0

    def _start_new_pressure(self, generation):
        """Select and start a new pressure."""
        pressure_name = self._select_next_pressure()
        min_dur = self.params.get('pressure_min_duration', 300)
        max_dur = self.params.get('pressure_max_duration', 800)
        duration = random_generator.random_uint(min_dur, max_dur)

        pressure_cls = PRESSURE_CLASSES.get(pressure_name)
        if pressure_cls:
            self.current_pressure = pressure_cls(duration)
            self.current_pressure.apply(
                self.grid, self.zone_manager, self.barrier_manager, self.params
            )
            self.pressure_start_gen = generation
            self.pressure_duration = duration
            self.last_pressure_name = pressure_name

    def _cap_hazard_coverage(self, max_fraction=0.70):
        """Ensure hazard zones don't cover more than max_fraction of the map."""
        zone_layer = self.grid.data[:, :, 2]
        total_cells = zone_layer.size
        hazard_count = int((zone_layer == 2).sum())
        if hazard_count > total_cells * max_fraction:
            # Convert excess hazard cells back to neutral, starting from random positions
            hazard_xs, hazard_ys = (zone_layer == 2).nonzero()
            excess = hazard_count - int(total_cells * max_fraction)
            # Randomly pick excess cells to convert back to neutral
            indices = np.arange(len(hazard_xs))
            np.random.shuffle(indices)
            for i in range(min(excess, len(indices))):
                idx = indices[i]
                self.grid.data[hazard_xs[idx], hazard_ys[idx], 2] = 0

    def _select_next_pressure(self):
        """Select next pressure using weighted random, avoiding repeats."""
        weights = self.params.get('pressure_weights', {})
        candidates = []
        total_weight = 0.0
        for name, weight in weights.items():
            if name != self.last_pressure_name and weight > 0:
                candidates.append((name, weight))
                total_weight += weight

        if not candidates:
            # All filtered out, allow repeat
            for name, weight in weights.items():
                if weight > 0:
                    candidates.append((name, weight))
                    total_weight += weight

        if not candidates:
            return 'wall'  # Fallback

        r = random_generator.random_float() * total_weight
        cumulative = 0.0
        for name, weight in candidates:
            cumulative += weight
            if r <= cumulative:
                return name
        return candidates[-1][0]
