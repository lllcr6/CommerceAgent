from app.core import model_guard as g


EVIDENCE = ("[1] 全景看护摄像头(型号 MH-CAM1): 供电:Type-C 供电,需连接 2.4G Wi-Fi\n"
            "[2] 自动喂食器 摄像头版(型号 MH-FD30): 粮桶容量:6L")
ANSWER_BAD = "确认 Type-C 供电线连接正常(针对 MH-CAD1 型号)[1],摄像头版(MH-FD30)保修 12 个月[2]。"
ANSWER_OK = "确认 Type-C 供电线连接正常(针对 MH-CAM1 型号)[1]。"


def test_detects_unsupported_model_numbers():
    assert g.unsupported_models(ANSWER_BAD, EVIDENCE) == ["MH-CAD1"]


def test_evidence_supported_model_numbers_pass():
    assert g.unsupported_models(ANSWER_OK, EVIDENCE) == []


def test_answer_without_model_numbers_passes():
    assert g.unsupported_models("满 99 元包邮[1]。", EVIDENCE) == []


def test_unique_model_numbers_preserve_order():
    bad = g.unsupported_models("MH-XX9 与 MH-YY1,再提一次 MH-XX9", EVIDENCE)
    assert bad == ["MH-XX9", "MH-YY1"]


def test_model_number_case_mismatch_is_unsupported():

    assert g.unsupported_models("针对 mh-cam1 型号", EVIDENCE) == []
    assert g.unsupported_models("针对 MH-Cam1 型号", EVIDENCE) == ["MH-Cam1"]


def test_regular_identifiers_are_not_product_models():
    for s in ("[1]", "2.4G Wi-Fi", "128G TF 卡", "MH-", "MHLP100"):
        assert g.models_in(s) == [], s


def test_repair_hint_does_not_guess_replacement_models():
    hint = g.repair_hint(["MH-CAD1"])
    assert "MH-CAD1" in hint and "MH-CAM1" not in hint
