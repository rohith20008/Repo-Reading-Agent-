import json
import unittest
from pathlib import Path

from run_benchmark import checks


ROOT = Path(__file__).resolve().parent


class BenchmarkDataTests(unittest.TestCase):
    def test_evaluation_set_and_training_set_are_separate_files(self):
        cases = [
            json.loads(line)
            for line in (ROOT / "evaluation_cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        examples = [
            json.loads(line)
            for line in (ROOT / "training" / "proposed_train.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(cases), 8)
        self.assertEqual(len(examples), 7)
        self.assertTrue(all(example["metadata"]["source"] == "synthetic" for example in examples))
        self.assertTrue(all("messages" in example for example in examples))

    def test_prompt_catalog_covers_all_six_specialists(self):
        prompts = json.loads((ROOT / "prompts_optimized.json").read_text(encoding="utf-8"))
        self.assertEqual(
            set(prompts),
            {
                "repository-explorer",
                "code-intelligence",
                "bug-investigator",
                "dependency-analyst",
                "documentation",
                "code-recommendation",
            },
        )

    def test_evidence_snippets_match_fixture_line_ranges(self):
        cases = [
            json.loads(line)
            for line in (ROOT / "evaluation_cases.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        fixture = ROOT / "fixtures" / "sample_repo"
        for case in cases:
            for evidence in case["evidence"]:
                with self.subTest(case=case["id"], evidence=evidence["id"]):
                    lines = (fixture / evidence["path"]).read_text(encoding="utf-8").splitlines()
                    excerpt = lines[evidence["startLine"] - 1 : evidence["endLine"]]
                    self.assertEqual(excerpt, evidence["snippet"].splitlines())


class ScoringTests(unittest.TestCase):
    def test_evidence_reference_counts_as_identifying_its_source_file(self):
        case = {
            "required_terms": ["None", ["dict.get", "get(key)"]],
            "expected_paths": ["src/cache.py"],
            "forbidden_paths": ["src/unknown.py"],
            "evidence": [{"id": "E1", "path": "src/cache.py"}],
        }
        result = checks(case, "The method returns None [E1].", {"src/cache.py"})
        self.assertEqual(result["required_term_coverage"], 0.5)
        self.assertEqual(result["expected_path_coverage"], 1.0)
        self.assertTrue(result["has_evidence_id_citation"])

    def test_unknown_and_forbidden_paths_are_reported(self):
        case = {
            "required_terms": ["observed"],
            "expected_paths": ["src/cache.py"],
            "forbidden_paths": ["src/secret.py"],
            "evidence": [{"id": "E1", "path": "src/cache.py"}],
        }
        result = checks(
            case,
            "Observed in src/secret.py; see src/fabricated.py.",
            {"src/cache.py"},
        )
        self.assertEqual(result["forbidden_path_mentions"], ["src/secret.py"])
        self.assertEqual(result["unknown_path_mentions"], ["src/fabricated.py"])
        self.assertEqual(result["unsupported_path_proxy_count"], 2)


if __name__ == "__main__":
    unittest.main()
