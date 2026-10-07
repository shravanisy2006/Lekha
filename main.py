from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, select

from billing import SHOP_STATE_CODE, calculate_totals, line_net
from database import create_tables, get_session
from models import (
    Invoice,
    InvoiceCreate,
    InvoiceLine,
    InvoiceRead,
    InvoiceStatus,
    Party,
    PartyCreate,
    Product,
    ProductCreate,
    Serial,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Lekha", lifespan=lifespan)


@app.post("/parties", response_model=Party, status_code=201)
def add_party(data: PartyCreate, session: Session = Depends(get_session)):
    party = Party.model_validate(data)
    session.add(party)
    session.commit()
    session.refresh(party)
    return party


@app.get("/parties", response_model=list[Party])
def list_parties(session: Session = Depends(get_session)):
    return session.exec(select(Party)).all()


@app.get("/parties/{party_id}", response_model=Party)
def get_party(party_id: int, session: Session = Depends(get_session)):
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")
    return party

@app.post("/products", response_model=Product, status_code=201)
def add_product(data: ProductCreate, session: Session = Depends(get_session)):
    product = Product.model_validate(data)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@app.get("/products", response_model=list[Product])
def list_products(session: Session = Depends(get_session)):
    return session.exec(select(Product)).all()

def find_sold_serials(serials: list[str], session: Session) -> list[str]:
    statement = (
        select(Serial.serial_number)
        .join(InvoiceLine, Serial.line_id == InvoiceLine.id)
        .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
        .where(Serial.serial_number.in_(serials))
        .where(Invoice.status == InvoiceStatus.active)
    )
    return list(session.exec(statement).all())

@app.post("/invoices", response_model=InvoiceRead, status_code=201)
def create_invoice(data: InvoiceCreate, session: Session = Depends(get_session)):
    party = session.get(Party, data.party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")

    all_serials = [s for item in data.lines for s in item.serials]
    if len(all_serials) != len(set(all_serials)):
        raise HTTPException(status_code=422, detail="The same serial number is entered twice")
    already_sold = find_sold_serials(all_serials, session)
    if already_sold:
        raise HTTPException(status_code=409, detail=f"Already sold: {', '.join(already_sold)}")

    invoice = Invoice(
        party_id=party.id,
        invoice_date=data.invoice_date or date.today(),
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        vehicle_number=data.vehicle_number,
    )

    amounts = []
    for item in data.lines:
        product = session.get(Product, item.product_id)
        if product is None:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")
        if item.serials and len(item.serials) != item.quantity:
            raise HTTPException(status_code=422, detail="Number of serials must match the quantity")

        net = line_net(item.quantity, product.base_price, item.discount)
        if net < 0:
            raise HTTPException(status_code=422, detail="Discount is more than the line total")

        line = InvoiceLine(
            product_id=product.id,
            description=product.name,
            hsn_code=product.hsn_code,
            gst_percent=product.gst_percent,
            quantity=item.quantity,
            base_price=product.base_price,
            discount=item.discount,
            net_amount=net,
        )
        line.serials = [Serial(serial_number=s) for s in item.serials]
        invoice.lines.append(line)
        amounts.append((net, product.gst_percent))

    totals = calculate_totals(amounts, same_state=party.state_code == SHOP_STATE_CODE)
    invoice.taxable_amount = totals["taxable_amount"]
    invoice.cgst = totals["cgst"]
    invoice.sgst = totals["sgst"]
    invoice.igst = totals["igst"]
    invoice.round_off = totals["round_off"]
    invoice.net_payable = totals["net_payable"]

    session.add(invoice)
    session.flush()
    invoice.number = f"LK-{invoice.id:05d}"
    session.commit()
    session.refresh(invoice)
    return invoice

@app.get("/invoices", response_model=list[InvoiceRead])
def list_invoices(session: Session = Depends(get_session)):
    return session.exec(select(Invoice)).all()


@app.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@app.post("/invoices/{invoice_id}/cancel", response_model=InvoiceRead)
def cancel_invoice(invoice_id: int, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.cancelled:
        raise HTTPException(status_code=409, detail="Invoice is already cancelled")
    invoice.status = InvoiceStatus.cancelled
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice