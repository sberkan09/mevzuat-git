from mevzuat_git.cli import SummaryRow, render_summary


def test_summary_table():
    out = render_summary([
        SummaryRow(law=193, acts=78, sentences=304, parsed=302, ops=441, articles=109,
                   match=98, rate=98 / 109),
        SummaryRow(law=5520, error="FileNotFoundError: data/processed/5520_amendments.json"),
    ])
    assert "| 193 | 78 | 304 | 302 | 441 | 109 | 98 | 89.9% |" in out
    assert "| 5520 | hata: FileNotFoundError" in out
