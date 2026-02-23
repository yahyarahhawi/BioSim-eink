import pygame
import numpy as np
import math
import logging
from visualization.challenge_renderer import ChallengeRenderer

# Set up logging
logger = logging.getLogger(__name__)

# E-ink 6-color palette for preview mode
EINK_PALETTE = [
    (0, 0, 0),        # black
    (255, 255, 255),   # white
    (255, 0, 0),       # red
    (0, 200, 0),       # green
    (0, 0, 255),       # blue
    (220, 180, 0),     # yellow
]


def _nearest_eink_color(color):
    """Quantize an RGB color to the nearest e-ink palette color."""
    best = EINK_PALETTE[0]
    best_dist = float('inf')
    for p in EINK_PALETTE:
        d = (color[0] - p[0]) ** 2 + (color[1] - p[1]) ** 2 + (color[2] - p[2]) ** 2
        if d < best_dist:
            best_dist = d
            best = p
    return best


class GridRenderer:
    """
    Handles rendering of the grid (zones, barriers, etc.) without creatures.
    """
    def __init__(self, display_scale):
        self.display_scale = display_scale
        self._zone_border_cache = None
        self._zone_border_gen = -1

    def render_grid(self, screen, grid, params=None):
        """Render the grid with zone outlines and barriers."""
        scale = self.display_scale
        eink = params and params.get('eink_preview', False)

        # Draw radiation (if enabled and params provided)
        if params and params.get('enable_radioactive_environment', False):
            for x in range(grid.size[0]):
                for y in range(grid.size[1]):
                    radiation = grid.data[x, y, 3]
                    if radiation > 0:
                        intensity = int(radiation * 255)
                        color = (intensity, intensity // 2, 0)
                        if eink:
                            color = _nearest_eink_color(color)
                        pygame.draw.rect(screen, color,
                                         (x * scale, y * scale, scale, scale))

        # Draw zone fills and borders
        self._render_zones(screen, grid, scale, eink)

        # Draw barriers — dark charcoal (black on e-ink)
        barrier_color = (50, 50, 50)
        if eink:
            barrier_color = (0, 0, 0)
        for bx, by in grid.barrier_locations:
            pygame.draw.rect(screen, barrier_color,
                             (bx * scale, by * scale, scale, scale))

    def _render_zones(self, screen, grid, scale, eink):
        """Draw zone fills and border outlines."""
        w, h = grid.size
        zone_layer = grid.data[:, :, 2]

        # E-ink compatible colors:
        # Hazard fill: yellow (220, 180, 0) — subtle on white background
        # Hazard border: red (255, 0, 0)
        # Safe fill: light green tint
        # Safe border: green (0, 200, 0)
        hazard_fill = (255, 248, 200) if not eink else (220, 180, 0)  # pale yellow / e-ink yellow
        hazard_border = (220, 120, 40) if not eink else (255, 0, 0)
        safe_fill = (220, 255, 220) if not eink else (0, 200, 0)  # pale green / e-ink green
        safe_border = (0, 200, 0)

        for x in range(w):
            for y in range(h):
                zt = zone_layer[x, y]
                if zt == 0:
                    continue

                # Check if this cell is on the border of its zone
                is_border = False
                for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nx, ny = x + dx, y + dy
                    if nx < 0 or nx >= w or ny < 0 or ny >= h:
                        is_border = True
                        break
                    if zone_layer[nx, ny] != zt:
                        is_border = True
                        break

                if zt == 2:  # Hazard zone
                    if is_border:
                        pygame.draw.rect(screen, hazard_border,
                                         (x * scale, y * scale, scale, scale))
                    else:
                        pygame.draw.rect(screen, hazard_fill,
                                         (x * scale, y * scale, scale, scale))
                elif zt == 1:  # Safe zone
                    if is_border:
                        pygame.draw.rect(screen, safe_border,
                                         (x * scale, y * scale, scale, scale))
                    else:
                        pygame.draw.rect(screen, safe_fill,
                                         (x * scale, y * scale, scale, scale))


class CreatureRenderer:
    """
    Handles rendering of creatures on the grid.
    """
    def __init__(self, display_scale):
        self.display_scale = display_scale

    def render_creatures(self, screen, creatures, params):
        """Render creatures as clean filled circles."""
        scale = self.display_scale
        eink = params.get('eink_preview', False)

        # Fixed radius of 3px for clean dots
        radius = 3

        screen_width, screen_height = screen.get_size()

        num_species = params.get('num_species', 1)
        species_colors_cfg = params.get('species_colors', [[220, 50, 50], [50, 100, 220]])

        # Species default colors
        sp_colors = [
            (220, 50, 50),   # Species 0 — red
            (50, 100, 220),  # Species 1 — blue
        ]
        for i in range(min(2, len(species_colors_cfg))):
            sp_colors[i] = tuple(species_colors_cfg[i])

        divergence_tint = params.get('genome_divergence_tint', False)
        divergence_color = (230, 200, 0)

        for creature in creatures:
            if not creature.alive:
                continue

            # Calculate screen coordinates
            screen_x = int(creature.position[0] * scale + scale / 2)
            screen_y = int(creature.position[1] * scale + scale / 2)

            # Skip off-screen creatures
            if screen_x < 0 or screen_x >= screen_width:
                continue
            if screen_y < 0 or screen_y >= screen_height:
                continue

            # Determine color
            if num_species >= 2:
                sid = getattr(creature, 'species_id', 0)
                creature_color = sp_colors[sid] if sid < len(sp_colors) else sp_colors[0]
                if divergence_tint:
                    creature_color = self._apply_divergence_tint(creature, creature_color, divergence_color)
            else:
                creature_color = self.genome_to_color(creature.genome)

            if eink:
                creature_color = _nearest_eink_color(creature_color)

            # Draw filled circle
            pygame.draw.circle(screen, creature_color,
                               (screen_x, screen_y), radius)

            # Draw direction line if enabled (off by default)
            if params.get('show_direction_lines', False):
                line_length = params.get('direction_line_length', 1)
                if line_length > 0:
                    line_end = (
                        int((creature.position[0] + creature.direction[0] * line_length) * scale + scale / 2),
                        int((creature.position[1] + creature.direction[1] * line_length) * scale + scale / 2)
                    )
                    if 0 <= line_end[0] < screen_width and 0 <= line_end[1] < screen_height:
                        pygame.draw.line(
                            screen, (180, 180, 180),
                            (screen_x, screen_y), line_end,
                            params.get('direction_line_thickness', 1)
                        )

    def _apply_divergence_tint(self, creature, base_color, tint_color):
        """Tint divergent genomes yellow."""
        if not hasattr(creature, 'genome') or not creature.genome.genes:
            return base_color
        weight_sum = sum(abs(g.weight) for g in creature.genome.genes[:4])
        if weight_sum > 2.0:
            return tint_color
        return base_color

    def genome_to_color(self, genome):
        """Hash full genome to a vivid HSV color so different genomes look distinct."""
        import colorsys
        # Hash the full genome hex string
        genome_str = ''.join(g.hex_value for g in genome.genes)
        h = hash(genome_str) & 0xFFFFFFFF
        # Hue from hash — full spectrum
        hue = (h % 360) / 360.0
        # Fixed high saturation and value for vivid, visible colors
        r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.9)
        return (int(r * 255), int(g * 255), int(b * 255))


class Renderer:
    """
    Main renderer class that handles the complete rendering process.
    Uses GridRenderer and CreatureRenderer for specific rendering tasks.
    """
    def __init__(self, params):
        """Initialize the renderer"""
        self.step = None
        self.generation = None
        self.params = params
        self.display_scale = params['display_scale']

        # Define border size
        self.border_size = 20

        # Calculate adjusted display size to include border
        grid_width = params['world_size'][0] * self.display_scale
        grid_height = params['world_size'][1] * self.display_scale
        display_width = grid_width + (self.border_size * 2)
        display_height = grid_height + (self.border_size * 2)
        self.display_size = (display_width, display_height)

        # Initialize component renderers
        self.grid_renderer = GridRenderer(self.display_scale)
        self.creature_renderer = CreatureRenderer(self.display_scale)
        self.challenge_renderer = ChallengeRenderer(self.display_scale)

        # Initialize Pygame
        pygame.init()
        self.world = pygame.display.set_mode(self.display_size)
        pygame.display.set_caption("DeepEvolution Simulator")
        self.clock = pygame.time.Clock()

        # Font for text
        self.font = pygame.font.SysFont(None, 24)
        self.title_font = pygame.font.SysFont(None, 28)

        # Help window — hidden by default
        self.show_help = False
        self.instructions_size = (350, 550)
        self.instructions_window = pygame.Surface(self.instructions_size)
        self.instructions_window.set_alpha(200)
        self.instructions_pos = (10, self.display_size[1] - self.instructions_size[1] - 10)

        # Kill counter
        self.kill_count = 0
        self.show_kill_counter = False

    def render_help_window(self):
        """Render the help window with instructions"""
        self.instructions_window.fill((0, 0, 50))
        y_offset = 10

        title = self.title_font.render("CONTROLS", True, (255, 255, 255))
        self.instructions_window.blit(title, (10, y_offset))
        y_offset += 30

        controls = [
            f"Status: {'PAUSED' if hasattr(self, 'paused') and self.paused else 'RUNNING'}",
            "SPACE: Pause/Resume simulation",
            "+/-: Adjust simulation speed",
            f"Speed: {self.params['fps']} fps"
        ]

        if self.show_kill_counter:
            controls.append(f"Kills: {self.kill_count}")

        controls.extend([
            "",
            "Visual Controls:",
            "S: Toggle challenge highlighting",
            f"Challenge highlighting: {'ON' if self.params.get('show_challenge_areas', False) else 'OFF'}",
            "D: Toggle direction lines",
            f"Direction lines: {'ON' if self.params.get('show_direction_lines', False) else 'OFF'}",
            "K: Toggle kill counter",
            f"Kill counter: {'ON' if self.show_kill_counter else 'OFF'}",
            "B: Cycle background colors",
            f"Background: {tuple(self.params.get('background_color', [245, 243, 238]))}",
            "",
            "Barrier Types:",
            "0: No barriers",
            "1: Vertical bar in center",
            "2: Vertical bar in random location",
            "3: Five staggered blocks",
            f"Current barrier type: {self.params.get('barrier_type', 0)}",
            "",
            "Generation Control:",
            "G: Force new generation (when paused)",
            "R: Reset simulation and delete logs (when paused)",
            "",
            "F1: Toggle help display"
        ])

        for control in controls:
            if control == "":
                y_offset += 5
                continue
            control_text = self.font.render(control, True, (200, 200, 200))
            self.instructions_window.blit(control_text, (10, y_offset))
            y_offset += 22

        self.world.blit(self.instructions_window, self.instructions_pos)

    def render_world(self, grid, creatures):
        """Render the world and all creatures."""
        self.world.fill((30, 30, 40))

        grid_width = grid.size[0] * self.display_scale
        grid_height = grid.size[1] * self.display_scale
        grid_surface = pygame.Surface((grid_width, grid_height))

        bg_color = self.params.get('background_color', [245, 243, 238])
        grid_surface.fill(tuple(bg_color))

        # Render challenge area only when environment_system is not enabled
        challenge_type = self.params.get('challenge', None)
        if challenge_type is not None and self.params.get('show_challenge_areas', False):
            if not self.params.get('environment_system', False):
                self.challenge_renderer.render_challenge_area(grid_surface, grid, challenge_type, self.params)

        self.grid_renderer.render_grid(grid_surface, grid, self.params)
        self.creature_renderer.render_creatures(grid_surface, creatures, self.params)

        border_rect = pygame.Rect(
            self.border_size - 2, self.border_size - 2,
            grid_width + 4, grid_height + 4
        )
        pygame.draw.rect(self.world, (100, 100, 100), border_rect, 2)
        self.world.blit(grid_surface, (self.border_size, self.border_size))

        info_text = self.font.render(
            f"Gen: {self.generation} | Pop: {len(creatures)} | Step: {self.step}/{self.params['steps_per_generation']}",
            True, (255, 255, 255))
        self.world.blit(info_text, (10, 10))

        if self.show_kill_counter:
            kill_text = self.font.render(f"KILLS: {self.kill_count}", True, (255, 0, 0))
            self.world.blit(kill_text, (self.display_size[0] - 150, 10))

        if self.show_help:
            self.render_help_window()

        pygame.display.flip()
        self.clock.tick(self.params['fps'])

    def set_generation(self, generation):
        self.generation = generation

    def set_step(self, step):
        self.step = step

    def set_kill_count(self, kill_count):
        self.kill_count = kill_count

    def handle_events(self):
        running = True
        paused = False
        key_events = []

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                key_events.append(event)

                if event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_F1:
                    self.show_help = not self.show_help
                elif event.key == pygame.K_s:
                    self.params['show_challenge_areas'] = not self.params.get('show_challenge_areas', False)
                elif event.key == pygame.K_d:
                    self.params['show_direction_lines'] = not self.params.get('show_direction_lines', False)
                elif event.key == pygame.K_k:
                    self.show_kill_counter = not self.show_kill_counter
                elif event.key == pygame.K_b:
                    current_color = tuple(self.params.get('background_color', [245, 243, 238]))
                    if current_color == (245, 243, 238):
                        self.params['background_color'] = [0, 0, 0]
                    elif current_color == (0, 0, 0):
                        self.params['background_color'] = [20, 20, 50]
                    elif current_color == (20, 20, 50):
                        self.params['background_color'] = [20, 50, 20]
                    elif current_color == (20, 50, 20):
                        self.params['background_color'] = [50, 20, 20]
                    elif current_color == (50, 20, 20):
                        self.params['background_color'] = [40, 40, 40]
                    else:
                        self.params['background_color'] = [245, 243, 238]
                elif event.key == pygame.K_MINUS or event.key == pygame.K_KP_MINUS:
                    self.params['fps'] = max(10, self.params['fps'] - 30)
                elif event.key == pygame.K_PLUS or event.key == pygame.K_KP_PLUS or event.key == pygame.K_EQUALS:
                    self.params['fps'] = min(1000, self.params['fps'] + 30)

        self.paused = paused
        return running, paused, key_events
