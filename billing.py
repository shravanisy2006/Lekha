SHOP_STATE_CODE = "27"


def line_net(quantity: int, base_price: int, discount: int) -> int:
    return quantity * base_price - discount


def split_tax(taxable: int, gst_percent: int, same_state: bool) -> tuple[int, int, int]:
    if same_state:
        half = (taxable * gst_percent + 100) // 200
        return half, half, 0
    igst = (taxable * gst_percent + 50) // 100
    return 0, 0, igst


def round_to_rupee(amount: int) -> tuple[int, int]:
    rounded = (amount + 50) // 100 * 100
    return rounded, rounded - amount


def calculate_totals(lines: list[tuple[int, int]], same_state: bool) -> dict:
    taxable_by_rate: dict[int, int] = {}
    for net, gst_percent in lines:
        taxable_by_rate[gst_percent] = taxable_by_rate.get(gst_percent, 0) + net

    taxable = cgst = sgst = igst = 0
    for gst_percent, amount in taxable_by_rate.items():
        c, s, i = split_tax(amount, gst_percent, same_state)
        taxable += amount
        cgst += c
        sgst += s
        igst += i

    net_payable, round_off = round_to_rupee(taxable + cgst + sgst + igst)
    return {
        "taxable_amount": taxable,
        "cgst": cgst,
        "sgst": sgst,
        "igst": igst,
        "round_off": round_off,
        "net_payable": net_payable,
    }