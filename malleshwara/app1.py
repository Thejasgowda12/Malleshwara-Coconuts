"""Malleshwara Coconuts - Import/Export Portal (Flask + SQLite)
Run:  pip install -r requirements.txt && python app.py   ->  http://127.0.0.1:5000
"""
import sqlite3, os
from functools import wraps
from flask import Flask, g, request, session, redirect, url_for, flash, render_template_string
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-in-production")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1")
DB = os.path.join(os.path.dirname(__file__), "malleshwara.db")
STATUSES = ["Pending", "Confirmed", "Processing", "Shipped", "Delivered", "Cancelled"]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db
@app.teardown_appcontext
def close(e=None):
    d = g.pop("db", None)
    if d: d.close()
def q(sql, a=(), one=False):
    r = db().execute(sql, a).fetchall(); return (r[0] if r else None) if one else r
def x(sql, a=()):
    c = db().execute(sql, a); db().commit(); return c.lastrowid

def init():
    c = sqlite3.connect(DB)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE, password TEXT,
      role TEXT, phone TEXT, country TEXT, company TEXT, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT, local_name TEXT, description TEXT,
      unit TEXT, price REAL, stock INTEGER, active INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT DEFAULT 'Pending',
      country TEXT, notes TEXT, total REAL, created TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, name TEXT,
      unit TEXT, qty INTEGER, price REAL);
    CREATE TABLE IF NOT EXISTS settings(k TEXT PRIMARY KEY, v TEXT);""")
    if not c.execute("SELECT 1 FROM users").fetchone():
        for n, e, p, r in [("Yashas H M", "superadmin@malleshwara.com", "Super@123", "superadmin"),
                           ("Thejas H S", "admin@malleshwara.com", "Admin@123", "admin"),
                           ("Demo Buyer", "buyer@example.com", "User@123", "user")]:
            c.execute("INSERT INTO users(name,email,password,role,country) VALUES(?,?,?,?,?)",
                      (n, e, generate_password_hash(p), r, "India"))
        for p in [("Coconut (Mature, Husked)", "Kayi", "Farm-fresh mature coconuts from Hassan, graded by size.", "1000 nuts", 24000, 500),
                  ("Copra (Milling / Ball)", "Kobbari", "Sun-dried, low-moisture copra for oil and edible use.", "Quintal", 14500, 300),
                  ("Dry Coconut Halves", "Kayi", "Clean dried halves, export-grade packing.", "Quintal", 12000, 200),
                  ("Coconut Shells", "Kayi Chippu", "Hard shells for activated carbon, fuel and crafts.", "Tonne", 9000, 150)]:
            c.execute("INSERT INTO products(name,local_name,description,unit,price,stock) VALUES(?,?,?,?,?,?)", p)
        for k, v in {"tagline": "Four decades of trust in every coconut.", "announcement": "Now accepting international export enquiries.",
                     "phone": "+91 00000 00000", "email": "info@malleshwaracoconuts.com",
                     "ordering_enabled": "1", "registration_enabled": "1"}.items():
            c.execute("INSERT INTO settings VALUES(?,?)", (k, v))
    c.commit(); c.close()

@app.context_processor
def inject():
    s = {r["k"]: r["v"] for r in q("SELECT * FROM settings")}
    return dict(S=s, me=session.get("name"), role=session.get("role"))

def need(*roles):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if session.get("role") not in roles:
                flash("Please sign in with the correct account."); return redirect(url_for("login", r=roles[0]))
            return f(*a, **k)
        return w
    return deco
def S(k): return q("SELECT v FROM settings WHERE k=?", (k,), True)["v"]
HOME = {"superadmin": "sa", "admin": "admin", "user": "shop"}

@app.route("/")
def home():
    return render_template_string(T["home"], products=q("SELECT * FROM products WHERE active=1"))

@app.route("/login", methods=["GET", "POST"])
def login():
    r = request.values.get("r", "user")
    if r not in HOME:
        r = "user"
    if request.method == "POST":
        r = request.form.get("r", r)
        if r not in HOME:
            r = "user"
        u = q("SELECT * FROM users WHERE email=? AND role=?", (request.form["email"].strip().lower(), r), True)
        if u and u["active"] and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], role=u["role"], name=u["name"])
            return redirect(url_for(HOME[r]))
        flash("Invalid credentials or account disabled.")
    return render_template_string(T["login"], r=r)

@app.route("/register", methods=["GET", "POST"])
def register():
    if S("registration_enabled") != "1":
        flash("Registration is currently closed."); return redirect(url_for("login"))
    if request.method == "POST":
        f = request.form
        try:
            x("INSERT INTO users(name,email,password,role,phone,country,company) VALUES(?,?,?,?,?,?,?)",
              (f["name"], f["email"].strip().lower(), generate_password_hash(f["password"]), "user", f["phone"], f["country"], f["company"]))
            flash("Account created. Please sign in."); return redirect(url_for("login", r="user"))
        except sqlite3.IntegrityError:
            flash("That email is already registered.")
    return render_template_string(T["register"])

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

# ---------- USER ----------
@app.route("/shop", methods=["GET", "POST"])
@need("user")
def shop():
    if request.method == "POST":
        if S("ordering_enabled") != "1":
            flash("Ordering is temporarily paused."); return redirect(url_for("shop"))
        lines, total = [], 0
        for p in q("SELECT * FROM products WHERE active=1"):
            try: n = int(request.form.get(f"q{p['id']}") or 0)
            except ValueError: n = 0
            if n > 0:
                if n > p["stock"]: flash(f"Only {p['stock']} {p['unit']} of {p['name']} in stock."); return redirect(url_for("shop"))
                lines.append((p, n)); total += n * p["price"]
        if not lines: flash("Add a quantity to at least one product."); return redirect(url_for("shop"))
        oid = x("INSERT INTO orders(user_id,country,notes,total) VALUES(?,?,?,?)",
                (session["uid"], request.form["country"], request.form["notes"], total))
        for p, n in lines:
            x("INSERT INTO items(order_id,product_id,name,unit,qty,price) VALUES(?,?,?,?,?,?)", (oid, p["id"], p["name"], p["unit"], n, p["price"]))
            x("UPDATE products SET stock=stock-? WHERE id=?", (n, p["id"]))
        flash(f"Order #{oid} placed successfully."); return redirect(url_for("my_orders"))
    return render_template_string(T["shop"], products=q("SELECT * FROM products WHERE active=1"),
                                  u=q("SELECT * FROM users WHERE id=?", (session["uid"],), True))

def orders_with_items(where="", a=()):
    os_ = q(f"SELECT o.*, u.name uname, u.email, u.company FROM orders o JOIN users u ON u.id=o.user_id {where} ORDER BY o.id DESC", a)
    return [(o, q("SELECT * FROM items WHERE order_id=?", (o["id"],))) for o in os_]

@app.route("/my-orders")
@need("user")
def my_orders():
    return render_template_string(T["orders"], data=orders_with_items("WHERE o.user_id=?", (session["uid"],)), manage=False, title="My Orders")

# ---------- ADMIN ----------
@app.route("/admin")
@need("admin", "superadmin")
def admin():
    st = request.args.get("status")
    data = orders_with_items("WHERE o.status=?", (st,)) if st else orders_with_items()
    cust = q("SELECT u.*, (SELECT COUNT(*) FROM orders WHERE user_id=u.id) n FROM users u WHERE role='user'")
    return render_template_string(T["orders"], data=data, manage=True, title="Order Desk", cust=cust, statuses=STATUSES)

@app.post("/admin/status/<int:oid>")
@need("admin", "superadmin")
def set_status(oid):
    x("UPDATE orders SET status=? WHERE id=?", (request.form["status"], oid)); flash(f"Order #{oid} updated.")
    return redirect(url_for("admin"))

# ---------- SUPER ADMIN ----------
@app.route("/sa")
@need("superadmin")
def sa():
    stats = dict(users=q("SELECT COUNT(*) c FROM users WHERE role='user'", one=True)["c"],
                 orders=q("SELECT COUNT(*) c FROM orders", one=True)["c"],
                 revenue=q("SELECT COALESCE(SUM(total),0) c FROM orders WHERE status!='Cancelled'", one=True)["c"],
                 pending=q("SELECT COUNT(*) c FROM orders WHERE status='Pending'", one=True)["c"])
    return render_template_string(T["sa"], stats=stats, products=q("SELECT * FROM products"),
                                  staff=q("SELECT * FROM users WHERE role!='user'"), users=q("SELECT * FROM users WHERE role='user'"))

@app.post("/sa/settings")
@need("superadmin")
def sa_settings():
    for k in ("tagline", "announcement", "phone", "email"): x("REPLACE INTO settings VALUES(?,?)", (k, request.form[k]))
    for k in ("ordering_enabled", "registration_enabled"): x("REPLACE INTO settings VALUES(?,?)", (k, "1" if request.form.get(k) else "0"))
    flash("Settings saved - changes are live for admins and users."); return redirect(url_for("sa"))

@app.post("/sa/product")
@need("superadmin")
def sa_product():
    f = request.form; pid = f.get("id")
    vals = (f["name"], f["local_name"], f["description"], f["unit"], float(f["price"]), int(f["stock"]), 1 if f.get("active") else 0)
    if pid: x("UPDATE products SET name=?,local_name=?,description=?,unit=?,price=?,stock=?,active=? WHERE id=?", vals + (pid,))
    else: x("INSERT INTO products(name,local_name,description,unit,price,stock,active) VALUES(?,?,?,?,?,?,?)", vals)
    flash("Product saved."); return redirect(url_for("sa") + "#products")

@app.post("/sa/staff")
@need("superadmin")
def sa_staff():
    f = request.form
    try:
        x("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", (f["name"], f["email"].lower(), generate_password_hash(f["password"]), f["role"]))
        flash("Staff account created.")
    except sqlite3.IntegrityError: flash("Email already exists.")
    return redirect(url_for("sa") + "#people")

@app.post("/sa/toggle/<int:uid>")
@need("superadmin")
def sa_toggle(uid):
    if uid != session["uid"]: x("UPDATE users SET active=1-active WHERE id=?", (uid,))
    return redirect(url_for("sa") + "#people")

# ---------- TEMPLATES ----------
BASE = """<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Malleshwara Coconuts</title>
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700&family=Inter:wght@400;500;600&display=swap" rel=stylesheet>
<style>
:root{--g:#0f3d2e;--g2:#165a43;--gold:#c9a24b;--cream:#f7f2e7;--ink:#1c2420;--mut:#6b756f}
*{box-sizing:border-box}body{margin:0;font-family:Inter,sans-serif;color:var(--ink);background:var(--cream)}
h1,h2,h3,.brand{font-family:'Playfair Display',serif}a{color:inherit;text-decoration:none}
nav{display:flex;justify-content:space-between;align-items:center;padding:16px 6vw;background:var(--g);color:#fff;position:sticky;top:0;z-index:9}
.brand{font-size:22px;color:var(--gold)}nav a{margin-left:20px;font-size:14px;opacity:.9}
.btn{display:inline-block;background:var(--gold);color:#1a1405;padding:11px 22px;border-radius:30px;border:0;font-weight:600;cursor:pointer;font-size:14px}
.btn.o{background:none;border:1px solid var(--gold);color:var(--gold)}.btn.s{padding:6px 14px;font-size:12px}
.ann{background:var(--gold);text-align:center;padding:8px;font-size:13px;font-weight:500}
.hero{background:linear-gradient(120deg,rgba(15,61,46,.93),rgba(22,90,67,.8)),radial-gradient(circle at 80% 20%,#c9a24b55,transparent 50%);color:#fff;padding:110px 6vw;background-color:var(--g)}
.hero h1{font-size:clamp(36px,6vw,66px);margin:0 0 16px;max-width:760px;line-height:1.1}.hero p{max-width:560px;opacity:.85;line-height:1.7}
.sec{padding:70px 6vw}.sec h2{font-size:34px;margin:0 0 8px;color:var(--g)}.sub{color:var(--mut);margin-bottom:34px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:22px}
.card{background:#fff;border-radius:16px;padding:24px;box-shadow:0 6px 24px #0f3d2e14;border:1px solid #0f3d2e10}
.card h3{margin:0 0 6px;color:var(--g)}.tag{font-size:12px;color:var(--gold);font-weight:600;letter-spacing:1px;text-transform:uppercase}
.dark{background:var(--g);color:#fff}.dark h2{color:var(--gold)}.stat b{font-size:34px;font-family:'Playfair Display';color:var(--gold);display:block}
.wrap{max-width:1150px;margin:0 auto;padding:30px 5vw}table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:14px}
th{background:var(--g);color:#fff;text-align:left;font-weight:500}td,th{padding:11px 14px;border-bottom:1px solid #eee;vertical-align:top}
input,select,textarea{width:100%;padding:11px;border:1px solid #d6d2c4;border-radius:10px;font:inherit;background:#fff;margin:4px 0 12px}
label{font-size:12px;font-weight:600;color:var(--mut)}.flash{background:#fff7dd;border-left:4px solid var(--gold);padding:12px 16px;margin:14px 6vw;border-radius:8px}
.auth{max-width:430px;margin:50px auto;background:#fff;padding:36px;border-radius:20px;box-shadow:0 20px 50px #0f3d2e22}
.tabs{display:flex;gap:6px;margin-bottom:22px;background:var(--cream);padding:5px;border-radius:30px}.tabs a{flex:1;text-align:center;padding:9px;border-radius:30px;font-size:13px;font-weight:600}.tabs a.on{background:var(--g);color:#fff}
.pill{padding:3px 10px;border-radius:20px;background:#e6efe9;color:var(--g);font-size:12px;font-weight:600}
.row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.mini{font-size:12px;color:var(--mut)}
footer{background:#0a2a20;color:#cfd8d3;padding:40px 6vw;font-size:14px;line-height:1.8}
</style></head><body>
<nav><a href="/" class=brand>🥥 Malleshwara Coconuts</a><div>
{% if role %}<a href="/{{ {'superadmin':'sa','admin':'admin','user':'shop'}[role] }}">Dashboard</a>{% if role=='user' %}<a href="/my-orders">My Orders</a>{% endif %}<a href="/logout">Logout ({{me}})</a>
{% else %}<a href="/#products">Products</a><a href="/#about">About</a><a href="/#contact">Contact</a><a href="/login?r=user" class="btn s">Sign in</a>{% endif %}</div></nav>
{% for m in get_flashed_messages() %}<div class=flash>{{m}}</div>{% endfor %}
{% block c %}{% endblock %}</body></html>"""

T = {"base": BASE}
T["home"] = """{% extends 'base' %}{% block c %}
{% if S.announcement %}<div class=ann>{{S.announcement}}</div>{% endif %}
<section class=hero><span class=tag>Est. 1980s · Hassan, Karnataka</span><h1>Premium coconuts, copra &amp; shells for the world.</h1>
<p>{{S.tagline}} From the heart of Karnataka's coconut belt, Malleshwara Coconuts now supplies international buyers with consistent quality, honest pricing and reliable export handling.</p><br>
<a class=btn href="/register">Request Trade Account</a> &nbsp;<a class="btn o" href="#products">View Products</a></section>
<section class="sec dark"><div class=grid>
<div class=stat><b>40+</b>Years in trade</div><div class=stat><b>4</b>Core product lines</div><div class=stat><b>Global</b>Import &amp; export</div><div class=stat><b>Hassan</b>Karnataka, India</div></div></section>
<section class=sec id=products><h2>Our Products</h2><div class=sub>Kayi · Kobbari · Coconut · Shells — sourced directly, graded carefully.</div>
<div class=grid>{% for p in products %}<div class=card><span class=tag>{{p.local_name}}</span><h3>{{p.name}}</h3><p class=mini>{{p.description}}</p><b>₹{{'{:,.0f}'.format(p.price)}}</b> <span class=mini>/ {{p.unit}}</span></div>{% endfor %}</div></section>
<section class=sec id=about style="background:#fff"><h2>Built on four decades of trust</h2><div class=sub>A family trading house now opening its doors to international partners.</div>
<div class=grid><div class=card><span class=tag>Founder</span><h3>Yashas H M</h3><p class=mini>Leads the legacy and vision of Malleshwara Coconuts.</p></div>
<div class=card><span class=tag>Partner</span><h3>Thejas H S</h3><p class=mini>Drives operations and the international expansion.</p></div></div></section>
<footer id=contact><b class=brand style="color:#c9a24b;font-size:20px">Malleshwara Coconuts</b><br>80 Feet Road, near Nayara Petrol Bunk, Hassan, Karnataka – 573201<br>
📞 {{S.phone}} · ✉ {{S.email}}<br><br>© Malleshwara Coconuts. All rights reserved.</footer>{% endblock %}"""
T["login"] = """{% extends 'base' %}{% block c %}<div class=auth><h2 style="margin-top:0;color:#0f3d2e">Welcome back</h2>
<div class=tabs>{% for k,l in [('user','Customer'),('admin','Admin'),('superadmin','Super Admin')] %}<a href="/login?r={{k}}" class="{{'on' if r==k}}">{{l}}</a>{% endfor %}</div>
<form method=post><input type=hidden name=r value="{{r}}"><label>EMAIL</label><input name=email type=email required><label>PASSWORD</label><input name=password type=password required>
<button class=btn style="width:100%">Sign in as {{r|replace('superadmin','super admin')|title}}</button></form>
{% if r=='user' %}<p class=mini style="text-align:center">New buyer? <a href="/register"><u>Create trade account</u></a></p>{% endif %}</div>{% endblock %}"""
T["register"] = """{% extends 'base' %}{% block c %}<div class=auth><h2 style="margin-top:0;color:#0f3d2e">Create trade account</h2><form method=post>
<label>FULL NAME</label><input name=name required><label>COMPANY</label><input name=company><label>EMAIL</label><input name=email type=email required>
<label>PHONE</label><input name=phone><label>COUNTRY</label><input name=country required><label>PASSWORD</label><input name=password type=password minlength=6 required>
<button class=btn style="width:100%">Register</button></form></div>{% endblock %}"""
T["shop"] = """{% extends 'base' %}{% block c %}<div class=wrap><h2>Place an Order</h2>
{% if S.ordering_enabled!='1' %}<div class=flash>Ordering is temporarily paused.</div>{% endif %}
<form method=post><table><tr><th>Product</th><th>Price</th><th>In stock</th><th style="width:130px">Quantity</th></tr>
{% for p in products %}<tr><td><b>{{p.name}}</b><br><span class=mini>{{p.local_name}} · {{p.description}}</span></td><td>₹{{'{:,.0f}'.format(p.price)}} / {{p.unit}}</td><td>{{p.stock}}</td>
<td><input type=number min=0 max="{{p.stock}}" name="q{{p.id}}" value=0 style="margin:0"></td></tr>{% endfor %}</table><br>
<div class=row><div><label>DESTINATION COUNTRY</label><input name=country value="{{u.country or ''}}" required></div></div>
<label>NOTES (packing, port, delivery terms)</label><textarea name=notes rows=3></textarea><button class=btn>Submit Order</button></form></div>{% endblock %}"""
T["orders"] = """{% extends 'base' %}{% block c %}<div class=wrap><h2>{{title}}</h2>
{% if manage %}<p>{% for s in statuses %}<a class="pill" style="margin-right:6px" href="/admin?status={{s}}">{{s}}</a>{% endfor %}<a class=pill href="/admin">All</a></p>{% endif %}
<table><tr><th>#</th>{% if manage %}<th>Customer</th>{% endif %}<th>Items (qty)</th><th>Destination</th><th>Total</th><th>Status</th></tr>
{% for o,its in data %}<tr><td>{{o.id}}<br><span class=mini>{{o.created[:10]}}</span></td>
{% if manage %}<td>{{o.uname}}<br><span class=mini>{{o.company or ''}} {{o.email}}</span></td>{% endif %}
<td>{% for i in its %}{{i.name}} — <b>{{i.qty}}</b> {{i.unit}}<br>{% endfor %}{% if o.notes %}<span class=mini>Note: {{o.notes}}</span>{% endif %}</td>
<td>{{o.country}}</td><td>₹{{'{:,.0f}'.format(o.total)}}</td>
<td>{% if manage %}<form method=post action="/admin/status/{{o.id}}"><select name=status onchange="this.form.submit()" style="margin:0">{% for s in statuses %}<option {{'selected' if s==o.status}}>{{s}}</option>{% endfor %}</select></form>
{% else %}<span class=pill>{{o.status}}</span>{% endif %}</td></tr>{% else %}<tr><td colspan=6>No orders yet.</td></tr>{% endfor %}</table>
{% if manage %}<h2 style="margin-top:40px">Customers</h2><table><tr><th>Name</th><th>Company</th><th>Email</th><th>Country</th><th>Orders</th></tr>
{% for c in cust %}<tr><td>{{c.name}}</td><td>{{c.company or '-'}}</td><td>{{c.email}}</td><td>{{c.country}}</td><td>{{c.n}}</td></tr>{% endfor %}</table>{% endif %}</div>{% endblock %}"""
T["sa"] = """{% extends 'base' %}{% block c %}<div class=wrap><h2>Super Admin Control Centre</h2>
<div class=grid>{% for l,v in [('Customers',stats.users),('Orders',stats.orders),('Pending',stats.pending),('Revenue','₹{:,.0f}'.format(stats.revenue))] %}<div class="card stat"><span class=mini>{{l}}</span><b style="color:#0f3d2e">{{v}}</b></div>{% endfor %}</div>
<p><a class=btn href="/admin">Open Order Desk →</a></p>
<h3>Site Settings <span class=mini>(live for admins &amp; customers)</span></h3><form method=post action="/sa/settings" class=card>
<div class=row><div><label>TAGLINE</label><input name=tagline value="{{S.tagline}}"></div><div><label>ANNOUNCEMENT BANNER</label><input name=announcement value="{{S.announcement}}"></div>
<div><label>PHONE</label><input name=phone value="{{S.phone}}"></div><div><label>EMAIL</label><input name=email value="{{S.email}}"></div></div>
<label><input type=checkbox name=ordering_enabled style="width:auto" {{'checked' if S.ordering_enabled=='1'}}> Ordering enabled</label> &nbsp;
<label><input type=checkbox name=registration_enabled style="width:auto" {{'checked' if S.registration_enabled=='1'}}> Registration open</label><br><br><button class="btn s">Save settings</button></form>
<h3 id=products>Products &amp; Pricing</h3>
{% for p in products %}<form method=post action="/sa/product" class=card style="margin-bottom:10px"><input type=hidden name=id value="{{p.id}}"><div class=row>
<div><label>NAME</label><input name=name value="{{p.name}}"></div><div><label>LOCAL NAME</label><input name=local_name value="{{p.local_name}}"></div><div><label>UNIT</label><input name=unit value="{{p.unit}}"></div>
<div><label>PRICE ₹</label><input name=price value="{{p.price}}"></div><div><label>STOCK</label><input name=stock value="{{p.stock}}"></div></div>
<input name=description value="{{p.description}}"><label><input type=checkbox name=active style="width:auto" {{'checked' if p.active}}> Visible</label> <button class="btn s">Update</button></form>{% endfor %}
<form method=post action="/sa/product" class=card style="border:2px dashed #c9a24b"><b>+ Add product</b><div class=row><input name=name placeholder=Name required><input name=local_name placeholder="Local name"><input name=unit placeholder=Unit required>
<input name=price placeholder=Price required><input name=stock placeholder=Stock value=0></div><input name=description placeholder=Description><input type=hidden name=active value=1><button class="btn s">Add</button></form>
<h3 id=people>Staff &amp; Access</h3><table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr>
{% for s in staff %}<tr><td>{{s.name}}</td><td>{{s.email}}</td><td>{{s.role}}</td><td>{{'Active' if s.active else 'Disabled'}}</td><td><form method=post action="/sa/toggle/{{s.id}}"><button class="btn s">Toggle</button></form></td></tr>{% endfor %}</table>
<form method=post action="/sa/staff" class=card style="margin-top:12px"><b>Create staff account</b><div class=row><input name=name placeholder=Name required><input name=email type=email placeholder=Email required><input name=password placeholder=Password required>
<select name=role><option>admin</option><option>superadmin</option></select></div><button class="btn s">Create</button></form>
<h3>Customer Accounts</h3><table><tr><th>Name</th><th>Email</th><th>Country</th><th>Status</th><th></th></tr>
{% for s in users %}<tr><td>{{s.name}}</td><td>{{s.email}}</td><td>{{s.country}}</td><td>{{'Active' if s.active else 'Blocked'}}</td><td><form method=post action="/sa/toggle/{{s.id}}"><button class="btn s">Block/Unblock</button></form></td></tr>{% endfor %}</table></div>{% endblock %}"""
app.jinja_loader = DictLoader(T)
init()

if __name__ == "__main__":
    # Bind to all network interfaces so this demo can be opened from another device.
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
