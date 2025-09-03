from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, Text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()

class Booking(Base):
    __tablename__ = "bookings"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(64), index=True)     # to map pending booking to user session
    guest_name = Column(String(200), nullable=True)
    checkin = Column(DateTime, nullable=True)
    checkout = Column(DateTime, nullable=True)
    nights = Column(Integer, nullable=True)
    guests = Column(Integer, nullable=True)
    breakfast = Column(String(50), nullable=True)   # e.g., "Yes", "No", "Continental"
    payment_method = Column(String(100), nullable=True)
    confirmed = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db(db_path="sqlite:///instance/bookings.db"):
    engine = create_engine(db_path, echo=False, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
