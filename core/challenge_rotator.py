from core.event_log import EventType

# All available challenges with their IDs and names
AVAILABLE_CHALLENGES = {
    0: "Circle",
    1: "Right Half",
    2: "Right Quarter",
    4: "Center Weighted",
    5: "Corner",
    8: "Center Sparse",
    9: "Left Eighth",
    11: "Against Any Wall",
    13: "East-West Eighths",
    19: "Center Unweighted",
}

# Default rotation list
DEFAULT_CHALLENGE_SEQUENCE = [4, 5, 1, 13, 11, 9]


class ChallengeRotator:
    """Cycles through curated positional challenges to create strong selection pressure."""

    def __init__(self, params, event_log=None):
        self.params = params
        self.event_log = event_log
        self.rotation_interval = params.get('challenge_rotation_interval', 500)
        self.current_index = 0
        self.started_at_gen = 0

        # Build challenge list from config or use defaults
        sequence = params.get('challenge_sequence', DEFAULT_CHALLENGE_SEQUENCE)
        self.challenges = []
        for cid in sequence:
            name = AVAILABLE_CHALLENGES.get(cid, f"Challenge {cid}")
            self.challenges.append((cid, name))

        if not self.challenges:
            self.challenges = [(cid, AVAILABLE_CHALLENGES[cid]) for cid in DEFAULT_CHALLENGE_SEQUENCE]

        # Set initial challenge
        self.params['challenge'] = self.challenges[self.current_index][0]

    def step_generation(self, generation):
        """Check if it's time to rotate. Mutates params['challenge']."""
        gens_in_current = generation - self.started_at_gen
        if gens_in_current >= self.rotation_interval and generation > 0:
            self.current_index = (self.current_index + 1) % len(self.challenges)
            self.started_at_gen = generation
            challenge_id, name = self.challenges[self.current_index]
            self.params['challenge'] = challenge_id
            if self.event_log:
                self.event_log.log(generation, EventType.CHALLENGE_CHANGE, f"Challenge -> {name}")
        # Always ensure params matches current
        self.params['challenge'] = self.challenges[self.current_index][0]

    def get_current_name(self):
        return self.challenges[self.current_index][1]

    def get_progress(self, generation):
        """Fraction through current challenge (0.0 to 1.0)."""
        elapsed = generation - self.started_at_gen
        return min(1.0, elapsed / self.rotation_interval) if self.rotation_interval > 0 else 0.0
