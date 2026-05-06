import unittest

from loadtest.prompt import PromptFactory, TokenEstimator


class PromptFactoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.estimator = TokenEstimator("glm-5.1")
        self.factory = PromptFactory(self.estimator)

    def test_build_prompt_matches_target_tokens(self) -> None:
        for target_tokens in (1, 10, 1000, 10000):
            with self.subTest(target_tokens=target_tokens):
                prompt = self.factory.build_prompt(target_tokens)
                self.assertEqual(target_tokens, self.estimator.count(prompt))

    def test_build_prompt_is_deterministic(self) -> None:
        prompt_a = self.factory.build_prompt(1000)
        prompt_b = self.factory.build_prompt(1000)

        self.assertEqual(prompt_a, prompt_b)

    def test_build_prompt_rejects_invalid_target(self) -> None:
        with self.assertRaises(ValueError):
            self.factory.build_prompt(0)


if __name__ == "__main__":
    unittest.main()
