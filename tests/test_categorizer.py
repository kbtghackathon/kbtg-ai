import pytest

from src.categorizer.categorization_module import CategorizationModule


@pytest.fixture
def categorizer():
    return CategorizationModule()


@pytest.mark.parametrize("name", ["MEAL BOX", "PEANUT SHOP", "RAISE CAFE", "RESTAURANT", "PAYMENT"])
def test_short_ascii_keywords_do_not_match_inside_other_words(categorizer, name):
    assert categorizer._match_merchant(name) is None


def test_ascii_keyword_matches_on_word_boundary(categorizer):
    category, _, confidence = categorizer._match_merchant("PAYMENT TO NETFLIX.COM")
    assert category == "subscription"
    assert confidence < 1.0


def test_exact_match_has_full_confidence(categorizer):
    assert categorizer._match_merchant("NETFLIX")[2] == 1.0


def test_longer_keyword_wins_over_shorter_prefix(categorizer):
    # "TRUEMONEY" must not be claimed by the higher-priority "TRUE" entry
    category, label, _ = categorizer._match_merchant("TRUEMONEY WALLET")
    assert category != "mobile"
    assert "TrueMoney" in label

    category, _, _ = categorizer._match_merchant("TRUE ONLINE FIBER")
    assert category == "internet"


def test_thai_keyword_still_matches_as_substring(categorizer):
    category, _, _ = categorizer._match_merchant("การไฟฟ้านครหลวง")
    assert category == "utility"


def test_thai_keyword_matches_nikhahit_spelling(categorizer):
    # dictionary keywords and merchant names are both folded to sara am
    assert categorizer._match_merchant("การไฟฟ้า") is not None


def test_health_style_cache_inspection_still_works(categorizer):
    assert CategorizationModule._merchant_dict_cache
    assert len(CategorizationModule._merchant_dict_cache) > 0
