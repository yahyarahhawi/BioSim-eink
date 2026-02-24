import time
import logging
import pygame
from core.simulator import Simulator
from core.event_log import EventType
from visualization.renderer import GridRenderer, CreatureRenderer
from visualization.challenge_renderer import ChallengeRenderer
from visualization.creature_lineage import CreatureLineageLogger
from visualization.display_driver import DisplayFrame, SidebarData

# Set up logging
logger = logging.getLogger(__name__)


class CustomRenderer:
    """Simple renderer that handles its own pygame surface"""

    def __init__(self, params):
        self.params = params
        self.display_scale = params['display_scale']
        
        # Define border sizes
        self.border_left = 20   # Pixels for left border
        self.border_right = 20  # Pixels for right border
        self.border_top = 60    # Pixels for top border (increased to make room for text)
        self.border_bottom = 20 # Pixels for bottom border
        
        # Create custom creature renderer that handles edge cases
        self.grid_renderer = GridRenderer(self.display_scale)
        
        # Use the updated CreatureRenderer from renderer.py
        # This version will skip rendering creatures that would be cut off at the edges
        self.creature_renderer = CreatureRenderer(self.display_scale)
        
        self.challenge_renderer = ChallengeRenderer(self.display_scale)

    def render_world(self, screen, grid, creatures):
        """Render the world with zones, barriers and creatures"""
        # Clear screen with white for e-ink palette compatibility
        bg = tuple(self.params.get('background_color', [255, 255, 255]))
        screen.fill(bg)
        
        # Create a surface for the grid with the exact grid dimensions
        grid_width = grid.size[0] * self.display_scale
        grid_height = grid.size[1] * self.display_scale
        grid_surface = pygame.Surface((grid_width, grid_height))
        
        # Use background color from params or default to white
        bg_color = self.params.get('background_color', [255, 255, 255])
        grid_surface.fill(tuple(bg_color))  # Background for grid
        
        # Render challenge area only when environment_system is not active
        challenge_type = self.params.get('challenge', None)
        if challenge_type is not None and self.params.get('show_challenge_areas', False):
            if not self.params.get('environment_system', False):
                self.challenge_renderer.render_challenge_area(grid_surface, grid, challenge_type, self.params)

        # Render grid elements (zones, barriers, etc.) on the grid surface
        self.grid_renderer.render_grid(grid_surface, grid, self.params)
        
        # Render creatures on the grid surface
        # The updated CreatureRenderer will skip creatures that would be cut off at the edges
        self.creature_renderer.render_creatures(grid_surface, creatures, self.params)
        
        # Draw a border around the grid
        border_rect = pygame.Rect(
            self.border_left - 2,  # Offset by 2 pixels to make border visible
            self.border_top - 2,
            grid_width + 6,  # Add 4 pixels to make border visible on all sides
            grid_height + 6
        )
        pygame.draw.rect(screen, (100, 100, 100), border_rect, 2)  # Gray border, 2 pixels thick
        
        # Blit the grid surface onto the main surface with the border offset
        screen.blit(grid_surface, (self.border_left, self.border_top))

    # genome_to_color method removed - now handled by CreatureRenderer


class InteractiveSimulator(Simulator):
    def __init__(self, params, grid, signals):
        """
        Initialize the interactive simulator with enhanced configuration tracking.

        Args:
            params (dict): Simulation configuration parameters
            grid (Grid): Simulation world grid
            signals (Signals): Pheromone/signal layer
        """
        # Initialize the base simulator
        super().__init__(params, grid, signals)
        
        # Track first-time initialization
        self._first_run = True

        # Store initial configuration
        self._initial_config = {
            'population_size': params['population_size'],
            'initial_params': params.copy()
        }

        # Interactive-specific state variables
        # Interactive UI state variables
        self.placing_zone = False
        self.zone_type = 1  # 1=safe, 2=hazard
        self.zone_size = params.get('zone_size', 50)
        self.directional_percentage = 10
        self.show_help = False
        self.show_kill_counter = False  # Toggle for kill counter display
        
        # Pygame references will be initialized in run()
        self.display_scale = params['display_scale']
        
        # Define border sizes
        self.border_left = 20   # Pixels for left border
        self.border_right = 20  # Pixels for right border
        self.border_top = 60    # Pixels for top border (increased to make room for text)
        self.border_bottom = 20 # Pixels for bottom border
        
        # Calculate adjusted display size to include borders
        grid_width = params['world_size'][0] * self.display_scale
        grid_height = params['world_size'][1] * self.display_scale
        display_width = grid_width + self.border_left + self.border_right
        display_height = grid_height + self.border_top + self.border_bottom
        self.display_size = (display_width, display_height)
        
        self.screen = None
        self.clock = None
        self.font = None
        self.title_font = None
        self.instructions_window = None
        self.instructions_size = (350, 550)
        self.instructions_pos = None
        self.custom_renderer = None

        # E-ink evolution display components
        self.event_log = None
        self.environment_manager = None
        self.challenge_rotator = None
        self.display_driver = None
        self.previous_population = 0
        self.similar_survival_counter = 0
        self.last_survivors_count = 0
        self.last_survivors_pct = 0.0

        # Continuous mode state
        self.total_steps = 0
        self.virtual_generation = 0
        self.rolling_births = 0
        self.rolling_deaths = 0
        self.rolling_reproducer_ids = set()
        self.birth_budget = 0.0          # fractional births owed
        self.deaths_last_vgen = 0        # deaths from previous vgen, sets next vgen's birth rate

    def initialize(self):
        """Initialize the simulation with interactive-specific behavior"""
        # Preserve initial configuration on first run
        if self._first_run:
            self._initial_config['initial_grid_data'] = self.grid.data.copy()
            self._initial_config['initial_signals_data'] = self.signals.data.copy()
            self._first_run = False

        # Reset grid with interactive zones preserved
        self.grid.reset(keep_interactive_zones=True)

        # Call the parent initialize method with our customizations
        super().initialize()

    def handle_events(self):
        """Handle pygame events and return control flags"""
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_SPACE:
                    # Toggle pause
                    self.paused = not self.paused
                    # logger.info(f"Simulation {'paused' if self.paused else 'resumed'}")

                # Challenge highlighting toggle
                elif event.key == pygame.K_s:
                    # Toggle challenge area highlighting
                    self.params['show_challenge_areas'] = not self.params.get('show_challenge_areas', False)
                    # logger.info(f"Challenge area highlighting {'enabled' if self.params['show_challenge_areas'] else 'disabled'}")
                
                # Barrier type keys (0-3)
                elif event.key == pygame.K_0:
                    self.params['barrier_type'] = 0
                    self.grid.reset()  # Clear existing barriers
                    self.barrier_manager.create_barriers(0)
                    # logger.info("Barrier type set to 0: None")
                elif event.key == pygame.K_1:
                    self.params['barrier_type'] = 1
                    self.grid.reset()  # Clear existing barriers
                    self.barrier_manager.create_barriers(1)
                    # logger.info("Barrier type set to 1: Vertical bar in center")
                elif event.key == pygame.K_2:
                    self.params['barrier_type'] = 2
                    self.grid.reset()  # Clear existing barriers
                    self.barrier_manager.create_barriers(2)
                    # logger.info("Barrier type set to 2: Vertical bar in random location")
                elif event.key == pygame.K_3:
                    self.params['barrier_type'] = 3
                    self.grid.reset()  # Clear existing barriers
                    self.barrier_manager.create_barriers(3)
                    # logger.info("Barrier type set to 3: Five staggered blocks")

                # Simulation speed controls
                elif event.key == pygame.K_MINUS or event.key == pygame.K_KP_MINUS:
                    self.params['fps'] = max(10, self.params['fps'] - 30)
                    # logger.info(f"Simulation speed decreased to {self.params['fps']} fps")
                elif event.key == pygame.K_PLUS or event.key == pygame.K_KP_PLUS or event.key == pygame.K_EQUALS:
                    self.params['fps'] = min(1000, self.params['fps'] + 30)
                    # logger.info(f"Simulation speed increased to {self.params['fps']} fps")

                # Feature toggles
                elif event.key == pygame.K_F1:
                    self.show_help = not self.show_help
                elif event.key == pygame.K_d:
                    self.params['show_direction_lines'] = not self.params.get('show_direction_lines', False)
                    # logger.info(f"Direction lines {'enabled' if self.params['show_direction_lines'] else 'disabled'}")
                elif event.key == pygame.K_k:
                    self.show_kill_counter = not self.show_kill_counter
                    print(f"Kill counter {'ON' if self.show_kill_counter else 'OFF'}")
                # Background color toggle
                elif event.key == pygame.K_b:
                    # Cycle through a few predefined colors
                    current_color = tuple(self.params.get('background_color', [255, 255, 255]))
                    if current_color == (255, 255, 255):  # White
                        self.params['background_color'] = [0, 0, 0]  # Black
                    elif current_color == (0, 0, 0):  # Black
                        self.params['background_color'] = [20, 20, 50]  # Dark blue
                    elif current_color == (20, 20, 50):  # Dark blue
                        self.params['background_color'] = [20, 50, 20]  # Dark green
                    elif current_color == (20, 50, 20):  # Dark green
                        self.params['background_color'] = [50, 20, 20]  # Dark red
                    elif current_color == (50, 20, 20):  # Dark red
                        self.params['background_color'] = [40, 40, 40]  # Dark gray
                    else:
                        self.params['background_color'] = [255, 255, 255]  # Back to white
                    print(f"Background color changed to: {self.params['background_color']}")

                # Force new generation (disabled in continuous mode)
                elif event.key == pygame.K_g and self.paused and not self.params.get('continuous_mode', False):
                    self.step = self.params['steps_per_generation']  # This will trigger a new generation
                    # logger.info("Forced new generation")

                # Save/Load population
                elif event.key == pygame.K_F5:
                    self._save_population()
                elif event.key == pygame.K_F9:
                    self._load_population()

                # Reset key
                elif event.key == pygame.K_r and self.paused:
                    # Delete log files from previous run
                    self._delete_log_files()
                    # Re-initialize simulation
                    self.initialize()
                    # logger.info("Simulation reset and log files deleted")

            # No more mouse events for placing zones

        return self.running, self.paused

    def create_zone(self, pos):
        """
        This method is kept for backward compatibility but doesn't create zones anymore
        since we're using different methods for reproduction selection
        """
        # We're not using zones anymore
        logger.info("Zone creation is disabled - using different methods for reproduction selection")

    def create_directional_zone(self, direction):
        """
        This method is kept for backward compatibility but doesn't create zones anymore
        since we're using different methods for reproduction selection
        """
        # We're not using zones anymore
        logger.info("Zone creation is disabled - using different methods for reproduction selection")
        
    def _save_population(self):
        """Save current population genomes to a pickle file."""
        import pickle
        save_data = {
            'generation': self.generation,
            'genomes': [([g.hex_value for g in c.genome.genes], getattr(c, 'species_id', 0)) for c in self.population.creatures],
        }
        path = 'population_save.pkl'
        try:
            with open(path, 'wb') as f:
                pickle.dump(save_data, f)
            print(f"Saved {len(self.population.creatures)} creatures at gen {self.generation} to {path}")
        except Exception as e:
            print(f"Save failed: {e}")

    def _load_population(self):
        """Load population genomes from a pickle file and rebuild creatures."""
        import pickle
        from agents.creature import Creature
        from agents.genome import Genome, Gene
        path = 'population_save.pkl'
        try:
            with open(path, 'rb') as f:
                save_data = pickle.load(f)
            genomes_data = save_data['genomes']
            new_creatures = []
            for hex_list, species_id in genomes_data:
                genome = Genome([Gene(h, params=self.params) for h in hex_list], params=self.params)
                creature = Creature(genome=genome, params=self.params, species_id=species_id)
                new_creatures.append(creature)
            self.population.creatures = new_creatures
            self._place_new_generation_optimized()
            print(f"Loaded {len(new_creatures)} creatures (saved at gen {save_data['generation']}), now at gen {self.generation}")
        except FileNotFoundError:
            print("No save file found (population_save.pkl)")
        except Exception as e:
            print(f"Load failed: {e}")

    def _delete_log_files(self):
        """Delete log files from previous runs"""
        import os
        import glob
        
        # Get the log folder from params
        log_folder = self.params.get('log_folder', 'evolution_logs')
        
        # Delete CSV log files
        csv_files = glob.glob(os.path.join(log_folder, "*.csv"))
        for file in csv_files:
            try:
                os.remove(file)
                # logger.info(f"Deleted log file: {file}")
            except Exception as e:
                # logger.error(f"Failed to delete log file {file}: {e}")
                pass
        
        # Delete other log files
        log_files = glob.glob("*.log") + glob.glob("*/*.log")
        for file in log_files:
            try:
                os.remove(file)
                # logger.info(f"Deleted log file: {file}")
            except Exception as e:
                # logger.error(f"Failed to delete log file {file}: {e}")
                pass

    def render_help_window(self):
        """Render the help window with instructions"""
        # Fill window with semi-transparent background
        self.instructions_window.fill((0, 0, 50))  # Dark blue background

        y_offset = 10

        # Display zone placement info if active
        if self.placing_zone:
            zone_text = self.font.render(
                f"Placing {'Safe' if self.zone_type == 1 else 'Hazard'} Zone | Size: {self.zone_size}",
                True, (255, 255, 0))
            self.instructions_window.blit(zone_text, (10, y_offset))

            action_text = self.font.render("Click to place, C to cancel", True, (255, 255, 0))
            self.instructions_window.blit(action_text, (10, y_offset + 30))
            y_offset += 60
        else:
            # General instructions
            title = self.title_font.render("CONTROLS", True, (255, 255, 255))
            self.instructions_window.blit(title, (10, y_offset))
            y_offset += 30

            # Basic controls
            controls = [
                f"Status: {'PAUSED' if self.paused else 'RUNNING'}",
                "SPACE: Pause/Resume simulation",
                "+/-: Adjust simulation speed",
                f"Speed: {self.params['fps']} fps"
            ]
            
            # Add kill count if kill counter is enabled
            if self.show_kill_counter:
                controls.append(f"Kills: {self.murder_count}")
                
            # Continue with the rest of the controls
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
            f"Background: {tuple(self.params.get('background_color', [255, 255, 255]))}",
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
                    y_offset += 5  # Less space for separation
                    continue

                control_text = self.font.render(control, True, (200, 200, 200))
                self.instructions_window.blit(control_text, (10, y_offset))
                y_offset += 22  # Reduced line spacing

        # Draw the instructions window
        self.screen.blit(self.instructions_window, self.instructions_pos)

    def update(self):
        """Update one simulation step — dispatches to generational or continuous mode."""
        if self.paused:
            return
        if self.params.get('continuous_mode', False):
            self._update_continuous()
        else:
            self._update_generational()

    def _update_generational(self):
        """Original generational update logic."""
        # Create a dictionary of creatures for quick lookup
        creatures_dict = {creature.id: creature for creature in self.population.creatures}

        # Update all creatures individually
        for creature in self.population.creatures:
            if creature.alive:
                # Pass the current simulation step to the creature update
                creature.update(self.grid, self.population.creatures, self.signals, self.step)

        # Process death queue and update kill count
        self.murder_count += len(self.grid.death_queue)
        self.grid.process_death_queue(creatures_dict)

        # Process move queue
        self.grid.process_move_queue(creatures_dict)

        # Update radiation if enabled
        if self.params.get('enable_radioactive_environment', False):
            self.radiation_manager.update_radiation()

        # Fade pheromones
        for layer in range(self.signals.num_layers):
            self.signals.fade(layer)

        # Increment step counter
        self.step += 1

        # Update params with current step for challenge visualization
        self.params['current_step'] = self.step

        # Check if generation is complete
        if self.step >= self.params['steps_per_generation']:
            self.end_generation()

    def _update_continuous(self):
        """Continuous mode: creatures have a fixed lifespan, die naturally,
        and are replaced by offspring of the fittest (highest energy) creatures.

        Simple loop:
          1. Move creatures (sensor → NN → action)
          2. Age creatures — kill those past lifespan
          3. Challenge energy: in-zone +bonus, out-of-zone -penalty
          4. Kill energy-depleted creatures
          5. Process queues, sweep dead
          6. Replace dead: spawn one offspring per death, parents chosen by energy rank
          7. Fade pheromones, challenge rotation, bookkeeping
        """
        from core.survival_criteria import SurvivalCriteria

        params = self.params
        target_pop = params['population_size']
        creatures_dict = {c.id: c for c in self.population.creatures}

        # 1. Move all alive creatures
        for creature in self.population.creatures:
            if creature.alive:
                creature.update(self.grid, self.population.creatures, self.signals, self.total_steps)

        # 2. Age + lifespan death
        for creature in self.population.creatures:
            if not creature.alive:
                continue
            creature.age_steps += 1
            if creature.max_lifespan > 0 and creature.age_steps >= creature.max_lifespan:
                creature.alive = False
                cx, cy = int(creature.position[0]), int(creature.position[1])
                if 0 <= cx < self.grid.size[0] and 0 <= cy < self.grid.size[1]:
                    if self.grid.data[cx, cy, 0] == creature.id:
                        self.grid.data[cx, cy, 0] = 0

        # 3. Challenge energy pressure (selective pressure — this is what drives evolution)
        criteria = SurvivalCriteria(params, self.grid)
        challenge_type = params.get('challenge', 0)
        bonus = params.get('continuous_challenge_bonus', 2.0)
        penalty = params.get('continuous_challenge_penalty', 3.0)

        for creature in self.population.creatures:
            if not creature.alive:
                continue
            if criteria.is_in_challenge_zone(creature, challenge_type):
                creature.energy += bonus
            else:
                creature.energy -= penalty

        # 4. Kill energy-depleted creatures
        deaths_this_step = 0
        for creature in self.population.creatures:
            if creature.alive and creature.energy <= 0:
                creature.alive = False
                deaths_this_step += 1
                cx, cy = int(creature.position[0]), int(creature.position[1])
                if 0 <= cx < self.grid.size[0] and 0 <= cy < self.grid.size[1]:
                    if self.grid.data[cx, cy, 0] == creature.id:
                        self.grid.data[cx, cy, 0] = 0

        self.rolling_deaths += deaths_this_step

        # 5. Process queues, sweep dead
        self.murder_count += len(self.grid.death_queue)
        self.grid.process_death_queue(creatures_dict)
        self.grid.process_move_queue(creatures_dict)

        prev_alive = len(self.population.creatures)
        self.population.creatures = [c for c in self.population.creatures if c.alive]
        total_died = prev_alive - len(self.population.creatures)
        self.rolling_deaths += max(0, total_died - deaths_this_step)  # catch queue deaths

        # 6. Replace dead: one offspring per death, parents = highest energy
        if total_died > 0:
            offspring, reproducer_ids = self.population.reproduce_top_n(
                self.grid, total_died)
            self.population.creatures.extend(offspring)
            self.rolling_births += len(offspring)
            self.rolling_reproducer_ids.update(reproducer_ids)

        # 7. Hard population floor (safety net)
        alive_count = len(self.population.creatures)
        min_pop = int(params.get('continuous_min_pop_fraction', 0.10) * target_pop)
        if alive_count < min_pop:
            injected = self.population.inject_random_creatures(self.grid, min_pop - alive_count)
            self.population.creatures.extend(injected)
            self.rolling_births += len(injected)

        # 8. Fade pheromones
        for layer in range(self.signals.num_layers):
            self.signals.fade(layer)

        # 9. Challenge rotation (step-based)
        rotation_interval = params.get('continuous_challenge_rotation_steps', 60000)
        if self.total_steps > 0 and self.total_steps % rotation_interval == 0:
            if self.challenge_rotator:
                self.challenge_rotator.step_generation(self.virtual_generation)
            if self.event_log:
                self.event_log.log(
                    self.virtual_generation, EventType.PRESSURE_CHANGE,
                    f"Challenge rotated at step {self.total_steps}",
                    {'step': self.total_steps}
                )

        # 10. Virtual generation bookkeeping
        self.total_steps += 1
        self.params['current_step'] = self.total_steps
        vgen_steps = params.get('continuous_virtual_gen_steps', 1000)
        if self.total_steps % vgen_steps == 0:
            self.virtual_generation += 1
            alive_now = len(self.population.creatures)
            repro_pct = (len(self.rolling_reproducer_ids) / alive_now * 100) if alive_now > 0 else 0.0
            print(f"VGen {self.virtual_generation} | Step {self.total_steps} | "
                  f"Pop: {alive_now}/{target_pop} | "
                  f"Births: {self.rolling_births} Deaths: {self.rolling_deaths} | "
                  f"Reproduced: {repro_pct:.1f}%")
            self.rolling_births = 0
            self.rolling_deaths = 0
            self.rolling_reproducer_ids = set()

    def end_generation(self):
        """Handle end of generation logic with interactive-specific behavior"""
        # Log generation stats
        self.logger.log_generation(self.generation, self.population.creatures, self.murder_count)

        # Count how many creatures will survive the radioactive walls challenge
        if self.params.get('challenge', 0) == 10:  # CHALLENGE_RADIOACTIVE_WALLS
            survivors_before_selection = 0
            for creature in self.population.creatures:
                if creature.alive:
                    result = self.survival_criteria.check_criterion(creature, 10)
                    if result[0]:  # If the creature passes the survival criterion
                        survivors_before_selection += 1
            print(f"Generation {self.generation}: {survivors_before_selection} creatures pass the radioactive walls challenge")

        # Perform natural selection
        pop_before = len(self.population.creatures)
        new_creatures, survivors_count, reproduction_count = self.population.natural_selection_tournament(self.grid)
        self.last_survivors_count = survivors_count
        self.last_survivors_pct = survivors_count / pop_before if pop_before > 0 else 0.0

        # Record survivors and reproduction counts in the logger
        if hasattr(self.logger, 'record_survivors'):
            self.logger.record_survivors(survivors_count)
        if hasattr(self.logger, 'record_reproduction'):
            self.logger.record_reproduction(reproduction_count)
        
        # Replace current population with new generation
        self.population.creatures = new_creatures
        
        # Log lineage information for the new generation
        self.lineage_logger.log_generation(self.generation, new_creatures)

        # Increment generation counter and reset step counter
        self.generation += 1
        self.step = 0
        self.murder_count = 0  # Reset kill count for new generation

        # Environment pressure system
        if self.environment_manager:
            self.environment_manager.step_generation(self.generation)

        # Challenge rotator
        if self.challenge_rotator:
            self.challenge_rotator.step_generation(self.generation)

        # Detect population events
        current_pop = len(self.population.creatures)
        if self.event_log and self.previous_population > 0:
            ratio = current_pop / self.previous_population if self.previous_population > 0 else 1.0
            if ratio < 0.5:
                self.event_log.log(
                    self.generation, EventType.POPULATION_CRASH,
                    f"Population crashed to {current_pop}",
                    {'previous': self.previous_population, 'current': current_pop}
                )
            elif ratio > 1.5:
                self.event_log.log(
                    self.generation, EventType.POPULATION_BOOM,
                    f"Population boomed to {current_pop}",
                    {'previous': self.previous_population, 'current': current_pop}
                )

            # Check genetic bottleneck
            from utils.genetic import calculate_genetic_diversity
            diversity = calculate_genetic_diversity(self.population.creatures[:50])
            if diversity < 0.1:
                self.event_log.log(
                    self.generation, EventType.GENETIC_BOTTLENECK,
                    f"Genetic bottleneck detected (diversity={diversity:.3f})",
                    {'diversity': diversity}
                )

            # Check species behavioral convergence
            if self.params.get('num_species', 1) >= 2 and hasattr(self.population, 'species_stats'):
                stats = self.population.species_stats
                if 0 in stats and 1 in stats:
                    r0 = stats[0].get('survival_rate', 0)
                    r1 = stats[1].get('survival_rate', 0)
                    if abs(r0 - r1) < 0.05 and r0 > 0.1:
                        self.similar_survival_counter += 1
                        if self.similar_survival_counter >= 20:
                            self.event_log.log(
                                self.generation, EventType.BEHAVIORAL_CONVERGENCE,
                                "Species showing behavioral convergence",
                                {'sp0_rate': r0, 'sp1_rate': r1}
                            )
                            self.similar_survival_counter = 0
                    else:
                        self.similar_survival_counter = 0

        self.previous_population = current_pop

        # Place new generation on the grid using the optimized approach
        self._place_new_generation_optimized()
        
        # Check if we've reached the maximum number of generations
        if 'max_generations' in self.params and self.generation >= self.params['max_generations']:
            print(f"Reached maximum number of generations ({self.params['max_generations']}). Simulation complete.")
            self.running = False
    
    def _place_new_generation_optimized(self):
        """Optimized version of placing new generation on the grid"""
        # Ultra-fast clearing using numpy operations and the non_barrier_mask
        creature_layer = self.grid.data[:, :, 0]
        creature_layer[self.grid.non_barrier_mask] = 0
        
        # Place creatures in valid locations - use a batch approach for better performance
        empty_positions = []
        
        # Pre-generate a pool of empty positions
        for _ in range(min(len(self.population.creatures) * 2, 1000)):  # Generate more positions than needed
            try:
                pos = self.grid.find_empty_location()
                empty_positions.append(pos)
            except Exception:
                break  # Stop if we can't find any more empty positions
        
        # Place creatures using the pre-generated positions
        for i, creature in enumerate(self.population.creatures):
            if i < len(empty_positions):
                position = empty_positions[i]
            else:
                # Fallback if we run out of pre-generated positions
                position = self.grid.find_empty_location()
                
            # Set creature position and update grid
            creature.position = position
            self.grid.data[int(position[0]), int(position[1]), 0] = creature.id
            
            # Initialize creature's last_move_offset to (0, 0)
            creature.last_move_offset = (0, 0)
            
            # Ensure direction is properly initialized
            if not hasattr(creature, 'direction') or creature.direction == (0, 0):
                import math
                import random
                angle = random.uniform(0, 2 * math.pi)
                creature.direction = (math.cos(angle), math.sin(angle))

    def render(self):
        """Render the current state of the simulation"""
        eink_preview = self.params.get('eink_preview', False)

        # In e-ink preview mode, only refresh display every 50 generations (at step 0)
        if eink_preview and not (self.step == 0 and self.generation % 50 == 0) and not self.paused:
            return

        # Use our custom renderer that manages its own surface
        self.custom_renderer.render_world(self.screen, self.grid, self.population.creatures)

        # Display generation and step information
        if self.params.get('continuous_mode', False):
            alive = sum(1 for c in self.population.creatures if c.alive)
            target = self.params['population_size']
            info_text = self.font.render(
                f"Step: {self.total_steps} | Pop: {alive}/{target} | "
                f"VGen: {self.virtual_generation} | B/D: {self.rolling_births}/{self.rolling_deaths} | "
                f"Speed: {self.params['fps']} fps",
                True, (255, 255, 255))
        else:
            info_text = self.font.render(
                f"Gen: {self.generation} | Pop: {len(self.population.creatures)} | "
                f"Step: {self.step}/{self.params['steps_per_generation']} | "
                f"Speed: {self.params['fps']} fps",
                True, (255, 255, 255))
        self.screen.blit(info_text, (10, 10))

        # Display challenge name only when environment system is off
        if not self.params.get('environment_system', False):
            challenge_type = self.params.get('challenge', None)
            if challenge_type is not None:
                challenge_name = self.custom_renderer.challenge_renderer.get_challenge_name(challenge_type)
                highlight_status = "ON" if self.params.get('show_challenge_areas', False) else "OFF"
                challenge_text = self.font.render(
                    f"Challenge: {challenge_name} | Highlighting: {highlight_status}",
                    True, (255, 255, 0))
                self.screen.blit(challenge_text, (10, 35))

        # Display kill count if kill counter is enabled
        if self.show_kill_counter:
            kill_text = self.font.render(
                f"KILLS: {self.murder_count}",
                True, (255, 0, 0))
            self.screen.blit(kill_text, (self.display_size[0] - 150, 10))

        # Render sidebar via display driver if present
        if self.display_driver:
            sidebar_data = self._build_sidebar_data()
            frame = DisplayFrame(sidebar_data=sidebar_data)
            self.display_driver.update(frame)

        # E-ink preview mode label
        if eink_preview:
            label = self.font.render("PREVIEW MODE", True, (200, 80, 80))
            self.screen.blit(label, (10, self.display_size[1] - 30))

        # Show status if paused
        if self.paused:
            pause_text = self.font.render("PAUSED - Press SPACE to resume",
                                          True, (255, 255, 0))
            text_rect = pause_text.get_rect(center=(self.display_size[0] // 2, 20))
            self.screen.blit(pause_text, text_rect)

        # Show help window if enabled
        if self.show_help:
            self.render_help_window()

        # Update display
        pygame.display.flip()

    def _build_sidebar_data(self):
        """Build SidebarData from current simulation state."""
        data = SidebarData()

        if self.params.get('continuous_mode', False):
            alive = sum(1 for c in self.population.creatures if c.alive)
            target = self.params['population_size']
            data.generation = self.virtual_generation
            data.total_population = alive
            data.survivors_last_gen_pct = alive / target if target > 0 else 0.0
            data.continuous_mode = True
            data.total_steps = self.total_steps
            data.births_this_vgen = self.rolling_births
            data.deaths_this_vgen = self.rolling_deaths
        else:
            data.generation = self.generation
            data.total_population = len(self.population.creatures)

        num_species = self.params.get('num_species', 1)
        if num_species >= 2:
            for sid in [0, 1]:
                count = sum(1 for c in self.population.creatures if getattr(c, 'species_id', 0) == sid)
                data.species_populations[sid] = count
            stats = getattr(self.population, 'species_stats', {})
            for sid in [0, 1]:
                if sid in stats:
                    data.species_survival_rates[sid] = stats[sid].get('survival_rate', 0.0)
                    rates = getattr(self.population, 'previous_survival_rates', {}).get(sid, [])
                    if len(rates) >= 3:
                        recent = rates[-3:]
                        if data.species_populations[sid] == 0:
                            data.species_trends[sid] = 'extinct'
                        elif recent[-1] > recent[0] + 0.05:
                            data.species_trends[sid] = 'up'
                        elif recent[-1] < recent[0] - 0.05:
                            data.species_trends[sid] = 'down'

        if self.challenge_rotator:
            data.current_pressure = self.challenge_rotator.get_current_name()
            data.pressure_since_gen = self.challenge_rotator.started_at_gen
            data.pressure_progress = self.challenge_rotator.get_progress(self.generation)
            data.mode_label = "Challenge"
        elif self.environment_manager:
            data.current_pressure = self.environment_manager.get_current_pressure_name()
            data.pressure_since_gen = self.environment_manager.pressure_start_gen
            elapsed = self.generation - self.environment_manager.pressure_start_gen
            dur = self.environment_manager.pressure_duration
            data.pressure_progress = min(1.0, elapsed / dur) if dur > 0 else 0.0

        if self.event_log:
            recent = self.event_log.get_recent(6)
            data.recent_events = [f"G{e.generation}: {e.description}" for e in recent]
            data.extinction_count = len(self.event_log.get_by_type(EventType.SPECIES_EXTINCTION))

        data.survivors_last_gen = self.last_survivors_count
        data.survivors_last_gen_pct = self.last_survivors_pct

        return data

    def run(self):
        """Run the interactive simulation loop"""
        # Initialize pygame from scratch
        pygame.init()
        # Determine window size
        eink_preview = self.params.get('eink_preview', False)
        if eink_preview:
            # E-ink preview: fixed 800x480 window
            display_size = (800, 480)
        else:
            display_size = self.display_size
            # Widen window for sidebar if display driver is present
            if self.display_driver:
                from visualization.pygame_driver import PyGameDriver
                if isinstance(self.display_driver, PyGameDriver):
                    display_size = (self.display_size[0] + PyGameDriver.SIDEBAR_WIDTH, self.display_size[1])
        self.screen = pygame.display.set_mode(display_size)
        caption = "Evolution Simulator - E-Ink Preview" if eink_preview else "Evolution Simulator - Interactive Mode"
        pygame.display.set_caption(caption)
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont(None, 24)
        self.title_font = pygame.font.SysFont(None, 28)
        self.instructions_window = pygame.Surface(self.instructions_size)
        self.instructions_window.set_alpha(200)  # Semi-transparent
        self.instructions_pos = (10, self.display_size[1] - self.instructions_size[1] - 10)

        # Create our custom renderer that doesn't rely on existing pygame surfaces
        self.custom_renderer = CustomRenderer(self.params)

        # Initialize display driver if present
        if self.display_driver:
            from visualization.pygame_driver import PyGameDriver
            if isinstance(self.display_driver, PyGameDriver):
                self.display_driver.initialize(self.screen)
        
        # Enable challenge highlighting by default for certain challenges (only if environment system is off)
        if not self.params.get('environment_system', False):
            if self.params.get('challenge', 0) in [1, 14]:
                self.params['show_challenge_areas'] = True

        # Initialize simulation
        self.initialize()

        try:
            # Main simulation loop
            while self.running:
                # Handle events
                run_flag, _ = self.handle_events()
                self.running = run_flag

                # Update simulation
                self.update()

                # Render current state
                self.render()

                # Control frame rate
                self.clock.tick(self.params['fps'])

        finally:
            # Clean up when simulation ends
            pygame.quit()
            self.logger.close()
            self.lineage_logger.close()

__all__ = ['InteractiveSimulator']
