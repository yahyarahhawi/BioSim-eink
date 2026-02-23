from enum import Enum
from dataclasses import dataclass, field
from typing import Any


class EventType(Enum):
    PRESSURE_START = "pressure_start"
    PRESSURE_END = "pressure_end"
    TRANSITION_START = "transition_start"
    TRANSITION_END = "transition_end"
    SPECIES_DIVERGENCE = "species_divergence"
    SPECIES_EXTINCTION_WARNING = "species_extinction_warning"
    SPECIES_EXTINCTION = "species_extinction"
    SPECIES_RESPAWN = "species_respawn"
    POPULATION_CRASH = "population_crash"
    POPULATION_BOOM = "population_boom"
    GENETIC_BOTTLENECK = "genetic_bottleneck"
    BEHAVIORAL_CONVERGENCE = "behavioral_convergence"
    CHALLENGE_CHANGE = "challenge_change"


@dataclass
class Event:
    generation: int
    event_type: EventType
    description: str
    data: dict = field(default_factory=dict)


class EventLog:
    def __init__(self):
        self.events = []

    def log(self, generation, event_type, description, data=None):
        event = Event(
            generation=generation,
            event_type=event_type,
            description=description,
            data=data or {}
        )
        self.events.append(event)
        return event

    def get_recent(self, n=10):
        return self.events[-n:]

    def get_by_type(self, event_type):
        return [e for e in self.events if e.event_type == event_type]
