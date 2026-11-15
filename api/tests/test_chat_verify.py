import pytest

from senda_api.chat.verify import unverified

RESULT = {"count": 156002, "ratio": 2.74, "median": 9000, "expected_error": 0.163, "ratio_to_average": 1.55,
          "area_km2": 89089, "rank": 3, "of": 24, "frp": 5.51}


def bad(text, user=()):
    return unverified(text, [RESULT], list(user))


@pytest.mark.parametrize("text", [
    "There were 156,002 detections.",
    "About 156,000 detections.",
    "About 156 thousand detections.",
    "About 156k detections.",
    "Nearly 0.16 million detections.",
    "It was 2.74 times the normal.",
    "It was 2.7 times the normal.",
    "That is 274% of the normal.",
    "That is 174% above the normal.",
    "The count is 55% higher than the average year.",
    "Typical error is 16%.",
    "Error 0.163.",
    "The median is 9,000 detections.",
    "9 000 detections",
    "It was 3 times the normal.",  # 2.74 rounds honestly to 3
    "Area of 89,089 km2.",
    "Ranked 3 of 24 for the month.",
    "In 2019 in the year 2003 and 2100.",
    "Between 3 and 12 areas.",
    "From 2019-01 to 2019-12, on 2026-11-12.",
    "Link [156,002](https://x.org/99999) is fine.",
    "FRP 5.51 MW.",
])
def test_allowed(text):
    assert bad(text) == []


@pytest.mark.parametrize("text", [
    "There were 157,000 detections.",      # truncation or wrong rounding
    "There were 156,003 detections.",
    "It was 2.8 times the normal.",
    "That is 85% of the normal.",
    "About 150 thousand detections.",
    "A total of 12 detections.",           # small number with a data unit is checked
    "Ranked 3 of 24, 1,234 more.",
    "Error 0.3.",
    "9.5 times usual.",
    "9,500 detections.",
])
def test_rejected(text):
    assert bad(text), text


def test_times_needs_a_ratio_field():
    assert bad("It was 9000 times.") != []
    assert bad("It was 6.4 times.") != []


def test_percent_of_ratio_only_for_ratio_fields():
    assert bad("That is 8800% more.") != []


def test_negative_value_is_matched_by_its_size():
    result = {"gap_pct": -2.94, "lon": -60.52}
    assert unverified("The gap is −2,94 %, at 60.52° W.", [result], []) == []
    assert unverified("The gap is 3,94 %.", [result], []) != []


def test_numbers_of_the_question_count():
    assert bad("You said 4,321 detections.", ["Were there 4321 detections?"]) == []
    assert bad("You said 4,322 detections.", ["Were there 4321 detections?"]) != []


def test_numbers_inside_tool_lists():
    series = {"series": [{"month": "2019-09", "count": 40100, "ratio": 2.74}]}
    assert unverified("September had 40,100 detections, 2.7 times usual.", [series], []) == []
    assert unverified("September had 40,101 detections.", [series], []) != []


def test_decimal_comma():
    assert bad("Error 0,16.") == []
    assert bad("Error 0,17.") != []


def test_empty_and_no_numbers():
    assert bad("") == [] and bad("Nothing to count here.") == []


@pytest.mark.parametrize("text", [
    "Было 156 002 очага.",  # a no-break space
    "Было 156 002 очага.",  # a narrow no-break space
    "Это в 2,74 раза больше нормы.",
    "Отношение к норме 0,16.",
    "Площадь 89 089 км².",
    "Данные до 11 ноября 2026 года, пик 3 из 24.",
    "El 11 de noviembre de 2026 hubo 156 002 detecciones, 2,7 veces lo normal.",
    "Le 11 novembre 2026: 156 002 détections.",
    "Медиана 9 000 очагов.",
])
def test_numbers_written_the_way_of_other_languages(text):
    assert bad(text) == [], text


@pytest.mark.parametrize("text", [
    "Было 3 964 очага.",
    "Было 156 003 очага.",
    "Это в 2,9 раза больше нормы.",
    "Отношение к норме 0,25.",
])
def test_wrong_numbers_in_other_formats_are_still_caught(text):
    assert bad(text) != [], text


def test_grouped_number_with_a_decimal_comma():
    assert unverified("Было 1 234,5 мм.", [{"v": 1234.5}], []) == []
    assert unverified("Было 1 234,6 мм.", [{"v": 1234.5}], []) != []


def test_a_space_between_thousands():
    assert unverified("В ноябре 2026 года было 3 963 очага.", [{"count": 3963}], []) == []
    assert unverified("В ноябре 2026 года было 3 964 очага.", [{"count": 3963}], []) != []
