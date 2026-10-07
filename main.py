from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, select

from database import create_tables, get_session
from models import Party, PartyCreate, Product, ProductCreate


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