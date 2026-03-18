import uuid
from database import SessionLocal
from models import User

def check_users():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        print(f"Total users: {len(users)}")
        for user in users:
            print(f"ID: {user.id}, Nome: {user.nome}, Email: {user.email}, Ativo: {user.ativo}, Perfil: {user.perfil}")
    finally:
        db.close()

if __name__ == "__main__":
    check_users()
