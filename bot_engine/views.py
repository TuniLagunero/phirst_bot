import json
import requests
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from decouple import config
from .models import HouseModel, Lead, Promo 
import re
from django.utils import timezone
import google.generativeai as genai
import logging
import hmac
import hashlib


logger = logging.getLogger(__name__)


genai.configure(api_key=config('GEMINI_API_KEY'))

def get_gemini_response(user_text):
    # Setup the model
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # The Knowledge Base based on your documents
    system_instruction = """
    You are 'PHirst Bot', a helpful sales assistant for Jeric, a real estate agent for Magalang East Phirst Park Homes.
    Answer in Taglish. Be professional but friendly.
    
    FACTS FROM DOCUMENTS:
    - Calista Mid/End: 15% Downpayment (16 months to pay) for PAG-IBIG financing. [cite: 9, 100]
    - Unna Regular: 20% Downpayment (16 months to pay). [cite: 56]
    - Amenities: Clubhouse, swimming pool, basketball court, outdoor cinema, and 24/7 security.
    - Bank financing is 10% downpayment in 12 months.
    - Pag-IBIG financing is 20% downpayment 16 months to pay.
    - Fully finished upon turnover with gate, and fence.
    - Location is in Magalang, Pampanga, 5-10 mins from the town proper and public market.
    - Ready for occupancy or pre-selling.
    - For calista mid monthly amortization is between 16-17k, For calista end is 19-20k, For calista pair is 26k-27, For unna 24-25k.
    - Our earliest turnover is first quarter of 2027.
    - What are the requirements? For locally employed- Two valid ids, proof of billing, Bank statement payroll 6 months latest, Payslips 6months latest, Cenomar or mar certificate, COEC. For Abroad or OFW- Two Valid ids, 8copies of notarized SPA or Consularizer SPA, Payslip 6months latest, bank statement 6months latest,proof of billing, coec,entry and exit stamp
    - Calista mid reservation fee is 15,000, Calista end reservation fee is 20,000, Calista pair reservation fee is 30,000, Unna regular reservation fee is 25,000.
    
    RULES:
    1. Keep answers under 3 sentences.
    2. If asked about price or computation, say: "Type 'house' para makita ang models at direct computations natin."
    3. Always end with a nudge to Jeric: "Gusto mo bang kausapin si Jeric? Click 'Ask Agent' sa menu."
    """
    
    try:
        # We combine prompt and instruction for Flash
        full_prompt = f"{system_instruction}\n\nUser Question: {user_text}"
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        # CRITICAL FIX: exc_info=True captures the full traceback in your server logs
        logger.error(f"Gemini API Error: {e}", exc_info=True)
        return "Pasensya na, busy lang ang system. Type 'house' para sa models o 'start' para mag-simula uli."

# --- HELPER FUNCTIONS ---

def send_fb_image(psid, image_url):
    """
    Sends a standalone image attachment via Meta Graph API.
    The image_url must be publicly accessible.
    """
    access_token = config('FB_PAGE_ACCESS_TOKEN')
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={access_token}"
    
    payload = {
        "recipient": {"id": psid},
        "message": {
            "attachment": {
                "type": "image",
                "payload": {
                    "url": image_url,
                    "is_reusable": True
                }
            }
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        
        # Log failures instead of printing them
        if response.status_code != 200:
            logger.error(f"Failed to send image to {psid}. Status: {response.status_code} | Error: {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Meta API Image Request Failed for {psid}: {e}", exc_info=True)

def send_fb_message(recipient_id, message_text):
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
    payload = {
        "messaging_type": "RESPONSE",
        "recipient": {"id": recipient_id},
        "message": {"text": message_text}
    }
    response = requests.post(url, json=payload)
    return response.json()

def send_house_models(recipient_id, location_filter=None):
    """Fetches active house models and filters them by location if provided."""
    
    if location_filter:
        # Filter houses where the location matches the user's preference
        houses = HouseModel.objects.filter(is_active=True, location__icontains=location_filter)[:10]
    else:
        houses = HouseModel.objects.filter(is_active=True)[:10]
    
    if not houses.exists():
        return send_fb_message(recipient_id, f"Pasensya na, wala kaming available units sa {location_filter} sa ngayon.")

    # 2. Build the 'elements' list dynamically
    elements = []
    today = timezone.now().date()
    

    for house in houses:
        # --- CALCULATION LOGIC START ---
        # 1. Check for Promo
        active_promo = house.promos.filter(
            is_active=True, 
            start_date__lte=today, 
            end_date__gte=today
        ).first()

        discount = 0
        if active_promo:
            discount = float(active_promo.discount_amount)

        # 2. Calculate Net Price & Loan
        net_tcp = float(house.total_contract_price) - discount
        loan_amount = net_tcp * 0.90 # 90% Loanable
        
        # 3. THE FIX: Dynamic "Starts at" calculation (15 Yrs Bank Financing)
        bank_rate = float(getattr(house, 'bank_interest_rate', 8.0))
        
        # Calculate exactly what the computation page will calculate
        est_monthly = calculate_monthly_amortization(loan_amount, bank_rate, 15)
        # --- CALCULATION LOGIC END ---

        elements.append({
            "title": house.name,
            "image_url": house.image_url,
            "subtitle": f"{house.description} | Starts at ₱{est_monthly:,.2f}/mo",
            "buttons": [
                {
                    "type": "postback",
                    "title": "Computation 📊",
                    "payload": f"COMPUTE_{house.id}"
                },
                {
                    "type": "postback",
                    "title": "Schedule Tripping",
                    "payload": f"SCHEDULE_TRIPPING_{house.id}"
                },
                {
                    "type": "web_url",
                    "url": house.details_link,
                    "title": "View Details"
                }
            ]
        })

    # 3. Send the payload to Meta
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": elements
                }
            }
        }
    }
    response = requests.post(url, json=payload)
    return response.json()


def get_user_profile(psid):
    """Fetches user's name and profile pic from Facebook."""
    url = f"https://graph.facebook.com/{psid}"
    params = {
        'fields': 'first_name,last_name',
        'access_token': config('FB_PAGE_ACCESS_TOKEN')
    }
    response = requests.get(url, params=params)
    return response.json()

def is_ph_phone_number(text):
    # Matches 09xxxxxxxxx or +639xxxxxxxxx
    pattern = r"^(09|\+639)\d{9}$"
    return bool(re.match(pattern, text.strip()))

def verify_meta_signature(raw_payload, signature_header):
    """
    Validates the X-Hub-Signature-256 header sent by Meta using HMAC-SHA256.
    """
    if not signature_header:
        return False
        
    app_secret = config('META_APP_SECRET', default='')
    if not app_secret:
        logger.error("META_APP_SECRET is missing from environment variables.")
        return False

    # Meta requires the hash to be prefixed with 'sha256='
    expected_hash = hmac.new(
        app_secret.encode('utf-8'), 
        raw_payload, 
        hashlib.sha256
    ).hexdigest()
    
    expected_signature = f"sha256={expected_hash}"
    
    # Strictly use compare_digest to prevent timing attacks
    return hmac.compare_digest(expected_signature, signature_header)

def send_quick_reply(recipient_id, text, options):
    """
    options should be a list of tuples: [("Title", "PAYLOAD"), ...]
    """
    url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
    
    replies = []
    for title, payload in options:
        replies.append({
            "content_type": "text",
            "title": title,
            "payload": payload
        })
        
    payload = {
        "recipient": {"id": recipient_id},
        "message": {
            "text": text,
            "quick_replies": replies
        }
    }
    return requests.post(url, json=payload).json()

def calculate_monthly_amortization(principal, annual_interest_rate, years):
    """Calculates dynamic monthly amortization based on any interest rate."""
    if annual_interest_rate <= 0:
        return principal / (years * 12)
    
    monthly_rate = (annual_interest_rate / 100) / 12
    total_months = years * 12
    
    return principal * (monthly_rate * (1 + monthly_rate)**total_months) / ((1 + monthly_rate)**total_months - 1)

def ask_financing_type(recipient_id, house_id):
    """
    Step 1: Ask the user which financing plan they want.
    """
    try:
        house = HouseModel.objects.get(id=house_id)
        text = f"Para sa {house.name}, anong financing plan ang gusto mong makita? 🏦"
        
        send_quick_reply(recipient_id, text, [
            ("Bank Financing 🏦", f"CALC_BANK_{house_id}"),
            ("Pag-IBIG 🏠", f"CALC_PAGIBIG_{house_id}"),
            ("Cash Payment 💵", f"CALC_CASH_{house_id}")
        ])
    except HouseModel.DoesNotExist:
        send_fb_message(recipient_id, "Error: House not found.")

def send_bank_computation(recipient_id, house_id):
    """
    Step 2: Show the BANK Specific Computation
    """
    try:
        house = HouseModel.objects.get(id=house_id)
        today = timezone.now().date()
        
        # --- A. CHECK PROMOS ---
        active_promo = house.promos.filter(
            is_active=True, 
            start_date__lte=today, 
            end_date__gte=today
        ).first()

        # --- B. BASE NUMBERS ---
        gross_tcp = float(house.total_contract_price)
        reservation_fee = float(house.reservation_fee)

        # --- C. APPLY DISCOUNT ---
        discount = 0
        promo_text = ""
        if active_promo:
            discount = float(active_promo.discount_amount)
            promo_text = f"\n🎉 PROMO: {active_promo.name} (-₱{discount:,.0f})"

        net_tcp = gross_tcp - discount
        


        # --- D. BANK FORMULA ---
        dp_percent = float(house.downpayment_percent) / 100
        total_dp = net_tcp * dp_percent
        dp_balance = total_dp - reservation_fee
        monthly_dp = dp_balance / 12  # 12 Months Term

        # Loan is 90% of NET TCP
        loan_amount = net_tcp * 0.90
        
        # Using dynamic bank interest rate (defaulting to 8.0% if missing)
        bank_rate = float(getattr(house, 'bank_interest_rate', 8.0))

        monthly_15y = calculate_monthly_amortization(loan_amount, bank_rate, 15)
        monthly_10y = calculate_monthly_amortization(loan_amount, bank_rate, 10)
        monthly_05y = calculate_monthly_amortization(loan_amount, bank_rate, 5)

        # --- E. BUILD MESSAGE ---
        text = (
            f"🏦 **BANK FINANCING COMPUTATION**\n"
            f"🏠 Unit: {house.name}\n"
            f"──────────────────\n"
            f"💰 TCP: ₱{gross_tcp:,.2f}"
            f"{promo_text}\n"
            f"✅ **NET TCP: ₱{net_tcp:,.2f}**\n"
            f"──────────────────\n"
            f"📉 **DOWNPAYMENT (12 Mos):**\n"
            f"• Required DP (10%): ₱{total_dp:,.2f}\n"
            f"• Less Reservation: -₱{reservation_fee:,.2f}\n"
            f"👉 **Monthly DP: ₱{monthly_dp:,.2f}** /mo\n"
            f"──────────────────\n"
            f"🏦 **EST. MONTHLY AMORTIZATION:**\n"
            f"• 15 Years: ₱{monthly_15y:,.2f}\n"
            f"• 10 Years: ₱{monthly_10y:,.2f}\n"
            f"• 05 Years: ₱{monthly_05y:,.2f}\n\n"
            "Note: Rates are subject to bank approval."
        )

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text, # Your computation text
                        "buttons": [
                            {"type": "postback", "title": "Reserve Now 📝", "payload": f"RESERVE_{house_id}"},
                            {"type": "postback", "title": "Schedule Tripping 📅", "payload": f"SCHEDULE_TRIPPING_{house_id}"},
                            {"type": "postback", "title": "Back to Options 🔙", "payload": f"COMPUTE_{house_id}"}
                        ]
                    }
                }
            }
        }
        url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
        requests.post(url, json=payload)
    except HouseModel.DoesNotExist:
        send_fb_message(recipient_id, "System Error: Cannot find house details.")

# views.py

def send_pagibig_computation(recipient_id, house_id):
    try:
        house = HouseModel.objects.get(id=house_id)
        today = timezone.now().date()
        
        # --- A. CHECK PROMOS ---
        active_promo = house.promos.filter(
            is_active=True, 
            start_date__lte=today, 
            end_date__gte=today
        ).first()

        # --- B. BASE NUMBERS ---
        gross_tcp = float(house.total_contract_price)
        reservation_fee = float(house.reservation_fee)

        # --- C. APPLY DISCOUNT ---
        discount = 0
        promo_text = ""
        if active_promo:
            discount = float(active_promo.discount_amount)
            promo_text = f"\n🎉 PROMO: {active_promo.name} (-₱{discount:,.0f})"

        net_tcp = gross_tcp - discount


        dp_percent = float(house.pagibig_downpayment_percent) / 100
        loan_percent = 1.0 - dp_percent

 
        total_dp = net_tcp * dp_percent
        dp_balance = total_dp - reservation_fee
        monthly_dp = dp_balance / 16

    
        loan_amount = net_tcp * loan_percent
        
 
        pagibig_rate = float(getattr(house, 'interest_rate', 9.0)) 

        monthly_30y = calculate_monthly_amortization(loan_amount, pagibig_rate, 30)
        monthly_20y = calculate_monthly_amortization(loan_amount, pagibig_rate, 20)
        monthly_10y = calculate_monthly_amortization(loan_amount, pagibig_rate, 10)
        # --- E. BUILD MESSAGE ---
        text = (
            f"🏠 **PAG-IBIG COMPUTATION**\n"
            f"Model: {house.name}\n"
            f"──────────────────\n"
            f"💰 TCP: ₱{gross_tcp:,.2f}"
            f"{promo_text}\n"
            f"✅ **NET TCP: ₱{net_tcp:,.2f}**\n"
            f"──────────────────\n"
            f"📉 **DOWNPAYMENT (16 Mos):**\n" # Explicitly 16 months
            f"• Required DP ({int(dp_percent*100)}%): ₱{total_dp:,.2f}\n"
            f"• Less Reservation: -₱{reservation_fee:,.2f}\n"
            f"👉 **Monthly DP: ₱{monthly_dp:,.2f}** /mo\n"
            f"──────────────────\n"
            f"🏠 **EST. MONTHLY AMORTIZATION:**\n"
            f"• 30 Years: ₱{monthly_30y:,.2f}\n"
            f"• 20 Years: ₱{monthly_20y:,.2f}\n"
            f"• 10 Years: ₱{monthly_10y:,.2f}\n"
        )

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text, # Your computation text
                        "buttons": [
                            {"type": "postback", "title": "Reserve Now 📝", "payload": f"RESERVE_{house_id}"},
                            {"type": "postback", "title": "Schedule Tripping 📅", "payload": f"SCHEDULE_TRIPPING_{house_id}"},
                            {"type": "postback", "title": "Back to Options 🔙", "payload": f"COMPUTE_{house_id}"}
                        ]
                    }
                }
            }
        }
        url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
        requests.post(url, json=payload)
    except HouseModel.DoesNotExist:
        send_fb_message(recipient_id, "System Error: Cannot find house details.")

def send_cash_computation(recipient_id, house_id):
    try:
        house = HouseModel.objects.get(id=house_id)
        today = timezone.now().date()
        
        # 1. Base Price & Promo Check
        active_promo = house.promos.filter(
            is_active=True, 
            start_date__lte=today, 
            end_date__gte=today
        ).first()

        gross_tcp = float(house.total_contract_price)
        
        # 2. Apply Promo First (Standard industry practice)
        discount_promo = 0
        if active_promo:
            discount_promo = float(active_promo.discount_amount)
        
        price_after_promo = gross_tcp - discount_promo

        # 3. Apply Cash Discount from DB
        cash_rate = float(house.cash_discount_percent) / 100
        cash_discount_amount = price_after_promo * cash_rate
        final_cash_price = price_after_promo - cash_discount_amount

        # 4. Build Message
        text = (
            f"💵 **CASH PAYMENT COMPUTATION**\n"
            f"🏠 Model: {house.name}\n"
            f"──────────────────\n"
            f"💰 TCP: ₱{gross_tcp:,.2f}"
            f"\n🎉 Promo: -₱{discount_promo:,.2f}" if discount_promo > 0 else ""
            f"💰 TCP: ₱{gross_tcp:,.2f}"
            f"\n✨ **Cash Discount ({house.cash_discount_percent}%): -₱{cash_discount_amount:,.2f}**\n"
            f"──────────────────\n"
            f"💎 **FINAL CASH PRICE: ₱{final_cash_price:,.2f}**\n"
            f"──────────────────\n"
            f"Note: Full payment is required within 30 days to avail this discount."
        )

        payload = {
            "recipient": {"id": recipient_id},
            "message": {
                "attachment": {
                    "type": "template",
                    "payload": {
                        "template_type": "button",
                        "text": text, # Your computation text
                        "buttons": [
                            {"type": "postback", "title": "Reserve Now 📝", "payload": f"RESERVE_{house_id}"},
                            {"type": "postback", "title": "Schedule Tripping 📅", "payload": f"SCHEDULE_TRIPPING_{house_id}"},
                            {"type": "postback", "title": "Back to Options 🔙", "payload": f"COMPUTE_{house_id}"}
                        ]
                    }
                }
            }
        }
        url = f"https://graph.facebook.com/v21.0/me/messages?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
        requests.post(url, json=payload)
    except HouseModel.DoesNotExist:
        send_fb_message(recipient_id, "System Error: Cannot find house details.")

def send_telegram_alert(message_text):
    bot_token = config('TELEGRAM_BOT_TOKEN')
    chat_id = config('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        
        # PROPER LOGGING LOGIC
        if response.status_code == 200:
            logger.info(f"Telegram alert sent successfully to chat_id {chat_id}.")
        else:
            logger.error(f"Telegram API Failed. Status: {response.status_code} | Response: {response.text}")
            
    except requests.exceptions.RequestException as e:
        # Catches network-level failures (e.g., your server loses internet connection)
        logger.error(f"Failed to connect to Telegram API: {e}", exc_info=True)

def pass_to_agent(psid):
    url = f"https://graph.facebook.com/v21.0/me/pass_thread_control?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
    payload = {
        "recipient": {"id": psid},
        "target_app_id": 263902037430900, # Fixed ID for Meta Inbox
        "metadata": "Handover to human agent"
    }
    requests.post(url, json=payload)

# --- MAIN WEBHOOK VIEW ---

@csrf_exempt
def messenger_webhook(request):
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if mode == 'subscribe' and token == config('FB_VERIFY_TOKEN'):
            return HttpResponse(challenge)
        return HttpResponse("Verification failed", status=403)

    elif request.method == 'POST':
        # --- 1. THE GATEKEEPER: VALIDATE SIGNATURE ---
        raw_body = request.body
        signature_header = request.headers.get('X-Hub-Signature-256')

        if not verify_meta_signature(raw_body, signature_header):
            logger.warning(f"Unauthorized payload blocked. Invalid signature: {signature_header}")
            # Drop the connection immediately if the signature is invalid or missing
            return HttpResponse("Forbidden", status=403)

        # --- 2. SAFE PARSING ---
        # If the code reaches here, the payload is 100% verified to be from Meta
        data = json.loads(raw_body.decode('utf-8'))
        
        if data.get('object') == 'page':
            for entry in data.get('entry', []):
                
                # --- 1. HANDLE COMMENTS ---
                if 'changes' in entry:
                    for change in entry['changes']:
                        if change.get('field') == 'comment':
                            comment_data = change['value']
                            if comment_data.get('item') == 'comment' and comment_data.get('verb') == 'add':
                                sender_id = comment_data.get('from', {}).get('id')
                                user_msg = comment_data.get('message', '').lower()
                                if sender_id == config('FB_PAGE_ID'): continue
                                trigger_words = ['hm', 'how much', 'price', 'details', 'interested', 'avail']
                                if any(word in user_msg for word in trigger_words):
                                    send_fb_message(sender_id, "Hi! I sent you a PM about our house models and prices. Check your inbox! 😊")

                # --- 2. HANDLE MESSAGES & POSTBACKS ---
                if 'messaging' in entry:
                    for messaging_event in entry['messaging']:
                        sender_id = messaging_event['sender']['id']
                        if messaging_event.get('message', {}).get('is_echo'): continue

                        # 1. GET OR CREATE LEAD IMMEDIATELY
                        lead, created = Lead.objects.get_or_create(psid=sender_id)
                        user_msg_obj = messaging_event.get('message')

                        # 2. DEFINE ALL TEXT VARIABLES AT THE TOP
                        if user_msg_obj and 'attachments' in user_msg_obj:
                            send_fb_message(sender_id, "Pasensya na, text and buttons lang muna ang kaya kong basahin. Please type your message or click an option. 😊")
                            return HttpResponse("EVENT_RECEIVED", status=200)

                        # Now it is safe to extract text (since we know it's not a standalone attachment)
                        # We use {} as a fallback in case it's a postback event instead of a message
                        safe_msg_obj = user_msg_obj or {} 
                        user_text = safe_msg_obj.get('text', '').strip()
                        user_text_lower = user_text.lower()
                        qr_payload = safe_msg_obj.get('quick_reply', {}).get('payload')
                        postback_payload = messaging_event.get('postback', {}).get('payload')

                        # 3. FETCH NAME IF MISSING (Fixes "Hi there" and "Name: None")
                        if not lead.full_name:
                            try:
                                profile = get_user_profile(sender_id)
                                if 'first_name' in profile:
                                    lead.full_name = f"{profile['first_name']} {profile.get('last_name', '')}"
                                    lead.save()
                            except Exception as e:
                                logger.error(f"Failed to fetch Meta profile for PSID {sender_id}. Error: {e}")

                        # --- NEW: 3.5 THE GLOBAL RESET (Overrides everything else) ---
                        if postback_payload in ['GET_STARTED', 'START_CHATTING']:
                            # Force reset the database state
                            lead.status = 'COLD'
                            lead.current_step = 'ASKED_BUDGET'
                            lead.save()
                            
                            first_name = lead.full_name.split()[0] if lead.full_name else "there"
                            send_quick_reply(sender_id, f"Hi {first_name}! 👋 To help you find the best home, ano ang budget range mo?", [
                                ("2M-3M", "BUDGET_2_3"), ("3M-4M", "BUDGET_3_4"), ("4M+", "BUDGET_4_UP")
                            ])
                            return HttpResponse("EVENT_RECEIVED", status=200)

                        # --- THE HARDENED GATEKEEPER & PHONE CAPTURE ---
                        if lead.status in ['HOT', 'WARM']:
                            
                            # 1. Backdoor to reset the bot
                            if user_text_lower == 'reset bot':
                                lead.status = 'COLD'
                                lead.current_step = 'START'
                                lead.save()
                                send_fb_message(sender_id, "Bot has been reset. Type 'start' to begin.")
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # 2. If we are STILL waiting for a phone number
                            if lead.current_step != 'COMPLETED':
                                if is_ph_phone_number(user_text):
                                    lead.phone_number = user_text
                                    lead.current_step = 'COMPLETED'
                                    intent = "RESERVATION" if lead.status == 'HOT' else "TRIPPING"
                                    
                                    # --- TELEGRAM ALERT WITH COOLDOWN ---
                                    from django.utils import timezone
                                    from datetime import timedelta
                                    now = timezone.now()
                                    
                                    # Check if 30 mins have passed since last alert to prevent spam
                                    if not lead.last_alert_sent or lead.last_alert_sent < now - timedelta(minutes=30):
                                        alert_msg = (
                                            f"🔥 **HOT LEAD: {intent}**\n"
                                            f"👤 Name: {lead.full_name}\n"
                                            f"📞 Phone: `{user_text}`\n"
                                            f"🏠 Unit: {lead.interested_house.name if getattr(lead, 'interested_house', None) else 'N/A'}"
                                        )
                                        send_telegram_alert(alert_msg)
                                        lead.last_alert_sent = now

                                    # --- FB REPLY ---
                                    send_fb_message(sender_id, f"Salamat! Na-save ko na ang number mo. Tatawagan ka ni Jeric shortly. 😊")
                                    
                                    lead.save()
                                    pass_to_agent(sender_id)
                                    return HttpResponse("EVENT_RECEIVED", status=200)
                                    
                                else:
                                    # VALIDATION FAILED: They typed text instead of a valid number
                                    if user_text: # Only reply if they actually typed something
                                        send_fb_message(sender_id, "Pasensya na, please enter a valid 11-digit phone number (e.g., 09171234567) para ma-forward ko kay Jeric. 😊")
                                    return HttpResponse("EVENT_RECEIVED", status=200)

                            # 3. If they already finished (Step is COMPLETED), bot stays completely silent.
                            return HttpResponse("EVENT_RECEIVED", status=200)

                        # --- C. PROCEED TO NORMAL BOT LOGIC ---
                        if 'message' in messaging_event:
                            qr_payload = messaging_event['message'].get('quick_reply', {}).get('payload')

                            # B. QUICK REPLIES (Financing & Funnel)
                            if qr_payload:
                                if qr_payload.startswith('CALC_BANK_'):
                                    send_bank_computation(sender_id, qr_payload.replace('CALC_BANK_', ''))
                                elif qr_payload.startswith('CALC_PAGIBIG_'):
                                    send_pagibig_computation(sender_id, qr_payload.replace('CALC_PAGIBIG_', ''))
                                elif qr_payload.startswith('CALC_CASH_'):
                                    lead.status = 'HOT' # Cash buyers are hot
                                    lead.save()
                                    send_cash_computation(sender_id, qr_payload.replace('CALC_CASH_', ''))
                                elif qr_payload.startswith('BUDGET_'):
                                    lead.budget_range = user_text
                                    lead.current_step = 'ASKED_FINANCING' # Skip location entirely
                                    lead.save()
                                    send_quick_reply(sender_id, "Anong financing plan ang balak mo?", [
                                        ("Bank Financing", "FIN_BANK"), ("Cash", "FIN_CASH"), ("Pag-IBIG", "FIN_PAGIBIG")
                                    ])
                                elif qr_payload.startswith('FIN_'):
                                    fin_map = {'FIN_BANK': 'BANK', 'FIN_CASH': 'CASH', 'FIN_PAGIBIG': 'PAGIBIG'}
                                    lead.financing_type = fin_map.get(qr_payload)
                                    lead.current_step = 'ASKED_TIMELINE'
                                    lead.save()
                                    send_quick_reply(sender_id, "Kailan mo balak kumuha ng unit?", [
                                        ("ASAP", "TIME_ASAP"), ("1-3 Months", "TIME_1_3"), ("Just looking", "TIME_LOOKING")
                                    ])
                                elif qr_payload.startswith('TIME_'):
                                    lead.timeline = user_text
                                    lead.current_step = 'COMPLETED'
                                    lead.save()
                                    send_fb_message(sender_id, "Salamat! Narito ang mga available models:")
                                    send_house_models(sender_id, location_filter=lead.location_pref)
                                
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # --- NEW: MID-FUNNEL VALIDATION (The "Missing Buttons" Fix) ---
                            if lead.current_step in ['ASKED_BUDGET', 'ASKED_FINANCING', 'ASKED_TIMELINE']:
                                if not qr_payload and postback_payload not in ['VIEW_MODELS', 'TALK_TO_AGENT']:
                                    error_msg = "Please use the buttons below para makapag-proceed tayo. 👇"
                                    
                                    if lead.current_step == 'ASKED_BUDGET':
                                        send_quick_reply(sender_id, f"{error_msg}\n\nAno ang budget range mo?", [
                                            ("2M-3M", "BUDGET_2_3"), ("3M-4M", "BUDGET_3_4"), ("4M+", "BUDGET_4_UP")
                                        ])
                                    elif lead.current_step == 'ASKED_FINANCING':
                                        send_quick_reply(sender_id, f"{error_msg}\n\nAnong financing plan ang balak mo?", [
                                            ("Bank Financing", "FIN_BANK"), ("Cash", "FIN_CASH"), ("Pag-IBIG", "FIN_PAGIBIG")
                                        ])
                                    elif lead.current_step == 'ASKED_TIMELINE':
                                        send_quick_reply(sender_id, f"{error_msg}\n\nKailan mo balak kumuha ng unit?", [
                                            ("ASAP", "TIME_ASAP"), ("1-3 Months", "TIME_1_3"), ("Just looking", "TIME_LOOKING")
                                        ])
                                    
                                    return HttpResponse("EVENT_RECEIVED", status=200)

                            # C. INITIAL TRIGGERS
                            if user_text_lower in ['start', 'hello', 'hi']:
                                first_name = lead.full_name.split()[0] if lead.full_name else "there"
                                send_quick_reply(sender_id, f"Hi {first_name}! 👋 Ano ang budget range mo?", [
                                    ("2M-3M", "BUDGET_2_3"), ("3M-4M", "BUDGET_3_4"), ("4M+", "BUDGET_4_UP")
                                ])
                                lead.current_step = 'ASKED_BUDGET'
                                lead.save()
                            elif 'house' in user_text_lower:
                                send_house_models(sender_id)
                            else: # <--- THE UNIFIED MEDIA INTERCEPTOR & GEMINI FALLBACK
                                # 1. Expanded triggers to include video/tours
                                media_triggers = ['pic', 'picture', 'photo', 'deliverable', 'turnover', 'mukha', 'itsura', 'model', 'video', 'vid', 'tour', 'virtual']
                                
                                is_asking_for_media = any(word in user_text_lower for word in media_triggers)
                                
                                if is_asking_for_media:
                                    house_names = [house.name.lower() for house in HouseModel.objects.filter(is_active=True)]
                                    target_house_name = next((name for name in house_names if name in user_text_lower), None)
                                    
                                    if target_house_name:
                                        house = HouseModel.objects.get(name__iexact=target_house_name)
                                        
                                        # --- VIDEO LOGIC FIRST ---
                                        if any(word in user_text_lower for word in ['video', 'vid', 'tour', 'virtual']):
                                            if house.virtual_tour_link:
                                                send_fb_message(sender_id, f"Eto po ang virtual tour video para sa {house.name}: {house.virtual_tour_link}")
                                            else:
                                                send_fb_message(sender_id, f"Pasensya na, wala pa kaming naka-upload na video para sa {house.name}. Pwede kitang i-connect kay Jeric para ma-assist ka.")
                                            return HttpResponse("EVENT_RECEIVED", status=200)

                                        # --- IMAGE LOGIC (Limited to 3 + Gallery Link) ---
                                        if any(word in user_text_lower for word in ['turnover', 'deliverable', 'bare']):
                                            images = house.images.filter(category='TURNOVER')[:3]
                                            gallery_link = house.turnover_gallery_link
                                            category_name = "turnover/deliverable unit"
                                        else:
                                            images = house.images.filter(category='DRESSED')[:3]
                                            gallery_link = house.dressed_gallery_link
                                            category_name = "dressed-up model unit"

                                        if images.exists():
                                            # Send Teaser Text
                                            send_fb_message(sender_id, f"Eto po ang 3 pictures ng {category_name} ng {house.name}:")
                                            
                                            # Fire API for max 3 images
                                            for img in images:
                                                send_fb_image(sender_id, img.image_url)
                                                
                                            # Send Full Gallery Link if Jeric provided one
                                            if gallery_link:
                                                send_fb_message(sender_id, f"Para makita ang full gallery at iba pang pictures, click here: {gallery_link}")
                                        else:
                                            send_fb_message(sender_id, f"Pasensya na, wala pa akong hawak na picture para sa {house.name}. Pwede kitang i-connect kay Jeric.")
                                        
                                        return HttpResponse("EVENT_RECEIVED", status=200)
                                
                                # 2. If it's not a media request, let Gemini handle it
                                ai_reply = get_gemini_response(user_text)
                                send_fb_message(sender_id, ai_reply)
                            
                            return HttpResponse("EVENT_RECEIVED", status=200)

                        # --- 2. HANDLE POSTBACKS ---
                        elif 'postback' in messaging_event:
                            payload = messaging_event['postback'].get('payload')
                            
                            # Standard Start
                            if payload in ['GET_STARTED', 'START_CHATTING']: 
                                # Fetch first name for a better experience
                                first_name = lead.full_name.split()[0] if lead.full_name else "there"
                                
                                greeting_msg = f"Hi {first_name}! 👋 To help you find the best home, ano ang budget range mo?"
                                
                                # CRITICAL: Ensure send_quick_reply is actually firing
                                send_quick_reply(sender_id, greeting_msg, [
                                    ("2M-3M", "BUDGET_2_3"),
                                    ("3M-4M", "BUDGET_3_4"),
                                    ("4M+", "BUDGET_4_UP")
                                ])
                                
                                lead.current_step = 'ASKED_BUDGET'
                                lead.save()
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # RE-TRIGGER COMPUTATION SELECTOR (Back to Options)
                            elif payload.startswith('COMPUTE_'):
                                house_id = payload.replace('COMPUTE_', '')
                                ask_financing_type(sender_id, house_id)
                                return HttpResponse("EVENT_RECEIVED", status=200)
                            
                            # --- NEW: PERSISTENT MENU HANDLERS ---
                            elif payload == 'VIEW_MODELS':
                                send_house_models(sender_id)
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            elif payload == 'TALK_TO_AGENT':
                                lead.status = 'WARM'
                                lead.save()
                                
                                # Notify Jeric on Telegram
                                alert_text = f"🙋 **AGENT REQUESTED**\n👤 Name: {lead.full_name}\n📍 Action: User clicked 'Talk to Agent' in the menu."
                                send_telegram_alert(alert_text)
                                
                                # Inform User & Pass Control
                                send_fb_message(sender_id, "Wait lang po, nililipat ko na ang chat kay Jeric. He will assist you shortly! 😊")
                                pass_to_agent(sender_id)
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # HANDLE RESERVATION INTENT
                            elif payload.startswith('RESERVE_'):
                                house_id = payload.replace('RESERVE_', '')
                                house = HouseModel.objects.get(id=house_id)
                                
                                lead.interested_house = house
                                lead.status = 'HOT'
                                lead.current_step = 'ASKED_PHONE' # <--- ADD THIS FIX
                                lead.save()
                                
                                send_fb_message(sender_id, f"Great choice! Para sa {house.name}, please provide your contact number para ma-assist ka ni Jeric sa reservation process.")
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # HANDLE TRIPPING INTENT
                            elif payload.startswith('SCHEDULE_TRIPPING_'):
                                house_id = payload.replace('SCHEDULE_TRIPPING_', '')
                                house = HouseModel.objects.get(id=house_id)
                                
                                lead.interested_house = house
                                lead.status = 'WARM'
                                lead.current_step = 'ASKED_PHONE' # <--- ADD THIS FIX
                                lead.save()
                                
                                send_fb_message(sender_id, f"Noted! Send your phone number para ma-confirm ang tripping schedule mo para sa {house.name}.")
                                return HttpResponse("EVENT_RECEIVED", status=200)
                            
                            # HANDLE AGENT HANDOVER
                            elif payload == 'CHAT_WITH_AGENT':
                                lead.status = 'WARM'
                                lead.save()
                                send_telegram_alert(f"🙋 **AGENT REQUESTED**\nUser: {lead.full_name}\nAction: Please check the Meta Inbox.")
                                send_fb_message(sender_id, "Wait lang po, nililipat ko na ang chat kay Jeric. He will assist you shortly! 😊")
                                pass_to_agent(sender_id)
                                return HttpResponse("EVENT_RECEIVED", status=200)

            return HttpResponse("EVENT_RECEIVED", status=200)
    return HttpResponse("Invalid Request", status=400)