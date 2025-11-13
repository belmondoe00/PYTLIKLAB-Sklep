import os
from datetime import datetime
from flask import Flask, request, jsonify, session, abort
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

# --- Konfiguracja ---
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'shop.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'bardzo-tajny-klucz-do-sesji'

db = SQLAlchemy(app)

# --- Nagłówki Bezpieczeństwa (Wymaganie niefunkcjonalne) ---
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# --- Modele Danych ---

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'price': self.price}

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_price = db.Column(db.Float, default=0.0)

    items = db.relationship('OrderItem', back_populates='order')

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat(),
            'total_price': self.total_price,
            'items': [item.to_dict() for item in self.items]
        }

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    qty = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False) 

    order = db.relationship('Order', back_populates='items')
    product = db.relationship('Product')

    def to_dict(self):
        return {
            'product_name': self.product.name,
            'qty': self.qty,
            'price': self.price,
            'line_total': self.qty * self.price
        }

# --- API: Produkty ---

@app.route('/api/products', methods=['GET'])
def get_products():
    products = Product.query.all()
    return jsonify([p.to_dict() for p in products])

@app.route('/api/products', methods=['POST'])
def add_product():
    data = request.get_json()
    if not data or 'name' not in data or 'price' not in data:
        return jsonify({'error': 'Missing name or price'}), 400
    
    if data['price'] < 0:
         return jsonify({'error': 'Price must be >= 0'}), 400

    new_product = Product(name=data['name'], price=data['price'])
    db.session.add(new_product)
    db.session.commit()
    
    response = jsonify(new_product.to_dict())
    response.status_code = 201
    response.headers['Location'] = f'/api/products/{new_product.id}'
    return response

# --- API: Koszyk (Session) ---

@app.route('/api/cart', methods=['GET'])
def get_cart():
    cart_session = session.get('cart', {})
    cart_items = []
    total = 0
    
    for p_id_str, qty in cart_session.items():
        product = Product.query.get(int(p_id_str))
        if product:
            line_total = product.price * qty
            total += line_total
            cart_items.append({
                'product_id': product.id,
                'name': product.name,
                'price': product.price,
                'qty': qty,
                'line_total': line_total
            })
            
    return jsonify({'items': cart_items, 'total': total})

@app.route('/api/cart/add', methods=['POST'])
def add_to_cart():
    data = request.get_json()
    if not data or 'product_id' not in data or 'qty' not in data:
        return jsonify({'error': 'Missing product_id or qty'}), 400
        
    p_id = str(data['product_id'])
    qty = int(data['qty'])
    
    if qty < 1:
        return jsonify({'error': 'Qty must be >= 1'}), 400

    if not Product.query.get(data['product_id']):
        return jsonify({'error': 'Product not found'}), 404

    cart = session.get('cart', {})
    
    if p_id in cart:
        cart[p_id] += qty
    else:
        cart[p_id] = qty
        
    session['cart'] = cart 
    return jsonify({'message': 'Added to cart', 'cart': cart}), 200

@app.route('/api/cart/item', methods=['PATCH'])
def update_cart_item():
    data = request.get_json()
    p_id = str(data.get('product_id'))
    qty = int(data.get('qty', 0))

    if qty < 1:
        return jsonify({'error': 'Qty must be >= 1'}), 400
        
    cart = session.get('cart', {})
    
    if p_id in cart:
        cart[p_id] = qty
        session['cart'] = cart
        return jsonify({'message': 'Updated'}), 200
    else:
        return jsonify({'error': 'Item not in cart'}), 404

@app.route('/api/cart/item/<int:product_id>', methods=['DELETE'])
def delete_from_cart(product_id):
    cart = session.get('cart', {})
    p_id = str(product_id)
    
    if p_id in cart:
        del cart[p_id]
        session['cart'] = cart
        return jsonify({'message': 'Deleted'}), 200
    else:
        return jsonify({'error': 'Item not in cart'}), 404

# --- API: Checkout (Zamówienie) ---

@app.route('/api/checkout', methods=['POST'])
def checkout():
    cart = session.get('cart', {})
    
    if not cart:
        return jsonify({'error': 'Cart is empty'}), 400
        
    new_order = Order()
    db.session.add(new_order)
    
    total_order_price = 0
    
    for p_id_str, qty in cart.items():
        product = Product.query.get(int(p_id_str))
        if product:
            item = OrderItem(
                order=new_order,
                product=product,
                qty=qty,
                price=product.price 
            )
            total_order_price += (product.price * qty)
            db.session.add(item)
            
    new_order.total_price = total_order_price
    db.session.commit()
    
    session['cart'] = {}
    
    response = jsonify({'order_id': new_order.id, 'total': total_order_price})
    response.status_code = 201
    return response

# --- UI ---
@app.route('/')
def index():
    if not os.path.exists('static'):
        os.makedirs('static')
    return app.send_static_file('index.html')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        if not Product.query.first():
            db.session.add(Product(name="Chleb", price=5.50))
            db.session.add(Product(name="Mleko", price=3.20))
            db.session.add(Product(name="Ser", price=12.99))
            db.session.commit()
            print("Dodano przykładowe produkty.")

    app.run(debug=True, port=5000)