from datetime import date

from mevzuat_git.model import Amendment, AmendmentOp, OpType, Path


def test_amendment_roundtrip():
    a = Amendment(
        amending_law="7524",
        article="1",
        rg_date=date(2024, 8, 2),
        rg_number="32620",
        effective_date=date(2024, 8, 2),
        target_law=193,
        ops=[
            AmendmentOp(
                op=OpType.REPLACE_PHRASE,
                target=Path(madde="23", fikra=1),
                old="X",
                new="Y",
                source_sentence='... "X" ibaresi "Y" şeklinde değiştirilmiştir.',
            )
        ],
    )
    assert Amendment.model_validate_json(a.model_dump_json()) == a
