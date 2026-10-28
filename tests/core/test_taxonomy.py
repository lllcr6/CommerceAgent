from app.core.taxonomy import (ID2LABEL, LABEL2ID, NUM_CLASSES, TOPIC_CLASSES,
                               TOPIC_NAMES, terminology_table)


def test_seventeen_unique_classes():
    assert NUM_CLASSES == 17
    assert len(set(TOPIC_NAMES)) == 17


def test_four_leads_first():
    assert TOPIC_NAMES[:4] == ("returns_refunds", "delivery_tracking", "size_fit", "receipts_invoices")


def test_every_class_has_boundary_examples_severity():
    for c in TOPIC_CLASSES:
        assert c.boundary.strip()
        assert c.name in LABEL2ID
        assert c.severity in ("strict", "standard", "flexible")


def test_label_id_roundtrip():
    for name, i in LABEL2ID.items():
        assert ID2LABEL[i] == name
    assert LABEL2ID["returns_refunds"] == 0 and LABEL2ID["other"] == 16


def test_terminology_table_covers_all():
    table = terminology_table()
    for name in TOPIC_NAMES:
        assert name in table
