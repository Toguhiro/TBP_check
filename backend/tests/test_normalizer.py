"""テキスト正規化のユニットテスト"""
import pytest
from app.services.text_normalizer import normalize_text, normalize_tag_no, extract_tag_nos


def test_normalize_fullwidth_to_halfwidth():
    assert normalize_text("ＴＥ－０Ｋ－１２１") == "TE-0K-121"


def test_normalize_newline_in_tag():
    assert normalize_text("88\nX") == "88X"


def test_normalize_spaces_in_tag():
    result = normalize_text("TE - 0K - 121")
    assert "TE-0K-121" in result


def test_normalize_tag_no():
    assert normalize_tag_no("TE－0K－121") == "TE-0K-121"
    assert normalize_tag_no("te-0k-121") == "TE-0K-121"
    assert normalize_tag_no("  88X  ") == "88X"


def test_extract_instrument_tags():
    text = "温度計TE-0K-121および圧力計PT-0K-201を確認する"
    tags = extract_tag_nos(text)
    tag_values = [t["tag"] for t in tags]
    assert "TE-0K-121" in tag_values
    assert "PT-0K-201" in tag_values


def test_extract_ansi_relay():
    text = "リレー88Xがトリップ、51-1が動作"
    tags = extract_tag_nos(text)
    tag_values = [t["tag"] for t in tags]
    assert any("88X" in v for v in tag_values)
