"""Amadeus API client via Secrets Manager OAuth; filters Le Marais, 4★, gym."""
import os, time, json, requests, boto3
from typing import Dict, Any, List, Optional
BASE_URL=os.getenv("AMADEUS_BASE_URL","https://test.api.amadeus.com"); SECRET_NAME=os.getenv("AMADEUS_SECRET_NAME","/lux/amadeus/credentials")
_secrets=boto3.client("secretsmanager"); _tok={"t":None,"exp":0}
def _creds()->Dict[str,str]: d=json.loads(_secrets.get_secret_value(SecretId=SECRET_NAME)["SecretString"]); return {"id":d["client_id"],"sec":d["client_secret"]}
def _token()->str:
    now=time.time()
    if _tok["t"] and now<_tok["exp"]-30: return _tok["t"]
    c=_creds(); r=requests.post(f"{BASE_URL}/v1/security/oauth2/token", data={"grant_type":"client_credentials","client_id":c["id"],"client_secret":c["sec"]}, timeout=12); r.raise_for_status(); j=r.json(); _tok.update({"t":j["access_token"],"exp":now+int(j.get("expires_in",1800))}); return _tok["t"]
def _hdrs()->Dict[str,str]: return {"Authorization":f"Bearer {_token()}","Accept":"application/json"}
BBOX={"lat_min":48.8538,"lat_max":48.8669,"lon_min":2.3469,"lon_max":2.3705}
def _in(lat:Optional[float],lon:Optional[float])->bool: return lat is not None and lon is not None and BBOX["lat_min"]<=lat<=BBOX["lat_max"] and BBOX["lon_min"]<=lon<=BBOX["lon_max"]
def _has_gym(am:List[str])->bool: g={"gym","fitness center","fitness centre","health club","fitness"}; return any(any(a in str(x).lower() for a in g) for x in (am or []))
def _has_pool(am:List[str])->bool: return any("pool" in str(x).lower() for x in (am or []))
def search_hotels(stay:Dict[str,Any])->List[Dict[str,Any]]:
    params={"cityCode":"PAR","adults":stay.get("adults",2),"checkInDate":stay.get("check_in"),"checkOutDate":stay.get("check_out"),"currency":"GBP","roomQuantity":1,"radius":10,"bestRateOnly":"true"}
    r=requests.get(f"{BASE_URL}/v3/shopping/hotel-offers", headers=_hdrs(), params=params, timeout=15); r.raise_for_status(); data=r.json()
    out=[]; 
    for item in data.get("data",[]):
        hotel=item.get("hotel",{}); geo=hotel.get("geoCode",{}); lat,lon=geo.get("latitude"),geo.get("longitude"); rating=hotel.get("rating")
        try: stars=int(float(rating)) if rating is not None else None
        except: stars=None
        am=hotel.get("amenities") or []
        for off in item.get("offers",[]): am+=off.get("amenities",[]) or []
        if not _in(lat,lon): continue
        if stars is not None and stars!=4: continue
        if not _has_gym(am): continue
        best=None
        for off in item.get("offers",[]): 
            p=off.get("price",{}); 
            if p.get("currency")=="GBP":
                amt=float(p.get("total",p.get("base",0)) or 0); 
                if amt>0 and (best is None or amt<best): best=amt
        out.append({"name":hotel.get("name"),"stars":stars or 4,"url":"","location_note":"Le Marais (approx)","amenities":list(dict.fromkeys([str(a) for a in am]))[:12],"est_price_gbp":best,"pool_bonus":_has_pool(am),"lat":lat,"lon":lon})
    return out
