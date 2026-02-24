import pygame
from visualization.display_driver import DisplayDriver, DisplayFrame, SidebarData


class PyGameDriver(DisplayDriver):
    """Pygame-based display driver with sidebar."""

    SIDEBAR_WIDTH = 250
    RESOLUTION = (1200, 800)

    def __init__(self):
        self.screen = None
        self.font = None
        self.small_font = None
        self.title_font = None

    def initialize(self, screen):
        """Receive the pygame screen reference."""
        self.screen = screen
        self.font = pygame.font.SysFont(None, 22)
        self.small_font = pygame.font.SysFont(None, 18)
        self.title_font = pygame.font.SysFont(None, 26)

    def get_resolution(self):
        return self.RESOLUTION

    def get_palette(self):
        return [
            (0, 0, 0),        # black
            (255, 255, 255),   # white
            (255, 0, 0),       # red
            (0, 200, 0),       # green
            (0, 0, 255),       # blue
            (220, 180, 0),     # yellow
        ]

    def should_update(self, generation):
        return True

    def update(self, frame):
        """Render sidebar to the pygame screen."""
        if self.screen is None:
            return

        sidebar_data = frame.sidebar_data or SidebarData()
        screen_w, screen_h = self.screen.get_size()
        sidebar_x = screen_w - self.SIDEBAR_WIDTH

        # Draw sidebar background
        sidebar_rect = pygame.Rect(sidebar_x, 0, self.SIDEBAR_WIDTH, screen_h)
        pygame.draw.rect(self.screen, (18, 18, 24), sidebar_rect)
        pygame.draw.line(self.screen, (50, 50, 60), (sidebar_x, 0), (sidebar_x, screen_h), 2)

        x = sidebar_x + 12
        y = 12
        content_w = self.SIDEBAR_WIDTH - 24

        # Title
        title = self.title_font.render("Evolution Display", True, (240, 240, 240))
        self.screen.blit(title, (x, y))
        y += 32

        self._draw_separator(sidebar_x, y, screen_w)
        y += 6

        # Generation / Population
        if sidebar_data.continuous_mode:
            self._draw_text(f"Virtual Gen: {sidebar_data.generation}", x, y, (200, 200, 200))
            y += 22
            self._draw_text(f"Population: {sidebar_data.total_population}", x, y, (200, 200, 200))
            y += 22
            self._draw_text(f"Total Steps: {sidebar_data.total_steps}", x, y, (160, 160, 200))
            y += 22
            self._draw_text(f"Births: {sidebar_data.births_this_vgen}", x, y, (100, 255, 100))
            y += 22
            self._draw_text(f"Deaths: {sidebar_data.deaths_this_vgen}", x, y, (255, 100, 100))
            y += 22
            # Pop health
            pct = sidebar_data.survivors_last_gen_pct
            health_color = (100, 255, 100) if pct > 0.5 else (255, 200, 80) if pct > 0.2 else (255, 80, 80)
            self._draw_text(f"Pop Health: {pct:.0%}", x, y, health_color)
            y += 22
        else:
            self._draw_text(f"Generation: {sidebar_data.generation}", x, y, (200, 200, 200))
            y += 22
            self._draw_text(f"Population: {sidebar_data.total_population}", x, y, (200, 200, 200))
            y += 22

            # Survivors from previous generation
            if sidebar_data.survivors_last_gen > 0:
                pct = sidebar_data.survivors_last_gen_pct
                pct_color = (100, 255, 100) if pct > 0.3 else (255, 200, 80) if pct > 0.1 else (255, 80, 80)
                self._draw_text(f"Survivors: {sidebar_data.survivors_last_gen} ({pct:.0%})", x, y, pct_color)
                y += 22

        y += 6
        self._draw_separator(sidebar_x, y, screen_w)
        y += 6

        # Pressure / Challenge info
        self._draw_text(sidebar_data.mode_label, x, y, (255, 200, 100))
        y += 22
        pressure_color = (100, 255, 100) if sidebar_data.current_pressure != "None" else (120, 120, 120)
        self._draw_text(f"  {sidebar_data.current_pressure}", x, y, pressure_color)
        y += 20
        if sidebar_data.pressure_since_gen > 0:
            self._draw_text(f"  Since gen {sidebar_data.pressure_since_gen}", x, y, (120, 120, 120), small=True)
            y += 16

        # Progress bar
        bar_x = x
        bar_w = content_w
        bar_h = 6
        pygame.draw.rect(self.screen, (40, 40, 45), (bar_x, y, bar_w, bar_h), border_radius=3)
        fill_w = int(bar_w * min(1.0, sidebar_data.pressure_progress))
        if fill_w > 1:
            pygame.draw.rect(self.screen, (80, 180, 80), (bar_x, y, fill_w, bar_h), border_radius=3)
        y += 18

        self._draw_separator(sidebar_x, y, screen_w)
        y += 6

        # Species info
        self._draw_text("Species", x, y, (255, 200, 100))
        y += 24
        species_colors = [(220, 50, 50), (50, 100, 220)]
        for sid in range(min(2, len(sidebar_data.species_populations))):
            pop = sidebar_data.species_populations[sid]
            rate = sidebar_data.species_survival_rates[sid] if sid < len(sidebar_data.species_survival_rates) else 0
            trend = sidebar_data.species_trends[sid] if sid < len(sidebar_data.species_trends) else 'stable'
            color = species_colors[sid]

            # Color swatch + label
            pygame.draw.rect(self.screen, color, (x, y + 2, 10, 10))

            trend_sym = {'up': '+', 'down': '-', 'stable': '', 'extinct': 'X'}.get(trend, '')
            label = f"Sp{sid}: {pop}"
            self._draw_text(label, x + 16, y, (210, 210, 210))

            # Rate text to the right
            rate_str = f"{rate:.0%}" + (f" {trend_sym}" if trend_sym else "")
            rate_surface = self.font.render(rate_str, True, (160, 160, 160))
            self.screen.blit(rate_surface, (x + content_w - rate_surface.get_width(), y))
            y += 20

            # Population bar — solid proportional rectangle
            max_pop = sidebar_data.total_population if sidebar_data.total_population > 0 else 1
            pop_frac = pop / max_pop
            bar_full_w = content_w
            pygame.draw.rect(self.screen, (35, 35, 40), (x, y, bar_full_w, 5), border_radius=2)
            pop_bar_w = int(bar_full_w * pop_frac)
            if pop_bar_w > 0:
                pygame.draw.rect(self.screen, color, (x, y, pop_bar_w, 5), border_radius=2)
            y += 14

        y += 6
        self._draw_separator(sidebar_x, y, screen_w)
        y += 6

        # Event log
        self._draw_text("Events", x, y, (255, 200, 100))
        y += 22
        events = sidebar_data.recent_events[-6:]
        for i, event_str in enumerate(events):
            # Most recent event is white, older ones are grey
            is_newest = (i == len(events) - 1)
            evt_color = (255, 255, 255) if is_newest else (150, 150, 150)
            # Word wrap long events instead of truncating
            y = self._draw_wrapped_text(event_str, x, y, content_w, evt_color, small=True)

        # Extinction count
        if sidebar_data.extinction_count > 0:
            y += 8
            self._draw_separator(sidebar_x, y, screen_w)
            y += 6
            self._draw_text(f"Extinctions: {sidebar_data.extinction_count}", x, y, (255, 80, 80))

    def _draw_text(self, text, x, y, color, small=False):
        font = self.small_font if small else self.font
        if font:
            surface = font.render(text, True, color)
            self.screen.blit(surface, (x, y))

    def _draw_wrapped_text(self, text, x, y, max_width, color, small=False):
        """Draw text with word wrapping. Returns the y position after the last line."""
        font = self.small_font if small else self.font
        if not font:
            return y + 16

        words = text.split(' ')
        lines = []
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            test_width = font.size(test_line)[0]
            if test_width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)

        line_height = 16 if small else 20
        for line in lines:
            surface = font.render(line, True, color)
            self.screen.blit(surface, (x, y))
            y += line_height

        return y

    def _draw_separator(self, sidebar_x, y, screen_w):
        """Draw a thin 1px separator line across the sidebar."""
        pygame.draw.line(self.screen, (45, 45, 55), (sidebar_x + 10, y), (screen_w - 10, y), 1)
