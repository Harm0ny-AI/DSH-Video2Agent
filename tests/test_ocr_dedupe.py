import unittest

from video2agent.visual import _collapse_repeated_text, _unique_ocr_boxes


class OcrDedupeTests(unittest.TestCase):
    def test_same_line_detected_many_times_is_one_box(self):
        boxes = [{"text": "输入是我的脸,输出是解锁成功。", "bbox": [10, 20, 500, 40], "confidence": 0.0} for _ in range(100)]
        self.assertEqual(len(_unique_ocr_boxes(boxes)), 1)

    def test_repeated_subtitle_is_collapsed(self):
        text = "输入是我的脸,输出是解锁成功。 " * 100
        self.assertEqual(_collapse_repeated_text(text), "输入是我的脸,输出是解锁成功。")

    def test_same_text_on_two_rows_is_kept(self):
        boxes = [
            {"text": "准确率", "bbox": [10, 20, 100, 40], "confidence": 0.8},
            {"text": "准确率", "bbox": [10, 120, 100, 140], "confidence": 0.8},
        ]
        self.assertEqual(len(_unique_ocr_boxes(boxes)), 2)
