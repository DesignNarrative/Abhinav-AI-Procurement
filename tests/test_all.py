# -*- coding: utf-8 -*-
"""
Comprehensive end-to-end test.
Usage: python tests/test_all.py
"""
import sys, os
sys.path.insert(0, os.getcwd())
sys.stdout.reconfigure(encoding="utf-8")
import requests

BASE = "http://localhost:8001"
http = requests.Session()
passed = 0; failed = 0; fail_list = []

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1; print("[PASS]", name, ("-- "+detail) if detail else "")
    else:
        failed += 1; fail_list.append(name); print("[FAIL]", name, ("-- "+detail) if detail else "")

def section(t): print("\n"+"="*62+"\n  "+t+"\n"+"="*62)

# ===== 1. AUTH =====
section("1  AUTHENTICATION")
r = requests.get(BASE+"/", allow_redirects=False)
test("Root / redirects", r.status_code in [301,302,307], f"status={r.status_code}")
r = requests.get(BASE+"/dashboard/", allow_redirects=False)
test("Dashboard protected (no cookie)", r.status_code in [302,307], f"status={r.status_code}")
test("Redirect -> /auth/login", "login" in r.headers.get("location",""), f"loc={r.headers.get('location','')}")
r = requests.get(BASE+"/auth/login")
test("Login page loads", r.status_code==200, f"status={r.status_code}")
test("Login page has username field", "username" in r.text.lower())
test("Login page has ABHINAV branding", "ABHINAV" in r.text.upper())
r = http.post(BASE+"/auth/login", data={"username":"admin","password":"wrongpass"}, allow_redirects=False)
test("Wrong password returns error page", r.status_code==200, f"status={r.status_code}")
test("Error message visible", any(x in r.text.lower() for x in ["invalid","incorrect","wrong"]))
r = http.post(BASE+"/auth/login", data={"username":"admin","password":"admin123"}, allow_redirects=False)
test("Correct login redirects", r.status_code in [302,307], f"status={r.status_code}")
test("JWT cookie set", "procurement_token" in http.cookies)
r = http.get(BASE+"/dashboard/")
test("Dashboard accessible after login", r.status_code==200, f"status={r.status_code}")
test("Dashboard shows Procurement", "Procurement" in r.text or "Dashboard" in r.text)
test("Dashboard has Supplier stats", "Supplier" in r.text)
test("Dashboard has RFQ stats", "RFQ" in r.text)
test("Dashboard has logout link", "logout" in r.text.lower())

# ===== 2. WEBHOOK =====
section("2  WHATSAPP WEBHOOK (public, no login needed)")
vt = "abhinav_supplier_webhook_2026"
r = requests.get(f"{BASE}/whatsapp/webhook?hub.mode=subscribe&hub.verify_token={vt}&hub.challenge=TEST123")
test("Webhook GET public (no login)", r.status_code==200, f"status={r.status_code}")
test("Webhook returns challenge", r.text.strip()=="TEST123", f"got='{r.text.strip()[:30]}'")
r = requests.get(f"{BASE}/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=badtoken&hub.challenge=X")
test("Webhook rejects bad token (403)", r.status_code==403, f"status={r.status_code}")

# ===== 3. DASHBOARD PAGES =====
section("3  ALL DASHBOARD PAGES")
for path, label in [
    ("/dashboard/suppliers","Suppliers"),("/dashboard/requirements","Requirements"),
    ("/dashboard/rfq","RFQ list"),("/dashboard/purchase-orders","Purchase Orders"),
    ("/dashboard/document-intelligence/","Quotations"),("/dashboard/inbox/","WhatsApp Inbox"),
]:
    r = http.get(BASE+path); test(f"{label} page loads", r.status_code==200, f"status={r.status_code}")

# ===== 4. INTENT DETECTION =====
section("4  QUOTATION INTENT DETECTION")
from app.services.whatsapp_quotation_service import detect_intent, detect_quote_start, extract_number, extract_percent, _CHANGE_PATTERN
for msg,label in [("quote","normal"),("quoet","typo"),("quatation","typo2"),("rate","rate"),("cost","cost"),("kota","hindi")]:
    test(f"QUOTE: '{msg}'", detect_intent(msg)=="quote")
for msg,label in [("confirm","normal"),("confrim","typo"),("ok","ok"),("done","done"),("yes","yes"),("submit","submit")]:
    test(f"CONFIRM: '{msg}'", detect_intent(msg)=="confirm")
for msg,label in [("cancel","normal"),("cancle","typo"),("stop","stop"),("quit","quit")]:
    test(f"CANCEL: '{msg}'", detect_intent(msg)=="cancel")
for msg,label in [("skip","normal"),("skp","typo"),("na","na"),("n/a","n/a")]:
    test(f"SKIP: '{msg}'", detect_intent(msg)=="skip")
for msg,label in [("change 1 2","normal"),("chnage 1 3","typo"),("cahnge 2 5","typo2")]:
    test(f"CHANGE: '{msg}'", detect_intent(msg)=="change")
for msg in ["UltraTech","340 rs","3 days","30 days credit"]:
    r2=detect_intent(msg); test(f"Plain answer not misclassified: '{msg}'", r2=="answer", f"got={r2}")

# ===== 5. QUOTE START =====
section("5  QUOTE-START DETECTION")
for msg,exp,label in [("quote",True,"exact"),("QUOTE",True,"upper"),("rate",True,"rate"),("hello",False,"casual"),("yes",False,"yes"),("ok",False,"ok")]:
    r2=detect_quote_start(msg); test(f"quote_start('{msg}')={exp}", r2==exp, f"got={r2}")

# ===== 6. NUMBER/PERCENT EXTRACTION =====
section("6  NUMBER AND PERCENT EXTRACTION")
for inp,exp,label in [("340","340","plain"),("340 rs","340","with rs"),("Rs. 340","340","Rs."),("price is 450 per bag","450","in sentence")]:
    r2=extract_number(inp); test(f"extract_number('{inp}')='{exp}'", r2==exp, f"got={r2}")
test("extract_number('1,43,500') not None", extract_number("1,43,500") is not None)
for inp,exp,label in [("18%","18","simple"),("28 percent","28","word"),("gst is 18%","18","sentence")]:
    r2=extract_percent(inp); test(f"extract_percent('{inp}')='{exp}'", r2==exp, f"got={r2}")
m=_CHANGE_PATTERN.match("change 1 2")
test("CHANGE regex 'change 1 2' matches", m is not None)
if m: test("mat=1", m.group(1)=="1"); test("field=2", m.group(2)=="2")
test("CHANGE typo 'chnage 2 5' matches", _CHANGE_PATTERN.match("chnage 2 5") is not None)

# ===== 7. SESSION DB =====
section("7  QUOTATION SESSION DB")
from app.database.database import SessionLocal
from app.services.whatsapp_quotation_service import get_active_session, create_session, cancel_session
db=SessionLocal()
try:
    ph="9000000001"
    ex=get_active_session(db,ph)
    if ex: cancel_session(db,ex)
    s=create_session(db,ph,None)
    test("Session created", s is not None)
    test("Session phone correct", s.phone_number==ph)
    test("Session IN_PROGRESS", s.conversation_status=="IN_PROGRESS")
    test("Session step=awaiting_rfq_number", s.current_step=="awaiting_rfq_number")
    test("Session has materials list", isinstance((s.collected_data or {}).get("materials"),list))
    f2=get_active_session(db,ph)
    test("get_active_session returns it", f2 is not None and f2.id==s.id)
    cancel_session(db,s); db.refresh(s)
    test("Session CANCELLED", s.conversation_status=="CANCELLED")
    test("No active after cancel", get_active_session(db,ph) is None)
finally:
    db.close()

# ===== 8. MESSAGES =====
section("8  RFQ TRIGGER AND AWARD MESSAGES")
from app.services.rfq_whatsapp_service import generate_quotation_trigger_message, send_award_winner_message, send_award_consolation_message, generate_rfq_whatsapp_message
trig=generate_quotation_trigger_message("RFQ-2026-033")
test("Trigger message generated", bool(trig))
test("Trigger has RFQ number", "RFQ-2026-033" in trig)
test("Trigger has QUOTE", "QUOTE" in trig)
msg=generate_rfq_whatsapp_message(rfq_number="RFQ-TEST",project_name="P",site_name="S",delivery_location="Pune",payment_terms="30d",
    items=[{"material_name":"Cement","quantity":100,"unit":"bags","brand_required":None,"dynamic_fields":{},"remarks":None,"material_category":None}])
test("RFQ message generated", bool(msg))
test("RFQ message has material", "Cement" in msg)
test("RFQ message has delivery", "Pune" in msg)
test("send_award_winner_message callable", callable(send_award_winner_message))
test("send_award_consolation_message callable", callable(send_award_consolation_message))

# ===== 9. ENDPOINTS REGISTERED =====
section("9  API ENDPOINTS REGISTERED")
from app.api.comparison import router as cr
from app.api.quotation_dashboard import router as qr
from app.api.auth import router as ar
cp=[x.path for x in cr.routes]; qp=[x.path for x in qr.routes]; ap=[x.path for x in ar.routes]
test("award-and-notify endpoint", any("award-and-notify" in p for p in cp))
test("comparison endpoint", any("comparison" in p for p in cp))
test("quotation edit endpoint", any("edit" in p for p in qp))
test("auth login endpoint", any("login" in p for p in ap))
test("auth logout endpoint", any("logout" in p for p in ap))

# ===== 10. DB TABLES =====
section("10  DATABASE TABLES")
from sqlalchemy import inspect as sai
from app.database.database import engine
tbls=sai(engine).get_table_names()
for t in ["suppliers","supplier_conversations","supplier_quotation_conversations","rfqs","rfq_items","rfq_vendors","quotations","quotation_items","purchase_orders","users"]:
    test(f"Table: {t}", t in tbls)

# ===== 11. REGISTRATION BOT (untouched) =====
section("11  SUPPLIER REGISTRATION BOT (must be untouched)")
from app.services.whatsapp_registration_service import process_whatsapp_message
db2=SessionLocal()
try:
    resp=process_whatsapp_message("9999888877","hi",db2)
    test("Bot responds to 'hi'", resp is not None)
    test("Response has 'reply' key", "reply" in resp)
    test("Reply is not empty", bool(resp.get("reply","")))
    print("     Preview:", resp.get("reply","")[:80].replace("\n"," "))
finally:
    db2.close()

# ===== 12. QUOTATION BOT (approved supplier) =====
section("12  QUOTATION BOT - APPROVED SUPPLIER")
from app.services.whatsapp_quotation_service import handle_inbound_quotation_message
from app.models.supplier import Supplier
db3=SessionLocal()
try:
    appr=db3.query(Supplier).filter(Supplier.registration_status=="APPROVED").first()
    if appr:
        ph3=appr.whatsapp_number or "9000000003"
        ex3=get_active_session(db3,ph3)
        if ex3: cancel_session(db3,ex3)
        reply=handle_inbound_quotation_message(db3,appr,ph3,"quote")
        test("handle_inbound returns reply for QUOTE", reply is not None)
        test("Reply is not empty", bool(reply))
        if reply: print("     Preview:", reply[:100].replace("\n"," "))
        s3=get_active_session(db3,ph3)
        if s3: cancel_session(db3,s3)
    else:
        print("     [INFO] No approved suppliers yet - skipping. Will work once suppliers are approved.")
finally:
    db3.close()

# ===== 13. LOGOUT =====
section("13  LOGOUT")
r=http.get(BASE+"/auth/logout", allow_redirects=False)
test("Logout redirects", r.status_code in [302,307], f"status={r.status_code}")
test("Logout goes to /auth/login", "login" in r.headers.get("location",""))
r=http.get(BASE+"/dashboard/", allow_redirects=False)
test("Dashboard blocked after logout", r.status_code in [302,307], f"status={r.status_code}")

# ===== RESULTS =====
print("\n"+"="*62)
print(f"  FINAL RESULTS: {passed} PASSED  |  {failed} FAILED")
print("="*62)
if fail_list:
    print("FAILED TESTS:")
    for f in fail_list: print("  -", f)
    sys.exit(1)
else:
    print("ALL TESTS PASSED!")
    sys.exit(0)
