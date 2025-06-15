import sqlite3

DB_PATH = 'database/warehouse.db'

def create_tables():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # MATERIAL table
    c.execute('''
        CREATE TABLE IF NOT EXISTS MATERIAL (
            material_id INTEGER PRIMARY KEY,
            product_code TEXT,
            material_name TEXT,
            part_code TEXT,
            group_name TEXT,
            classification TEXT,
            specification TEXT,
            brand_name TEXT,
            unit TEXT,
            supplier_name TEXT,
            location TEXT,
            status TEXT,
            created_at DATETIME,
            updated_at DATETIME
        )
    ''')

    # MONTHLY_INVENTORY table
    c.execute('''
        CREATE TABLE IF NOT EXISTS MONTHLY_INVENTORY (
            inventory_id INTEGER PRIMARY KEY,
            material_id INTEGER,
            year INTEGER,
            month INTEGER,
            opening_stock REAL,
            input_quantity REAL,
            output_quantity REAL,
            closing_stock REAL,
            physical_inventory REAL,
            created_at DATETIME,
            updated_at DATETIME,
            FOREIGN KEY(material_id) REFERENCES MATERIAL(material_id)
        )
    ''')

    # STOCK_TRANSACTION table
    c.execute('''
        CREATE TABLE IF NOT EXISTS STOCK_TRANSACTION (
            transaction_id INTEGER PRIMARY KEY,
            material_id INTEGER,
            transaction_type TEXT,
            quantity REAL,
            transaction_date DATE,
            reference_number TEXT,
            notes TEXT,
            created_at DATETIME,
            FOREIGN KEY(material_id) REFERENCES MATERIAL(material_id)
        )
    ''')

    conn.commit()
    conn.close()

if __name__ == '__main__':
    create_tables()
    print('Database and tables created successfully!')
