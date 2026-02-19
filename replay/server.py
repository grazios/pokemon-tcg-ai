"""ポケカTCG AI リプレイビューア — バックエンド (stdlib)"""
from __future__ import annotations
import sys, os, uuid, copy, json, glob, pickle, random
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import io

# engine/ をインポートできるようにする
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engine.game import Game
from engine.card_db import DECK_NAMES, build_deck
from engine.card import PokemonCard, TrainerCard, EnergyCard, PokemonInPlay
from engine.actions import decode_action, NUM_ACTIONS, END_TURN

# Lazy imports for heavy libs
HAS_SB3 = False
MaskablePPO = None
np = None
PTCGEnv = None

def _ensure_sb3():
    global HAS_SB3, MaskablePPO, np, PTCGEnv
    if MaskablePPO is not None:
        return
    try:
        from sb3_contrib import MaskablePPO as _M
        import numpy as _np
        from env.ptcg_env import PTCGEnv as _E
        MaskablePPO = _M
        np = _np
        PTCGEnv = _E
        HAS_SB3 = True
    except ImportError:
        pass

# ── グローバル ────────────────────────────────────
GAMES: dict[str, dict] = {}
MODEL_CACHE: dict[str, object] = {}
MODELS_DIR = ROOT / "models"

def _available_models() -> list[str]:
    models = ["random"]
    for p in sorted(MODELS_DIR.glob("*.zip")):
        models.append(p.stem)
    return models

def _load_model(name: str):
    if name == "random":
        return None
    _ensure_sb3()
    if not HAS_SB3:
        return None
    if name in MODEL_CACHE:
        return MODEL_CACHE[name]
    path = MODELS_DIR / f"{name}.zip"
    if not path.exists():
        return None
    model = MaskablePPO.load(str(path))
    MODEL_CACHE[name] = model
    return model

# ── シリアライズ ──────────────────────────────────
def _serialize_pokemon(p: PokemonInPlay | None) -> dict | None:
    if p is None:
        return None
    energy_list = []
    for e in p.attached_energy:
        energy_list.append(e.energy_type if not e.is_special else f"Special({e.name})")
    return {
        "name": p.card.name, "hp": p.current_hp, "maxHp": p.card.hp,
        "types": p.card.types, "stage": p.card.stage,
        "isEx": p.card.is_ex, "isTera": p.card.is_tera,
        "retreatCost": p.effective_retreat_cost, "energy": energy_list,
        "attacks": [{"name": a.name, "damage": a.damage, "cost": a.cost} for a in p.card.attacks],
        "abilities": [a.name for a in p.card.abilities],
        "tool": p.tool.name if p.tool else None,
        "weakness": p.card.weakness, "evolvesFrom": p.card.evolves_from,
        "evolutionChain": [c.name for c in p.evolution_chain],
    }

def _serialize_player(player) -> dict:
    return {
        "active": _serialize_pokemon(player.active),
        "bench": [_serialize_pokemon(bp) for bp in player.bench],
        "handCount": len(player.hand),
        "prizeCount": len(player.prizes),
        "prizesTaken": player.prizes_taken,
        "deckCount": len(player.deck),
    }

def _card_name(c) -> str:
    if isinstance(c, PokemonCard): return c.name
    elif isinstance(c, TrainerCard): return c.name
    elif isinstance(c, EnergyCard): return c.name or c.energy_type
    return str(c)

def _game_state(gid: str) -> dict:
    g = GAMES[gid]
    game: Game = g["game"]
    return {
        "id": gid, "turnCount": game.turn_count,
        "currentPlayer": game.current_player,
        "done": game.done, "winner": game.winner,
        "hasAttacked": game.has_attacked,
        "stadium": game.stadium.name if game.stadium else None,
        "players": [_serialize_player(game.players[0]), _serialize_player(game.players[1])],
        "stepIndex": g["step_index"],
    }

# ── AI ────────────────────────────────────────────
def _ai_choose_action(game: Game, player_id: int, model) -> int:
    valid = game.get_valid_actions()
    if not valid:
        return END_TURN
    if model is None:
        return random.choice(valid)
    _ensure_sb3()
    env = PTCGEnv.__new__(PTCGEnv)
    env.game = game
    env.agent_id = player_id
    obs = env._get_obs()
    mask = np.zeros(NUM_ACTIONS, dtype=bool)
    for a in valid:
        if 0 <= a < NUM_ACTIONS:
            mask[a] = True
    action, _ = model.predict(obs, action_masks=mask, deterministic=True)
    action = int(action)
    if action not in valid:
        action = random.choice(valid)
    return action

def _action_description(game: Game, player_id: int, action: int) -> str:
    info = decode_action(action)
    atype = info["type"]
    player = game.players[player_id]
    if atype == "end_turn": return "ターン終了"
    elif atype == "play_card":
        idx = info["hand_idx"]
        if idx < len(player.hand):
            c = player.hand[idx]
            if isinstance(c, PokemonCard) and c.is_basic:
                return f"ベンチに出す: {_card_name(c)}"
            elif isinstance(c, TrainerCard):
                return f"トレーナーズ: {_card_name(c)}"
            return f"カードプレイ: {_card_name(c)}"
        return "カードプレイ"
    elif atype == "evolve_active":
        idx = info["hand_idx"]
        if idx < len(player.hand):
            target = player.active.card.name if player.active else "?"
            return f"進化: {target} → {player.hand[idx].name}"
        return "進化（アクティブ）"
    elif atype == "evolve_bench":
        idx, bi = info["hand_idx"], info["bench_idx"]
        if idx < len(player.hand) and bi < len(player.bench):
            return f"進化: {player.bench[bi].card.name} → {player.hand[idx].name}"
        return "進化（ベンチ）"
    elif atype == "energy_active":
        idx = info["hand_idx"]
        if idx < len(player.hand):
            c = player.hand[idx]
            ename = c.energy_type if isinstance(c, EnergyCard) else "?"
            target = player.active.card.name if player.active else "?"
            return f"エネルギー: {ename} → {target}"
        return "エネルギー（アクティブ）"
    elif atype == "energy_bench":
        idx, bi = info["hand_idx"], info["bench_idx"]
        if idx < len(player.hand) and bi < len(player.bench):
            c = player.hand[idx]
            ename = c.energy_type if isinstance(c, EnergyCard) else "?"
            return f"エネルギー: {ename} → {player.bench[bi].card.name}"
        return "エネルギー（ベンチ）"
    elif atype == "attack":
        ai = info["attack_idx"]
        if player.active and ai < len(player.active.card.attacks):
            atk = player.active.card.attacks[ai]
            return f"技: {atk.name} ({atk.damage}ダメージ)"
        return "技"
    elif atype == "retreat":
        bi = info["bench_idx"]
        if player.active is None:
            if bi < len(player.bench): return f"プロモート: {player.bench[bi].card.name}"
            return "プロモート"
        if bi < len(player.bench): return f"にげる → {player.bench[bi].card.name}"
        return "にげる"
    elif atype in ("rare_candy_active", "rare_candy_bench"):
        return f"ふしぎなアメ"
    elif atype == "use_ability":
        target = info.get("target", "active")
        if target == "active" and player.active and player.active.card.abilities:
            return f"特性: {player.active.card.abilities[0].name} ({player.active.card.name})"
        elif target == "bench":
            bi = info.get("bench_idx", 0)
            if bi < len(player.bench) and player.bench[bi].card.abilities:
                return f"特性: {player.bench[bi].card.abilities[0].name} ({player.bench[bi].card.name})"
        return "特性"
    return f"アクション#{action}"

# ── HTTP Handler ──────────────────────────────────
REPLAY_DIR = Path(__file__).resolve().parent

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        if path == "/" or path == "/index.html":
            self.send_file(REPLAY_DIR / "index.html", "text/html")
        elif path == "/api/decks":
            self.send_json({"decks": DECK_NAMES})
        elif path == "/api/models":
            self.send_json({"models": _available_models()})
        elif path.startswith("/api/game/") and path.endswith("/state"):
            gid = path.split("/")[3]
            if gid in GAMES:
                self.send_json(_game_state(gid))
            else:
                self.send_json({"error": "not found"}, 404)
        elif path.startswith("/api/game/") and path.endswith("/log"):
            gid = path.split("/")[3]
            if gid in GAMES:
                self.send_json({"log": GAMES[gid]["log"]})
            else:
                self.send_json({"error": "not found"}, 404)
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len) if content_len > 0 else b'{}'
        try:
            data = json.loads(body)
        except:
            data = {}
        
        if path == "/api/game/start":
            self.handle_start(data)
        elif path.startswith("/api/game/") and path.endswith("/step"):
            gid = path.split("/")[3]
            self.handle_step(gid)
        elif path.startswith("/api/game/") and path.endswith("/play-turn"):
            gid = path.split("/")[3]
            self.handle_play_turn(gid)
        elif path.startswith("/api/game/") and path.endswith("/step-back"):
            gid = path.split("/")[3]
            self.handle_step_back(gid)
        else:
            self.send_error(404)
    
    def handle_start(self, data):
        d0 = int(data.get("deck0", 0))
        d1 = int(data.get("deck1", 1))
        m0 = data.get("model0", "random")
        m1 = data.get("model1", "random")
        
        game = Game(d0, d1)
        game.reset()
        
        gid = uuid.uuid4().hex[:8]
        GAMES[gid] = {
            "game": game,
            "models": [_load_model(m0), _load_model(m1)],
            "model_names": [m0, m1],
            "deck_ids": [d0, d1],
            "log": [],
            "step_index": 0,
            "snapshots": [pickle.dumps(game)],
        }
        self.send_json({"id": gid, "state": _game_state(gid)})
    
    def handle_step(self, gid):
        if gid not in GAMES:
            self.send_json({"error": "not found"}, 404); return
        g = GAMES[gid]
        game: Game = g["game"]
        if game.done:
            self.send_json({"state": _game_state(gid), "action": None, "done": True}); return
        
        cp = game.current_player
        model = g["models"][cp]
        action = _ai_choose_action(game, cp, model)
        desc = _action_description(game, cp, action)
        info = decode_action(action)
        game.step(action)
        g["step_index"] += 1
        
        entry = {"step": g["step_index"], "player": cp, "turn": game.turn_count, "action": action, "type": info["type"], "description": desc}
        g["log"].append(entry)
        g["snapshots"].append(pickle.dumps(game))
        
        self.send_json({"state": _game_state(gid), "action": entry, "done": game.done})
    
    def handle_play_turn(self, gid):
        if gid not in GAMES:
            self.send_json({"error": "not found"}, 404); return
        g = GAMES[gid]
        game: Game = g["game"]
        if game.done:
            self.send_json({"state": _game_state(gid), "actions": [], "done": True}); return
        
        start_turn = game.turn_count
        actions = []
        safety = 0
        while not game.done and game.turn_count == start_turn and safety < 100:
            cp = game.current_player
            model = g["models"][cp]
            action = _ai_choose_action(game, cp, model)
            desc = _action_description(game, cp, action)
            info = decode_action(action)
            game.step(action)
            g["step_index"] += 1
            entry = {"step": g["step_index"], "player": cp, "turn": start_turn, "action": action, "type": info["type"], "description": desc}
            g["log"].append(entry)
            g["snapshots"].append(pickle.dumps(game))
            actions.append(entry)
            safety += 1
        
        self.send_json({"state": _game_state(gid), "actions": actions, "done": game.done})
    
    def handle_step_back(self, gid):
        if gid not in GAMES:
            self.send_json({"error": "not found"}, 404); return
        g = GAMES[gid]
        if g["step_index"] <= 0:
            self.send_json({"state": _game_state(gid), "error": "already at start"}); return
        
        g["step_index"] -= 1
        g["game"] = pickle.loads(g["snapshots"][g["step_index"]])
        g["snapshots"] = g["snapshots"][:g["step_index"] + 1]
        g["log"] = g["log"][:g["step_index"]]
        
        self.send_json({"state": _game_state(gid)})
    
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)
    
    def send_file(self, filepath, content_type):
        data = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def log_message(self, format, *args):
        pass  # quiet


if __name__ == "__main__":
    print("🎮 ポケカTCG AI リプレイビューア")
    print(f"   デッキ: {DECK_NAMES}")
    print(f"   モデル数: {len(_available_models())}")
    print(f"   → http://localhost:8877")
    sys.stdout.flush()
    # Avoid DNS lookup hang
    import socket as _socket
    _orig_getfqdn = _socket.getfqdn
    _socket.getfqdn = lambda name='': name or 'localhost'
    
    import socketserver
    socketserver.TCPServer.allow_reuse_address = True
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", 8877), Handler)
    
    _socket.getfqdn = _orig_getfqdn
    print("   サーバー起動完了!")
    sys.stdout.flush()
    server.serve_forever()
