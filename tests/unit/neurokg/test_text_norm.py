import os
import sys
import unittest

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from brain_researcher.services.neurokg.utils.text_norm import normalize_task_name


class TestNormalizeTaskName(unittest.TestCase):
    def test_cases(self):
        cases = {
            "n-back": "n back",
            "NBack": "n back",
            "go-no-go": "go no go",
            "GoNoGo": "go no go",
            "Stop_signal": "stop signal",
            "StopSignalTask": "stop signal task",
            "VisualWorkingMemory": "visual working memory",
            "visualWorkingMemoryTask": "visual working memory task",
            "faceRecognition": "face recognition",
            "FaceRecog": "face recog",
            "   spaced   out ": "spaced out",
            "BART": "balloon analogue risk task",
            "BalloonAnalogueRiskTask": "balloon analogue risk task",
            "Balloon_Analog_Risk_Task": "balloon analogue risk task",
            "balloon analog risk task": "balloon analogue risk task",
            "bart task": "balloon analogue risk task task",
            "MixedCaseExample": "mixed case example",
            "": "",
            "under_score-test": "under score test",
            "CamelCASE": "camel case",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_task_name(raw), expected)


if __name__ == "__main__":
    unittest.main()
