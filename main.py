"""
Valmont Self-Bot Client — full Python/PyWebView backend
Discord REST + Gateway WebSocket + AI + Scripts + Backup + Cloner
"""
import sys, os, json, traceback, threading, subprocess, tempfile, time
import urllib.request, urllib.error, urllib.parse, ssl
import webview

# ── paths ─────────────────────────────────────────────────────────────────────
def resource(rel):
    base = sys._MEIPASS if getattr(sys,"frozen",False) else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, rel)

CONFIG_FILE = os.path.join(
    os.path.dirname(sys.executable if getattr(sys,"frozen",False) else os.path.abspath(__file__)),
    "valmont_config.json"
)
def load_cfg():
    try:
        with open(CONFIG_FILE,encoding="utf-8") as f: return json.load(f)
    except: return {}
def save_cfg(data):
    try:
        with open(CONFIG_FILE,"w",encoding="utf-8") as f: json.dump(data,f,indent=2); return True
    except: return False

# ── Discord REST ──────────────────────────────────────────────────────────────
BASE = "https://discord.com/api/v10"
UA   = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def dreq(method, path, token, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req  = urllib.request.Request(
        BASE+path, data=data,
        headers={"Authorization":token,"Content-Type":"application/json","User-Agent":UA},
        method=method
    )
    try:
        with urllib.request.urlopen(req,timeout=timeout) as r:
            raw=r.read()
            return {"ok":True,"data":json.loads(raw) if raw.strip() else {},"status":r.status}
    except urllib.error.HTTPError as e:
        body_txt=""
        try: body_txt=e.read().decode("utf-8","replace")
        except: pass
        return {"ok":False,"status":e.code,"error":f"HTTP {e.code}","detail":body_txt}
    except Exception as e:
        return {"ok":False,"error":str(e)}

# ── Gateway (pure stdlib WebSocket) ──────────────────────────────────────────
import struct, base64, socket

class Gateway:
    URL="wss://gateway.discord.gg/?v=10&encoding=json"
    def __init__(self,token,on_event):
        self.token=token; self.on_event=on_event
        self._stop=threading.Event(); self._thread=None
        self.seq=None; self.session_id=None; self.connected=False
        self._sock=None; self._send_lock=threading.Lock()
        self._hb_last_ack=True; self._ping_ms=0
    def start(self):
        self._stop.clear()
        self._thread=threading.Thread(target=self._run,daemon=True,name="valmont-gw")
        self._thread.start()
    def stop(self):
        self._stop.set(); self.connected=False
        try:
            if self._sock: self._sock.close()
        except: pass
    def send_presence(self,status="online",activities=None):
        self._send_json({"op":3,"d":{"since":None,"activities":activities or [],"status":status,"afk":False}})
    def _send_json(self,obj):
        with self._send_lock:
            try: self._send_frame(json.dumps(obj).encode())
            except: pass
    def _send_frame(self,data,opcode=1):
        mask=os.urandom(4)
        masked=bytes(b^mask[i%4] for i,b in enumerate(data))
        n=len(data)
        if n<126:      hdr=bytes([0x80|opcode,0x80|n])
        elif n<65536:  hdr=bytes([0x80|opcode,0x80|126])+struct.pack(">H",n)
        else:          hdr=bytes([0x80|opcode,0x80|127])+struct.pack(">Q",n)
        self._sock.sendall(hdr+mask+masked)
    def _run(self):
        try:
            u_parsed=urllib.parse.urlparse(self.URL)
            host=u_parsed.hostname; port=443
            path=u_parsed.path+("?"+u_parsed.query if u_parsed.query else "")
            ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
            raw_sock=socket.create_connection((host,port),timeout=20)
            self._sock=ctx.wrap_socket(raw_sock,server_hostname=host)
            key=base64.b64encode(os.urandom(16)).decode()
            self._sock.sendall((
                f"GET {path} HTTP/1.1\r\nHost: {host}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                f"User-Agent: {UA}\r\n\r\n"
            ).encode())
            resp=b""
            while b"\r\n\r\n" not in resp: resp+=self._sock.recv(4096)
            buf=b""
            def recv_frame():
                nonlocal buf
                while len(buf)<2: buf+=self._sock.recv(65536)
                b0,b1=buf[0],buf[1]; op=b0&0x0F; plen=b1&0x7F; idx=2
                if plen==126:
                    while len(buf)<idx+2: buf+=self._sock.recv(65536)
                    plen=struct.unpack(">H",buf[idx:idx+2])[0]; idx+=2
                elif plen==127:
                    while len(buf)<idx+8: buf+=self._sock.recv(65536)
                    plen=struct.unpack(">Q",buf[idx:idx+8])[0]; idx+=8
                while len(buf)<idx+plen:
                    chunk=self._sock.recv(65536)
                    if not chunk: raise ConnectionError("disconnected")
                    buf+=chunk
                payload=buf[idx:idx+plen]; buf=buf[idx+plen:]
                return op,payload
            hb_interval=None
            def heartbeat(ms):
                while not self._stop.is_set():
                    time.sleep(ms/1000)
                    t0=time.time()
                    self._send_json({"op":1,"d":self.seq})
                    self._hb_last_ack=False
                    time.sleep(0.5)
                    self._ping_ms=int((time.time()-t0)*1000)
                    self.on_event("ping_update",{"ms":self._ping_ms})
            self.on_event("gateway_connect",{"status":"connecting"})
            self._sock.settimeout(120)
            while not self._stop.is_set():
                op,raw=recv_frame()
                if op==8: break
                if op==9: self._send_frame(raw,opcode=10); continue
                if op==11: self._hb_last_ack=True; continue
                if op not in(1,2): continue
                msg=json.loads(raw); d=msg.get("d"); t=msg.get("t"); s=msg.get("s")
                if s: self.seq=s
                if msg.get("op")==10:
                    hb_interval=d["heartbeat_interval"]
                    threading.Thread(target=heartbeat,args=(hb_interval,),daemon=True).start()
                    self._send_json({"op":2,"d":{"token":self.token,"capabilities":16381,
                        "properties":{"os":"Windows","browser":"Chrome","device":""},
                        "presence":{"status":"online","since":0,"activities":[],"afk":False},
                        "compress":False,"intents":53608447}})
                elif msg.get("op")==0:
                    self._dispatch(t,d)
        except Exception as e:
            if not self._stop.is_set(): self.on_event("gateway_error",{"error":str(e)})
        finally:
            self.connected=False
            self.on_event("gateway_disconnect",{"reason":"closed"})
            try: self._sock.close()
            except: pass

    def _dispatch(self,t,d):
        if not t or not d: return
        if t=="READY":
            self.session_id=d.get("session_id"); self.connected=True
            self.on_event("gateway_ready",{"user":d.get("user",{})})
        elif t=="MESSAGE_CREATE":
            self.on_event("message_create",{
                "id":d.get("id"),"content":d.get("content",""),
                "author":d.get("author",{}),"channel_id":d.get("channel_id"),
                "guild_id":d.get("guild_id"),"embeds":d.get("embeds",[]),
                "components":d.get("components",[]),"mentions":d.get("mentions",[]),
            })
            import re as _re
            codes=_re.findall(r"(?:discord\.gift/|discord\.com/gifts/)([A-Za-z0-9]+)",d.get("content",""))
            for code in codes: self.on_event("nitro_gift_detected",{"code":code,"channel_id":d.get("channel_id")})
            if not d.get("guild_id"): self.on_event("dm_received",{"message":d})
            # invite links
            inv=_re.findall(r"discord(?:\.gg|\.com/invite)/([A-Za-z0-9-]+)",d.get("content",""))
            for code in inv: self.on_event("invite_detected",{"code":code,"channel_id":d.get("channel_id")})
        elif t=="MESSAGE_DELETE":
            self.on_event("message_delete",{"id":d.get("id"),"channel_id":d.get("channel_id")})
        elif t=="MESSAGE_UPDATE":
            self.on_event("message_update",{"id":d.get("id"),"content":d.get("content",""),
                "channel_id":d.get("channel_id"),"author":d.get("author",{})})
        elif t=="GUILD_MEMBER_ADD":
            self.on_event("member_join",{"guild_id":d.get("guild_id"),"user":d.get("user",{})})
        elif t=="GUILD_MEMBER_REMOVE":
            self.on_event("member_leave",{"guild_id":d.get("guild_id"),"user":d.get("user",{})})
        elif t=="PRESENCE_UPDATE":
            self.on_event("presence_update",{"user":d.get("user",{}),"status":d.get("status"),
                "activities":d.get("activities",[]),"guild_id":d.get("guild_id")})
        elif t=="TYPING_START":
            self.on_event("typing_start",{"user_id":d.get("user_id"),"channel_id":d.get("channel_id")})
        elif t=="RELATIONSHIP_ADD":
            self.on_event("friend_add",{"user":d.get("user",{})})
        elif t=="RELATIONSHIP_REMOVE":
            self.on_event("friend_remove",{"id":d.get("id")})
        else:
            self.on_event("gateway_raw",{"type":t})

# ── API ───────────────────────────────────────────────────────────────────────
class ValmontAPI:
    def __init__(self):
        self._win=None; self._gw=None; self._token=""
        self._autos=[]; self._keywords=[]; self._ping_ms=38
        self._snipers={"nitro_sniper":True,"giveaway_joiner":True,"promo_sniper":False,"invite_joiner":False}
        self._loggers={1:True,2:False,3:True,4:False,5:True,6:True}
        self._stop_anim=threading.Event()

    def _fire(self,event,data=None):
        try:
            if self._win:
                p=json.dumps({"event":event,"data":data or {}})
                self._win.evaluate_js(f"window.__valmontEvent&&window.__valmontEvent({p})")
        except: pass

    def _gw_event(self,event,data):
        self._fire(event,data)
        if event=="message_create":
            self._route_message(data)
        elif event=="nitro_gift_detected" and self._snipers.get("nitro_sniper"):
            threading.Thread(target=self._snipe_nitro,args=(data,),daemon=True).start()
        elif event=="invite_detected" and self._snipers.get("invite_joiner"):
            threading.Thread(target=self._auto_join_invite,args=(data,),daemon=True).start()
        elif event=="message_delete" and self._loggers.get(1):
            self._fire("logger_event",{"type":"deleted","data":data})
        elif event=="message_update" and self._loggers.get(1):
            self._fire("logger_event",{"type":"edited","data":data})
        elif event=="dm_received" and self._loggers.get(5):
            self._fire("logger_event",{"type":"dm","data":data.get("message",{})})
        elif event=="member_join" and self._loggers.get(3):
            self._fire("logger_event",{"type":"join","data":data})
        elif event=="member_leave" and self._loggers.get(3):
            self._fire("logger_event",{"type":"leave","data":data})
        elif event=="presence_update" and self._loggers.get(4):
            self._fire("logger_event",{"type":"presence","data":data})
        elif event=="friend_add" and self._loggers.get(6):
            self._fire("logger_event",{"type":"friend_add","data":data})
        elif event=="friend_remove" and self._loggers.get(6):
            self._fire("logger_event",{"type":"friend_remove","data":data})
        elif event=="gateway_ready":
            self._fire("gateway_status",{"connected":True,"user":data.get("user",{})})
        elif event=="gateway_disconnect":
            self._fire("gateway_status",{"connected":False})
        elif event=="ping_update":
            self._ping_ms=data.get("ms",self._ping_ms)

    def _route_message(self,msg):
        content=msg.get("content",""); ch=msg.get("channel_id"); author=msg.get("author",{})
        # Keywords
        for kw in self._keywords:
            if kw.lower() in content.lower():
                self._fire("keyword_alert",{"keyword":kw,"message":msg})
        # Giveaway detection
        if self._snipers.get("giveaway_joiner"):
            for embed in msg.get("embeds",[]):
                desc=(embed.get("description") or "").lower()
                if any(x in desc for x in ["giveaway","react to enter","winner","prize"]):
                    self._fire("giveaway_detected",{"embed":embed,"channel_id":ch,"message_id":msg.get("id")})
                    # Auto-react
                    if ch and msg.get("id") and self._token:
                        threading.Thread(target=lambda: dreq("PUT",f"/channels/{ch}/messages/{msg['id']}/reactions/%F0%9F%8E%89/@me",self._token),daemon=True).start()
        # Automations
        for auto in self._autos:
            if not auto.get("on"): continue
            trigger=auto.get("trigger","").lower(); matched=False
            if "dm received" in trigger and not msg.get("guild_id"): matched=True
            if "keyword" in trigger:
                for kw in self._keywords:
                    if kw.lower() in content.lower(): matched=True
            if "message deleted" in trigger: pass  # handled via message_delete event
            if matched:
                auto["runs"]=auto.get("runs",0)+1
                self._fire("automation_fired",{"auto":auto,"message":msg})
                self._exec_auto(auto,msg)

    def _exec_auto(self,auto,msg):
        action=auto.get("action","").lower(); ch=msg.get("channel_id")
        if not ch or not self._token: return
        import re as _re
        if "reply" in action or "send" in action:
            m=_re.search(r'"([^"]+)"',auto.get("action",""))
            text=m.group(1) if m else auto.get("action","")
            threading.Thread(target=lambda: dreq("POST",f"/channels/{ch}/messages",self._token,{"content":text}),daemon=True).start()
        elif "react" in action:
            mid=msg.get("id")
            if mid: threading.Thread(target=lambda: dreq("PUT",f"/channels/{ch}/messages/{mid}/reactions/%F0%9F%91%8D/@me",self._token),daemon=True).start()
        elif "leave" in action:
            gid=msg.get("guild_id")
            if gid: threading.Thread(target=lambda: dreq("DELETE",f"/users/@me/guilds/{gid}",self._token),daemon=True).start()

    def _snipe_nitro(self,data):
        code=data.get("code","")
        if not code or not self._token: return
        t0=time.time(); r=dreq("POST",f"/entitlements/gift-codes/{code}/redeem",self._token,{},timeout=5)
        ms=int((time.time()-t0)*1000)
        self._fire("snipe_result",{"type":"nitro","code":code,"ok":r.get("ok",False),"ms":ms,"detail":r.get("detail","")})

    def _auto_join_invite(self,data):
        code=data.get("code","")
        if not code or not self._token: return
        r=dreq("POST",f"/invites/{code}",self._token,{})
        self._fire("invite_joined",{"code":code,"ok":r.get("ok",False)})

    # ── Config ────────────────────────────────────────────────────────────────
    def get_config(self):       return json.dumps(load_cfg())
    def set_config(self,k,v):   cfg=load_cfg(); cfg[k]=v; return save_cfg(cfg)
    def get_saved_token(self):  return load_cfg().get("token","")
    def save_token(self,t):     cfg=load_cfg(); cfg["token"]=t; return save_cfg(cfg)
    def clear_token(self):      cfg=load_cfg(); cfg.pop("token",None); return save_cfg(cfg)

    # ── Discord REST ──────────────────────────────────────────────────────────
    def fetch_discord_user(self,token):    return json.dumps(dreq("GET","/users/@me",token))
    def fetch_discord_guilds(self,token):  return json.dumps(dreq("GET","/users/@me/guilds?limit=200",token))
    def fetch_discord_friends(self,token): return json.dumps(dreq("GET","/users/@me/relationships",token))

    def discord_send(self,token,channel_id,content):
        return json.dumps(dreq("POST",f"/channels/{channel_id}/messages",token,{"content":content}))

    def discord_delete_message(self,token,channel_id,message_id):
        return json.dumps(dreq("DELETE",f"/channels/{channel_id}/messages/{message_id}",token))

    def discord_dm(self,token,user_id,content):
        ch=dreq("POST","/users/@me/channels",token,{"recipient_id":user_id})
        if not ch.get("ok"): return json.dumps(ch)
        return json.dumps(dreq("POST",f"/channels/{ch['data']['id']}/messages",token,{"content":content}))

    def discord_react(self,token,channel_id,message_id,emoji):
        enc=urllib.parse.quote(emoji,safe="")
        return json.dumps(dreq("PUT",f"/channels/{channel_id}/messages/{message_id}/reactions/{enc}/@me",token))

    def discord_bulk_delete(self,token,channel_id,count):
        count=min(int(count),100)
        msgs_r=dreq("GET",f"/channels/{channel_id}/messages?limit=100",token)
        if not msgs_r.get("ok"): return json.dumps(msgs_r)
        me_r=dreq("GET","/users/@me",token)
        if not me_r.get("ok"): return json.dumps(me_r)
        my_id=me_r["data"]["id"]
        my_msgs=[m["id"] for m in msgs_r["data"] if m.get("author",{}).get("id")==my_id][:count]
        deleted,errors=0,[]
        for mid in my_msgs:
            r=dreq("DELETE",f"/channels/{channel_id}/messages/{mid}",token)
            if r.get("ok"): deleted+=1
            else: errors.append(r.get("error",""))
            time.sleep(0.35)
        return json.dumps({"ok":True,"deleted":deleted,"errors":errors})

    def discord_join_invite(self,token,code):
        return json.dumps(dreq("POST",f"/invites/{code}",token,{}))

    def discord_leave_guild(self,token,guild_id):
        return json.dumps(dreq("DELETE",f"/users/@me/guilds/{guild_id}",token))

    def discord_clone_server(self,token,src_id,dst_id,opts_json):
        opts=json.loads(opts_json) if isinstance(opts_json,str) else opts_json
        def run():
            def prog(msg,done=False): self._fire("clone_progress",{"msg":msg,"done":done})
            try:
                prog("Fetching source server…")
                if opts.get("roles",True):
                    prog("Fetching roles…")
                    roles_r=dreq("GET",f"/guilds/{src_id}/roles",token)
                    if roles_r.get("ok") and dst_id:
                        roles=[r for r in roles_r["data"] if r["name"]!="@everyone"]
                        for role in sorted(roles,key=lambda r:r.get("position",0)):
                            dreq("POST",f"/guilds/{dst_id}/roles",token,{
                                "name":role["name"],"permissions":str(role.get("permissions","0")),
                                "color":role.get("color",0),"hoist":role.get("hoist",False),
                                "mentionable":role.get("mentionable",False)
                            }); time.sleep(0.3)
                        prog(f"Cloned {len(roles)} roles")
                    elif not dst_id: prog("No destination — skipping role clone")
                if opts.get("channels",True):
                    prog("Fetching channels…")
                    chans_r=dreq("GET",f"/guilds/{src_id}/channels",token)
                    if chans_r.get("ok") and dst_id:
                        cats=[c for c in chans_r["data"] if c["type"]==4]
                        others=[c for c in chans_r["data"] if c["type"]!=4]
                        for cat in cats:
                            dreq("POST",f"/guilds/{dst_id}/channels",token,{"name":cat["name"],"type":4}); time.sleep(0.25)
                        prog(f"Cloned {len(cats)} categories")
                        for ch in others:
                            body={"name":ch["name"],"type":ch["type"]}
                            if ch.get("topic"): body["topic"]=ch["topic"]
                            dreq("POST",f"/guilds/{dst_id}/channels",token,body); time.sleep(0.25)
                        prog(f"Cloned {len(others)} channels")
                if opts.get("bans",False) and dst_id:
                    bans_r=dreq("GET",f"/guilds/{src_id}/bans",token)
                    if bans_r.get("ok"):
                        for ban in bans_r["data"]:
                            dreq("PUT",f"/guilds/{dst_id}/bans/{ban['user']['id']}",token,{}); time.sleep(0.5)
                        prog(f"Copied {len(bans_r['data'])} bans")
                prog("Clone complete.",done=True)
            except Exception as e:
                prog(f"Error: {e}",done=True)
        threading.Thread(target=run,daemon=True).start()
        return json.dumps({"ok":True})

    # ── Gateway ───────────────────────────────────────────────────────────────
    def gateway_connect(self,token):
        self._token=token
        if self._gw:
            try: self._gw.stop()
            except: pass
            time.sleep(0.3)
        self._gw=Gateway(token,self._gw_event)
        self._gw.start()
        return json.dumps({"ok":True})

    def gateway_disconnect(self):
        if self._gw: self._gw.stop()
        return json.dumps({"ok":True})

    def get_ping(self):
        return json.dumps({"ok":True,"ms":self._ping_ms})

    def discord_set_status(self,status,activity_name=""):
        if not self._gw or not self._gw.connected:
            return json.dumps({"ok":False,"error":"Gateway not connected"})
        acts=[]
        if activity_name: acts=[{"type":4,"name":"Custom Status","state":activity_name,"emoji":None}]
        self._gw.send_presence(status=status,activities=acts)
        return json.dumps({"ok":True})

    # ── Feature toggles ───────────────────────────────────────────────────────
    def set_snipers(self,sj):
        s=json.loads(sj) if isinstance(sj,str) else sj
        self._snipers=s; return json.dumps({"ok":True})

    def set_automations(self,aj):
        self._autos=json.loads(aj) if isinstance(aj,str) else aj
        return json.dumps({"ok":True})

    def set_loggers(self,lj):
        self._loggers=json.loads(lj) if isinstance(lj,str) else lj
        return json.dumps({"ok":True})

    def set_keywords(self,kj):
        self._keywords=json.loads(kj) if isinstance(kj,str) else kj
        return json.dumps({"ok":True})

    # ── Animations ────────────────────────────────────────────────────────────
    def start_animation(self,token,mode,frames_json,speed_ms):
        frames=json.loads(frames_json) if isinstance(frames_json,str) else frames_json
        speed=int(speed_ms)
        if not frames: return json.dumps({"ok":False,"error":"No frames"})
        self._stop_anim.set(); time.sleep(0.1); self._stop_anim=threading.Event()
        def loop():
            idx=0
            while not self._stop_anim.is_set():
                f=frames[idx%len(frames)]
                if mode in("status","both") and self._gw and self._gw.connected:
                    self._gw.send_presence(status="online",activities=[{"type":4,"name":"Custom Status","state":f,"emoji":None}])
                self._fire("animation_frame",{"frame":f,"index":idx%len(frames)})
                idx+=1; time.sleep(speed/1000)
        threading.Thread(target=loop,daemon=True).start()
        return json.dumps({"ok":True})

    def stop_animation(self):
        self._stop_anim.set()
        if self._gw and self._gw.connected:
            self._gw.send_presence(status="online",activities=[])
        return json.dumps({"ok":True})

    # ── Backup ────────────────────────────────────────────────────────────────
    def create_backup(self,token):
        def run():
            results={}
            steps=[
                ("Fetching user profile…",  "/users/@me"),
                ("Fetching servers…",        "/users/@me/guilds?limit=200"),
                ("Fetching friends…",        "/users/@me/relationships"),
                ("Fetching DM channels…",    "/users/@me/channels"),
                ("Fetching settings…",       "/users/@me/settings"),
            ]
            for label,path in steps:
                self._fire("backup_progress",{"msg":label,"done":False})
                r=dreq("GET",path,token)
                results[label]=r.get("data") if r.get("ok") else None
                time.sleep(0.4)
            self._fire("backup_progress",{"msg":"Compressing…","done":False})
            backup={
                "timestamp":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()),
                "user":results.get("Fetching user profile…"),
                "guilds":results.get("Fetching servers…",[]),
                "friends":results.get("Fetching friends…",[]),
                "dms":results.get("Fetching DM channels…",[]),
                "settings":results.get("Fetching settings…"),
                "valmont_config":load_cfg(),
            }
            cfg_dir=os.path.dirname(CONFIG_FILE)
            ts=time.strftime("%Y%m%d_%H%M%S")
            path=os.path.join(cfg_dir,f"valmont_backup_{ts}.json")
            with open(path,"w",encoding="utf-8") as f: json.dump(backup,f,indent=2)
            guilds=backup["guilds"] or []; friends=backup["friends"] or []
            self._fire("backup_progress",{"msg":"Backup complete.","done":True,
                "path":path,"guilds":len(guilds) if isinstance(guilds,list) else 0,
                "friends":len(friends) if isinstance(friends,list) else 0})
        threading.Thread(target=run,daemon=True).start()
        return json.dumps({"ok":True})

    def list_backups(self):
        try:
            d=os.path.dirname(CONFIG_FILE)
            files=sorted([f for f in os.listdir(d) if f.startswith("valmont_backup_") and f.endswith(".json")],reverse=True)
            result=[]
            for f in files:
                p=os.path.join(d,f); st=os.stat(p)
                result.append({"filename":f,"path":p,"size_bytes":st.st_size,
                    "modified":time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime(st.st_mtime))})
            return json.dumps({"ok":True,"backups":result})
        except Exception as e: return json.dumps({"ok":False,"error":str(e)})

    # ── Scripts ───────────────────────────────────────────────────────────────
    def run_script(self,code):
        stub='''import asyncio
class _Bot:
    channel_id="000000000000000000"
    async def send_message(self,ch,c): print(f"[send] #{ch}: {c!r}")
    async def delete_message(self,ch,mid): print(f"[delete] #{ch} id={mid}")
    async def edit_message(self,ch,mid,c): print(f"[edit] #{ch}: {c!r}")
    async def react(self,ch,mid,em): print(f"[react] #{ch} {em}")
bot=_Bot()
class _Msg:
    content=".hello"; channel_id=bot.channel_id; id="0"; guild_id=None
    author={"id":"0","username":"test"}
'''
        runner="\nif 'on_message' in dir():\n    asyncio.run(on_message(bot,_Msg()))\n"
        try:
            with tempfile.NamedTemporaryFile(mode="w",suffix=".py",delete=False,encoding="utf-8") as f:
                f.write(stub+"\n"+code+runner); tmp=f.name
            proc=subprocess.run([sys.executable,tmp],capture_output=True,text=True,timeout=8)
            os.unlink(tmp)
            out=proc.stdout+(("\n[stderr]\n"+proc.stderr) if proc.stderr else "")
            return json.dumps({"ok":True,"output":out.strip() or "(no output)"})
        except subprocess.TimeoutExpired: return json.dumps({"ok":False,"error":"Timed out (8s)"})
        except Exception as e: return json.dumps({"ok":False,"error":str(e)})

    # ── AI ────────────────────────────────────────────────────────────────────
    def ai_chat(self,messages_json,system_prompt):
        key=load_cfg().get("anthropic_key") or os.environ.get("ANTHROPIC_API_KEY","")
        if not key: return json.dumps({"ok":False,"error":'Add "anthropic_key":"sk-ant-..." to valmont_config.json'})
        try:
            messages=json.loads(messages_json)
            payload=json.dumps({"model":"claude-sonnet-4-6","max_tokens":1000,"system":system_prompt,"messages":messages}).encode()
            req=urllib.request.Request("https://api.anthropic.com/v1/messages",data=payload,
                headers={"Content-Type":"application/json","x-api-key":key,"anthropic-version":"2023-06-01"},method="POST")
            with urllib.request.urlopen(req,timeout=30) as r:
                data=json.loads(r.read())
                content="".join(b.get("text","") for b in data.get("content",[]))
                return json.dumps({"ok":True,"content":content})
        except urllib.error.HTTPError as e:
            try: msg=json.loads(e.read()).get("error",{}).get("message",f"HTTP {e.code}")
            except: msg=f"HTTP {e.code}"
            return json.dumps({"ok":False,"error":msg})
        except Exception as e: return json.dumps({"ok":False,"error":str(e)})

    # ── Window ────────────────────────────────────────────────────────────────
    def minimize_window(self):
        if self._win: self._win.minimize()
    def maximize_window(self):
        if self._win: self._win.toggle_fullscreen()
    def close_window(self):
        if self._win: self._win.destroy()

# ── Entry ─────────────────────────────────────────────────────────────────────
def main():
    try:
        api=ValmontAPI()
        html_path=resource(os.path.join("ui","index.html"))
        print(f"[valmont] UI: {html_path}"); print(f"[valmont] exists: {os.path.exists(html_path)}")
        if not os.path.exists(html_path):
            raise FileNotFoundError(f"ui/index.html not found next to main.py")
        win=webview.create_window(
            title="Valmont",url="file:///"+html_path.replace("\\","/"),
            width=1160,height=780,min_size=(980,660),
            frameless=False,background_color="#000000",
            js_api=api,confirm_close=False,
        )
        api._win=win
        webview.start(debug=False,private_mode=False)
    except Exception:
        traceback.print_exc(); input("\nPress Enter to exit…")

if __name__=="__main__":
    main()
