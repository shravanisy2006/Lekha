from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select

from auth import (
    create_access_token,
    get_current_user,
    get_optional_user,
    hash_password,
    require_owner,
    verify_password,
)
from billing import SHOP_STATE_CODE, calculate_totals, line_net
from database import create_tables, get_session
from models import (
    Invoice,
    InvoiceCreate,
    InvoiceLine,
    InvoiceRead,
    InvoiceStatus,
    OutstandingRow,
    Party,
    PartyBalance,
    PartyCreate,
    Payment,
    PaymentCreate,
    PaymentRead,
    Product,
    ProductCreate,
    Role,
    Serial,
    Token,
    User,
    UserCreate,
    UserRead,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_tables()
    yield


app = FastAPI(title="Lekha", lifespan=lifespan)

# Every route on `api` needs a logged-in user. Routes on `app` (login, dashboard page) are open.
api = APIRouter(dependencies=[Depends(get_current_user)])
owner_only = [Depends(require_owner)]


# ---------- Login and users ----------

@app.post("/auth/register", response_model=UserRead, status_code=201)
def register(
    data: UserCreate,
    session: Session = Depends(get_session),
    current_user: User | None = Depends(get_optional_user),
):
    has_users = session.exec(select(User)).first() is not None
    if has_users and (current_user is None or current_user.role != Role.owner):
        raise HTTPException(status_code=403, detail="Only the owner can add users")
    if session.exec(select(User).where(User.username == data.username)).first():
        raise HTTPException(status_code=409, detail="That username is taken")

    user = User(
        username=data.username,
        hashed_password=hash_password(data.password),
        role=data.role if has_users else Role.owner,  # the very first user is the owner
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@app.post("/auth/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.username == form.username)).first()
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=401,
            detail="Wrong username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(access_token=create_access_token(user), token_type="bearer")


@app.get("/auth/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


# ---------- Parties ----------

@api.post("/parties", response_model=Party, status_code=201)
def add_party(data: PartyCreate, session: Session = Depends(get_session)):
    party = Party.model_validate(data)
    session.add(party)
    session.commit()
    session.refresh(party)
    return party


@api.get("/parties", response_model=list[Party])
def list_parties(session: Session = Depends(get_session)):
    return session.exec(select(Party)).all()


@api.get("/parties/{party_id}", response_model=Party)
def get_party(party_id: int, session: Session = Depends(get_session)):
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")
    return party


# ---------- Products ----------

@api.post("/products", response_model=Product, status_code=201, dependencies=owner_only)
def add_product(data: ProductCreate, session: Session = Depends(get_session)):
    product = Product.model_validate(data)
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@api.get("/products", response_model=list[Product])
def list_products(session: Session = Depends(get_session)):
    return session.exec(select(Product)).all()


# ---------- Invoices ----------

def find_sold_serials(serials: list[str], session: Session) -> list[str]:
    statement = (
        select(Serial.serial_number)
        .join(InvoiceLine, Serial.line_id == InvoiceLine.id)
        .join(Invoice, InvoiceLine.invoice_id == Invoice.id)
        .where(Serial.serial_number.in_(serials))
        .where(Invoice.status == InvoiceStatus.active)
    )
    return list(session.exec(statement).all())


@api.post("/invoices", response_model=InvoiceRead, status_code=201)
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

    if data.pay_now:
        invoice.payments.append(
            Payment(amount=invoice.net_payable, mode=data.pay_now, payment_date=invoice.invoice_date)
        )

    session.add(invoice)
    session.flush()
    invoice.number = f"LK-{invoice.id:05d}"
    session.commit()
    session.refresh(invoice)
    return invoice


@api.get("/invoices", response_model=list[InvoiceRead])
def list_invoices(session: Session = Depends(get_session)):
    return session.exec(select(Invoice)).all()


@api.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


@api.post("/invoices/{invoice_id}/cancel", response_model=InvoiceRead, dependencies=owner_only)
def cancel_invoice(invoice_id: int, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.cancelled:
        raise HTTPException(status_code=409, detail="Invoice is already cancelled")
    if invoice.payments:
        raise HTTPException(status_code=409, detail="Invoice has payments, so it cannot be cancelled")
    invoice.status = InvoiceStatus.cancelled
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


# ---------- Payments and balances ----------

@api.post("/invoices/{invoice_id}/payments", response_model=InvoiceRead, status_code=201)
def add_payment(invoice_id: int, data: PaymentCreate, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status == InvoiceStatus.cancelled:
        raise HTTPException(status_code=409, detail="A cancelled invoice cannot be paid")
    if data.amount > invoice.balance_due:
        raise HTTPException(
            status_code=422,
            detail=f"Payment is more than the balance due ({invoice.balance_due} paise)",
        )

    payment = Payment(
        amount=data.amount,
        mode=data.mode,
        payment_date=data.payment_date or date.today(),
        note=data.note,
    )
    invoice.payments.append(payment)
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


@api.get("/invoices/{invoice_id}/payments", response_model=list[PaymentRead])
def list_payments(invoice_id: int, session: Session = Depends(get_session)):
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice.payments


@api.get("/parties/{party_id}/balance", response_model=PartyBalance)
def party_balance(party_id: int, session: Session = Depends(get_session)):
    party = session.get(Party, party_id)
    if party is None:
        raise HTTPException(status_code=404, detail="Party not found")

    statement = (
        select(Invoice)
        .where(Invoice.party_id == party_id)
        .where(Invoice.status == InvoiceStatus.active)
    )
    invoices = session.exec(statement).all()

    return PartyBalance(
        party_id=party.id,
        name=party.name,
        total_billed=sum(invoice.net_payable for invoice in invoices),
        total_paid=sum(invoice.paid_amount for invoice in invoices),
        balance_due=sum(invoice.balance_due for invoice in invoices),
        unpaid_invoices=sum(1 for invoice in invoices if invoice.balance_due > 0),
    )


# ---------- Dashboard ----------

@api.get("/outstanding", response_model=list[OutstandingRow], dependencies=owner_only)
def outstanding(session: Session = Depends(get_session)):
    statement = select(Invoice).where(Invoice.status == InvoiceStatus.active)
    rows: dict[int, OutstandingRow] = {}

    for invoice in session.exec(statement).all():
        if invoice.balance_due == 0:
            continue
        row = rows.get(invoice.party_id)
        if row is None:
            party = session.get(Party, invoice.party_id)
            row = OutstandingRow(
                party_id=party.id,
                name=party.name,
                balance_due=0,
                unpaid_invoices=0,
                oldest_unpaid_days=0,
            )
            rows[invoice.party_id] = row

        days_old = (date.today() - invoice.invoice_date).days
        row.balance_due += invoice.balance_due
        row.unpaid_invoices += 1
        row.oldest_unpaid_days = max(row.oldest_unpaid_days, days_old)

    return sorted(rows.values(), key=lambda row: row.balance_due, reverse=True)


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html")


# Must come last: attaches every route defined on `api` above.
app.include_router(api)