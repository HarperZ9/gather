"""Every citation is checked by string comparison; nothing unverifiable is hidden."""
import pytest

from gather.citecheck import MIN_QUOTE_WORDS, check_report, normalize, sentences

EXCERPTS = ["Every run writes a receipt you can re-check. The core runs with zero third-party dependencies.",
            "Gather stops at the first bot check and never answers it."]


def statuses(report, excerpts=EXCERPTS):
    return [c["status"] for c in check_report(report, excerpts)["citations"]]


def test_an_exact_quote_from_the_cited_excerpt_is_verified():
    assert statuses('It records "every run writes a receipt" [1].') == ["verified"]


def test_normalisation_covers_curly_quotes_dashes_space_and_case():
    report = "It says \u201cEvery  run writes a\u00a0RECEIPT\u201d [1]."
    assert statuses(report) == ["verified"]
    assert normalize("A\u2014b  \u2019c\u2019") == "a-b 'c'"


def test_a_quote_from_the_wrong_excerpt_is_not_in_source():
    assert statuses('Gather "stops at the first bot check" [1].') == ["not-in-source"]


def test_a_number_with_no_excerpt_is_unknown_source():
    assert statuses('Gather "stops at the first bot check" [3].') == ["unknown-source"]


def test_a_short_quote_is_not_counted_as_verified():
    assert statuses('It keeps "a receipt" [1].') == ["too-short"]
    words = " ".join(EXCERPTS[0].split()[:MIN_QUOTE_WORDS])
    assert statuses(f'It says "{words}" [1].') == ["verified"]


def test_a_bare_number_is_unchecked_and_an_uncited_sentence_is_listed():
    check = check_report("Gather is fast [1]. It is also popular.", EXCERPTS)
    assert [c["status"] for c in check["citations"]] == ["unchecked"]
    assert check["uncited_sentences"] == ["It is also popular."]


def test_precision_counts_every_citation_in_the_denominator():
    report = ('A "every run writes a receipt" [1]. B "stops at the first bot check" [2]. '
              'C "never said anywhere in these" [2]. D [1].')
    check = check_report(report, EXCERPTS)
    assert check["total"] == 4 and check["counts"]["verified"] == 2 and check["precision"] == 0.5


def test_no_citations_means_no_precision():
    assert check_report("Nothing cited here.", EXCERPTS)["precision"] is None


def test_a_sentence_end_inside_a_quote_does_not_split_the_citation():
    report = 'It says "re-check. The core runs with zero" [1].'
    assert sentences(report) == [report]
    assert statuses(report) == ["verified"]


def test_headings_and_list_markers_are_handled():
    report = '# Answer\n- It says "every run writes a receipt" [1].\n2. 2026 matters.'
    assert sentences(report) == ['It says "every run writes a receipt" [1].', "2026 matters."]


@pytest.mark.parametrize("edge", ['"every run writes a receipt." [1]', '"every run writes a receipt," [1]'])
def test_trailing_punctuation_inside_the_quote_is_ignored(edge):
    assert statuses(f"It says {edge}.") == ["verified"]


def test_zero_is_not_an_excerpt_number():
    assert statuses('Gather "stops at the first bot check" [0].') == ["unknown-source"]
