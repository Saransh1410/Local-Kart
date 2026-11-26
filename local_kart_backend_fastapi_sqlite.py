"""
Local Kart - Backend API (FastAPI + SQLite)
Academic Project MVP

Team Members:
  - Saransh Devpura (EN23CS306045)
  - Nitin Dhakad    (EN23CS306036)
Project Guide: Prof. Ajaj Khan

Note: Paid services (Razorpay gateway, store subscriptions, premium listings)
are mocked locally so the full system can be demonstrated without paid hosting
or merchant accounts.
"""

import hashlib
import math
import os
import sqlite3
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

DB_FILE = "localkart.db"

app = FastAPI(title="Local Kart API", version="1.0")

# Enabling CORS so index.html works whether opened directly or via localhost/LAN
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Database & Helper Functions ---

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(raw_password: str) -> str:
    # Using built-in hashlib (SHA-256) to keep setup simple without extra C dependencies
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest()


def calculate_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """
    Haversine formula to calculate straight-line distance (in metres)
    between the customer location and a store. Used for the 500m radius check.
    """
    earth_radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(round(earth_radius * c))


def setup_database():
    """Creates tables on first run and inserts sample stores & demo accounts."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('customer', 'store', 'admin')),
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            distance_m INTEGER NOT NULL,
            premium INTEGER NOT NULL DEFAULT 0,
            subscription_active INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'Active',
            FOREIGN KEY (owner_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT '1 unit',
            description TEXT NOT NULL DEFAULT '',
            stock INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (store_id) REFERENCES stores(id)
        );

        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            customer_email TEXT NOT NULL,
            store_id INTEGER NOT NULL,
            store_name TEXT NOT NULL,
            delivery_location TEXT NOT NULL,
            subtotal REAL NOT NULL,
            distance_fee REAL NOT NULL DEFAULT 0,
            instant_fee REAL NOT NULL DEFAULT 0,
            delivery_fee REAL NOT NULL DEFAULT 0,
            total REAL NOT NULL,
            is_instant INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'Pending Acceptance',
            payment_method TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            payment_ref TEXT,
            batch TEXT NOT NULL DEFAULT 'Unassigned',
            created_at TEXT NOT NULL,
            FOREIGN KEY (store_id) REFERENCES stores(id)
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            qty INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );
        """
    )

    # Safely add unit and description columns if an older localkart.db already exists
    cursor.execute("PRAGMA table_info(products)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    if "unit" not in existing_cols:
        cursor.execute("ALTER TABLE products ADD COLUMN unit TEXT NOT NULL DEFAULT '1 unit'")
    if "description" not in existing_cols:
        cursor.execute("ALTER TABLE products ADD COLUMN description TEXT NOT NULL DEFAULT ''")

    # Seed initial demo records only if the users table is empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Default demo users for testing all three roles
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Platform Admin", "admin@localkart.com", hash_password("admin123"), "admin", now),
        )
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Sharma Ji", "store@localkart.com", hash_password("store123"), "store", now),
        )
        sharma_owner_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Demo Customer", "customer@localkart.com", hash_password("customer123"), "customer", now),
        )

        # Sample local stores (users can also register real stores with live GPS)
        sample_stores = [
            (sharma_owner_id, "Sharma Groceries", "Scheme 54, Vijay Nagar", 22.7533, 75.8937, 280, 1, 1, "Active"),
            (None, "Daily Needs Mart", "Near C21 Mall", 22.7550, 75.8950, 440, 0, 1, "Active"),
            (None, "Faraway Superstore", "AB Road Extension", 22.7602, 75.8980, 820, 0, 1, "Active"),
        ]
        cursor.executemany(
            """
            INSERT INTO stores (owner_id, name, address, lat, lng, distance_m, premium, subscription_active, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            sample_stores,
        )

        sample_products = [
            (1, "Aashirvaad Atta", 250, "5 kg", "100% whole wheat chakki fresh atta", 12),
            (1, "Amul Taaza Milk", 66, "1 L", "Pasteurized toned fresh milk pouch", 25),
            (1, "Tata Tea Gold", 290, "500 g", "Rich aroma Assam tea with long leaves", 8),
            (2, "Tata Salt", 28, "1 kg", "Vacuum evaporated iodized table salt", 20),
            (2, "Maggi Noodles", 56, "4-Pack (280 g)", "2-minute masala instant noodles", 15),
            (2, "Amul Taaza Milk", 66, "1 L", "Pasteurized toned fresh milk pouch", 10),
            (3, "Brown Bread", 45, "400 g", "Soft whole wheat bakery sandwich bread", 14),
            (3, "Olive Oil", 520, "500 ml", "Extra light olive oil for daily cooking", 6),
        ]
        cursor.executemany(
            "INSERT INTO products (store_id, name, price, unit, description, stock) VALUES (?, ?, ?, ?, ?, ?)",
            sample_products,
        )

    conn.commit()
    conn.close()


# Initialize SQLite tables when server starts
setup_database()


# --- Request Models (Pydantic) ---

class AuthPayload(BaseModel):
    name: Optional[str] = "User"
    email: str
    password: str
    role: str
    store_name: Optional[str] = None
    store_address: Optional[str] = "Local Area"
    store_lat: Optional[float] = 22.7540
    store_lng: Optional[float] = 75.8940


class NewProductPayload(BaseModel):
    name: str
    price: float
    unit: str = "1 unit"
    description: str = ""
    stock: int


class UpdateProductPayload(BaseModel):
    price: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    stock: Optional[int] = None


class UpdateStorePayload(BaseModel):
    premium: Optional[bool] = None
    subscription_active: Optional[bool] = None
    status: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


class OrderItemPayload(BaseModel):
    product_id: int
    name: str
    price: float
    qty: int


class CreateOrderPayload(BaseModel):
    customer_email: str
    store_id: int
    delivery_location: str
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None
    items: List[OrderItemPayload]
    is_instant: bool = False
    payment_method: str


class UpdateOrderPayload(BaseModel):
    status: Optional[str] = None
    batch: Optional[str] = None
    payment_status: Optional[str] = None


class MockRazorpayPayload(BaseModel):
    order_id: str
    mock_payment_id: str


# --- API Endpoints ---

@app.get("/")
def serve_home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "Local Kart API is running. Place index.html in this folder to view the UI."}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "database": DB_FILE}


@app.post("/api/auth/register")
def register_user(data: AuthPayload):
    # Admin accounts cannot be created from the public signup screen
    if data.role == "admin":
        raise HTTPException(status_code=403, detail="Admin registration is restricted.")

    clean_email = data.email.strip().lower()
    if not clean_email or not data.password.strip():
        raise HTTPException(status_code=400, detail="Email and password cannot be empty.")

    conn = get_connection()
    cursor = conn.cursor()
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        display_name = data.name.strip() if data.name else clean_email.split("@")[0]

        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (display_name, clean_email, hash_password(data.password), data.role, now),
        )
        new_user_id = cursor.lastrowid
        linked_store_id = None

        # Create a store with the owner's real GPS coordinates if provided
        if data.role == "store":
            shop_name = data.store_name.strip() if data.store_name else f"{display_name}'s Store"
            shop_address = data.store_address.strip() if data.store_address else "Local Area"
            lat = data.store_lat if data.store_lat is not None else 22.7540
            lng = data.store_lng if data.store_lng is not None else 75.8940

            cursor.execute(
                """
                INSERT INTO stores (owner_id, name, address, lat, lng, distance_m, premium, subscription_active, status)
                VALUES (?, ?, ?, ?, ?, 0, 0, 1, 'Active')
                """,
                (new_user_id, shop_name, shop_address, lat, lng),
            )
            linked_store_id = cursor.lastrowid

        conn.commit()
        return {
            "user": {
                "id": new_user_id,
                "name": display_name,
                "email": clean_email,
                "role": data.role,
                "store_id": linked_store_id,
            }
        }
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="An account with this email already exists.")
    finally:
        conn.close()


@app.post("/api/auth/login")
def login_user(data: AuthPayload):
    clean_email = data.email.strip().lower()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT id, name, email, password_hash, role FROM users WHERE email = ? AND role = ?",
        (clean_email, data.role),
    )
    user = cursor.fetchone()

    if not user or user["password_hash"] != hash_password(data.password):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password for the selected role.")

    linked_store_id = None
    if user["role"] == "store":
        cursor.execute("SELECT id FROM stores WHERE owner_id = ?", (user["id"],))
        store_row = cursor.fetchone()
        linked_store_id = store_row["id"] if store_row else 1

    conn.close()
    return {
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"],
            "store_id": linked_store_id,
        }
    }


@app.get("/api/stores")
def get_stores(lat: Optional[float] = None, lng: Optional[float] = None):
    """Returns stores with real-time Haversine distance, sorted by premium first then nearest."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stores")
    store_rows = cursor.fetchall()

    stores_list = []
    for row in store_rows:
        cursor.execute(
            "SELECT id, name, price, unit, description, stock FROM products WHERE store_id = ?",
            (row["id"],),
        )
        products = [dict(p) for p in cursor.fetchall()]

        if lat is not None and lng is not None:
            dist = calculate_distance_meters(lat, lng, row["lat"], row["lng"])
        else:
            dist = row["distance_m"]

        stores_list.append({
            "id": row["id"],
            "name": row["name"],
            "address": row["address"],
            "lat": row["lat"],
            "lng": row["lng"],
            "distance": dist,
            "premium": bool(row["premium"]),
            "subscriptionActive": bool(row["subscription_active"]),
            "status": row["status"],
            "products": products,
        })

    conn.close()

    # Sort dynamically: premium stores first, then closest distance
    stores_list.sort(key=lambda s: (not s["premium"], s["distance"]))
    return stores_list


@app.patch("/api/stores/{store_id}")
def update_store(store_id: int, data: UpdateStorePayload):
    """Updates store subscription, premium listing, status, or live GPS coordinates."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM stores WHERE id = ?", (store_id,))
    store = cursor.fetchone()
    if not store:
        conn.close()
        raise HTTPException(status_code=404, detail="Store not found.")

    premium = int(data.premium) if data.premium is not None else store["premium"]
    subscription_active = (
        int(data.subscription_active) if data.subscription_active is not None else store["subscription_active"]
    )
    status = data.status if data.status is not None else store["status"]
    address = data.address if data.address is not None else store["address"]
    lat = data.lat if data.lat is not None else store["lat"]
    lng = data.lng if data.lng is not None else store["lng"]

    cursor.execute(
        """
        UPDATE stores
        SET premium = ?, subscription_active = ?, status = ?, address = ?, lat = ?, lng = ?
        WHERE id = ?
        """,
        (premium, subscription_active, status, address, lat, lng, store_id),
    )
    conn.commit()
    conn.close()
    return {
        "id": store_id,
        "premium": bool(premium),
        "subscriptionActive": bool(subscription_active),
        "status": status,
        "address": address,
        "lat": lat,
        "lng": lng,
    }


@app.post("/api/stores/{store_id}/products")
def add_store_product(store_id: int, prod: NewProductPayload):
    if prod.price <= 0 or prod.stock < 0:
        raise HTTPException(status_code=400, detail="Price must be greater than 0 and stock cannot be negative.")

    clean_unit = prod.unit.strip() if prod.unit and prod.unit.strip() else "1 unit"
    clean_desc = prod.description.strip() if prod.description else ""

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO products (store_id, name, price, unit, description, stock) VALUES (?, ?, ?, ?, ?, ?)",
        (store_id, prod.name.strip(), prod.price, clean_unit, clean_desc, prod.stock),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {
        "id": new_id,
        "store_id": store_id,
        "name": prod.name.strip(),
        "price": prod.price,
        "unit": clean_unit,
        "description": clean_desc,
        "stock": prod.stock,
    }


@app.patch("/api/products/{product_id}")
def update_product_stock(product_id: int, data: UpdateProductPayload):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        raise HTTPException(status_code=404, detail="Product not found.")

    updated_price = data.price if data.price is not None else product["price"]
    updated_unit = data.unit.strip() if data.unit is not None and data.unit.strip() else product["unit"]
    updated_desc = data.description.strip() if data.description is not None else product["description"]
    updated_stock = max(0, data.stock) if data.stock is not None else product["stock"]

    cursor.execute(
        "UPDATE products SET price = ?, unit = ?, description = ?, stock = ? WHERE id = ?",
        (updated_price, updated_unit, updated_desc, updated_stock, product_id),
    )
    conn.commit()
    conn.close()
    return {
        "id": product_id,
        "price": updated_price,
        "unit": updated_unit,
        "description": updated_desc,
        "stock": updated_stock,
    }


@app.post("/api/orders")
def create_order(order_req: CreateOrderPayload):
    if not order_req.items:
        raise HTTPException(status_code=400, detail="Cannot place an empty order.")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM stores WHERE id = ?", (order_req.store_id,))
    store = cursor.fetchone()
    if not store or not store["subscription_active"] or store["status"] != "Active":
        conn.close()
        raise HTTPException(status_code=400, detail="This store is currently unavailable.")

    # Check stock before confirming the order to avoid overselling
    subtotal = 0.0
    for item in order_req.items:
        cursor.execute(
            "SELECT stock, price FROM products WHERE id = ? AND store_id = ?",
            (item.product_id, order_req.store_id),
        )
        db_item = cursor.fetchone()
        if not db_item or db_item["stock"] < item.qty:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Not enough stock for {item.name}.")
        subtotal += db_item["price"] * item.qty

    # Reduce stock quantities once validated
    for item in order_req.items:
        cursor.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (item.qty, item.product_id))

    # Calculate real-time Haversine distance if customer coordinates were sent
    if order_req.customer_lat is not None and order_req.customer_lng is not None:
        actual_distance = calculate_distance_meters(
            order_req.customer_lat, order_req.customer_lng, store["lat"], store["lng"]
        )
    else:
        actual_distance = store["distance_m"]

    # Apply delivery charges: Rs 40 if outside 500m radius, Rs 50 if instant delivery
    distance_fee = 40.0 if actual_distance > 500 else 0.0
    instant_fee = 50.0 if order_req.is_instant else 0.0
    delivery_fee = distance_fee + instant_fee
    total_amount = subtotal + delivery_fee

    order_id = "ORD-" + uuid.uuid4().hex[:6].upper()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pay_status = "Pending Verification" if order_req.payment_method == "razorpay" else "Pending (COD)"
    pay_ref = f"RZP_MOCK_{uuid.uuid4().hex[:8].upper()}" if order_req.payment_method == "razorpay" else f"COD_{order_id}"
    batch_slot = "Instant Dispatch" if order_req.is_instant else "Unassigned"

    cursor.execute(
        """
        INSERT INTO orders (
            id, customer_email, store_id, store_name, delivery_location,
            subtotal, distance_fee, instant_fee, delivery_fee, total,
            is_instant, status, payment_method, payment_status, payment_ref, batch, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id, order_req.customer_email, store["id"], store["name"], order_req.delivery_location,
            subtotal, distance_fee, instant_fee, delivery_fee, total_amount,
            int(order_req.is_instant), "Pending Acceptance", order_req.payment_method,
            pay_status, pay_ref, batch_slot, timestamp,
        ),
    )

    for item in order_req.items:
        cursor.execute(
            "INSERT INTO order_items (order_id, product_id, name, price, qty) VALUES (?, ?, ?, ?, ?)",
            (order_id, item.product_id, item.name, item.price, item.qty),
        )

    conn.commit()
    conn.close()
    return {
        "order_id": order_id,
        "payment_ref": pay_ref,
        "distance_m": actual_distance,
        "total": total_amount,
        "payment_status": pay_status,
    }


@app.post("/api/payments/razorpay/mock-verify")
def verify_mock_razorpay(payload: MockRazorpayPayload):
    """
    Simulates server-side Razorpay signature verification & webhook handling.
    Kept idempotent so repeated calls do not duplicate updates.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, payment_status FROM orders WHERE id = ?", (payload.order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found.")

    if order["payment_status"] == "Verified (Mock Razorpay)":
        conn.close()
        return {"status": "already_verified", "order_id": payload.order_id}

    cursor.execute(
        "UPDATE orders SET payment_status = ?, payment_ref = ? WHERE id = ?",
        ("Verified (Mock Razorpay)", payload.mock_payment_id, payload.order_id),
    )
    conn.commit()
    conn.close()
    return {"status": "verified", "order_id": payload.order_id, "payment_ref": payload.mock_payment_id}


@app.get("/api/orders")
def get_orders(role: Optional[str] = None, email: Optional[str] = None, store_id: Optional[int] = None):
    conn = get_connection()
    cursor = conn.cursor()

    if role == "customer" and email:
        cursor.execute("SELECT * FROM orders WHERE customer_email = ? ORDER BY created_at DESC", (email,))
    elif role == "store" and store_id:
        cursor.execute("SELECT * FROM orders WHERE store_id = ? ORDER BY created_at DESC", (store_id,))
    else:
        cursor.execute("SELECT * FROM orders ORDER BY created_at DESC")

    rows = cursor.fetchall()
    orders_list = []

    for row in rows:
        cursor.execute(
            "SELECT product_id as id, name, price, qty FROM order_items WHERE order_id = ?",
            (row["id"],),
        )
        items = [dict(i) for i in cursor.fetchall()]

        orders_list.append({
            "id": row["id"],
            "customerEmail": row["customer_email"],
            "storeId": row["store_id"],
            "storeName": row["store_name"],
            "deliveryLocation": row["delivery_location"],
            "items": items,
            "subtotal": row["subtotal"],
            "distanceFee": row["distance_fee"],
            "instantFee": row["instant_fee"],
            "deliveryFee": row["delivery_fee"],
            "total": row["total"],
            "isInstant": bool(row["is_instant"]),
            "status": row["status"],
            "paymentMethod": row["payment_method"],
            "paymentStatus": row["payment_status"],
            "paymentRef": row["payment_ref"],
            "batch": row["batch"],
            "timestamp": row["created_at"],
        })

    conn.close()
    return orders_list


@app.patch("/api/orders/{order_id}")
def update_order_status(order_id: str, data: UpdateOrderPayload):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        raise HTTPException(status_code=404, detail="Order not found.")

    status = data.status if data.status is not None else order["status"]
    batch = data.batch if data.batch is not None else order["batch"]
    payment_status = data.payment_status if data.payment_status is not None else order["payment_status"]

    cursor.execute(
        "UPDATE orders SET status = ?, batch = ?, payment_status = ? WHERE id = ?",
        (status, batch, payment_status, order_id),
    )
    conn.commit()
    conn.close()
    return {"id": order_id, "status": status, "batch": batch, "paymentStatus": payment_status}


if __name__ == "__main__":
    import uvicorn
    print("Starting Local Kart backend on http://127.0.0.1:8000 ...")
    print("Tip: Open two browser windows (Normal + Incognito) to test Customer & Store in real time.")
    uvicorn.run(app, host="0.0.0.0", port=8000)