"""CoreCloud Marketplace commerce API. Python standard library, SQLite, no third-party dependencies."""
import os, json, sqlite3, secrets, hashlib, hmac, time, re, threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DB=Path(os.environ.get('MARKETPLACE_DB',str(ROOT/'commerce'/'marketplace.sqlite3')))
HOST=os.environ.get('MARKETPLACE_HOST','127.0.0.1'); PORT=int(os.environ.get('PORT','8787'))
ADMIN_KEY=os.environ.get('MARKETPLACE_ADMIN_KEY','')
ORIGIN=os.environ.get('MARKETPLACE_ORIGIN','')
LOCK=threading.RLock()
def conn():
 c=sqlite3.connect(DB,timeout=10); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL'); return c
def init():
 DB.parent.mkdir(parents=True,exist_ok=True)
 with conn() as c:
  c.executescript("""CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,description TEXT NOT NULL,price_cents INTEGER NOT NULL CHECK(price_cents>=0),stock INTEGER NOT NULL CHECK(stock>=0),active INTEGER NOT NULL DEFAULT 0,image TEXT DEFAULT '',updated INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,email TEXT NOT NULL,customer TEXT NOT NULL,phone TEXT NOT NULL,province TEXT NOT NULL,programme TEXT NOT NULL,status TEXT NOT NULL,total_cents INTEGER NOT NULL,created INTEGER NOT NULL,lookup_hash TEXT NOT NULL,consent INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS order_items(order_id TEXT NOT NULL,product_id TEXT NOT NULL,product_name TEXT NOT NULL,quantity INTEGER NOT NULL,unit_cents INTEGER NOT NULL,FOREIGN KEY(order_id) REFERENCES orders(id));
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT NOT NULL,action TEXT NOT NULL,created INTEGER NOT NULL,details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS leads(id TEXT PRIMARY KEY,email TEXT NOT NULL,kind TEXT NOT NULL,details TEXT NOT NULL,created INTEGER NOT NULL);""")
  c.execute('CREATE TABLE IF NOT EXISTS reservations(order_id TEXT PRIMARY KEY, expires INTEGER NOT NULL, released INTEGER NOT NULL DEFAULT 0)')
  for col in ('address_line1','city','postal_code'):
   if col not in [r[1] for r in c.execute('PRAGMA table_info(orders)')]:
    c.execute('ALTER TABLE orders ADD COLUMN '+col+" TEXT NOT NULL DEFAULT ''")
  c.execute('CREATE INDEX IF NOT EXISTS idx_reservations_expiry ON reservations(expires,released)')
  if not c.execute('SELECT 1 FROM products LIMIT 1').fetchone():
   for id,name,cat,desc in [('thinkpad-t14','Lenovo ThinkPad T14','Professional','Refurbished business laptop; configuration to be confirmed'),('latitude-74','Dell Latitude 74-series','Professional','Premium refurbished laptop; configuration to be confirmed'),('thinkpad-l14','Lenovo ThinkPad L14','Everyday','Refurbished everyday laptop; configuration to be confirmed')]:
    c.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?)',(id,name,cat,desc,0,0,0,'',int(time.time())))
RESERVATION_SECONDS=int(os.environ.get('MARKETPLACE_RESERVATION_SECONDS','900'))
def expire_reservations():
 now=int(time.time())
 with LOCK,conn() as c:
  c.execute('BEGIN IMMEDIATE')
  rows=c.execute("SELECT r.order_id FROM reservations r JOIN orders o ON o.id=r.order_id WHERE r.expires<=? AND r.released=0 AND o.status IN ('awaiting_review','awaiting_payment')",(now,)).fetchall()
  for r in rows:
   oid=r['order_id']
   for it in c.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?',(oid,)):
    c.execute('UPDATE products SET stock=stock+? WHERE id=?',(it['quantity'],it['product_id']))
   c.execute('UPDATE reservations SET released=1 WHERE order_id=?',(oid,))
   c.execute("UPDATE orders SET status='expired' WHERE id=?",(oid,))
   c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(oid,'reservation_expired',now,'Unpaid reservation released'))
 return len(rows)
def valid_email(s):return isinstance(s,str) and len(s)<=254 and re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',s) is not None
def sfield(v,n=150):return isinstance(v,str) and 0<len(v.strip())<=n
class API(BaseHTTPRequestHandler):
 server_version='CoreCloudCommerce/1.0'
 def log_message(self,*args):pass
 def respond(self,code,obj):
  b=json.dumps(obj,separators=(',',':')).encode(); self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','no-referrer');self.end_headers();self.wfile.write(b)
 def body(self):
  if int(self.headers.get('Content-Length','0'))>16000:raise ValueError('Request too large')
  return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))) or b'{}')
 def admin(self):return bool(ADMIN_KEY) and hmac.compare_digest(self.headers.get('X-Admin-Key',''),ADMIN_KEY)
 def guard(self):
  if ORIGIN and self.headers.get('Origin') not in ('',ORIGIN):self.respond(403,{'error':'Origin not allowed'});return False
  return True
 def do_GET(self):
  path=urlparse(self.path).path
  if path=='/api/health':return self.respond(200,{'status':'ok','payments':'disabled','mode':'catalogue-and-reservation'})
  if path=='/api/products':
   expire_reservations()
   with conn() as c: rows=[dict(r) for r in c.execute('SELECT id,name,category,description,price_cents,stock,image FROM products WHERE active=1 AND stock>0 ORDER BY name')]
   return self.respond(200,{'products':rows,'currency':'ZAR','prices_include_vat':True})
  if path=='/api/admin/products':
   if not self.admin():return self.respond(403,{'error':'Forbidden'})
   with conn() as c: rows=[dict(r) for r in c.execute('SELECT * FROM products ORDER BY name')]
   return self.respond(200,{'products':rows})
  if path=='/api/admin/orders':
   if not self.admin():return self.respond(403,{'error':'Forbidden'})
   with conn() as c: rows=[dict(r) for r in c.execute('SELECT id,email,customer,phone,province,programme,status,total_cents,created FROM orders ORDER BY created DESC LIMIT 200')]
   return self.respond(200,{'orders':rows})
  return self.respond(404,{'error':'Not found'})
 def do_POST(self):
  if not self.guard():return
  path=urlparse(self.path).path
  try: data=self.body()
  except (ValueError,json.JSONDecodeError):return self.respond(400,{'error':'Invalid JSON or size'})
  if path=='/api/admin/product':
   if not self.admin():return self.respond(403,{'error':'Forbidden'})
   if not sfield(data.get('id'),64) or not re.fullmatch('[a-z0-9-]+',data['id']) or not sfield(data.get('name')) or not sfield(data.get('category')) or not sfield(data.get('description'),1000):return self.respond(400,{'error':'Invalid product'})
   price=data.get('price_cents');stock=data.get('stock');active=data.get('active')
   if type(price)!=int or type(stock)!=int or price<0 or stock<0 or type(active)!=bool:return self.respond(400,{'error':'Invalid stock, price or active'})
   with LOCK,conn() as c:c.execute('INSERT INTO products(id,name,category,description,price_cents,stock,active,image,updated) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,category=excluded.category,description=excluded.description,price_cents=excluded.price_cents,stock=excluded.stock,active=excluded.active,updated=excluded.updated',(data['id'],data['name'],data['category'],data['description'],price,stock,int(active),'',int(time.time())))
   return self.respond(200,{'ok':True})
  if path=='/api/orders':
   expire_reservations()
   if not valid_email(data.get('email')) or not all(sfield(data.get(x)) for x in ('customer','phone','province','address_line1','city','postal_code')) or data.get('consent') is not True:return self.respond(400,{'error':'Customer information and consent required'})
   items=data.get('items'); programme=data.get('programme','General')
   if not isinstance(items,list) or not 1<=len(items)<=15 or not sfield(programme,80):return self.respond(400,{'error':'Invalid basket'})
   qty={}
   for item in items:
    if not isinstance(item,dict) or not sfield(item.get('id'),64) or type(item.get('quantity'))!=int or not 1<=item['quantity']<=10:return self.respond(400,{'error':'Invalid item'})
    qty[item['id']]=qty.get(item['id'],0)+item['quantity']
   if any(v>10 for v in qty.values()):return self.respond(400,{'error':'Quantity limit exceeded'})
   order='CCM-'+secrets.token_hex(6).upper();token=secrets.token_urlsafe(24);total=0
   with LOCK,conn() as c:
    try:
     c.execute('BEGIN IMMEDIATE');lines=[]
     for pid,q in qty.items():
      product=c.execute('SELECT * FROM products WHERE id=? AND active=1',(pid,)).fetchone()
      if not product or product['stock']<q or product['price_cents']<=0:raise ValueError('Product unavailable: '+pid)
      lines.append((pid,product['name'],q,product['price_cents']));total+=q*product['price_cents']
     now=int(time.time());c.execute('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)',(order,data['email'].strip().lower(),data['customer'].strip(),data['phone'].strip(),data['province'].strip(),programme,'awaiting_review',total,now,hashlib.sha256(token.encode()).hexdigest(),1))
     c.execute('UPDATE orders SET address_line1=?,city=?,postal_code=? WHERE id=?',(data['address_line1'].strip(),data['city'].strip(),data['postal_code'].strip(),order))
     c.execute('INSERT INTO reservations(order_id,expires) VALUES(?,?)',(order,now+RESERVATION_SECONDS))
     for pid,name,q,price in lines:
      c.execute('UPDATE products SET stock=stock-? WHERE id=?',(q,pid));c.execute('INSERT INTO order_items VALUES(?,?,?,?,?)',(order,pid,name,q,price))
     c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(order,'reserved',now,'Pending manual confirmation; no payment collected'))
     c.commit()
    except ValueError as e:c.rollback();return self.respond(409,{'error':str(e)})
   return self.respond(201,{'order_id':order,'lookup_token':token,'total_cents':total,'status':'awaiting_review','reservation_expires':now+RESERVATION_SECONDS,'payment':'No payment taken; team will confirm availability and invoice'})
  if path=='/api/order/status':
   expire_reservations()
   order=data.get('order_id','');token=data.get('lookup_token','')
   if not sfield(order,40) or not sfield(token,100):return self.respond(400,{'error':'Invalid lookup'})
   with conn() as c:r=c.execute('SELECT id,status,total_cents,created FROM orders WHERE id=? AND lookup_hash=?',(order,hashlib.sha256(token.encode()).hexdigest())).fetchone()
   return self.respond(200,{'order':dict(r)}) if r else self.respond(404,{'error':'Order not found'})
  if path=='/api/admin/status':
   if not self.admin():return self.respond(403,{'error':'Forbidden'})
   order=data.get('order_id');status=data.get('status')
   transitions={'awaiting_review':{'confirmed','cancelled'},'confirmed':{'awaiting_payment','cancelled'},'awaiting_payment':{'cancelled'},'paid_sandbox':{'fulfilling'},'fulfilling':{'dispatched'},'dispatched':{'completed'}}
   if not sfield(order,40) or not isinstance(status,str):return self.respond(400,{'error':'Invalid status'})
   with LOCK,conn() as c:
    c.execute('BEGIN IMMEDIATE')
    row=c.execute('SELECT status FROM orders WHERE id=?',(order,)).fetchone()
    if not row:return self.respond(404,{'error':'Not found'})
    if status not in transitions.get(row['status'],set()):return self.respond(409,{'error':'Invalid order transition','from':row['status'],'to':status})
    if status=='fulfilling':
     supplier=c.execute('SELECT status FROM supplier_orders WHERE order_id=?',(order,)).fetchone()
     if not supplier or supplier['status']!='accepted':return self.respond(409,{'error':'Supplier acceptance required'})
    c.execute('UPDATE orders SET status=? WHERE id=?',(status,order))
    c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(order,'status_changed',int(time.time()),status))
    if status=='cancelled':
     r=c.execute('SELECT released FROM reservations WHERE order_id=?',(order,)).fetchone()
     if r and not r['released']:
      for it in c.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?',(order,)):
       c.execute('UPDATE products SET stock=stock+? WHERE id=?',(it['quantity'],it['product_id']))
      c.execute('UPDATE reservations SET released=1 WHERE order_id=?',(order,))
   return self.respond(200,{'ok':True})
  return self.respond(404,{'error':'Not found'})
if __name__=='__main__':
 init();print('Commerce API on',HOST,PORT,'(payments disabled)');ThreadingHTTPServer((HOST,PORT),API).serve_forever()
