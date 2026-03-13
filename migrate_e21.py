"""Run once: creates new tables from models (yield_history, users, nfe_pending, etc.)"""
import sys
sys.path.insert(0, ".")
from database import engine
from models import Base

Base.metadata.create_all(bind=engine)
print("Migration complete — all tables created/updated.")
