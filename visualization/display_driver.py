from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


@dataclass
class SidebarData:
    generation: int = 0
    total_population: int = 0
    species_populations: List[int] = field(default_factory=lambda: [0, 0])
    species_survival_rates: List[float] = field(default_factory=lambda: [0.0, 0.0])
    species_trends: List[str] = field(default_factory=lambda: ['stable', 'stable'])
    current_pressure: str = "None"
    pressure_since_gen: int = 0
    pressure_progress: float = 0.0
    next_pressure_hint: str = ""
    mode_label: str = "Pressure"
    recent_events: List[str] = field(default_factory=list)
    extinction_count: int = 0
    survivors_last_gen: int = 0
    survivors_last_gen_pct: float = 0.0
    continuous_mode: bool = False
    total_steps: int = 0
    births_this_vgen: int = 0
    deaths_this_vgen: int = 0


@dataclass
class DisplayFrame:
    grid_pixels: Optional[np.ndarray] = None  # H x W x 3 uint8
    sidebar_data: Optional[SidebarData] = None


class DisplayDriver(ABC):
    @abstractmethod
    def get_resolution(self):
        """Return (width, height) tuple."""
        pass

    @abstractmethod
    def get_palette(self):
        """Return list of RGB tuples available."""
        pass

    @abstractmethod
    def update(self, frame):
        """Update the display with a new frame."""
        pass

    @abstractmethod
    def should_update(self, generation):
        """Return True if the display should be updated this generation."""
        pass
