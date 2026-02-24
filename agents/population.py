import random
import csv
import os
import datetime
import math

from agents.creature import Creature
from agents.genome import Genome, Gene
from core.survival_criteria import SurvivalCriteria, CHALLENGE_ALTRUISM_SACRIFICE, CHALLENGE_ALTRUISM
from core.types import calculate_genetic_similarity
from utils.genetic import analyze_genome_complexity, calculate_genetic_diversity

class Population:
    def __init__(self, size, params):
        """
        Initialize a population of creatures.

        Args:
            size: Number of creatures in the population
            params: Simulation parameters dictionary
        """
        self.timestamp = None
        self.params = params
        self.creatures = []
        self.size = size
        self.generation = 0
        self.event_log = None
        self.environment_manager = None
        self.extinction_warning_counters = {0: 0, 1: 0}
        self.species_stats = {}
        self.previous_survival_rates = {0: [], 1: []}

    def initialize(self, grid):
        """Initialize the first generation with uniform placement"""
        self.creatures = []

        # Create a grid-based placement strategy for more uniform distribution
        world_width = self.params['world_size'][0]
        world_height = self.params['world_size'][1]

        # Calculate ideal spacing
        spacing = max(1, min(world_width, world_height) // int(math.sqrt(self.size)))

        # Generate positions grid
        positions = []
        for x in range(spacing // 2, world_width, spacing):
            for y in range(spacing // 2, world_height, spacing):
                positions.append((x, y))

        # Shuffle positions
        random.shuffle(positions)

        # If we need more positions than our grid provides, add random ones
        while len(positions) < self.size:
            x = random.randint(0, world_width - 1)
            y = random.randint(0, world_height - 1)
            positions.append((x, y))

        # Track occupied positions to avoid duplicates
        occupied_positions = set()
        
        # Create creatures at these positions
        for i in range(min(self.size, len(positions))):
            # Create a genome with higher initial diversity
            genome = Genome(length=self.params['genome_length'], params=self.params)

            # Apply normalization but make it less aggressive
            if hasattr(Genome, 'normalize_genome_weights_mild'):
                Genome.normalize_genome_weights_mild(genome)
            else:
                Genome.normalize_genome_weights(genome)

            # If position is already occupied or is a barrier, find a new one
            position = positions[i]
            if not grid.is_valid_move_target(int(position[0]), int(position[1])) or (int(position[0]), int(position[1])) in occupied_positions:
                position = grid.find_empty_location()
                
                # Ensure the position is not already occupied
                attempts = 0
                while (int(position[0]), int(position[1])) in occupied_positions and attempts < 10:
                    position = grid.find_empty_location()
                    attempts += 1
            
            # Mark position as occupied
            occupied_positions.add((int(position[0]), int(position[1])))

            species_id = 0
            if self.params.get('num_species', 1) >= 2:
                species_id = 0 if i < self.size // 2 else 1
            creature = Creature(genome=genome, position=position, params=self.params, species_id=species_id)
            self.creatures.append(creature)

            # Register creature in the world grid
            grid.data[int(creature.position[0]), int(creature.position[1]), 0] = creature.id
            
        # Verify no duplicates
        duplicates = []
        position_counts = {}
        for creature in self.creatures:
            pos = (int(creature.position[0]), int(creature.position[1]))
            if pos in position_counts:
                position_counts[pos].append(creature.id)
            else:
                position_counts[pos] = [creature.id]
                
        for pos, creature_ids in position_counts.items():
            if len(creature_ids) > 1:
                duplicates.append((pos, creature_ids))
                
        if duplicates:
            print(f"WARNING: Found {len(duplicates)} positions with multiple creatures after initialization:")
            for pos, creature_ids in duplicates:
                print(f"  Position {pos} has creatures: {creature_ids}")
                
                # Fix duplicates by moving all but one creature to a new position
                first_creature_id = creature_ids[0]
                for creature_id in creature_ids[1:]:
                    for creature in self.creatures:
                        if creature.id == creature_id:
                            # Find a new empty location
                            try:
                                new_pos = grid.find_empty_location()
                                # Update grid
                                grid.data[pos[0], pos[1], 0] = first_creature_id
                                grid.data[int(new_pos[0]), int(new_pos[1]), 0] = creature_id
                                # Update creature position
                                creature.position = new_pos
                                print(f"    Moved creature {creature_id} to {new_pos}")
                            except Exception as e:
                                print(f"    Failed to move creature {creature_id}: {e}")

    def natural_selection_tournament(self, grid):
        """
        Perform natural selection based on survival criteria

        Args:
            grid: The world grid

        Returns:
            List of offspring creatures for next generation
        """
        if len(self.creatures) == 0:
            # Create a new random population
            self.initialize(grid)
            return self.creatures

        # Build survivor list
        survivors = []

        if self.params.get('environment_system', False) and self.environment_manager is not None:
            # Environment system mode: selection is purely energy-based.
            # Creatures that survived (energy > 0) are ranked by energy.
            # Pressure modifiers further adjust scores.
            for creature in self.creatures:
                if not creature.alive or not creature.brain.connections:
                    continue
                # Score = normalized energy (0-1)
                score = min(1.0, creature.energy / 1000.0)
                # Apply pressure modifier
                _, score = self.environment_manager.apply_survival_modifiers(creature, True, score)
                if score > 0:
                    survivors.append((creature, score))
        else:
            # Classic challenge mode
            criteria = SurvivalCriteria(self.params, grid)
            for creature in self.creatures:
                result = criteria.check_criterion(creature, self.params['challenge'])
                passed, score = result
                if passed and creature.brain.connections:
                    survivors.append((creature, score))

            # Fallback: if no survivors, take any alive creature in right half
            if not survivors:
                for creature in self.creatures:
                    if creature.alive and creature.position[0] > self.params['world_size'][0] / 2:
                        survivors.append((creature, 1.0))
        
        # Sort survivors by score (highest first)
        survivors.sort(key=lambda x: x[1], reverse=True)

        # Special case for altruism challenge
        if self.params['challenge'] == CHALLENGE_ALTRUISM:
            sacrifices = []
            for creature in self.creatures:
                passed, score = criteria.check_criterion(
                    creature, CHALLENGE_ALTRUISM_SACRIFICE)
                if passed and creature.brain.connections:
                    sacrifices.append((creature, score))

            # Handle kinship-based reproduction
            if self.generation > 10 and sacrifices:  # Apply after 10 generations
                altruism_factor = 10  # How many saved per sacrifice

                # Find genetically similar creatures to sacrifices
                saved_kin = []
                for sacrifice, _ in sacrifices:
                    # For each sacrifice, find related survivors
                    for _ in range(altruism_factor):
                        most_similar = None
                        highest_similarity = 0.7  # Threshold for kinship

                        for survivor, survivor_score in survivors:
                            similarity = calculate_genetic_similarity(
                                sacrifice.genome, survivor.genome)

                            if similarity > highest_similarity:
                                highest_similarity = similarity
                                most_similar = (survivor, survivor_score)

                        if most_similar:
                            saved_kin.append(most_similar)

                # Replace survivors with saved kin
                if saved_kin:
                    survivors = saved_kin

        # Two-species handling
        num_species = self.params.get('num_species', 1)
        if num_species >= 2:
            return self._species_aware_selection(survivors, grid)

        # Create offspring population
        offspring = []

        # Make sure we have survivors
        if not survivors:
            # Instead of creating a random population, select the top-scoring creatures
            # based on the fallback scoring mechanism in SurvivalCriteria.check_criterion
            fallback_survivors = []
            criteria = SurvivalCriteria(self.params, grid)
            
            for creature in self.creatures:
                if creature.alive:
                    # Get the fallback score (the second element in the tuple)
                    _, score = criteria.check_criterion(creature, self.params['challenge'])
                    # Only add if the creature has a valid brain with connections
                    if hasattr(creature.brain, 'connections') and creature.brain.connections:
                        fallback_survivors.append((creature, score))
            
            # Sort by score (highest first)
            fallback_survivors.sort(key=lambda x: x[1], reverse=True)
            
            # Take the top 20% as survivors
            survivor_count = max(10, int(len(fallback_survivors) * 0.2))
            survivors = fallback_survivors[:survivor_count]
            
            # If we still have no survivors, create a random population
            if not survivors:
                return [Creature(genome=Genome(length=self.params['genome_length'], params=self.params),
                               params=self.params) for _ in range(self.size)]

        # Apply elitism - keep top performers
        elite_count = max(1, int(self.size * 0.10))  # Save top 10%
        elites = [s[0] for s in survivors[:elite_count]]

        # Add elite clones to offspring
        for elite in elites:
            genome_copy = Genome([Gene(g.hex_value, params=self.params) for g in elite.genome.genes], params=self.params)
            child = Creature(genome=genome_copy, params=self.params)
            offspring.append(child)

        # Fill the rest with crossover and mutation
        while len(offspring) < self.size:
            # Select parents using tournament selection
            parent1 = self.tournament_selection(survivors)
            parent2 = self.tournament_selection(survivors)

            # Ensure different parents when possible
            attempts = 0
            while parent1 == parent2 and len(survivors) > 1 and attempts < 3:
                parent2 = self.tournament_selection(survivors)
                attempts += 1

            # Create child through crossover and mutation
            child_genome = parent1.genome.crossover(parent2.genome)
            child_genome.mutate(self.params['mutation_rate'])

            # Create child creature with parent information
            child = Creature(
                genome=child_genome, 
                params=self.params,
                parent1_id=parent1.id,
                parent2_id=parent2.id
            )
            offspring.append(child)

        # Update generation counter
        self.generation += 1

        # Export parent genome information
        parent_creatures = [creature for creature, _ in survivors]
        self.export_parent_genomes(parent_creatures)
        
        # Count unique parents that contributed to reproduction
        # This is a set of parent IDs that were used for reproduction
        reproducer_ids = set()
        
        # We need to track which parents were actually used for reproduction
        # This happens in the tournament selection process
        # For simplicity, we'll consider all survivors as potential reproducers
        # and count the actual number of unique parents used
        
        # Count survivors
        survivors_count = len(survivors)
        
        # For reproduction count, we'll use the number of unique parents
        # that contributed to the offspring (excluding elites)
        reproduction_count = len(parent_creatures)
        
        print(f"Generation {self.generation}: {survivors_count} survivors, {reproduction_count} reproducers")
        
        return offspring, survivors_count, reproduction_count

    def _species_aware_selection(self, survivors, grid):
        """Perform species-aware natural selection for two-species competition."""
        from core.event_log import EventType

        # Split survivors by species
        survivors_by_species = {0: [], 1: []}
        for creature, score in survivors:
            sid = getattr(creature, 'species_id', 0)
            survivors_by_species[sid].append((creature, score))

        # Compute per-species stats
        total_pop = len(self.creatures)
        for sid in [0, 1]:
            species_pop = sum(1 for c in self.creatures if getattr(c, 'species_id', 0) == sid)
            species_survivors = len(survivors_by_species[sid])
            survival_rate = species_survivors / species_pop if species_pop > 0 else 0.0
            diversity = calculate_genetic_diversity(
                [c for c, _ in survivors_by_species[sid]]
            ) if survivors_by_species[sid] else 0.0
            self.species_stats[sid] = {
                'population': species_pop,
                'survivors': species_survivors,
                'survival_rate': survival_rate,
                'diversity': diversity,
            }
            self.previous_survival_rates[sid].append(survival_rate)
            if len(self.previous_survival_rates[sid]) > 25:
                self.previous_survival_rates[sid] = self.previous_survival_rates[sid][-25:]

        offspring = []
        half = self.size // 2

        for sid in [0, 1]:
            species_survivors = survivors_by_species[sid]
            target_count = half if sid == 0 else self.size - half

            if not species_survivors:
                # Check extinction
                self.extinction_warning_counters[sid] = 0
                if self.event_log:
                    self.event_log.log(
                        self.generation, EventType.SPECIES_EXTINCTION,
                        f"Species {sid} went extinct",
                        {'species_id': sid}
                    )
                if self.params.get('species_respawn_on_extinction', True):
                    # Respawn at 10% of total pop
                    respawn_count = max(10, self.size // 10)
                    for _ in range(min(respawn_count, target_count)):
                        genome = Genome(length=self.params['genome_length'], params=self.params)
                        child = Creature(genome=genome, params=self.params, species_id=sid)
                        offspring.append(child)
                    if self.event_log:
                        self.event_log.log(
                            self.generation, EventType.SPECIES_RESPAWN,
                            f"Species {sid} respawned with {respawn_count} creatures",
                            {'species_id': sid, 'count': respawn_count}
                        )
                    # Fill remaining with random
                    while len([o for o in offspring if o.species_id == sid]) < target_count:
                        genome = Genome(length=self.params['genome_length'], params=self.params)
                        child = Creature(genome=genome, params=self.params, species_id=sid)
                        offspring.append(child)
                continue

            # Extinction warning: below 5% survival rate
            if self.species_stats[sid]['survival_rate'] < 0.05:
                self.extinction_warning_counters[sid] += 1
                if self.extinction_warning_counters[sid] >= 3 and self.event_log:
                    self.event_log.log(
                        self.generation, EventType.SPECIES_EXTINCTION_WARNING,
                        f"Species {sid} at risk (survival rate {self.species_stats[sid]['survival_rate']:.1%})",
                        {'species_id': sid, 'consecutive_low_gens': self.extinction_warning_counters[sid]}
                    )
            else:
                self.extinction_warning_counters[sid] = 0

            # Elite selection per species
            elite_count = max(1, int(target_count * 0.10))
            elites = [s[0] for s in species_survivors[:elite_count]]

            for elite in elites:
                genome_copy = Genome(
                    [Gene(g.hex_value, params=self.params) for g in elite.genome.genes],
                    params=self.params
                )
                child = Creature(genome=genome_copy, params=self.params, species_id=sid)
                offspring.append(child)

            # Fill rest with crossover
            while len([o for o in offspring if o.species_id == sid]) < target_count:
                parent1 = self.tournament_selection(species_survivors)
                parent2 = self.tournament_selection(species_survivors)
                attempts = 0
                while parent1 == parent2 and len(species_survivors) > 1 and attempts < 3:
                    parent2 = self.tournament_selection(species_survivors)
                    attempts += 1
                child_genome = parent1.genome.crossover(parent2.genome)
                child_genome.mutate(self.params['mutation_rate'])
                child = Creature(
                    genome=child_genome, params=self.params,
                    parent1_id=parent1.id, parent2_id=parent2.id,
                    species_id=sid
                )
                offspring.append(child)

        self.generation += 1
        parent_creatures = [creature for creature, _ in survivors]
        self.export_parent_genomes(parent_creatures)
        survivors_count = len(survivors)
        reproduction_count = len(parent_creatures)
        print(f"Generation {self.generation}: {survivors_count} survivors, {reproduction_count} reproducers"
              f" (sp0: {self.species_stats.get(0, {}).get('survivors', 0)}"
              f", sp1: {self.species_stats.get(1, {}).get('survivors', 0)})")
        return offspring, survivors_count, reproduction_count

    def attempt_continuous_reproduction(self, grid, survival_criteria):
        """Find fertile creatures and attempt reproduction with nearby mates.

        Returns list of new offspring creatures (already placed on grid).
        """
        params = self.params
        target_pop = params['population_size']
        alive_count = sum(1 for c in self.creatures if c.alive)
        pop_ratio = alive_count / target_pop if target_pop > 0 else 1.0

        # Scale threshold: lower when underpopulated (easier to breed),
        # higher when overpopulated (harder to breed)
        base_threshold = params.get('continuous_reproduction_threshold', 800)
        if pop_ratio < 1.0:
            threshold = base_threshold * max(0.4, pop_ratio)
        else:
            # Quadratic increase above target — gets very hard to reproduce
            overshoot = pop_ratio - 1.0
            threshold = base_threshold * (1.0 + 2.0 * overshoot + 3.0 * overshoot * overshoot)
        cost = params.get('continuous_reproduction_cost', 400)
        radius = params.get('continuous_reproduction_radius', 5)

        fertile = [c for c in self.creatures if c.alive and c.energy >= threshold]
        random.shuffle(fertile)

        offspring = []
        reproducers = set()
        for parent1 in fertile:
            if not parent1.alive or parent1.energy < cost:
                continue

            # Find a nearby alive mate within Manhattan distance
            mate = None
            for c in self.creatures:
                if c is parent1 or not c.alive:
                    continue
                dist = abs(int(c.position[0]) - int(parent1.position[0])) + \
                       abs(int(c.position[1]) - int(parent1.position[1]))
                if dist <= radius:
                    mate = c
                    break

            if mate is None:
                continue

            # Find empty cell anywhere on the map
            try:
                spot = grid.find_empty_location()
                spot = (int(spot[0]), int(spot[1]))
            except Exception:
                continue

            # Crossover + mutate
            child_genome = parent1.genome.crossover(mate.genome)
            child_genome.mutate(params['mutation_rate'])

            child = Creature(
                genome=child_genome,
                position=spot,
                params=params,
                parent1_id=parent1.id,
                parent2_id=mate.id,
                species_id=getattr(parent1, 'species_id', 0),
            )

            # Place on grid
            grid.data[spot[0], spot[1], 0] = child.id

            # Deduct energy
            parent1.energy -= cost
            mate.energy -= cost * 0.5

            reproducers.add(parent1.id)
            reproducers.add(mate.id)
            offspring.append(child)

        return offspring, reproducers

    def reproduce_top_n(self, grid, n):
        """Pick top-N highest-energy creatures to reproduce once each.

        Returns (offspring_list, reproducer_id_set).
        """
        params = self.params
        cost = params.get('continuous_reproduction_cost', 400)
        alive = [c for c in self.creatures if c.alive]
        # Sort by energy descending — fittest reproduce first
        alive.sort(key=lambda c: c.energy, reverse=True)

        offspring = []
        reproducers = set()

        for parent1 in alive:
            if len(offspring) >= n:
                break
            if parent1.energy < cost:
                continue

            # Pick a random mate from alive creatures (not self)
            mate = None
            candidates = [c for c in alive if c is not parent1 and c.alive]
            if not candidates:
                continue
            mate = random.choice(candidates)

            try:
                spot = grid.find_empty_location()
                spot = (int(spot[0]), int(spot[1]))
            except Exception:
                continue

            child_genome = parent1.genome.crossover(mate.genome)
            child_genome.mutate(params['mutation_rate'])

            child = Creature(
                genome=child_genome,
                position=spot,
                params=params,
                parent1_id=parent1.id,
                parent2_id=mate.id,
                species_id=getattr(parent1, 'species_id', 0),
            )

            grid.data[spot[0], spot[1], 0] = child.id
            parent1.energy -= cost

            reproducers.add(parent1.id)
            reproducers.add(mate.id)
            offspring.append(child)

        return offspring, reproducers

    def _find_nearby_empty(self, grid, cx, cy, radius=3):
        """Search outward from (cx, cy) for an empty non-barrier cell."""
        for r in range(1, radius + 1):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    if abs(dx) != r and abs(dy) != r:
                        continue  # only check perimeter of this ring
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < grid.size[0] and 0 <= ny < grid.size[1]:
                        if grid.is_valid_move_target(nx, ny):
                            return (nx, ny)
        return None

    def inject_random_creatures(self, grid, count):
        """Create random-genome creatures at empty grid locations (extinction safety net)."""
        new_creatures = []
        for _ in range(count):
            try:
                pos = grid.find_empty_location()
            except Exception:
                break
            genome = Genome(length=self.params['genome_length'], params=self.params)
            creature = Creature(genome=genome, position=pos, params=self.params)
            grid.data[int(pos[0]), int(pos[1]), 0] = creature.id
            new_creatures.append(creature)
        return new_creatures

    def tournament_selection(self, scored_creatures, tournament_size=5):
        """
        Select a creature using tournament selection

        Args:
            scored_creatures: List of (creature, score) tuples
            tournament_size: Number of creatures in tournament

        Returns:
            Selected creature
        """
        # Select random contestants
        if len(scored_creatures) <= tournament_size:
            contestants = scored_creatures
        else:
            contestants = random.sample(scored_creatures, tournament_size)

        # Return creature with highest score
        return max(contestants, key=lambda x: x[1])[0]

    def update(self, grid, signals=None):
        """
        Update all creatures in the population
        
        This method calls move() on each creature, which queues movement
        requests that will be processed at the end of the step.
        """
        # Create a dictionary of creatures for quick lookup
        creatures_dict = {creature.id: creature for creature in self.creatures}
        
        # The main creature update logic (sensors, feed-forward, movement queuing)
        # is now handled in Simulator.update calling creature.update.
        # This loop is likely redundant and was causing the TypeError.
        # for creature in self.creatures:
        #     if creature.alive and creature.age <= self.params['max_age']:
        #         creature.move(grid, self.creatures, signals)
        
        # Process queued operations
        grid.process_death_queue(creatures_dict)
        grid.process_move_queue(creatures_dict)

    # Helper method to cluster similar genomes
    def cluster_similar_genomes(self, creatures, similarity_threshold=0.8):
        clusters = []
        unclustered = creatures.copy()

        while unclustered:
            # Start a new cluster with the first creature
            current = unclustered.pop(0)
            current_cluster = [current]

            # Find all similar creatures
            i = 0
            while i < len(unclustered):
                similarity = calculate_genetic_similarity(
                    current.genome, unclustered[i].genome
                )
                if similarity > similarity_threshold:
                    current_cluster.append(unclustered.pop(i))
                else:
                    i += 1

            clusters.append(current_cluster)

        return clusters

    def export_parent_genomes(self, reproducers):
        """
        Export detailed information about parent genomes that survived and reproduced.

        This method provides a comprehensive log of parent creatures, capturing
        key genomic, neural, and behavioral characteristics.

        Args:
            reproducers (list): List of creatures selected for reproduction
        """
        # Validate logging configuration
        if not self.params.get('log_to_csv', False):
            return

        # Ensure log directory exists
        log_folder = self.params.get('log_folder', 'logs')
        os.makedirs(log_folder, exist_ok=True)

        # Generate unique timestamp if not already present
        if not hasattr(self, "timestamp"):
            self.timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        # Construct detailed filename
        genome_filename = os.path.join(
            log_folder,
            f"parent_genomes_gen{self.generation}_{self.timestamp}.csv"
        )

        try:
            with open(genome_filename, 'w', newline='') as file:
                writer = csv.writer(file)

                # Comprehensive header capturing multiple aspects of parent creatures
                header = [
                    'Parent_ID',
                    'Generation',
                    'In_Safe_Zone',
                    'Energy',
                    'Age',
                    'Brain_Active_Neurons',
                    'Brain_Total_Connections',
                    'Genome_Length',
                    'Genetic_Complexity_Score',
                    'Parent1_ID',
                    'Parent2_ID'
                ]

                # Add detailed gene information to header
                max_genes = max(len(parent.genome.genes) for parent in reproducers) if reproducers else 0
                for i in range(max_genes):
                    header.extend([
                        f'Gene_{i}_Hex_Value',
                        f'Gene_{i}_Source_Type',
                        f'Gene_{i}_Sink_Type',
                        f'Gene_{i}_Weight'
                    ])

                writer.writerow(header)

                # Log details for each reproducing parent
                for parent in reproducers:
                    # Compute genetic complexity score
                    try:
                        complexity_score = self._compute_genome_complexity_score(parent.genome)
                    except Exception:
                        complexity_score = 0.0

                    # Prepare base row with parent information
                    row = [
                        parent.id,
                        self.generation,
                        int(parent.in_safe_zone),  # Convert boolean to integer
                        f"{parent.energy:.2f}",
                        0,  # Age removed, using 0 as placeholder
                        parent.brain.active_internal_neurons,
                        parent.brain.total_connections,
                        len(parent.genome.genes),
                        f"{complexity_score:.4f}",
                        parent.parent1_id if hasattr(parent, 'parent1_id') and parent.parent1_id is not None else "None",
                        parent.parent2_id if hasattr(parent, 'parent2_id') and parent.parent2_id is not None else "None"
                    ]

                    # Add detailed gene information
                    for gene in parent.genome.genes:
                        row.extend([
                            gene.hex_value,
                            gene.source_type,
                            gene.sink_type,
                            f"{gene.weight:.4f}"
                        ])

                    writer.writerow(row)

        except Exception as e:
            pass

    def _compute_genome_complexity_score(self, genome):
        """
        Compute a complexity score for a genome based on various characteristics.

        Args:
            genome (Genome): Genome to analyze

        Returns:
            float: Complexity score
        """
        try:
            # Use existing genome analysis function
            complexity = analyze_genome_complexity(genome)

            # Combine multiple complexity metrics
            complexity_score = (
                    complexity['gene_diversity'] * 0.3 +
                    complexity['computational_capacity'] * 0.3 +
                    complexity['recurrent_ratio'] * 0.2 +
                    (len(genome.genes) / self.params.get('genome_max_length', 300)) * 0.2
            )

            return complexity_score
        except Exception:
            # Fallback if computation fails
            return 0.0

    def analyze_population(self):
        """
        Analyze the current population and return statistics

        Returns:
            Dictionary with population statistics
        """
        if not self.creatures:
            return {"population_size": 0}

        # Extract genome stats for all creatures
        genome_stats = []
        for creature in self.creatures:
            genome_stats.append(analyze_genome_complexity(creature.genome))

        # Calculate population-level statistics
        avg_gene_diversity = sum(stats["gene_diversity"] for stats in genome_stats) / len(genome_stats)
        avg_computational_capacity = sum(stats["computational_capacity"] for stats in genome_stats) / len(genome_stats)
        avg_recurrent_ratio = sum(stats["recurrent_ratio"] for stats in genome_stats) / len(genome_stats)

        # Calculate metrics about behavioral diversity
        energy_values = [c.energy for c in self.creatures]
        neuron_counts = [c.brain.active_internal_neurons for c in self.creatures]
        connection_counts = [c.brain.total_connections for c in self.creatures]
        zone_distribution = sum(1 for c in self.creatures if c.in_safe_zone) / len(self.creatures)

        # Calculate genetic diversity
        genetic_diversity = calculate_genetic_diversity(self.creatures)

        # Identify most successful genomes
        creatures_by_energy = sorted(self.creatures, key=lambda c: c.energy, reverse=True)
        top_creature = creatures_by_energy[0] if creatures_by_energy else None

        return {
            "population_size": len(self.creatures),
            "avg_gene_diversity": avg_gene_diversity,
            "avg_computational_capacity": avg_computational_capacity,
            "avg_recurrent_ratio": avg_recurrent_ratio,
            "genetic_diversity": genetic_diversity,
            "zone_distribution": zone_distribution,
            "avg_energy": sum(energy_values) / len(energy_values) if energy_values else 0,
            "min_energy": min(energy_values) if energy_values else 0,
            "max_energy": max(energy_values) if energy_values else 0,
            "avg_neurons": sum(neuron_counts) / len(neuron_counts) if neuron_counts else 0,
            "avg_connections": sum(connection_counts) / len(connection_counts) if connection_counts else 0,
            "top_creature_id": top_creature.id if top_creature else None,
            "top_creature_energy": top_creature.energy if top_creature else 0,
            "top_creature_metrics": analyze_genome_complexity(top_creature.genome) if top_creature else None
        }
