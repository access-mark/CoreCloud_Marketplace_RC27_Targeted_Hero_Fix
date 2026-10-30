"""ReWorks API boundary. No assumed supplier endpoints; disabled until contract verified."""
import os,json,urllib.request,urllib.error,urllib.parse,ssl
from dataclasses import dataclass

class SupplierUnavailable(RuntimeError):pass

@dataclass(frozen=True)
class ReWorksConfig:
    base_url:str
    api_key:str
    catalogue_path:str
    availability_path:str
    reserve_path:str
    orders_path:str
    status_path:str
    enabled:bool=False
    @classmethod
    def from_env(cls):
        return cls(*(os.getenv(k,'') for k in ('REWORKS_API_BASE_URL','REWORKS_API_KEY','REWORKS_CATALOGUE_PATH','REWORKS_AVAILABILITY_PATH','REWORKS_RESERVE_PATH','REWORKS_ORDERS_PATH','REWORKS_STATUS_PATH')),os.getenv('REWORKS_API_ENABLED','false').lower()=='true')

class ReWorksClient:
    def __init__(self,config=None,transport=None):
        self.config=config or ReWorksConfig.from_env()
        self.transport=transport or self._http
    def _url(self,path):
        c=self.config
        if not c.enabled:raise SupplierUnavailable('ReWorks integration is disabled pending supplier API confirmation')
        parsed=urllib.parse.urlsplit(c.base_url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise SupplierUnavailable('ReWorks requires a valid HTTPS API base URL')
        if not path.startswith('/') or path.startswith('//') or '..' in path.split('/') or '?' in path or '#' in path:
            raise SupplierUnavailable('Unconfigured or unsafe supplier endpoint')
        if not c.api_key:raise SupplierUnavailable('Missing supplier API credential')
        return c.base_url.rstrip('/')+path
    def _http(self,method,url,payload,headers):
        body=json.dumps(payload).encode() if payload is not None else None
        req=urllib.request.Request(url,data=body,headers=headers,method=method)
        try:
            with urllib.request.urlopen(req,timeout=10,context=ssl.create_default_context()) as response:
                if response.status<200 or response.status>=300:raise SupplierUnavailable('Supplier rejected request')
                data=response.read(1024*1024)
                return json.loads(data)
        except (urllib.error.URLError,TimeoutError,ValueError) as e:raise SupplierUnavailable('Supplier request failed') from e
    def request(self,method,path,payload=None,idempotency_key=None):
        url=self._url(path)
        headers={'Authorization':'Bearer '+self.config.api_key,'Accept':'application/json','Content-Type':'application/json'}
        if idempotency_key:headers['Idempotency-Key']=idempotency_key
        return self.transport(method,url,payload,headers)
    def catalogue(self):return self.request('GET',self.config.catalogue_path)
    def availability(self,sku):
        if not isinstance(sku,str) or not sku or len(sku)>100:raise ValueError('Invalid SKU')
        return self.request('POST',self.config.availability_path,{'sku':sku})
    def reserve(self,order_id,items):return self.request('POST',self.config.reserve_path,{'external_order_id':order_id,'items':items},order_id+'-reserve')
    def submit_order(self,order_id,items,delivery):return self.request('POST',self.config.orders_path,{'external_order_id':order_id,'items':items,'delivery':delivery},order_id)
    def status(self,reference):return self.request('POST',self.config.status_path,{'supplier_order_reference':reference})
