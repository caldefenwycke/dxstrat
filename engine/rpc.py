import requests
class Rpc:
    def __init__(self,h,p,u,pw): self.url=f'http://{h}:{p}'; self.auth=(u,pw)
    def call(self,m,params=None):
        r=requests.post(self.url,auth=self.auth,json={'jsonrpc':'2.0','id':'darwinx','method':m,'params':params or []},timeout=10);
        r.raise_for_status(); j=r.json();
        if j.get('error'): raise RuntimeError(j['error'])
        return j['result']
    def getblocktemplate(self): return self.call('getblocktemplate',[{'rules':['segwit'],'capabilities':['coinbasetxn','workid']}])
    def submitblock(self,hexblk): return self.call('submitblock',[hexblk])
