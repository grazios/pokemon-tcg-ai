"""ゲーム状態のテキスト化 - LLM/人間可読なテキストに変換"""
from __future__ import annotations
from .card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay
from .actions import (
    decode_action, PLAY_CARD_BASE, EVOLVE_ACTIVE_BASE, EVOLVE_BENCH_BASE,
    ENERGY_ACTIVE_BASE, ENERGY_BENCH_BASE, ATTACK_BASE, RETREAT_BASE,
    END_TURN, RARE_CANDY_ACTIVE_BASE, RARE_CANDY_BENCH_BASE,
    USE_ABILITY_ACTIVE, USE_ABILITY_BENCH_BASE, MAX_HAND,
)
from .game import Game
from .player import Player


# Japanese type names
TYPE_JP = {
    "Fire": "炎", "Water": "水", "Grass": "草", "Lightning": "雷",
    "Psychic": "超", "Fighting": "闘", "Darkness": "悪", "Metal": "鋼",
    "Dragon": "竜", "Colorless": "無色", "Special": "特殊",
}


def _type_jp(t: str) -> str:
    return TYPE_JP.get(t, t)


def _format_energy_list(pip: PokemonInPlay) -> str:
    """付いてるエネルギーを表示"""
    counts = pip.energy_count_by_type()
    if not counts:
        return "エネなし"
    parts = []
    for etype, count in sorted(counts.items()):
        if etype == "_any":
            parts.append(f"任意×{count}")
        else:
            parts.append(f"{_type_jp(etype)}×{count}")
    return ", ".join(parts)


def _format_pokemon(pip: PokemonInPlay, idx: int | None = None,
                    show_attacks: bool = False) -> str:
    """ポケモン1体の情報"""
    c = pip.card
    prefix = ""
    if idx is not None:
        prefix = f"  {idx+1}. "
    
    line = f"{prefix}{c.name} HP{pip.current_hp}/{c.hp} [{_format_energy_list(pip)}]"
    
    if c.stage != "Basic":
        line += f" ({c.stage})"
    if c.is_ex:
        line += " [ex]"
    if c.is_tera:
        line += " [テラスタル]"
    
    lines = [line]
    
    if show_attacks:
        for i, atk in enumerate(c.attacks):
            cost_str = "+".join(f"{_type_jp(t)}×{n}" for t, n in atk.cost.items())
            usable = "使用可能" if pip.can_use_attack(atk) else "エネ不足"
            dmg_str = f"{atk.damage}ダメ" if atk.damage > 0 else "特殊効果"
            desc = f"    技{i+1}: {atk.name} [{cost_str}] {dmg_str} → {usable}"
            if atk.text:
                desc += f" ({atk.text[:60]})"
            lines.append(desc)
        for ab in c.abilities:
            lines.append(f"    特性: {ab.name}" + (f" ({ab.text[:60]})" if ab.text else ""))
    else:
        # Compact: just show abilities
        for ab in c.abilities:
            line_parts = f"    特性:{ab.name}"
            lines.append(line_parts)
    
    if pip.tool:
        lines.append(f"    ツール: {pip.tool.name}")
    
    return "\n".join(lines)


def format_game_state(game: Game, player_id: int) -> str:
    """ゲーム状態を人間/LLM可読なテキストに変換"""
    me = game.players[player_id]
    opp = game.players[1 - player_id]
    
    lines = []
    lines.append(f"=== {'あなた' if game.current_player == player_id else '相手'}のターン (T{game.turn_count}) ===")
    
    # My side
    lines.append(f"あなた: サイド残り{len(me.prizes)}枚(取得{me.prizes_taken}) | 手札{len(me.hand)}枚 | 山札{len(me.deck)}枚")
    if me.active:
        lines.append(f"バトル場: {_format_pokemon(me.active, show_attacks=True)}")
    else:
        lines.append("バトル場: なし")
    
    if me.bench:
        lines.append("ベンチ:")
        for i, bp in enumerate(me.bench):
            lines.append(_format_pokemon(bp, idx=i, show_attacks=False))
    
    if game.stadium:
        lines.append(f"スタジアム: {game.stadium.name}")
    
    lines.append("")
    
    # Opponent side
    lines.append(f"相手: サイド残り{len(opp.prizes)}枚(取得{opp.prizes_taken}) | 手札{len(opp.hand)}枚 | 山札{len(opp.deck)}枚")
    if opp.active:
        lines.append(f"バトル場: {_format_pokemon(opp.active, show_attacks=False)}")
    else:
        lines.append("バトル場: なし")
    
    if opp.bench:
        lines.append("ベンチ:")
        for i, bp in enumerate(opp.bench):
            lines.append(_format_pokemon(bp, idx=i, show_attacks=False))
    
    lines.append("")
    
    # Hand
    hand_strs = []
    for c in me.hand:
        if isinstance(c, PokemonCard):
            hand_strs.append(f"{c.name}({c.stage})")
        elif isinstance(c, TrainerCard):
            hand_strs.append(f"{c.name}[{c.trainer_type}]")
        elif isinstance(c, EnergyCard):
            hand_strs.append(f"{c.name}")
        else:
            hand_strs.append(str(c))
    lines.append(f"手札: [{', '.join(hand_strs)}]")
    
    # State flags
    flags = []
    if me.supporter_played_this_turn:
        flags.append("サポーター使用済み")
    if me.energy_attached_this_turn:
        flags.append("エネルギー付与済み")
    if game.has_attacked:
        flags.append("攻撃済み")
    if flags:
        lines.append(f"状態: {', '.join(flags)}")
    
    return "\n".join(lines)


def format_action(action: int, player: Player, opponent: Player, game: Game) -> str:
    """アクションIDを人間可読な説明に変換"""
    info = decode_action(action)
    atype = info["type"]
    
    if atype == "end_turn":
        return "ターン終了"
    
    if atype == "play_card":
        hi = info["hand_idx"]
        if hi < len(player.hand):
            card = player.hand[hi]
            if isinstance(card, PokemonCard):
                return f"{card.name}をベンチに出す"
            elif isinstance(card, TrainerCard):
                return f"{card.name}を使う"
        return f"手札{hi}をプレイ"
    
    if atype == "evolve_active":
        hi = info["hand_idx"]
        if hi < len(player.hand):
            card = player.hand[hi]
            target = player.active.card.name if player.active else "?"
            return f"{target}を{card.name}に進化"
        return "アクティブを進化"
    
    if atype == "evolve_bench":
        hi, bi = info["hand_idx"], info["bench_idx"]
        card_name = player.hand[hi].name if hi < len(player.hand) else "?"
        target_name = player.bench[bi].card.name if bi < len(player.bench) else "?"
        return f"ベンチの{target_name}を{card_name}に進化"
    
    if atype == "energy_active":
        hi = info["hand_idx"]
        if hi < len(player.hand):
            card = player.hand[hi]
            target = player.active.card.name if player.active else "?"
            return f"{card.name}を{target}に付ける"
        return "アクティブにエネルギー"
    
    if atype == "energy_bench":
        hi, bi = info["hand_idx"], info["bench_idx"]
        card_name = player.hand[hi].name if hi < len(player.hand) else "?"
        target_name = player.bench[bi].card.name if bi < len(player.bench) else "?"
        return f"{card_name}を{target_name}に付ける"
    
    if atype == "attack":
        ai = info["attack_idx"]
        if player.active and ai < len(player.active.card.attacks):
            atk = player.active.card.attacks[ai]
            target = opponent.active.card.name if opponent.active else "?"
            return f"技「{atk.name}」を使う → {target}に{atk.damage}+ダメージ"
        return "技を使う"
    
    if atype == "retreat":
        bi = info["bench_idx"]
        if player.active is None:
            target = player.bench[bi].card.name if bi < len(player.bench) else "?"
            return f"{target}をバトル場に出す(プロモート)"
        target = player.bench[bi].card.name if bi < len(player.bench) else "?"
        return f"にげる → {target}と入れ替え"
    
    if atype == "rare_candy_active":
        hi = info["hand_idx"]
        card_name = player.hand[hi].name if hi < len(player.hand) else "?"
        target = player.active.card.name if player.active else "?"
        return f"ふしぎなアメ: {target}を{card_name}に進化"
    
    if atype == "rare_candy_bench":
        hi, bi = info["hand_idx"], info["bench_idx"]
        card_name = player.hand[hi].name if hi < len(player.hand) else "?"
        target = player.bench[bi].card.name if bi < len(player.bench) else "?"
        return f"ふしぎなアメ: {target}を{card_name}に進化"
    
    if atype == "use_ability":
        target = info.get("target", "active")
        if target == "active" and player.active:
            abs_list = player.active.card.abilities
            ab_name = abs_list[0].name if abs_list else "?"
            return f"特性「{ab_name}」を使う({player.active.card.name})"
        elif target == "bench":
            bi = info.get("bench_idx", 0)
            if bi < len(player.bench):
                abs_list = player.bench[bi].card.abilities
                ab_name = abs_list[0].name if abs_list else "?"
                return f"特性「{ab_name}」を使う({player.bench[bi].card.name})"
        return "特性を使う"
    
    return f"不明なアクション({action})"


def format_valid_actions(game: Game, player_id: int) -> str:
    """有効アクションリストをテキスト化"""
    valid = game.get_valid_actions()
    me = game.players[player_id]
    opp = game.players[1 - player_id]
    
    lines = ["有効なアクション:"]
    for i, a in enumerate(valid):
        desc = format_action(a, me, opp, game)
        lines.append(f"  {i+1}. [{a}] {desc}")
    
    return "\n".join(lines)
