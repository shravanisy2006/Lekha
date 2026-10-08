import pytest

from billing import calculate_totals, line_net, round_to_rupee


def test_matches_real_car_battery_bill():
    # Real bill: Rs 6,123.20 taxable -> CGST 551.09 + SGST 551.09, round off -0.38, payable Rs 7,225
    totals = calculate_totals([(612320, 18)], same_state=True)
    assert totals["cgst"] == 55109
    assert totals["sgst"] == 55109
    assert totals["igst"] == 0
    assert totals["round_off"] == -38
    assert totals["net_payable"] == 722500


def test_matches_real_eight_battery_bill():
    # Real bill: 8 x Rs 1,328.69 -> payable Rs 12,543
    totals = calculate_totals([(line_net(8, 132869, 0), 18)], same_state=True)
    assert totals["taxable_amount"] == 1062952
    assert totals["cgst"] == 95666
    assert totals["round_off"] == 16
    assert totals["net_payable"] == 1254300


def test_other_state_uses_igst():
    totals = calculate_totals([(612320, 18)], same_state=False)
    assert totals["cgst"] == 0
    assert totals["sgst"] == 0
    assert totals["igst"] == 110218


def test_discount_reduces_taxable_amount():
    assert line_net(quantity=1, base_price=612320, discount=50000) == 562320


@pytest.mark.parametrize(
    "amount, expected_total, expected_round_off",
    [
        (722538, 722500, -38),  # 37 paise or less rounds down
        (156785, 156800, 15),  # more than 50 paise rounds up
        (100050, 100100, 50),  # exactly 50 paise rounds up
        (100000, 100000, 0),  # already a whole rupee
    ],
)
def test_round_to_rupee(amount, expected_total, expected_round_off):
    assert round_to_rupee(amount) == (expected_total, expected_round_off)