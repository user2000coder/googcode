from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, send_file, session
import os
from datetime import datetime
import pandas as pd
import qrcode
from docx import Document
from docx.shared import Inches
import io
import uuid
import tempfile
import openpyxl
import sqlite3
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash
from functools import wraps

app = Flask(__name__)
# Sử dụng biến môi trường cho secret key để tăng bảo mật
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

@app.template_filter('format_datetime')
def format_datetime(value, format='%d/%m/%Y %H:%M'):
    if not value:
        return ''
    try:
        dt = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        return dt.strftime(format)
    except Exception:
        return value

# Decorator để yêu cầu đăng nhập
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Decorator để kiểm tra quyền truy cập
def role_required(allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] not in allowed_roles:
                flash('Bạn không có quyền truy cập chức năng này')
                return redirect(url_for('home'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

DATABASE_PATH = 'database/warehouse.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM USERS WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['role'] = user['role']
            return redirect(url_for('home'))
        
        return render_template('login.html', error='Sai tên đăng nhập hoặc mật khẩu')
    
    return render_template('login.html')

# Logout route
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM MATERIAL').fetchall()
    total_materials = len(products)
    low_stock_count = sum(1 for row in products if int(row['quantity'] if 'quantity' in row.keys() else 0) < 50)
    today = datetime.now().strftime('%Y-%m-%d')
    # Tổng nhập hôm nay
    input_today = conn.execute("""
        SELECT COUNT(*) FROM STOCK_TRANSACTION st
        JOIN MATERIAL m ON st.material_id = m.material_id
        WHERE st.transaction_type = 'input' AND st.transaction_date LIKE ?
    """, (today+'%',)).fetchone()[0]
    # Tổng xuất hôm nay
    output_today = conn.execute("""
        SELECT COUNT(*) FROM STOCK_TRANSACTION st
        JOIN MATERIAL m ON st.material_id = m.material_id
        WHERE st.transaction_type = 'output' AND st.transaction_date LIKE ?
    """, (today+'%',)).fetchone()[0]
    # Hoạt động gần đây (5 giao dịch gần nhất)
    recent_activities = conn.execute("""
        SELECT st.*, m.material_name, m.part_code FROM STOCK_TRANSACTION st
        JOIN MATERIAL m ON st.material_id = m.material_id
        ORDER BY st.created_at DESC LIMIT 5
    """).fetchall()
    # Cảnh báo tồn kho (dưới 50)
    low_stock_alerts = [row for row in products if int(row['quantity'] if 'quantity' in row.keys() else 0) < 50][:5]
    conn.close()
    return render_template('home.html', 
        total_materials=total_materials, 
        low_stock_count=low_stock_count, 
        input_today=input_today, 
        output_today=output_today, 
        recent_activities=recent_activities, 
        low_stock_alerts=low_stock_alerts
    )

# Nhập kho route
@app.route('/nhap-kho')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def nhap_kho():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM MATERIAL').fetchall()
    # Lấy lịch sử nhập kho mới nhất từ STOCK_TRANSACTION, join MATERIAL để lấy thông tin vật tư và người nhập kho
    history = conn.execute('''
        SELECT st.*, m.group_name, m.product_code, m.classification, m.part_code, m.material_name, m.specification, m.brand_name, m.unit, m.location, m.imported_by
        FROM STOCK_TRANSACTION st
        JOIN MATERIAL m ON st.material_id = m.material_id
        WHERE st.transaction_type = 'input'
        ORDER BY st.created_at DESC, st.transaction_date DESC
        LIMIT 100
    ''').fetchall()
    conn.close()
    # Đảo lại thứ tự để bản ghi mới nhất lên đầu (nếu cần)
    history = list(history)
    return render_template('nhap_kho.html', products=products, history=history)


# Nhập kho POST route - xử lý form submit
@app.route('/nhap-kho', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def nhap_kho_post():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Không có dữ liệu'})
        # Validate required fields
        required_fields = ['group_use', 'product_code', 'classify', 'part_code', 'material_name', 'specification', 'brand', 'unit', 'location', 'quantity', 'imported_by']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'status': 'error', 'message': f'Thiếu trường bắt buộc: {field}'})

        conn = get_db_connection()
        cursor = conn.cursor()
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        quantity = float(data['quantity'])
        # Check if material exists by specification
        existing = cursor.execute('SELECT material_id, input, opening_stock, output FROM MATERIAL WHERE specification = ?', (data['specification'],)).fetchone()
        if existing:
            material_id = existing['material_id'] if isinstance(existing, sqlite3.Row) else existing[0]
            old_input = existing['input'] if isinstance(existing, sqlite3.Row) else existing[1]
            opening_stock = existing['opening_stock'] if isinstance(existing, sqlite3.Row) else existing[2]
            output = existing['output'] if isinstance(existing, sqlite3.Row) else existing[3]
            # Cộng dồn input
            new_input = (old_input or 0) + quantity
            # closing_stock tự động tính lại
            closing_stock = (opening_stock or 0) + new_input - (output or 0)
            cursor.execute('''
                UPDATE MATERIAL SET 
                    group_name = ?, product_code = ?, classification = ?, part_code = ?,
                    material_name = ?, brand_name = ?, unit = ?, location = ?,
                    input = ?, closing_stock = ?, imported_by = ?, updated_at = ?, last_update = ?, last_time = ?
                WHERE material_id = ?
            ''', (
                data['group_use'], data['product_code'], data['classify'], data['part_code'],
                data['material_name'], data['brand'], data['unit'], data['location'],
                new_input, closing_stock, data['imported_by'],
                current_time, current_time, current_time, material_id
            ))
        else:
            # Insert new material
            opening_stock = float(data.get('opening_stock', 0))
            output = float(data.get('output', 0))
            closing_stock = opening_stock + quantity - output
            cursor.execute('''
                INSERT INTO MATERIAL (
                    group_name, product_code, classification, part_code, material_name,
                    specification, brand_name, unit, location,
                    opening_stock, input, output, closing_stock, imported_by,
                    created_at, updated_at, last_update, last_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['group_use'], data['product_code'], data['classify'], data['part_code'],
                data['material_name'], data['specification'], data['brand'], data['unit'], data['location'],
                opening_stock, quantity, output, closing_stock, data['imported_by'],
                current_time, current_time, current_time, current_time
            ))
            material_id = cursor.lastrowid
        # Add stock transaction
        if quantity > 0:
            ref_number = f"INPUT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            cursor.execute('''
                INSERT INTO STOCK_TRANSACTION (
                    material_id, transaction_type, quantity, transaction_date,
                    reference_number, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                material_id, 'input', quantity, current_time,
                ref_number, f'Nhập kho bởi {data["imported_by"]}', current_time
            ))
        # Generate QR code
        try:
            import qrcode
            import os
            import re
            clean_spec = re.sub(r'[^\w\-_\.]', '_', data['specification'])
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(data['specification'])
            qr.make(fit=True)
            qr_img = qr.make_image(fill_color="black", back_color="white")
            qr_filename = f"{clean_spec}.png"
            qr_path = f"static/qr_codes/{qr_filename}"
            os.makedirs("static/qr_codes", exist_ok=True)
            qr_img.save(qr_path)
            qr_code_name = clean_spec
        except Exception as qr_error:
            print(f"QR generation error: {qr_error}")
            qr_code_name = None
        conn.commit()
        conn.close()
        return jsonify({
            'status': 'success',
            'message': 'Nhập kho thành công!',
            'qr_code': qr_code_name
        })
    except ValueError as ve:
        return jsonify({'status': 'error', 'message': f'Lỗi dữ liệu: {str(ve)}'})
    except Exception as e:
        print(f"Error in nhap_kho_post: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'message': f'Lỗi hệ thống: {str(e)}'})


# Xuất kho route
@app.route('/xuat-kho')
@login_required
@role_required(['admin', 'SEQPEKHO', 'SEQPELINE'])
def xuat_kho():
    conn = get_db_connection()
    products = conn.execute('SELECT * FROM MATERIAL').fetchall()
    conn.close()
    return render_template('xuat_kho.html', products=products)

# Các route khác chỉ cho admin
@app.route('/bao-cao')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def bao_cao():
    conn = get_db_connection()
    products = conn.execute('''
        SELECT * FROM MATERIAL WHERE material_id IN (
            SELECT MAX(material_id) FROM MATERIAL GROUP BY specification
        )    ''').fetchall()
    report = []
    for idx, row in enumerate(products, 1):
        material_id = row['material_id']
        specification = row['specification']
        input_qty = conn.execute('''SELECT COALESCE(SUM(quantity),0) FROM STOCK_TRANSACTION WHERE material_id IN (SELECT material_id FROM MATERIAL WHERE specification=?) AND transaction_type="input"''', (specification,)).fetchone()[0]
        output_qty = conn.execute('''SELECT COALESCE(SUM(quantity),0) FROM STOCK_TRANSACTION WHERE material_id IN (SELECT material_id FROM MATERIAL WHERE specification=?) AND transaction_type="output"''', (specification,)).fetchone()[0]
        inventory_row = conn.execute('''SELECT quantity, created_at FROM STOCK_TRANSACTION WHERE material_id IN (SELECT material_id FROM MATERIAL WHERE specification=?) AND transaction_type="inventory" ORDER BY created_at DESC LIMIT 1''', (specification,)).fetchone()
        inventory_qty = inventory_row['quantity'] if inventory_row else ''
        inventory_time = inventory_row['created_at'] if inventory_row else ''
        opening_row = conn.execute('''SELECT quantity FROM STOCK_TRANSACTION WHERE material_id IN (SELECT material_id FROM MATERIAL WHERE specification=?) AND transaction_type="inventory" ORDER BY created_at ASC LIMIT 1''', (specification,)).fetchone()
        opening_stock = opening_row['quantity'] if opening_row else 0
        closing_stock = opening_stock + input_qty - output_qty
        
        report.append({
            'material_id': row['material_id'] if 'material_id' in row.keys() else '',
            'group_name': row['group_name'] if 'group_name' in row.keys() else '',
            'product_code': row['product_code'] if 'product_code' in row.keys() else '',
            'classification': row['classification'] if 'classification' in row.keys() else '',
            'part_code': row['part_code'] if 'part_code' in row.keys() else '',
            'material_name': row['material_name'] if 'material_name' in row.keys() else '',
            'specification': row['specification'] if 'specification' in row.keys() else '',
            'brand_name': row['brand_name'] if 'brand_name' in row.keys() else '',
            'unit': row['unit'] if 'unit' in row.keys() else '',            'opening_stock': row['opening_stock'] if 'opening_stock' in row.keys() else '',
            'input': row['input'] if 'input' in row.keys() else '',
            'output': row['output'] if 'output' in row.keys() else '',
            'closing_stock': row['closing_stock'] if 'closing_stock' in row.keys() else '',
            'inventory': row['inventory'] if 'inventory' in row.keys() else '',            'location': row['location'] if 'location' in row.keys() else '',
            'safety_stock': row['safety_stock'] if 'safety_stock' in row.keys() else '',
            'purchase_se': row['purchase_se'] if 'purchase_se' in row.keys() else '',
            'purchase_order': row['purchase_order'] if 'purchase_order' in row.keys() else '',
            'cost_opening_stock': row['cost_opening_stock'] if 'cost_opening_stock' in row.keys() else '',
            'cost_input': row['cost_input'] if 'cost_input' in row.keys() else '',
            'cost_output': row['cost_output'] if 'cost_output' in row.keys() else '',
            'cost_closing_stock': row['cost_closing_stock'] if 'cost_closing_stock' in row.keys() else '',
            'cost_safety_stock': row['cost_safety_stock'] if 'cost_safety_stock' in row.keys() else '',
            'price': row['price'] if 'price' in row.keys() else '',
            'currency': row['currency'] if 'currency' in row.keys() else '',
            'imported_by': row['imported_by'] if 'imported_by' in row.keys() else '',
            'created_at': row['created_at'] if 'created_at' in row.keys() else '',
            'updated_at': row['updated_at'] if 'updated_at' in row.keys() else '',
            'last_update': row['last_update'] if 'last_update' in row.keys() else '',
            'last_time': row['last_time'] if 'last_time' in row.keys() else ''
        })
    conn.close()
    return render_template('bao_cao.html', report=report)

# Route for updating report data
@app.route('/update-bao-cao', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def update_bao_cao():
    data = request.json
    conn = get_db_connection()
    try:        # Update the MATERIAL table
        conn.execute('''
            UPDATE MATERIAL 
            SET 
                group_name = ?,
                product_code = ?,
                classification = ?,
                material_name = ?,
                specification = ?,
                brand_name = ?,
                unit = ?,
                location = ?,
                location_safety = ?,
                purchase_se = ?,
                purchase_order = ?,
                cost_center = ?,
                cost_input = ?,
                cost_output = ?,
                cost_stock = ?,
                cost_stock_safety = ?,
                price = ?,
                currency = ?,
                supplier_name = ?,
                status = ?,
                last_update = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE specification = ?
        ''', (
            data.get('group_name', ''),
            data.get('product_code', ''),
            data.get('classification', ''),
            data.get('material_name', ''),
            data.get('specification', ''),
            data.get('brand_name', ''),
            data.get('unit', ''),
            data.get('location', ''),
            data.get('location_safety', ''),
            data.get('purchase_se', ''),
            data.get('purchase_order', ''),
            data.get('cost_center', ''),
            data.get('cost_input', ''),
            data.get('cost_output', ''),
            data.get('cost_stock', ''),
            data.get('cost_stock_safety', ''),
            data.get('price', ''),
            data.get('currency', ''),
            data.get('supplier_name', ''),
            data.get('status', ''),
            data.get('last_update', ''),
            data.get('old_specification', '')
        ))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error updating report: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

# Route for deleting products
@app.route('/delete-product', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def delete_product():
    data = request.json
    qr_code = data.get('qr_code')
    if not qr_code:
        return jsonify({'status': 'error', 'message': 'QR code is required'})
    
    conn = get_db_connection()
    try:
        # First delete from STOCK_TRANSACTION
        conn.execute('DELETE FROM STOCK_TRANSACTION WHERE material_id IN (SELECT material_id FROM MATERIAL WHERE specification = ?)', (qr_code,))
        # Then delete from MATERIAL
        conn.execute('DELETE FROM MATERIAL WHERE specification = ?', (qr_code,))
        conn.commit()
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error deleting product: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()

# Route để xóa toàn bộ lịch sử giao dịch
@app.route('/delete-transaction-history', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def delete_transaction_history():
    """Xóa toàn bộ lịch sử giao dịch (chỉ admin và SEQPEKHO)"""
    try:
        conn = get_db_connection()
        # Xóa toàn bộ bảng STOCK_TRANSACTION
        conn.execute('DELETE FROM STOCK_TRANSACTION')
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success', 
            'message': 'Đã xóa toàn bộ lịch sử giao dịch thành công!'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error', 
            'message': f'Lỗi khi xóa lịch sử: {str(e)}'
        })

# API endpoint to search material by specification for auto-fill
@app.route('/api/search-material', methods=['GET'])
@login_required
@role_required(['admin', 'SEQPEKHO', 'SEQPELINE'])
def search_material():
    specification = request.args.get('specification', '').strip()
    if not specification:
        return jsonify({'status': 'error', 'message': 'Specification is required'})
    
    try:
        conn = get_db_connection()
        # Search for material with exact matching specification (original behavior)
        material = conn.execute(
            'SELECT * FROM MATERIAL WHERE specification = ? ORDER BY created_at DESC LIMIT 1',
            (specification,)
        ).fetchone()
        
        if material:
            # Convert row to dictionary
            material_dict = dict(material)
            return jsonify({
                'status': 'success',
                'material': material_dict
            })
        else:
            return jsonify({
                'status': 'not_found',
                'message': 'Không tìm thấy vật tư với specification này'
            })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

# Bổ sung route /bo-sung-bao-cao để frontend không lỗi 404
@app.route('/bo-sung-bao-cao', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def bo_sung_bao_cao():
    data = request.get_json()
    # Map các trường đầu vào về đúng tên trường trong DB
    mapped_data = {
        'group_name': data.get('group_name') or data.get('group_use'),
        'product_code': data.get('product_code'),
        'classification': data.get('classification') or data.get('classify'),
        'part_code': data.get('part_code'),
        'material_name': data.get('material_name'),
        'specification': (data.get('specification') or '').strip(),
        'brand_name': data.get('brand_name') or data.get('brand'),
        'unit': data.get('unit'),
        'location': data.get('location'),
        'last_update': data.get('last_update') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'last_time': data.get('last_time') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'opening_stock': data.get('opening_stock'),
        'input': data.get('input'),
        'output': data.get('output'),
        'closing_stock': data.get('closing_stock'),
        'inventory': data.get('inventory'),        # New fields for all columns
        'supplier_name': data.get('supplier_name'),
        'safety_stock': data.get('safety_stock'),
        'purchase_order': data.get('purchase_order'),
        'purchase_se': data.get('purchase_se'),
        'cost_opening_stock': data.get('cost_opening_stock'),
        'cost_input': data.get('cost_input'),
        'cost_output': data.get('cost_output'),
        'cost_closing_stock': data.get('cost_closing_stock'),
        'cost_safety_stock': data.get('cost_safety_stock'),
        'price': data.get('price'),
        'currency': data.get('currency'),
        'inventory_org': data.get('inventory_org'),
        'inventory_on': data.get('inventory_on'),
        'status': data.get('status'),
        'quantity': data.get('quantity'),        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    required_fields = [
        'specification'
    ]
    missing = [f for f in required_fields if not mapped_data.get(f)]
    if missing:
        return jsonify({'status': 'error', 'message': f'Thiếu trường: {", ".join(missing)}'})
    
    try:
        conn = get_db_connection()        # Kiểm tra đã tồn tại chưa (chuẩn hóa specification để so sánh chính xác)
        normalized_spec = mapped_data['specification'].strip()
        exists = conn.execute('SELECT * FROM MATERIAL WHERE TRIM(specification) = ?', (normalized_spec,)).fetchone()
        if exists:
            # Nếu đã tồn tại, cập nhật các trường thông tin mới nhất
            update_fields = [
                'group_name', 'product_code', 'classification', 'part_code',
                'material_name', 'brand_name', 'unit', 'location', 'last_update', 'last_time',
                'opening_stock', 'input', 'output', 'closing_stock', 'inventory',
                'supplier_name', 'safety_stock', 'purchase_order', 'purchase_se',
                'cost_opening_stock', 'cost_input', 'cost_output', 'cost_closing_stock', 'cost_safety_stock',
                'price', 'currency', 'inventory_org', 'inventory_on', 'status', 'quantity', 'updated_at'
            ]
            set_clause = ', '.join([f"{f} = ?" for f in update_fields if mapped_data.get(f) is not None])
            values = [mapped_data[f] for f in update_fields if mapped_data.get(f) is not None]
            values.append(normalized_spec)
            conn.execute(f"UPDATE MATERIAL SET {set_clause} WHERE TRIM(specification) = ?", values)
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Vật tư đã được cập nhật'})
        else:
            # Thêm mới vật tư, bổ sung tất cả các trường
            insert_fields = [
                'group_name', 'product_code', 'classification', 'part_code', 'material_name', 'specification',
                'brand_name', 'unit', 'location', 'last_update', 'last_time', 'created_at',
                'opening_stock', 'input', 'output', 'closing_stock', 'inventory',
                'supplier_name', 'safety_stock', 'purchase_order', 'purchase_se',
                'cost_opening_stock', 'cost_input', 'cost_output', 'cost_closing_stock', 'cost_safety_stock',
                'price', 'currency', 'inventory_org', 'inventory_on', 'status', 'quantity', 'updated_at'
            ]
            field_names = ', '.join([f for f in insert_fields if mapped_data.get(f) is not None or f == 'created_at'])
            placeholders = ', '.join(['?' for f in insert_fields if mapped_data.get(f) is not None or f == 'created_at'])
            values = [mapped_data[f] if f != 'created_at' else datetime.now().strftime('%Y-%m-%d %H:%M:%S') for f in insert_fields if mapped_data.get(f) is not None or f == 'created_at']
            conn.execute(f'''
                INSERT INTO MATERIAL ({field_names})
                VALUES ({placeholders})
            ''', values)
            conn.commit()
            return jsonify({'status': 'success', 'message': 'Vật tư đã được thêm mới'})
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if 'conn' in locals():
            conn.close()


# Route cho trang bổ sung dữ liệu
@app.route('/bo-sung-du-lieu')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def bo_sung_du_lieu():
    return render_template('bo_sung_du_lieu.html')


# Route để xuất Excel
@app.route('/bao-cao-xls')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def export_excel():
    conn = get_db_connection()
    products = conn.execute('''
        SELECT * FROM MATERIAL WHERE material_id IN (
            SELECT MAX(material_id) FROM MATERIAL GROUP BY specification
        )
    ''').fetchall()
    
    # Tạo DataFrame từ dữ liệu
    data = []
    for row in products:
        data.append({
            'Group use': row['group_name'] if row['group_name'] else '',
            'Product code': row['product_code'] if row['product_code'] else '',
            'Classify': row['classification'] if row['classification'] else '',
            'Part Code': row['part_code'] if row['part_code'] else '',
            'Material name': row['material_name'] if row['material_name'] else '',
            'Specification': row['specification'] if row['specification'] else '',
            'Brand': row['brand_name'] if row['brand_name'] else '',
            'Unit': row['unit'] if row['unit'] else '',
           
            'Safety Stock': row['safety_stock'] if row['safety_stock'] else '',
            'Location Safety': row['location_safety'] if row['location_safety'] else '',
            'Purchase Order': row['purchase_order'] if row['purchase_order'] else '',
            'Purchase SE': row['purchase_se'] if row['purchase_se'] else '',
            'Cost Center': row['cost_center'] if row['cost_center'] else '',
            'Cost Input': row['cost_input'] if row['cost_input'] else '',
            'Cost Output': row['cost_output'] if row['cost_output'] else '',
            'Cost Stock': row['cost_stock'] if row['cost_stock'] else '',
            'Cost Stock Safety': row['cost_stock_safety'] if row['cost_stock_safety'] else '',
            'Price': row['price'] if row['price'] else '',
            'Currency': row['currency'] if row['currency'] else '',
            'Opening stock': row['opening_stock'] if row['opening_stock'] else '',
            'Input': row['input'] if row['input'] else '',
            'Output': row['output'] if row['output'] else '',
            'Closing stock': row['closing_stock'] if row['closing_stock'] else '',
            'Inventory': row['inventory'] if row['inventory'] else '',
            'Inventory Org': row['inventory_org'] if row['inventory_org'] else '',
            'Inventory On': row['inventory_on'] if row['inventory_on'] else '',
            'Status': row['status'] if row['status'] else '',
            'Quantity': row['quantity'] if row['quantity'] else '',
            'Location': row['location'] if row['location'] else '',
            'Last update': row['last_update'] if row['last_update'] else '',
            'Last time': row['last_time'] if row['last_time'] else ''
        })
    
    conn.close()
    
    df = pd.DataFrame(data)
    
    # Tạo file Excel trong memory
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Báo cáo tồn kho', index=False)
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'bao_cao_ton_kho_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


# Route danh sách (lịch sử)
@app.route('/danh-sach')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def danh_sach():
    conn = get_db_connection()
    # Lấy lịch sử giao dịch với thông tin vật tư
    history = conn.execute('''
        SELECT st.*, m.group_name, m.product_code, m.classification, m.part_code, 
               m.material_name, m.specification, m.brand_name, m.unit, m.location
        FROM STOCK_TRANSACTION st
        JOIN MATERIAL m ON st.material_id = m.material_id
        ORDER BY st.created_at DESC
        LIMIT 1000
    ''').fetchall()
    conn.close()
    return render_template('danh_sach.html', history=history)


# Route kiểm kê
@app.route('/kiem-ke')
@login_required
@role_required(['admin', 'SEQPEKHO'])
def kiem_ke():
    conn = get_db_connection()
    materials = conn.execute('SELECT * FROM MATERIAL ORDER BY material_name').fetchall()
    conn.close()
    return render_template('kiem_ke.html', materials=materials)


# Route cập nhật kiểm kê - POST
@app.route('/kiem-ke', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def kiem_ke_post():
    data = request.get_json()
    qr_code = data.get('qr_code')
    inventory = data.get('inventory')
    
    if not qr_code or inventory is None:
        return jsonify({'status': 'error', 'message': 'Thiếu thông tin QR code hoặc số lượng kiểm kê'})
    
    try:
        inventory = float(inventory)
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Số lượng kiểm kê phải là số'})
    
    conn = get_db_connection()
    try:
        # Tìm vật tư theo specification (QR code)
        material = conn.execute('SELECT * FROM MATERIAL WHERE TRIM(LOWER(specification)) = TRIM(LOWER(?)) ORDER BY created_at DESC LIMIT 1', (qr_code,)).fetchone()
        if not material:
            return jsonify({'status': 'error', 'message': 'Không tìm thấy vật tư với QR code này'})
        
        # Thêm giao dịch kiểm kê vào STOCK_TRANSACTION
        conn.execute('''INSERT INTO STOCK_TRANSACTION 
                       (material_id, transaction_type, quantity, transaction_date, created_at, created_by) 
                       VALUES (?, ?, ?, ?, ?, ?)''', (
            material['material_id'],
            'inventory',
            inventory,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            session.get('username', 'System')
        ))
        
        # Cập nhật inventory trong MATERIAL
        conn.execute('UPDATE MATERIAL SET inventory = ?, updated_at = ? WHERE material_id = ?',
                     (inventory, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), material['material_id']))
        conn.commit()
        
        return jsonify({'status': 'success', 'message': f'Đã cập nhật kiểm kê thành công cho {material["material_name"]}'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()


# Route cập nhật kiểm kê
@app.route('/update-inventory', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO'])
def update_inventory():
    data = request.get_json()
    material_id = data.get('material_id')
    inventory = data.get('inventory')
    
    if not material_id or inventory is None:
        return jsonify({'status': 'error', 'message': 'Thiếu thông tin material_id hoặc inventory'})
    
    try:
        inventory = float(inventory)
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Inventory phải là số'})
    
    conn = get_db_connection()
    try:
        # Lấy thông tin vật tư
        material = conn.execute('SELECT * FROM MATERIAL WHERE material_id = ?', (material_id,)).fetchone()
        if not material:
            return jsonify({'status': 'error', 'message': 'Không tìm thấy vật tư'})
        
        # Thêm giao dịch kiểm kê
        conn.execute('INSERT INTO STOCK_TRANSACTION (material_id, transaction_type, quantity, transaction_date, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)', (
            material['material_id'],
            'inventory',
            inventory,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ))
        
        # Cập nhật inventory và closing_stock trong MATERIAL
        conn.execute('UPDATE MATERIAL SET inventory = ?, closing_stock = ?, quantity = ?, last_update = datetime("now") WHERE material_id = ?',
                     (inventory, inventory, inventory, material['material_id']))
        conn.commit()
        return jsonify({'status': 'success', 'message': 'Cập nhật kiểm kê thành công'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        conn.close()


# Route test để kiểm tra chức năng lưu
@app.route('/test-save')
def test_save():
    return render_template('test_save.html')


# API endpoint to get product info by specification for xuat_kho page
@app.route('/api/product-info/<specification>')
@login_required
@role_required(['admin', 'SEQPEKHO', 'SEQPELINE'])
def get_product_info(specification):
    try:
        conn = get_db_connection()
        # Search for material with matching specification (case-insensitive and trimmed)
        material = conn.execute(
            'SELECT * FROM MATERIAL WHERE TRIM(LOWER(specification)) = TRIM(LOWER(?)) ORDER BY created_at DESC LIMIT 1',
            (specification,)
        ).fetchone()
        
        if material:
            # Convert row to dictionary
            material_dict = dict(material)
            return jsonify({
                'status': 'success',
                'product': material_dict
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Không tìm thấy sản phẩm với specification này'
            })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

# Route xử lý xuất kho hàng loạt
@app.route('/xuat-kho-batch', methods=['POST'])
@login_required
@role_required(['admin', 'SEQPEKHO', 'SEQPELINE'])
def xuat_kho_batch():
    try:
        data = request.get_json()
        items = data.get('items', [])
        
        if not items:
            return jsonify({'status': 'error', 'message': 'Danh sách xuất kho trống'})
        
        conn = get_db_connection()
        success_count = 0
        error_list = []
        
        for item in items:
            try:
                qr_code = item.get('qr_code', '').strip()
                quantity = float(item.get('quantity', 0))
                exported_by = item.get('exported_by', '').strip()
                
                if not qr_code or quantity <= 0:
                    error_list.append(f"Thông tin không hợp lệ cho {qr_code}")
                    continue
                
                # Tìm material theo specification
                material = conn.execute(
                    'SELECT * FROM MATERIAL WHERE TRIM(LOWER(specification)) = TRIM(LOWER(?)) LIMIT 1',
                    (qr_code,)
                ).fetchone()
                
                if not material:
                    error_list.append(f"Không tìm thấy vật tư: {qr_code}")
                    continue
                
                # Thêm giao dịch xuất kho vào STOCK_TRANSACTION
                conn.execute('''
                    INSERT INTO STOCK_TRANSACTION (material_id, transaction_type, quantity, transaction_date, reference_number, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    material['material_id'],
                    'output',
                    quantity,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    f'EXPORT-{datetime.now().strftime("%Y%m%d%H%M%S")}',
                    f'Xuất kho bởi {exported_by}',
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))
                  # Cập nhật số lượng trong MATERIAL (trừ đi số lượng xuất)
                new_output = float(material['output'] or 0) + quantity
                new_closing_stock = float(material['closing_stock'] or 0) - quantity
                
                conn.execute('''
                    UPDATE MATERIAL 
                    SET output = ?, closing_stock = ?, updated_at = ?
                    WHERE material_id = ?
                ''', (new_output, new_closing_stock, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), material['material_id']))
                
                success_count += 1
                
            except Exception as e:
                error_list.append(f"Lỗi xử lý {qr_code}: {str(e)}")
        
        conn.commit();
        
        if error_list:
            message = f"Xuất kho {success_count} sản phẩm thành công. Lỗi: {'; '.join(error_list)}"
            return jsonify({'status': 'partial', 'message': message})
        else:
            return jsonify({'status': 'success', 'message': f'Xuất kho thành công {success_count} sản phẩm'})
            
    except Exception as e:
        if 'conn' in locals():
            conn.rollback()
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == '__main__':
    # Sử dụng biến môi trường cho secret key
    app.secret_key = os.environ.get('SECRET_KEY', 'fallback-secret-key-change-in-production')
    
    # Chỉ bật debug mode trong môi trường development
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=5000)
