from __future__ import annotations

import math

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


LOREM = (
    "Large language model load testing requires stable prompts, good observability, "
    "careful concurrency control, retry policies, and accurate token accounting. "
    "This synthetic corpus is repeated to generate long prompts for pressure testing. "
)


class TokenEstimator:
    def __init__(self, model: str):
        self.model = model
        self.encoder = None
        if tiktoken is not None:
            try:
                self.encoder = tiktoken.encoding_for_model(model)
            except Exception:
                try:
                    self.encoder = tiktoken.get_encoding("cl100k_base")
                except Exception:
                    self.encoder = None

    def count(self, text: str) -> int:
        if self.encoder is not None:
            return len(self.encoder.encode(text))
        return max(1, math.ceil(len(text) / 4))


class PromptFactory:
    def __init__(self, estimator: TokenEstimator):
        self.estimator = estimator

    def build_prompt(self, target_tokens: int) -> str:
        if target_tokens < 1:
            raise ValueError("target_tokens must be greater than 0")

        if self.estimator.encoder is not None:
            return self._build_exact_prompt(target_tokens)
        return self._build_estimated_prompt(target_tokens)

    def _build_exact_prompt(self, target_tokens: int) -> str:
        encoder = self.estimator.encoder
        tokens: list[int] = []
        block_idx = 0

        while len(tokens) < target_tokens:
            prefix = "" if block_idx == 0 else "\n"
            block = f"{prefix}[BLOCK {block_idx}] {LOREM}"
            tokens.extend(encoder.encode(block))
            block_idx += 1

        prompt = encoder.decode(tokens[:target_tokens])
        if self.estimator.count(prompt) == target_tokens:
            return prompt

        return self._refine_to_target(prompt, target_tokens)

    def _build_estimated_prompt(self, target_tokens: int) -> str:
        prompt = ""
        block_idx = 0
        while self.estimator.count(prompt) < target_tokens:
            prefix = "" if not prompt else "\n"
            prompt += f"{prefix}[BLOCK {block_idx}] {LOREM}"
            block_idx += 1

        return self._refine_to_target(prompt, target_tokens)

    def _refine_to_target(self, prompt: str, target_tokens: int) -> str:
        while self.estimator.count(prompt) > target_tokens and prompt:
            prompt = prompt[:-1]

        filler_idx = 0
        while self.estimator.count(prompt) < target_tokens:
            prompt += f" filler{filler_idx}"
            filler_idx += 1

        while self.estimator.count(prompt) > target_tokens and prompt:
            prompt = prompt[:-1]

        return prompt
