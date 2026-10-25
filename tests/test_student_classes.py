"""과목별 반 배정 시험: python3 -m unittest discover -s tests"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from student_classes import guess_class_subject, class_assignment_fields


class StudentClassesTests(unittest.TestCase):
    def test_guess_subject_from_class_name(self):
        self.assertEqual(guess_class_subject("고2 수학 A반"), "math")
        self.assertEqual(guess_class_subject("영어 독해반"), "english")
        self.assertEqual(guess_class_subject("고3 국어 수요일"), "korean")
        self.assertEqual(guess_class_subject("미강고 토요일"), "korean")

    def test_math_class_keeps_korean_class(self):
        # 임지섭: 예전 방식으로 국어반만 있던 학생을 수학반에 넣는다
        jiseop = {"class_name": "고2 국어 미사고", "subjects": ["korean"]}
        out = class_assignment_fields(jiseop, "math", "고2 수학 A반")
        self.assertEqual(out["class_names"], {"korean": "고2 국어 미사고", "math": "고2 수학 A반"})
        self.assertNotIn("class_name", out)                      # 국어 한 칸은 건드리지 않는다
        self.assertEqual(out["subjects"], ["korean", "math"])    # 수학도 듣는 것으로

    def test_korean_class_also_updates_old_field(self):
        out = class_assignment_fields({"class_names": {"math": "고2 수학 A반"}, "subjects": ["korean", "math"]}, "korean", "고2 국어 풍산고")
        self.assertEqual(out["class_names"], {"math": "고2 수학 A반", "korean": "고2 국어 풍산고"})
        self.assertEqual(out["class_name"], "고2 국어 풍산고")
        self.assertNotIn("subjects", out)

    def test_unassign_one_subject_only(self):
        out = class_assignment_fields({"class_names": {"korean": "국어A", "math": "수학A"}}, "math", "")
        self.assertEqual(out["class_names"], {"korean": "국어A", "math": ""})


if __name__ == "__main__":
    unittest.main()


from student_classes import merge_added_student


class AddStudentAgainTests(unittest.TestCase):
    def test_new_student(self):
        out = merge_added_student({}, "미사고", "2", "고2 국어 미사고", None, ["korean"])
        self.assertEqual(out["subjects"], ["korean"])
        self.assertEqual(out["class_names"], {"korean": "고2 국어 미사고"})
        self.assertEqual(out["class_name"], "고2 국어 미사고")

    def test_adding_again_for_math_keeps_korean(self):
        jiseop = {"school": "미사고", "grade": "2", "class_name": "고2 국어 미사고", "subjects": ["korean"]}
        out = merge_added_student(jiseop, "미사고", "2", "고2 수학 A반", None, ["math"])
        self.assertEqual(out["subjects"], ["korean", "math"])
        self.assertEqual(out["class_names"], {"korean": "고2 국어 미사고", "math": "고2 수학 A반"})
        self.assertNotIn("class_name", out)               # 국어반 칸을 수학반으로 덮지 않는다

    def test_class_names_map_from_form(self):
        out = merge_added_student({}, "풍산고", "1", "", {"korean": "국어A", "math": "수학B", "english": ""}, ["korean", "math"])
        self.assertEqual(out["class_names"], {"korean": "국어A", "math": "수학B"})
        self.assertEqual(out["subjects"], ["korean", "math"])
