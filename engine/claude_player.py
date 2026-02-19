"""Claudeプレイヤー - LLMにポケカをプレイさせる"""
from __future__ import annotations
import os
import re
import time
import anthropic
from .game import Game
from .text_state import format_game_state, format_valid_actions
from .actions import END_TURN, decode_action

SYSTEM_PROMPT = """\
あなたはポケモンカードゲームのプロプレイヤーです。
毎ターン、ゲーム状態と有効アクションが提示されます。

このターンで実行するアクション番号を、優先順に**カンマ区切り**で全て回答してください。
数字のみ回答。例: 3, 7, 12, 1

戦略の指針:
- メインアタッカーを早く立てる（進化+エネ加速）
- 特性→進化→サポーター→グッズ→エネ付与→技 の順で考える
- 技を撃てるなら基本的に撃つ（ただし先にサポート等を使い切ってから）
- エネルギーはメインアタッカーに集中させる
- ボスの指令は相手のキーポケモン（進化前やダメージ蓄積済み）を狙う
- 技を撃つとターン終了になるので、技は最後に使う
- 何もすることがなければターン終了を選ぶ
"""


class ClaudePlayer:
    """Claudeを使ってポケカをプレイするプレイヤー"""

    def __init__(self, model: str = "claude-sonnet-4-20250514",
                 max_retries: int = 3, verbose: bool = False):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable not set")
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.total_calls = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def choose_turn_actions(self, game: Game, player_id: int) -> list[int]:
        """1ターン分のアクション列をClaudeに選ばせる。
        
        Returns:
            有効アクションのインデックスリスト（format_valid_actionsの番号）
        """
        state_text = format_game_state(game, player_id)
        actions_text = format_valid_actions(game, player_id)
        valid = game.get_valid_actions()

        prompt = f"{state_text}\n\n{actions_text}\n\nこのターンで実行するアクション番号をカンマ区切りで回答してください。"

        for attempt in range(self.max_retries):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=100,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                self.total_calls += 1
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens

                text = response.content[0].text.strip()
                if self.verbose:
                    print(f"  Claude response: {text}")

                # Parse comma-separated numbers
                numbers = re.findall(r'\d+', text)
                action_indices = []
                for n in numbers:
                    idx = int(n) - 1  # 1-indexed → 0-indexed
                    if 0 <= idx < len(valid):
                        action_indices.append(idx)

                if action_indices:
                    return action_indices

            except anthropic.RateLimitError:
                time.sleep(2 ** attempt)
            except Exception as e:
                if self.verbose:
                    print(f"  Claude error (attempt {attempt+1}): {e}")
                time.sleep(1)

        # Fallback: return END_TURN index
        for i, a in enumerate(valid):
            if a == END_TURN:
                return [i]
        return [0]

    def choose_action(self, game: Game, player_id: int) -> int:
        """1アクションだけ選ぶ（step-by-step用）"""
        valid = game.get_valid_actions()
        if len(valid) == 1:
            return valid[0]

        indices = self.choose_turn_actions(game, player_id)
        if indices:
            return valid[indices[0]]
        return valid[0]

    def get_stats(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
        }
