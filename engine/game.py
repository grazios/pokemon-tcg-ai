"""ゲームエンジン - Phase 3: Sparse Reward"""
from __future__ import annotations
import random
import copy
from .card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay, Card
from .card_db import build_deck
from .player import Player
from .actions import (
    NUM_ACTIONS, get_valid_actions, decode_action,
    PLAY_CARD_BASE, MAX_HAND, EVOLVE_ACTIVE_BASE, EVOLVE_BENCH_BASE,
    ENERGY_ACTIVE_BASE, ENERGY_BENCH_BASE, ATTACK_BASE, RETREAT_BASE,
    END_TURN, RARE_CANDY_ACTIVE_BASE, RARE_CANDY_BENCH_BASE,
    USE_ABILITY_ACTIVE, USE_ABILITY_BENCH_BASE,
)


class Game:
    MAX_TURNS = 200
    PRIZE_TARGET = 6
    
    def __init__(self, deck_id_0: int = 0, deck_id_1: int = 1):
        self.deck_id_0 = deck_id_0
        self.deck_id_1 = deck_id_1
        self.players: list[Player] = []
        self.current_player: int = 0
        self.turn_count: int = 0
        self.done: bool = False
        self.winner: int | None = None
        self.has_attacked: bool = False
        self.stadium: TrainerCard | None = None
        self.stadium_owner: int = -1
        self.first_player: int = 0
        self.briar_active: bool = False
        self.acerola_target: PokemonInPlay | None = None
        # Prize tracking for sparse reward
        self._prev_prizes_taken: list[int] = [0, 0]
    
    def reset(self):
        deck0 = build_deck(self.deck_id_0)
        deck1 = build_deck(self.deck_id_1)
        self.players = [Player(deck0, 0), Player(deck1, 1)]
        self.current_player = 0
        self.turn_count = 0
        self.done = False
        self.winner = None
        self.has_attacked = False
        self.stadium = None
        self.stadium_owner = -1
        self.briar_active = False
        self.acerola_target = None
        self._prev_prizes_taken = [0, 0]
        
        self.first_player = random.randint(0, 1)
        self.current_player = self.first_player
        
        for p in self.players:
            p.setup()
        
        for p in self.players:
            basics = p.get_basics_in_hand()
            if basics:
                p.place_active(basics[0])
        
        self.turn_count = 1
        self.players[self.current_player].start_turn()
    
    def get_current_player(self) -> Player:
        return self.players[self.current_player]
    
    def get_opponent(self) -> Player:
        return self.players[1 - self.current_player]
    
    def _game_state(self) -> dict:
        return {
            "has_attacked": self.has_attacked,
            "is_first_turn": self.turn_count <= 2,
            "is_first_turn_of_game": self.turn_count == 1,
            "turn_count": self.turn_count,
            "stadium": self.stadium,
        }
    
    def get_valid_actions(self) -> list[int]:
        return get_valid_actions(
            self.get_current_player(),
            self.get_opponent(),
            self._game_state()
        )
    
    def step(self, action: int) -> tuple[float, bool]:
        """Execute action, return (reward, done).
        
        Sparse reward:
          +0.1 per prize card taken by current player
          -0.1 per prize card taken by opponent
          +1.0 for winning / -1.0 for losing (replaces prize reward on terminal)
        """
        if self.done:
            return 0.0, True
        
        player = self.get_current_player()
        opponent = self.get_opponent()
        cp = self.current_player
        
        # Snapshot prize counts before action
        prizes_before = [p.prizes_taken for p in self.players]
        
        valid = self.get_valid_actions()
        if action not in valid:
            action = END_TURN
        
        info = decode_action(action)
        atype = info["type"]
        
        try:
            if atype == "play_card":
                self._handle_play_card(player, opponent, info["hand_idx"])
            elif atype == "evolve_active":
                self._handle_evolve(player, player.active, info["hand_idx"])
            elif atype == "evolve_bench":
                bi = info["bench_idx"]
                if bi < len(player.bench):
                    self._handle_evolve(player, player.bench[bi], info["hand_idx"])
            elif atype == "energy_active":
                if player.active:
                    player.attach_energy(info["hand_idx"], player.active)
            elif atype == "energy_bench":
                bi = info["bench_idx"]
                if bi < len(player.bench):
                    player.attach_energy(info["hand_idx"], player.bench[bi])
            elif atype == "attack":
                self._handle_attack(player, opponent, info["attack_idx"])
            elif atype == "retreat":
                bi = info["bench_idx"]
                if player.active is None:
                    player.promote_from_bench(bi)
                else:
                    player.retreat(bi)
            elif atype == "rare_candy_active":
                if player.active:
                    self._handle_rare_candy(player, player.active, info["hand_idx"])
            elif atype == "rare_candy_bench":
                bi = info["bench_idx"]
                if bi < len(player.bench):
                    self._handle_rare_candy(player, player.bench[bi], info["hand_idx"])
            elif atype == "use_ability":
                target = info.get("target", "active")
                if target == "active" and player.active:
                    self._handle_ability(player, opponent, player.active)
                elif target == "bench":
                    bi = info.get("bench_idx", 0)
                    if bi < len(player.bench):
                        self._handle_ability(player, opponent, player.bench[bi])
            elif atype == "end_turn":
                self._end_turn()
        except Exception:
            self._end_turn()
        
        if not self.done:
            self._check_win_conditions()
        
        # === Sparse reward calculation ===
        reward = 0.0
        if self.done:
            if self.winner == cp:
                reward = 1.0
            elif self.winner is not None:
                reward = -1.0
            # draw = 0
        else:
            # Prize delta reward
            my_delta = self.players[cp].prizes_taken - prizes_before[cp]
            opp_delta = self.players[1 - cp].prizes_taken - prizes_before[1 - cp]
            reward = 0.1 * my_delta - 0.1 * opp_delta
        
        return reward, self.done
    
    # ── Card handling (no reward returns) ──────────────────────────
    
    def _handle_play_card(self, player: Player, opponent: Player, hand_idx: int):
        if hand_idx >= len(player.hand):
            return
        card = player.hand[hand_idx]
        
        if isinstance(card, PokemonCard) and card.is_basic:
            player.place_bench(hand_idx)
            return
        
        if isinstance(card, TrainerCard):
            self._handle_trainer(player, opponent, hand_idx)
    
    def _handle_trainer(self, player: Player, opponent: Player, hand_idx: int):
        card = player.hand[hand_idx]
        if not isinstance(card, TrainerCard):
            return
        
        eid = card.effect_id
        
        player.hand.pop(hand_idx)
        
        if card.trainer_type == "Supporter":
            player.supporter_played_this_turn = True
        
        if card.trainer_type == "Stadium":
            if self.stadium:
                if self.stadium_owner == 0:
                    self.players[0].discard.append(self.stadium)
                else:
                    self.players[1].discard.append(self.stadium)
            self.stadium = card
            self.stadium_owner = self.current_player
            player.stadium_played_this_turn = True
            self._update_bench_limits()
            player.discard.append(card)
            return
        
        if card.trainer_type == "Pokemon Tool":
            self._handle_tool(player, card)
            return
        
        if eid == "boss_orders":
            if opponent.bench:
                idx = random.randint(0, len(opponent.bench) - 1)
                old = opponent.active
                opponent.active = opponent.bench.pop(idx)
                if old:
                    opponent.bench.append(old)
        
        elif eid == "iono":
            for p in [player, opponent]:
                cards = list(p.hand)
                p.hand.clear()
                random.shuffle(cards)
                p.deck = cards + p.deck
                random.shuffle(p.deck)
            player.draw(len(player.prizes))
            opponent.draw(len(opponent.prizes))
        
        elif eid == "dawn":
            found = 0
            for stage in ["Basic", "Stage 1", "Stage 2"]:
                indices = player.find_in_deck(
                    lambda c, s=stage: isinstance(c, PokemonCard) and c.stage == s
                )
                if indices:
                    card_found = player.take_from_deck(indices[0])
                    if card_found:
                        player.hand.append(card_found)
                        found += 1
            if found > 0:
                player.shuffle_deck()
        
        elif eid == "lillies_determination":
            cards = list(player.hand)
            player.hand.clear()
            player.deck.extend(cards)
            player.shuffle_deck()
            draw_count = 8 if len(player.prizes) == 6 else 6
            player.draw(draw_count)
        
        elif eid == "crispin":
            energy_indices = player.find_in_deck(
                lambda c: isinstance(c, EnergyCard) and not c.is_special
            )
            types_found = {}
            for idx in energy_indices:
                e = player.deck[idx]
                if isinstance(e, EnergyCard) and e.energy_type not in types_found:
                    types_found[e.energy_type] = idx
                if len(types_found) >= 2:
                    break
            items = list(types_found.items())
            if len(items) >= 2:
                idx1 = items[0][1]
                idx2 = items[1][1]
                for idx in sorted([idx1, idx2], reverse=True):
                    e = player.take_from_deck(idx)
                    if e:
                        if len(items) > 1 and idx == idx1:
                            player.hand.append(e)
                        else:
                            target = player.active or (player.bench[0] if player.bench else None)
                            if target and isinstance(e, EnergyCard):
                                target.attach_energy(e)
                            else:
                                player.hand.append(e)
                player.shuffle_deck()
            elif len(items) == 1:
                e = player.take_from_deck(items[0][1])
                if e:
                    player.hand.append(e)
                player.shuffle_deck()
        
        elif eid == "sada_vitality":
            ancient_pokemon = [p for p in player.get_all_pokemon_in_play() if p.card.is_ancient]
            attached = 0
            for ap in ancient_pokemon[:2]:
                energy_indices = player.find_in_discard(
                    lambda c: isinstance(c, EnergyCard) and not c.is_special
                )
                if energy_indices:
                    e = player.take_from_discard(energy_indices[0])
                    if e and isinstance(e, EnergyCard):
                        ap.attach_energy(e)
                        attached += 1
            if attached > 0:
                player.draw(3)
        
        elif eid == "briar":
            self.briar_active = True
        
        elif eid == "acerola_mischief":
            if player.active:
                player.active.protected_from_ex = True
        
        elif eid == "turo_scenario":
            if player.bench:
                bp = player.bench.pop(0)
                player.hand.append(bp.card)
                for e in bp.attached_energy:
                    player.discard.append(e)
                if bp.tool:
                    player.discard.append(bp.tool)
                for c in bp.evolution_chain:
                    player.discard.append(c)
        
        elif eid == "buddy_buddy_poffin":
            found = 0
            for _ in range(2):
                if len(player.bench) >= player.max_bench:
                    break
                indices = player.find_in_deck(
                    lambda c: isinstance(c, PokemonCard) and c.is_basic and c.hp <= 70
                )
                if indices:
                    c = player.take_from_deck(indices[0])
                    if c and isinstance(c, PokemonCard):
                        player.place_bench_from_deck(c)
                        found += 1
            if found > 0:
                player.shuffle_deck()
        
        elif eid == "nest_ball":
            if len(player.bench) < player.max_bench:
                indices = player.find_in_deck(
                    lambda c: isinstance(c, PokemonCard) and c.is_basic
                )
                if indices:
                    c = player.take_from_deck(indices[0])
                    if c and isinstance(c, PokemonCard):
                        player.place_bench_from_deck(c)
                        player.shuffle_deck()
        
        elif eid == "ultra_ball":
            discarded = 0
            for _ in range(2):
                if player.hand:
                    player.discard.append(player.hand.pop(-1))
                    discarded += 1
            if discarded == 2:
                indices = player.find_in_deck(lambda c: isinstance(c, PokemonCard))
                if indices:
                    best = indices[0]
                    for idx in indices:
                        c = player.deck[idx]
                        if isinstance(c, PokemonCard):
                            if c.is_ex and c.stage == "Stage 2":
                                best = idx
                                break
                    c = player.take_from_deck(best)
                    if c:
                        player.hand.append(c)
                        player.shuffle_deck()
        
        elif eid == "night_stretcher":
            indices = player.find_in_discard(
                lambda c: isinstance(c, PokemonCard) or (isinstance(c, EnergyCard) and not c.is_special)
            )
            if indices:
                c = player.take_from_discard(indices[0])
                if c:
                    player.hand.append(c)
        
        elif eid == "super_rod":
            count = 0
            for _ in range(3):
                indices = player.find_in_discard(
                    lambda c: isinstance(c, PokemonCard) or (isinstance(c, EnergyCard) and not c.is_special)
                )
                if indices:
                    c = player.take_from_discard(indices[0])
                    if c:
                        player.deck.append(c)
                        count += 1
            if count > 0:
                player.shuffle_deck()
        
        elif eid == "prime_catcher":
            if opponent.bench and player.bench:
                idx_opp = random.randint(0, len(opponent.bench) - 1)
                old_opp = opponent.active
                opponent.active = opponent.bench.pop(idx_opp)
                if old_opp:
                    opponent.bench.append(old_opp)
                idx_own = 0
                old_own = player.active
                player.active = player.bench.pop(idx_own)
                if old_own:
                    player.bench.append(old_own)
        
        elif eid == "counter_catcher":
            if opponent.bench:
                idx = random.randint(0, len(opponent.bench) - 1)
                old = opponent.active
                opponent.active = opponent.bench.pop(idx)
                if old:
                    opponent.bench.append(old)
        
        elif eid == "unfair_stamp":
            for p in [player, opponent]:
                cards = list(p.hand)
                p.hand.clear()
                p.deck.extend(cards)
                p.shuffle_deck()
            player.draw(5)
            opponent.draw(2)
        
        elif eid == "earthen_vessel":
            if player.hand:
                player.discard.append(player.hand.pop(-1))
            found = 0
            for _ in range(2):
                indices = player.find_in_deck(
                    lambda c: isinstance(c, EnergyCard) and not c.is_special
                )
                if indices:
                    c = player.take_from_deck(indices[0])
                    if c:
                        player.hand.append(c)
                        found += 1
            if found > 0:
                player.shuffle_deck()
        
        elif eid == "energy_switch":
            all_p = player.get_all_pokemon_in_play()
            source = None
            for p in all_p:
                if p is not player.active and p.total_energy() > 0:
                    source = p
                    break
            if source and player.active:
                if source.attached_energy:
                    e = source.attached_energy.pop(0)
                    player.active.attach_energy(e)
        
        elif eid == "glass_trumpet":
            count = 0
            for bp in player.bench:
                if count >= 2:
                    break
                if "Colorless" in bp.card.types:
                    indices = player.find_in_discard(
                        lambda c: isinstance(c, EnergyCard) and not c.is_special
                    )
                    if indices:
                        e = player.take_from_discard(indices[0])
                        if e and isinstance(e, EnergyCard):
                            bp.attach_energy(e)
                            count += 1
        
        player.discard.append(card)
    
    def _handle_tool(self, player: Player, card: TrainerCard):
        for p in player.get_all_pokemon_in_play():
            if p.tool is None:
                p.tool = card
                return
        player.discard.append(card)
    
    def _handle_evolve(self, player: Player, target: PokemonInPlay | None,
                       hand_idx: int):
        if target is None or hand_idx >= len(player.hand):
            return
        card = player.hand[hand_idx]
        if not isinstance(card, PokemonCard):
            return
        if not player.evolve(target, card, hand_idx):
            return
        self._trigger_evolution_ability(player, target)
    
    def _handle_rare_candy(self, player: Player, target: PokemonInPlay,
                           hand_idx_stage2: int):
        if hand_idx_stage2 >= len(player.hand):
            return
        stage2_card = player.hand[hand_idx_stage2]
        if not isinstance(stage2_card, PokemonCard):
            return
        candy_idx = None
        for i, c in enumerate(player.hand):
            if isinstance(c, TrainerCard) and c.effect_id == "rare_candy" and i != hand_idx_stage2:
                candy_idx = i
                break
        if candy_idx is None:
            return
        if not player.evolve_with_rare_candy(target, stage2_card, candy_idx, hand_idx_stage2):
            return
        player.discard.append(TrainerCard(id="rare_candy", name="Rare Candy",
                                          trainer_type="Item", effect_id="rare_candy"))
        self._trigger_evolution_ability(player, target)
    
    def _trigger_evolution_ability(self, player: Player, pokemon: PokemonInPlay):
        opponent = self.get_opponent()
        for ab in pokemon.card.abilities:
            eid = ab.effect_id
            if eid == "infernal_reign":
                attached = 0
                for _ in range(3):
                    indices = player.search_deck_energy("Fire", basic_only=True)
                    if indices:
                        e = player.take_from_deck(indices[0])
                        if e and isinstance(e, EnergyCard):
                            target = player.active or (player.bench[0] if player.bench else None)
                            if target:
                                target.attach_energy(e)
                                attached += 1
                if attached > 0:
                    player.shuffle_deck()
            elif eid == "jewel_seeker":
                if player.has_tera_in_play():
                    for _ in range(2):
                        indices = player.find_in_deck(lambda c: isinstance(c, TrainerCard))
                        if indices:
                            c = player.take_from_deck(indices[0])
                            if c:
                                player.hand.append(c)
                    player.shuffle_deck()
            elif eid == "recon_directive":
                if player.deck:
                    player.draw(1)
            break
    
    def _handle_ability(self, player: Player, opponent: Player,
                        pokemon: PokemonInPlay):
        for ab in pokemon.card.abilities:
            eid = ab.effect_id
            if eid == "teal_dance":
                for i, c in enumerate(player.hand):
                    if isinstance(c, EnergyCard) and c.energy_type == "Grass" and not c.is_special:
                        player.hand.pop(i)
                        pokemon.attach_energy(c)
                        player.draw(1)
                        break
            elif eid == "fan_call":
                player.fan_call_used_this_turn = True
                found = 0
                for _ in range(3):
                    indices = player.find_in_deck(
                        lambda c: isinstance(c, PokemonCard) and "Colorless" in c.types and c.hp <= 100
                    )
                    if indices:
                        c = player.take_from_deck(indices[0])
                        if c:
                            player.hand.append(c)
                            found += 1
                if found > 0:
                    player.shuffle_deck()
            elif eid == "flip_the_script":
                player.flip_the_script_used_this_turn = True
                player.draw(3)
            elif eid == "quick_search":
                player.quick_search_used_this_turn = True
                if player.deck:
                    best_idx = 0
                    for i, c in enumerate(player.deck):
                        if isinstance(c, PokemonCard) and c.is_ex and c.stage == "Stage 2":
                            best_idx = i
                            break
                        if isinstance(c, TrainerCard) and c.effect_id == "rare_candy":
                            best_idx = i
                    c = player.take_from_deck(best_idx)
                    if c:
                        player.hand.append(c)
                        player.shuffle_deck()
            elif eid == "run_errand":
                player.run_errand_used_this_turn = True
                player.draw(2)
            elif eid == "restart":
                cards_needed = 3 - len(player.hand)
                if cards_needed > 0:
                    player.draw(cards_needed)
            elif eid == "cursed_blast":
                target = opponent.active
                if target:
                    target.put_damage_counters(13)
                pokemon.current_hp = 0
                self._handle_ko(pokemon, player, opponent, is_self_ko=True)
            elif eid == "adrena_brain":
                if opponent.active:
                    source = None
                    for p in player.get_all_pokemon_in_play():
                        if p.damage_counters > 0 and p is not pokemon:
                            source = p
                            break
                    if source is None:
                        source = pokemon
                    moved = min(3, source.damage_counters)
                    if moved > 0:
                        source.current_hp += moved * 10
                        source.damage_counters -= moved
                        opponent.active.put_damage_counters(moved)
            break
    
    def _handle_attack(self, player: Player, opponent: Player, attack_idx: int):
        if not player.active or attack_idx >= len(player.active.card.attacks):
            return
        attack = player.active.card.attacks[attack_idx]
        if not player.active.can_use_attack(attack):
            return
        
        self.has_attacked = True
        eid = attack.effect_id
        damage = attack.damage
        
        if eid == "burning_darkness":
            damage = 180 + 30 * opponent.prizes_taken
        elif eid == "bellowing_thunder":
            total_discarded = 0
            for p in player.get_all_pokemon_in_play():
                to_remove = []
                for i, e in enumerate(p.attached_energy):
                    if not e.is_special:
                        to_remove.append(i)
                for i in reversed(to_remove):
                    e = p.attached_energy.pop(i)
                    player.discard.append(e)
                    total_discarded += 1
            damage = 70 * total_discarded
        elif eid == "phantom_dive":
            damage = 200
            if opponent.bench:
                counters_left = 6
                while counters_left > 0 and opponent.bench:
                    target = random.choice(opponent.bench)
                    target.put_damage_counters(1)
                    counters_left -= 1
        elif eid == "myriad_leaf_shower":
            total_energy = player.active.total_energy() + (opponent.active.total_energy() if opponent.active else 0)
            damage = 30 + 30 * total_energy
        elif eid == "burst_roar":
            cards = list(player.hand)
            player.hand.clear()
            player.discard.extend(cards)
            player.draw(6)
            damage = 0
        elif eid == "unified_beatdown":
            damage = 30 * len(player.bench)
        elif eid == "crown_opal":
            damage = 180
        elif eid == "cruel_arrow":
            if opponent.bench:
                target = random.choice(opponent.bench)
                target.put_damage_counters(10)
            elif opponent.active:
                opponent.active.take_damage(100, player.active.card.types)
            damage = 0
        elif eid == "thunderburst_storm":
            energy_count = player.active.total_energy()
            if opponent.bench:
                target = random.choice([opponent.active] + opponent.bench if opponent.active else opponent.bench)
                if target:
                    target.put_damage_counters(energy_count * 3)
            damage = 0
        elif eid == "megafire_of_envy":
            damage = 50
            if player.pokemon_knocked_out_last_turn:
                damage += 90
        elif eid == "flare_bringer":
            for _ in range(2):
                indices = player.find_in_discard(
                    lambda c: isinstance(c, EnergyCard) and c.energy_type == "Fire" and not c.is_special
                )
                if indices:
                    e = player.take_from_discard(indices[0])
                    if e and isinstance(e, EnergyCard):
                        target = player.active or (player.bench[0] if player.bench else None)
                        if target:
                            target.attach_energy(e)
            damage = 0
        elif eid == "shadow_bind":
            damage = 150
            if opponent.active:
                opponent.active.cant_retreat_next = True
        elif eid == "blustery_wind":
            damage = 120
            if self.stadium:
                if self.stadium_owner == 0:
                    self.players[0].discard.append(self.stadium)
                else:
                    self.players[1].discard.append(self.stadium)
                self.stadium = None
                self._update_bench_limits()
        elif eid == "eon_blade":
            damage = 200
            player.active.cant_attack_next = True
        elif eid == "rapid_fire_combo":
            damage = 200
            import random as rng
            while rng.random() < 0.5:
                damage += 50
        elif eid == "genome_hacking":
            # Mew ex: Copy one of the opponent's Active Pokémon's attacks
            # Use the highest-damage attack from opponent's active
            if opponent.active and opponent.active.card.attacks:
                best_atk = max(opponent.active.card.attacks, key=lambda a: a.damage)
                damage = best_atk.damage
                # For attacks with special effects, apply the copied effect
                copied_eid = best_atk.effect_id
                if copied_eid == "phantom_dive":
                    damage = 200
                    if opponent.bench:
                        counters_left = 6
                        while counters_left > 0 and opponent.bench:
                            target = random.choice(opponent.bench)
                            target.put_damage_counters(1)
                            counters_left -= 1
                elif copied_eid == "burning_darkness":
                    damage = 180 + 30 * opponent.prizes_taken
                elif copied_eid == "shadow_bind":
                    damage = 150
                    if opponent.active:
                        opponent.active.cant_retreat_next = True
                elif copied_eid == "eon_blade":
                    damage = 200
                    player.active.cant_attack_next = True
                # Other effects: just use base damage
            else:
                damage = 0
        elif eid == "assault_landing":
            if self.stadium is None:
                damage = 0
            else:
                damage = 70
        elif eid == "triple_stab":
            import random as rng
            hits = sum(1 for _ in range(3) if rng.random() < 0.5)
            damage = 10 * hits
        elif eid == "call_for_family":
            if len(player.bench) < player.max_bench:
                indices = player.find_in_deck(
                    lambda c: isinstance(c, PokemonCard) and c.is_basic
                )
                if indices:
                    c = player.take_from_deck(indices[0])
                    if c and isinstance(c, PokemonCard):
                        player.place_bench_from_deck(c)
                        player.shuffle_deck()
            damage = 0
        
        # Vitality Band
        if player.active.tool and player.active.tool.effect_id == "vitality_band":
            if damage > 0:
                damage += 10
        
        # Apply damage
        if damage > 0 and opponent.active:
            if opponent.active.protected_from_ex and player.active.card.is_ex:
                damage = 0
            if damage > 0:
                ko = opponent.active.take_damage(damage, player.active.card.types)
                if ko:
                    prize_count = opponent.active.card.prize_value
                    if self.briar_active and player.active.card.is_tera:
                        prize_count += 1
                    self._handle_ko(opponent.active, opponent, player,
                                    prize_taker=player, prize_count=prize_count)
        
        # Check bench KOs
        for bp in list(opponent.bench):
            if bp.is_knocked_out:
                prize_count = bp.card.prize_value
                idx = opponent.bench.index(bp)
                opponent.bench.pop(idx)
                opponent._discard_pokemon(bp)
                player.take_prize(prize_count)
        
        self.briar_active = False
    
    def _handle_ko(self, ko_pokemon: PokemonInPlay, ko_owner: Player,
                   opponent_of_ko: Player, prize_taker: Player | None = None,
                   prize_count: int | None = None, is_self_ko: bool = False):
        if prize_count is None:
            prize_count = ko_pokemon.card.prize_value
        if prize_taker is None:
            prize_taker = opponent_of_ko
        
        ko_owner.pokemon_knocked_out_last_turn = True
        
        if ko_pokemon is ko_owner.active:
            ko_owner._discard_pokemon(ko_pokemon)
            ko_owner.active = None
        else:
            if ko_pokemon in ko_owner.bench:
                idx = ko_owner.bench.index(ko_pokemon)
                ko_owner.bench.pop(idx)
                ko_owner._discard_pokemon(ko_pokemon)
        
        if not is_self_ko:
            prize_taker.take_prize(prize_count)
            if prize_taker.prizes_taken >= self.PRIZE_TARGET or not prize_taker.prizes:
                self.done = True
                self.winner = prize_taker.player_id
                return
        
        if ko_owner.active is None and not ko_owner.bench:
            self.done = True
            self.winner = 1 - ko_owner.player_id
            return
        
        if ko_owner.active is None and ko_owner.bench:
            ko_owner.active = ko_owner.bench.pop(0)
    
    def _end_turn(self):
        player = self.get_current_player()
        player.end_turn()
        self.has_attacked = False
        self.briar_active = False
        
        opponent = self.get_opponent()
        opponent.pokemon_knocked_out_last_turn = player.pokemon_knocked_out_last_turn if self.current_player == 1 else False
        
        self.current_player = 1 - self.current_player
        self.turn_count += 1
        
        if self.turn_count > self.MAX_TURNS:
            self.done = True
            if self.players[0].prizes_taken > self.players[1].prizes_taken:
                self.winner = 0
            elif self.players[1].prizes_taken > self.players[0].prizes_taken:
                self.winner = 1
            else:
                self.winner = None
            return
        
        new_player = self.get_current_player()
        new_player.start_turn()
        
        if not new_player.draw(1):
            self.done = True
            self.winner = 1 - self.current_player
            return
        
        for p in new_player.get_all_pokemon_in_play():
            p.cant_retreat_next = False
    
    def _check_win_conditions(self):
        for i, p in enumerate(self.players):
            if p.prizes_taken >= self.PRIZE_TARGET:
                self.done = True
                self.winner = i
                return
            if p.active is None and not p.bench:
                self.done = True
                self.winner = 1 - i
                return
    
    def _update_bench_limits(self):
        for p in self.players:
            if self.stadium and self.stadium.effect_id == "area_zero_underdepths":
                if p.has_tera_in_play():
                    p.max_bench = 8
                else:
                    p.max_bench = 5
            else:
                p.max_bench = 5
                while len(p.bench) > p.max_bench:
                    bp = p.bench.pop()
                    p._discard_pokemon(bp)
