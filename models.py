from datetime import date
from enum import Enum


from sqlmodel import Field, Relationship, SQLModel

# All money is stored in paise (1 rupee = 100 paise) as whole numbers.
# Example: Rs 1,328.69 is stored as 132869.
# Whole numbers never have the tiny rounding errors that decimals (floats) have.


# ---------- Parties (customers and suppliers) ----------

class PartyKind(str, Enum):
    customer = "customer"
    supplier = "supplier"


class PartyCreate(SQLModel):
    name: str = Field(min_length=1)
    kind: PartyKind
    phone: str | None = None
    address: str | None = None
    pin: str | None = None
    state_code: str = "27"  # 27 = Maharashtra
    gstin: str | None = None
    dealer_code: str | None = None


class Party(PartyCreate, table=True):
    id: int | None = Field(default=None, primary_key=True)


# ---------- Products ----------

class ProductCreate(SQLModel):
    name: str = Field(min_length=1)
    hsn_code: str
    gst_percent: int = Field(ge=0, le=28)
    base_price: int = Field(gt=0)  # paise, before tax


class Product(ProductCreate, table=True):
    id: int | None = Field(default=None, primary_key=True)


# ---------- Invoices: what the user sends ----------

class LineCreate(SQLModel):
    product_id: int
    quantity: int = Field(gt=0)
    discount: int = Field(default=0, ge=0)  # paise, e.g. for an old battery handed over
    serials: list[str] = []


class InvoiceCreate(SQLModel):
    party_id: int
    invoice_date: date | None = None  # today if left empty
    customer_name: str | None = None  # for walk-in customers
    customer_phone: str | None = None
    vehicle_number: str | None = None
    lines: list[LineCreate] = Field(min_length=1)


# ---------- Invoices: the database tables ----------

class InvoiceStatus(str, Enum):
    active = "active"
    cancelled = "cancelled"


class Invoice(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    number: str | None = Field(default=None, index=True, unique=True)
    invoice_date: date
    party_id: int = Field(foreign_key="party.id")
    customer_name: str | None = None
    customer_phone: str | None = None
    vehicle_number: str | None = None
    status: InvoiceStatus = InvoiceStatus.active
    taxable_amount: int = 0
    cgst: int = 0
    sgst: int = 0
    igst: int = 0
    round_off: int = 0
    net_payable: int = 0

    lines: list["InvoiceLine"] = Relationship(back_populates="invoice")


class InvoiceLine(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    invoice_id: int | None = Field(default=None, foreign_key="invoice.id")
    product_id: int = Field(foreign_key="product.id")
    # The product details are copied onto the line, so an old bill
    # does not change when the product's price changes later.
    description: str
    hsn_code: str
    gst_percent: int
    quantity: int
    base_price: int
    discount: int = 0
    net_amount: int

    invoice: Invoice | None = Relationship(back_populates="lines")
    serials: list["Serial"] = Relationship(back_populates="line")


class Serial(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    line_id: int | None = Field(default=None, foreign_key="invoiceline.id")
    serial_number: str = Field(index=True)

    line: InvoiceLine | None = Relationship(back_populates="serials")


# ---------- Invoices: what the API sends back ----------

class SerialRead(SQLModel):
    serial_number: str


class LineRead(SQLModel):
    id: int
    product_id: int
    description: str
    hsn_code: str
    gst_percent: int
    quantity: int
    base_price: int
    discount: int
    net_amount: int
    serials: list[SerialRead]


class InvoiceRead(SQLModel):
    id: int
    number: str
    invoice_date: date
    party_id: int
    customer_name: str | None
    customer_phone: str | None
    vehicle_number: str | None
    status: InvoiceStatus
    taxable_amount: int
    cgst: int
    sgst: int
    igst: int
    round_off: int
    net_payable: int
    lines: list[LineRead]

