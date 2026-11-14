"""Entity rules and the language rule for ``gather saves``: each type with cases that must match
and cases that must not."""

from gather.saves_entities import extract_entities
from gather.saves_lang import detect_language, sidecar_language


def found(text, kind):
    return [(r["value"], r["normalized"], r["count"]) for r in extract_entities(text) if r["type"] == kind]


def test_url_lowercases_scheme_and_host_and_drops_trailing_punctuation():
    text = "See HTTPS://Example.COM/Path?q=A. Again https://example.com/Path?q=A, and ftp://example.com/x."
    assert found(text, "url") == [("HTTPS://Example.COM/Path?q=A", "https://example.com/Path?q=A", 2)]
    assert found("www.example.com and example.com/page", "url") == []


def test_doi_is_found_bare_and_inside_a_doi_link():
    text = "doi:10.1000/XYZ.12; also https://doi.org/10.5555/abc-1."
    assert found(text, "doi") == [("10.1000/XYZ.12", "10.1000/xyz.12", 1), ("10.5555/abc-1", "10.5555/abc-1", 1)]
    assert found("version 10.12/3 and 110.1000/x and 10.1/abc", "doi") == []


def test_arxiv_needs_the_prefix_or_an_arxiv_link():
    text = "arXiv:2301.12345v2, https://arxiv.org/abs/1706.03762 and arXiv:hep-th/9901001."
    assert [v for v, _, _ in found(text, "arxiv")] == ["1706.03762", "2301.12345v2", "hep-th/9901001"]
    assert found("a bare 1234.5678 and 2301.12345 and hep-th/9901001", "arxiv") == []


def test_handle_matches_names_and_never_an_email_address():
    text = "Thanks @Ana_1 and @ana_1, see u/bob-2 in r/Python."
    assert found(text, "handle") == [("@Ana_1", "@ana_1", 2), ("r/Python", "r/python", 1), ("u/bob-2", "u/bob-2", 1)]
    assert found("write to ana@example.com or https://example.com/@ana and/or https://reddit.com/r/python", "handle") == []


def test_hashtag_needs_a_letter_and_is_not_read_from_an_address():
    assert found("#Money and #money and #web3", "hashtag") == [("#Money", "#money", 2), ("#web3", "#web3", 1)]
    assert found("issue #42, a&#38;b, and https://example.com/page#section", "hashtag") == []


def test_date_normalizes_three_forms_and_rejects_impossible_dates():
    text = "On 2026-11-14, 5 March 2024, March 5th, 2024 and Sept. 3, 2021."
    assert found(text, "date") == [("2026-11-14", "2026-11-14", 1), ("5 March 2024", "2024-03-05", 2),
                                   ("Sept. 3, 2021", "2021-09-03", 1)]
    assert found("2026-02-30, 2026-13-01, 31 April 2026, 12026-01-01 and 5 Marches 2024", "date") == []


def test_quantity_reads_percent_currency_units_and_multiplier_words():
    text = "$1,200.50 or USD 40, 60 EUR, 5€, up 45% (12 percent), 5 km at 30fps, 20°C, 3.5 million views, $2 billion."
    assert [n for _, n, _ in found(text, "quantity")] == [
        "1200.50 $", "2 billion $", "12 percent", "20 °C", "3.5 million", "30 fps", "45 %", "5 km", "5 €",
        "60 EUR", "40 USD"]
    assert found("7 apples in 2026, v1.2 m, $5K, 3 seconds, 10 minutes and room 404", "quantity") == []


def test_language_rule_names_clear_cases_and_leaves_the_rest_undetermined():
    assert detect_language("The report is clear and it was not what they would have wanted") == "en"
    assert detect_language("El informe es muy claro pero los datos no son para todos") == "es"
    assert detect_language("これは日本語の文章です。漢字も使います。") == "ja"
    assert detect_language("Это было очень хорошо, мы ещё вернёмся") == "ru"
    assert detect_language("Це дуже цікаво, її їжа є тут") == "uk"
    assert detect_language("中文文本测试") == "zh"
    assert detect_language("안녕하세요 반갑습니다") == "ko"
    for unclear in ("", "ok lol 123", "https://example.com/the/and/of @the #and", "Привет", "the gato es grande"):
        assert detect_language(unclear) == "und"


def test_sidecar_language_accepts_only_a_well_formed_tag():
    assert [sidecar_language(v) for v in ("es-MX", "EN", "zh-Hant-TW", "english!", "", None, 7)] == [
        "es", "en", "zh", "", "", "", ""]
