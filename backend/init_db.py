from database import engine, Base
import models

def init_db():
    print("Creating tables in ig_scrapp.db...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")

if __name__ == "__main__":
    init_db()
