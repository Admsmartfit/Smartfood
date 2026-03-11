"""
E-02 — Seed: Ingredientes com FC/FCoc médios conforme PRD SmartFood
Valores padrão do PRD:
  frango=1.38/0.72, boi=1.45/0.68, bacalhau=1.52/0.74, porco=1.30/0.75, massa=1.05/0.90
"""
from database import SessionLocal
from models import Ingredient


INGREDIENTES_PADRAO = [
    {
        "nome": "Frango (inteiro c/ osso)",
        "unidade": "kg",
        "fc_medio": 1.38,  # 38% perda em osso/pele
        "custo_atual": 12.50,
        "estoque_minimo": 10.0,
        "lead_time_dias": 2,
    },
    {
        "nome": "Carne Bovina (dianteiro)",
        "unidade": "kg",
        "fc_medio": 1.45,  # 45% perda
        "custo_atual": 28.00,
        "estoque_minimo": 5.0,
        "lead_time_dias": 2,
    },
    {
        "nome": "Bacalhau (seco e salgado)",
        "unidade": "kg",
        "fc_medio": 1.52,  # 52% perda em hidratação/desossamento
        "custo_atual": 45.00,
        "estoque_minimo": 3.0,
        "lead_time_dias": 5,
    },
    {
        "nome": "Carne Suína",
        "unidade": "kg",
        "fc_medio": 1.30,  # 30% perda
        "custo_atual": 18.00,
        "estoque_minimo": 5.0,
        "lead_time_dias": 2,
    },
    {
        "nome": "Massa (farinha de trigo)",
        "unidade": "kg",
        "fc_medio": 1.05,  # 5% perda
        "custo_atual": 4.50,
        "estoque_minimo": 20.0,
        "lead_time_dias": 1,
    },
]

# FCoc médios por ingrediente (para referência nas fichas técnicas)
# O FCoc fica no produto (Product.fcoc), mas registramos aqui como referência
FCOC_REFERENCIA = {
    "Frango": 0.72,     # 28% perda de água no cozimento
    "Boi":    0.68,     # 32% perda
    "Bacalhau": 0.74,   # 26% perda
    "Porco":  0.75,     # 25% perda
    "Massa":  0.90,     # 10% perda
}


def run_seed():
    db = SessionLocal()
    try:
        inserted = 0
        skipped = 0
        for data in INGREDIENTES_PADRAO:
            exists = db.query(Ingredient).filter(Ingredient.nome == data["nome"]).first()
            if exists:
                skipped += 1
                continue
            ingredient = Ingredient(**data)
            db.add(ingredient)
            inserted += 1

        db.commit()
        print(f"Seed E-02 concluído: {inserted} ingrediente(s) inserido(s), {skipped} já existente(s).")
        print("\nFCoc médios de referência por proteína:")
        for proteina, fcoc in FCOC_REFERENCIA.items():
            print(f"  {proteina}: {fcoc} (perda de {(1 - fcoc) * 100:.0f}% no cozimento)")
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()
