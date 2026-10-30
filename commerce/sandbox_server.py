"""PayFast sandbox-only checkout extension. Never processes live money."""
import os, json, hmac, hashlib, ipaddress, socket, urllib.parse, urllib.request, urllib.error, time
from http.server import ThreadingHTTPServer
import server as base
from reworks_adapter import ReWorksClient, SupplierUnavailable

SANDBOX_HOST='https://sandbox.payfast.co.za'
MERCHANT_ID=os.environ.get('PAYFAST_SANDBOX_MERCHANT_ID','10000100')
MERCHANT_KEY=os.environ.get('PAYFAST_SANDBOX_MERCHANT_KEY','46f0cd694581a')
PASSPHRASE=os.environ.get('PAYFAST_SANDBOX_PASSPHRASE','jt7NOE43FZPn')
PUBLIC_API_URL=os.environ.get('MARKETPLACE_PUBLIC_API_URL','').rstrip('/')
PUBLIC_SITE_URL=os.environ.get('MARKETPLACE_PUBLIC_SITE_URL','').rstrip('/')
PAYFAST_HOSTS=('sandbox.payfast.co.za','www.payfast.co.za','w1w.payfast.co.za','w2w.payfast.co.za')

def signature(data,passphrase):
    pairs=[(k,str(v).strip()) for k,v in data.items() if k!='signature' and v is not None and str(v).strip()!='']
    raw=urllib.parse.urlencode(pairs,quote_via=urllib.parse.quote_plus)
    if passphrase:raw+='&passphrase='+urllib.parse.quote_plus(passphrase.strip())
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def trusted_ip(remote):
    try:
        addr=ipaddress.ip_address(remote)
        return any(addr==ipaddress.ip_address(ip) for host in PAYFAST_HOSTS for ip in socket.gethostbyname_ex(host)[2])
    except (ValueError,OSError):return False

def validate_remote(raw):
    req=urllib.request.Request(SANDBOX_HOST+'/eng/query/validate',data=raw.encode(),headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=8) as r:return r.read(256).strip()==b'VALID'
    except (urllib.error.URLError,TimeoutError):return False

class SandboxAPI(base.API):
    server_version='CoreCloudSandbox/1.0'
    def end_headers(self):
        origin=self.headers.get('Origin','')
        if base.ORIGIN and origin==base.ORIGIN:
            self.send_header('Access-Control-Allow-Origin',base.ORIGIN)
            self.send_header('Vary','Origin')
            self.send_header('Access-Control-Allow-Headers','Content-Type')
            self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
        super().end_headers()
    def do_OPTIONS(self):
        if not base.ORIGIN or self.headers.get('Origin')!=base.ORIGIN:return self.respond(403,{'error':'Origin not allowed'})
        self.send_response(204);self.end_headers()
    def do_GET(self):
        if urllib.parse.urlparse(self.path).path=='/api/health':return self.respond(200,{'status':'ok','payments':'sandbox-only','live_payments':False,'mode':'verified-inventory-sandbox'})
        return super().do_GET()
    def do_POST(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/api/payfast/itn':return self.itn()
        if path=='/api/sandbox/checkout':return self.checkout()
        if path=='/api/admin/reworks/submit':return self.reworks_submit()
        return super().do_POST()
    def reworks_submit(self):
        if not self.admin():return self.respond(403,{'error':'Forbidden'})
        if not self.guard():return
        try:d=self.body()
        except (ValueError,json.JSONDecodeError):return self.respond(400,{'error':'Invalid request'})
        oid=d.get('order_id','')
        if not base.sfield(oid,40):return self.respond(400,{'error':'Invalid order'})
        # Explicit human approval required even in sandbox; no automatic dispatch.
        if d.get('approved') is not True:return self.respond(409,{'error':'Supplier submission requires explicit approval'})
        with base.LOCK,base.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
            if not row:return self.respond(404,{'error':'Order not found'})
            if row['status']!='paid_sandbox':return self.respond(409,{'error':'Only verified sandbox-paid orders can be submitted'})
            existing=c.execute('SELECT supplier_reference,status FROM supplier_orders WHERE order_id=?',(oid,)).fetchone()
            if existing:return self.respond(409,{'error':'Supplier order already recorded','status':existing['status']})
            items=[{'sku':r['product_id'],'quantity':r['quantity']} for r in c.execute('SELECT product_id,quantity FROM order_items WHERE order_id=?',(oid,))]
            delivery=c.execute('SELECT customer,phone,address_line1,city,province,postal_code FROM orders WHERE id=?',(oid,)).fetchone()
            if not delivery or not all(delivery[k] for k in ('address_line1','city','postal_code')):return self.respond(409,{'error':'Complete delivery address required'})
            c.execute('INSERT INTO supplier_orders(order_id,status,created) VALUES(?,?,?)',(oid,'submitting',int(time.time())))
        try:
            result=ReWorksClient().submit_order(oid,items,dict(delivery))
            if not isinstance(result,dict) or not result.get('order_reference'):
                raise SupplierUnavailable('Supplier did not return an order reference')
        except SupplierUnavailable:
            with base.LOCK,base.conn() as c:c.execute('UPDATE supplier_orders SET status=? WHERE order_id=?',('needs_reconciliation',oid))
            return self.respond(502,{'error':'Supplier submission not confirmed; reconcile before retrying'})
        with base.LOCK,base.conn() as c:
            c.execute('UPDATE supplier_orders SET status=?,supplier_reference=? WHERE order_id=?',('accepted',str(result['order_reference'])[:150],oid))
            c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(oid,'supplier_order_accepted',int(time.time()),'ReWorks API acknowledged supplier order'))
        return self.respond(200,{'ok':True,'supplier_reference':str(result['order_reference'])[:150]})

    def checkout(self):
        if not self.guard():return
        if not PUBLIC_API_URL or not PUBLIC_SITE_URL or not PUBLIC_API_URL.startswith('https://') or not PUBLIC_SITE_URL.startswith('https://'):
            return self.respond(503,{'error':'Public HTTPS URLs are required before sandbox checkout'})
        try:d=self.body()
        except (ValueError,json.JSONDecodeError):return self.respond(400,{'error':'Invalid request'})
        base.expire_reservations()
        oid=d.get('order_id','');token=d.get('lookup_token','')
        if not base.sfield(oid,40) or not base.sfield(token,100):return self.respond(400,{'error':'Invalid order credentials'})
        with base.LOCK,base.conn() as c:
            r=c.execute('SELECT * FROM orders WHERE id=? AND lookup_hash=?',(oid,hashlib.sha256(token.encode()).hexdigest())).fetchone()
            if not r:return self.respond(404,{'error':'Order not found'})
            if r['status'] not in ('awaiting_review','confirmed','awaiting_payment'):return self.respond(409,{'error':'Order is not payable'})
            reservation=c.execute('SELECT expires,released FROM reservations WHERE order_id=?',(oid,)).fetchone()
            if not reservation or reservation['released'] or reservation['expires']<=int(time.time()):return self.respond(409,{'error':'Reservation expired'})
            if r['total_cents']<500:return self.respond(409,{'error':'Invalid order amount'})
            c.execute('UPDATE orders SET status=? WHERE id=?',('awaiting_payment',oid))
            c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(oid,'sandbox_checkout_created',int(time.time()),'Sandbox checkout initiated; payment not confirmed'))
        data={'merchant_id':MERCHANT_ID,'merchant_key':MERCHANT_KEY,'return_url':PUBLIC_SITE_URL+'/sandbox-return.html','cancel_url':PUBLIC_SITE_URL+'/sandbox-return.html?cancelled=1','notify_url':PUBLIC_API_URL+'/api/payfast/itn','email_address':r['email'],'m_payment_id':oid,'amount':f"{r['total_cents']/100:.2f}",'item_name':'CoreCloud Marketplace '+oid}
        data['signature']=signature(data,PASSPHRASE)
        return self.respond(200,{'sandbox':True,'action':SANDBOX_HOST+'/eng/process','fields':data,'message':'Sandbox wallet simulation only. No credit card is charged.'})
    def itn(self):
        # ITNs are form encoded, not JSON. Do not accept forwarded IP headers as proof of origin.
        length=int(self.headers.get('Content-Length','0'))
        if length<1 or length>12000:return self.respond(400,{'error':'Invalid notification length'})
        if not trusted_ip(self.client_address[0]):return self.respond(403,{'error':'Untrusted notification source'})
        raw=self.rfile.read(length).decode('utf-8','strict')
        pairs=urllib.parse.parse_qsl(raw,keep_blank_values=True)
        if len(pairs)!=len(dict(pairs)):return self.respond(400,{'error':'Duplicate fields'})
        d=dict(pairs);sig=d.get('signature','')
        if not sig or not hmac.compare_digest(sig,signature(d,PASSPHRASE)):
            return self.respond(403,{'error':'Invalid notification signature'})
        if d.get('merchant_id')!=MERCHANT_ID:return self.respond(403,{'error':'Merchant mismatch'})
        oid=d.get('m_payment_id','')
        with base.conn() as c:r=c.execute('SELECT id,total_cents,status FROM orders WHERE id=?',(oid,)).fetchone()
        if not r:return self.respond(404,{'error':'Unknown order'})
        try:amount=int(round(float(d.get('amount_gross','-1'))*100))
        except ValueError:return self.respond(400,{'error':'Invalid amount'})
        if amount!=r['total_cents']:return self.respond(403,{'error':'Amount mismatch'})
        if not validate_remote(raw):return self.respond(403,{'error':'PayFast validation failed'})
        if d.get('payment_status')!='COMPLETE':return self.respond(200,{'received':True,'paid':False})
        with base.LOCK,base.conn() as c:
            current=c.execute('SELECT status FROM orders WHERE id=?',(oid,)).fetchone()
            if current['status'] in ('paid_sandbox','fulfilling','dispatched','completed'):return self.respond(200,{'received':True,'duplicate':True})
            if current['status']!='awaiting_payment':return self.respond(409,{'error':'Invalid order transition'})
            c.execute('UPDATE orders SET status=? WHERE id=?',('paid_sandbox',oid))
            c.execute('UPDATE reservations SET expires=? WHERE order_id=?',(int(time.time())+86400*365,oid))
            c.execute('INSERT INTO events(order_id,action,created,details) VALUES(?,?,?,?)',(oid,'sandbox_payment_confirmed',int(time.time()),'PayFast sandbox ITN verified; no real funds received'))
        return self.respond(200,{'received':True,'paid_sandbox':True})

if __name__=='__main__':
    base.init()
    with base.conn() as c:c.execute('CREATE TABLE IF NOT EXISTS supplier_orders(order_id TEXT PRIMARY KEY,supplier_reference TEXT,status TEXT NOT NULL,created INTEGER NOT NULL)')
    print('SANDBOX ONLY commerce API',base.HOST,base.PORT,flush=True)
    ThreadingHTTPServer((base.HOST,base.PORT),SandboxAPI).serve_forever()
