import unittest

import vllm_offline as v


class FakeTokenizer:
    """Renders like a template that adds a default system prompt when none is given."""

    def __init__(self, default):
        self.default = default

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True):
        system = next((m["content"] for m in messages if m["role"] == "system"), self.default)
        head = f"<|system|>{system}<|end|>" if system else ""
        turns = "".join(f"<|{m['role']}|>{m['content']}<|end|>" for m in messages if m["role"] != "system")
        return head + turns + "<|assistant|>"


class VllmHelperTests(unittest.TestCase):
    def test_short_name(self):
        self.assertEqual(v.short_name("meta-llama/Llama-3.3-70B-Instruct"), "llama-3.3-70b-instruct")
        self.assertNotIn("|", v.short_name("org/odd|name"))

    def test_split_reasoning(self):
        self.assertEqual(v.split_reasoning("<think>hmm</think>\n\nAnswer."), ("Answer.", "hmm"))
        self.assertEqual(v.split_reasoning("analysis stuff assistantfinal Answer."),
                         ("Answer.", "analysis stuff"))
        self.assertEqual(v.split_reasoning(" Plain. "), ("Plain.", ""))

    def test_default_system_found_and_kept(self):
        tok = FakeTokenizer("You are a helpful assistant.")
        self.assertEqual(v.default_system(tok), "You are a helpful assistant.")
        self.assertEqual(v.default_system(FakeTokenizer("")), "")
        cell = {"system": "Saved memory: the user is a teacher.", "user": "Q?"}
        system = v.messages_for(cell, v.default_system(tok))[0]["content"]
        self.assertTrue(system.startswith("You are a helpful assistant."))
        self.assertTrue(system.endswith("Saved memory: the user is a teacher."))

    def test_no_system_prompt_left_to_the_template(self):
        self.assertEqual(v.messages_for({"system": "", "user": "Q?"}, "Default."),
                         [{"role": "user", "content": "Q?"}])


if __name__ == "__main__":
    unittest.main()
