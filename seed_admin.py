import uuid
from database import SessionLocal
from models import User

def seed_admin():
    db = SessionLocal()
    try:
        # Check if any user exists
        existing_user = db.query(User).filter(User.email == "admin@smartfood.com").first()
        if existing_user:
            print(f"User {existing_user.email} already exists. ID: {existing_user.id}")
            if not existing_user.ativo:
                existing_user.ativo = True
                db.commit()
                print("User reactivated.")
            return

        admin = User(
            id=uuid.uuid4(),
            nome="Administrador",
            email="admin@smartfood.com",
            perfil="admin",
            pin_code="1234",
            ativo=True
        )
        db.add(admin)
        db.commit()
        print(f"Admin user created: admin@smartfood.com / PIN: 1234")
    except Exception as e:
        print(f"Error seeding admin: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_admin()
