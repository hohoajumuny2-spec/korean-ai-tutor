"""해설 보고 이해했는지(1/0) 표시 · 과제 배포 때 요약 해설(qmeta) 얹기."""
import ast
import json
import os
import unittest

import study_extras

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "main.py"), encoding="utf-8").read()
_NAMES = {"understood_map", "homework_qmeta_with", "_num"}
_ns = {"json": json, "study_extras": study_extras}
_code = ""
for _n in ast.parse(_SRC).body:
    if isinstance(_n, ast.FunctionDef) and _n.name in _NAMES:
        _code += ast.get_source_segment(_SRC, _n) + "\n"
exec(_code, _ns)
understood_map, qmeta_with = _ns["understood_map"], _ns["homework_qmeta_with"]


class UnderstoodTests(unittest.TestCase):
    def test_keeps_only_0_and_1(self):
        rep = {"understood": {"3": 1, "5": 0, "x": 1, "7": 2}}
        self.assertEqual(understood_map(rep), {"3": 1, "5": 0})

    def test_empty(self):
        self.assertEqual(understood_map({}), {})
        self.assertEqual(understood_map({"understood": None}), {})


class QmetaTests(unittest.TestCase):
    def test_no_incoming_keeps_old(self):
        old = {"1": {"tag": "비문학"}}
        self.assertEqual(qmeta_with(old, ""), {"1": {"tag": "비문학"}})
        self.assertEqual(qmeta_with(old, "not json"), {"1": {"tag": "비문학"}})

    def test_adds_summary_on_top(self):
        old = {"1": {"tag": "비문학"}}
        got = qmeta_with(old, json.dumps({"1": {"summary": "③이 답인 까닭"}, "2": {"summary": "④", "tag": "문법"}}))
        self.assertEqual(got["1"], {"tag": "비문학", "summary": "③이 답인 까닭"})
        self.assertEqual(got["2"]["tag"], "문법")


if __name__ == "__main__":
    unittest.main()
