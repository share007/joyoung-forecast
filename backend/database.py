"""
数据库模块 - SQLite
"""
import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Optional

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'forecast.db')
DB_PATH = os.environ.get('FORECAST_DB_PATH', DEFAULT_DB_PATH)

def get_db():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """初始化数据库表"""
    conn = get_db()
    cursor = conn.cursor()
    
    # 产品表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            current_stock INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 销售数据表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            sales INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            UNIQUE(product_id, date)
        )
    ''')
    
    # 预测结果表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS forecast_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            forecast_days INTEGER NOT NULL,
            predictions TEXT NOT NULL,
            metrics TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # 导入批次表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS import_batches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            file_name TEXT,
            source_type TEXT DEFAULT 'excel',
            sheet_name TEXT,
            imported_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'success',
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')

    # 计划建议表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS planning_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            planning_payload TEXT NOT NULL,
            forecast_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (forecast_id) REFERENCES forecast_results(id)
        )
    ''')

    # 最近一次导入文件（原始数据）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS latest_import_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT,
            sheet_name TEXT,
            source_type TEXT DEFAULT 'excel',
            row_count INTEGER DEFAULT 0,
            columns_json TEXT,
            detected_columns_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS latest_import_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            import_file_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            row_data TEXT NOT NULL,
            FOREIGN KEY (import_file_id) REFERENCES latest_import_files(id)
        )
    ''')
    
    conn.commit()
    conn.close()

def seed_products():
    """保留兼容函数：不再注入示例数据。"""
    return None

# 产品操作
def get_all_products() -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products ORDER BY id')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_product_by_name(name: str) -> Optional[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products WHERE name = ?', (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def create_product(name: str, category: str, current_stock: int = 0) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO products (name, category, current_stock) VALUES (?, ?, ?)',
        (name, category, current_stock)
    )
    conn.commit()
    product_id = cursor.lastrowid
    conn.close()
    return product_id

# 销售数据操作
def get_sales_data(product_id: int, limit: int = None) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    query = 'SELECT * FROM sales_data WHERE product_id = ? ORDER BY date'
    if limit:
        query += f' LIMIT {limit}'
    cursor.execute(query, (product_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_sales_data_by_product_name(product_name: str, limit: int = None) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    query = '''
        SELECT sd.* FROM sales_data sd
        JOIN products p ON sd.product_id = p.id
        WHERE p.name = ? ORDER BY sd.date
    '''
    if limit:
        query += f' LIMIT {limit}'
    cursor.execute(query, (product_name,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def add_sales_data(product_id: int, date: str, sales: int) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT OR REPLACE INTO sales_data (product_id, date, sales) VALUES (?, ?, ?)',
            (product_id, date, sales)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"添加销售数据失败: {e}")
        return False
    finally:
        conn.close()

def bulk_add_sales_data(product_id: int, data: List[Dict]) -> int:
    """批量添加销售数据"""
    conn = get_db()
    cursor = conn.cursor()
    count = 0
    try:
        for item in data:
            cursor.execute(
                'INSERT OR REPLACE INTO sales_data (product_id, date, sales) VALUES (?, ?, ?)',
                (product_id, item['date'], int(item['sales']))
            )
            count += 1
        conn.commit()
    except Exception as e:
        print(f"批量添加销售数据失败: {e}")
    finally:
        conn.close()
    return count

def delete_sales_data(product_id: int, date: str = None) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    try:
        if date:
            cursor.execute('DELETE FROM sales_data WHERE product_id = ? AND date = ?', (product_id, date))
        else:
            cursor.execute('DELETE FROM sales_data WHERE product_id = ?', (product_id,))
        conn.commit()
        return True
    except Exception as e:
        return False
    finally:
        conn.close()

# 预测结果操作
def save_forecast_result(product_id: int, forecast_days: int, predictions: List[Dict], metrics: Dict) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO forecast_results (product_id, forecast_days, predictions, metrics) VALUES (?, ?, ?, ?)',
        (
            product_id,
            forecast_days,
            json.dumps(predictions, ensure_ascii=False),
            json.dumps(metrics, ensure_ascii=False),
        )
    )
    conn.commit()
    result_id = cursor.lastrowid
    conn.close()
    return result_id

def get_latest_forecast(product_id: int) -> Optional[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM forecast_results WHERE product_id = ? ORDER BY created_at DESC LIMIT 1',
        (product_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    result['predictions'] = _safe_json_loads(result.get('predictions'))
    result['metrics'] = _safe_json_loads(result.get('metrics'))
    return result


def create_import_batch(
    product_id: Optional[int],
    file_name: str,
    imported_count: int,
    sheet_name: Optional[str] = None,
    source_type: str = 'excel',
    status: str = 'success',
    details: Optional[Dict] = None,
) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''
        INSERT INTO import_batches (product_id, file_name, source_type, sheet_name, imported_count, status, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''',
        (
            product_id,
            file_name,
            source_type,
            sheet_name,
            imported_count,
            status,
            json.dumps(details or {}, ensure_ascii=False),
        )
    )
    conn.commit()
    batch_id = cursor.lastrowid
    conn.close()
    return batch_id


def save_planning_result(product_id: int, payload: Dict, forecast_id: Optional[int] = None) -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO planning_results (product_id, planning_payload, forecast_id) VALUES (?, ?, ?)',
        (product_id, json.dumps(payload, ensure_ascii=False), forecast_id),
    )
    conn.commit()
    result_id = cursor.lastrowid
    conn.close()
    return result_id


def save_latest_import_file(
    file_name: str,
    rows: List[Dict],
    sheet_name: Optional[str] = None,
    source_type: str = 'excel',
    detected_columns: Optional[Dict] = None,
) -> int:
    conn = get_db()
    cursor = conn.cursor()

    # 仅保留最近一次导入数据
    cursor.execute('DELETE FROM latest_import_rows')
    cursor.execute('DELETE FROM latest_import_files')

    columns = list(rows[0].keys()) if rows else []
    cursor.execute(
        '''
        INSERT INTO latest_import_files (file_name, sheet_name, source_type, row_count, columns_json, detected_columns_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (
            file_name,
            sheet_name,
            source_type,
            len(rows),
            json.dumps(columns, ensure_ascii=False),
            json.dumps(detected_columns or {}, ensure_ascii=False),
        ),
    )
    import_file_id = cursor.lastrowid

    for idx, row in enumerate(rows):
        cursor.execute(
            'INSERT INTO latest_import_rows (import_file_id, row_index, row_data) VALUES (?, ?, ?)',
            (import_file_id, idx, json.dumps(row, ensure_ascii=False)),
        )

    conn.commit()
    conn.close()
    return import_file_id


def begin_latest_import_file(
    file_name: str,
    columns: List[str],
    sheet_name: Optional[str] = None,
    source_type: str = 'excel',
    detected_columns: Optional[Dict] = None,
) -> int:
    conn = get_db()
    cursor = conn.cursor()

    # Keep only the newest imported file snapshot.
    cursor.execute('DELETE FROM latest_import_rows')
    cursor.execute('DELETE FROM latest_import_files')

    cursor.execute(
        '''
        INSERT INTO latest_import_files (file_name, sheet_name, source_type, row_count, columns_json, detected_columns_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ''',
        (
            file_name,
            sheet_name,
            source_type,
            0,
            json.dumps(columns, ensure_ascii=False),
            json.dumps(detected_columns or {}, ensure_ascii=False),
        ),
    )

    import_file_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return import_file_id


def append_latest_import_rows(import_file_id: int, rows: List[Dict], start_index: int = 0) -> int:
    if not rows:
        return 0

    conn = get_db()
    cursor = conn.cursor()
    payload = [
        (
            import_file_id,
            start_index + idx,
            json.dumps(row, ensure_ascii=False),
        )
        for idx, row in enumerate(rows)
    ]

    cursor.executemany(
        'INSERT INTO latest_import_rows (import_file_id, row_index, row_data) VALUES (?, ?, ?)',
        payload,
    )
    conn.commit()
    conn.close()
    return len(rows)


def finalize_latest_import_file(import_file_id: int, row_count: int, detected_columns: Optional[Dict] = None) -> None:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE latest_import_files SET row_count = ?, detected_columns_json = ? WHERE id = ?',
        (
            row_count,
            json.dumps(detected_columns or {}, ensure_ascii=False),
            import_file_id,
        ),
    )
    conn.commit()
    conn.close()


def get_latest_import_file() -> Optional[Dict]:
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM latest_import_files ORDER BY id DESC LIMIT 1')
    file_row = cursor.fetchone()
    if not file_row:
        conn.close()
        return None

    file_dict = dict(file_row)
    import_file_id = file_dict['id']

    cursor.execute(
        'SELECT row_data FROM latest_import_rows WHERE import_file_id = ? ORDER BY row_index',
        (import_file_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    parsed_rows = []
    for row in rows:
        parsed_rows.append(_safe_json_loads(row['row_data']))

    file_dict['columns'] = _safe_json_loads(file_dict.get('columns_json')) or []
    file_dict['detected_columns'] = _safe_json_loads(file_dict.get('detected_columns_json')) or {}
    file_dict['rows'] = parsed_rows
    return file_dict


def upsert_products_by_codes(product_codes: List[str]) -> int:
    codes = sorted({str(code).strip() for code in product_codes if str(code).strip()})
    if not codes:
        return 0

    conn = get_db()
    cursor = conn.cursor()
    inserted = 0
    for code in codes:
        cursor.execute(
            'INSERT OR IGNORE INTO products (name, category, current_stock) VALUES (?, ?, ?)',
            (code, '导入产品', 0),
        )
        if cursor.rowcount > 0:
            inserted += 1
    conn.commit()
    conn.close()
    return inserted


def get_recent_import_batches(product_id: int, limit: int = 10) -> List[Dict]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM import_batches WHERE product_id = ? ORDER BY created_at DESC LIMIT ?',
        (product_id, limit),
    )
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        item = dict(row)
        item['details'] = _safe_json_loads(item.get('details'))
        results.append(item)
    return results


def _safe_json_loads(value: Optional[str]):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value

# 初始化数据库
init_db()