from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base() 

DATABASE_URL = "postgresql://postgres:1234@localhost:5432/company_tables"

engine = create_engine(DATABASE_URL)


class login_info(Base):

    __tablename__ = "login_info"

    user_id = Column(String, primary_key=True)
    password = Column(String, nullable=False)


class availability(Base):

    __tablename__ = "availability"

    S_No = Column(Integer, autoincrement=True, nullable=False) 
    location = Column(String, nullable=False)
    D365_Project = Column(String, nullable=False)
    Project_name_unit_number = Column(String, primary_key = True)
    wings = Column(String, nullable=True)
    Unit_number = Column(String, nullable=True)
    SBA_In_Sq_ft = Column(Float, nullable=True)
    Value_In_Mn = Column(Float, nullable=False)
    Status = Column(String, nullable=False)
    Types = Column(String, nullable=True)
    Unit_type = Column(String, nullable=True)
    Unit_category = Column(String, nullable=True)
    SBA_in_Range = Column(String, nullable=True)
    


Base.metadata.create_all(engine)

SessionLocal = sessionmaker(autocommit = False, autoflush = False, bind = engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close() 



