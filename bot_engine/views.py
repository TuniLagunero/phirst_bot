import json
import requests
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from decouple import config
from .models import HouseModel, Lead, Promo 
import re
from django.utils import timezone
import google.generativeai as genai


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
        print(f"Gemini Error: {e}")
        return "Pasensya na, busy lang ang system. Type 'house' para sa models o 'start' para mag-simula uli."

# --- HELPER FUNCTIONS ---

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
    
    # FACTOR for 15 Years (Derived from your images: 0.0101427)
    # We use this to show a "Starts at X/mo" price
    amort_factor = 0.0101427 

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
        
        # 3. Calculate Estimated Monthly (15 Yrs)
        est_monthly = loan_amount * amort_factor
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

# views.py

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
        
        # --- D. BANK FORMULA (Strictly based on your images) ---
        # DP is 10% of NET TCP

        dp_percent = float(house.downpayment_percent) / 100
        
        total_dp = net_tcp * dp_percent
        dp_balance = total_dp - reservation_fee
        monthly_dp = dp_balance / 12  # 12 Months Term

        # Loan is 90% of NET TCP
        loan_amount = net_tcp * 0.90
        
        # Factors from your sheet
        monthly_15y = loan_amount * 0.0101427
        monthly_10y = loan_amount * 0.0126676
        monthly_05y = loan_amount * 0.0207584

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

        # --- D. PAG-IBIG LOGIC (Derived from your PDF Files) ---
        
        # RULE 1: Determine DP % based on Model Name
        # Unna = 20% DP
        # Calista (Mid/End) = 15% DP
        dp_percent = float(house.pagibig_downpayment_percent) / 100
        loan_percent = 1.0 - dp_percent

        # RULE 2: Calculate DP (16 Months Term)
        total_dp = net_tcp * dp_percent
        dp_balance = total_dp - reservation_fee
        monthly_dp = dp_balance / 16

        # RULE 3: Calculate Loan Amount
        loan_amount = net_tcp * loan_percent
        
        # RULE 4: Amortization Factors (Interest Rate 6.25%)
        # Derived from your sheets (e.g., 16,748.58 / 2,720,174.55)
        factor_30y = 0.00615717
        factor_25y = 0.00659670
        factor_20y = 0.00730928
        factor_15y = 0.00857423
        factor_10y = 0.01122800

        monthly_30y = loan_amount * factor_30y
        monthly_20y = loan_amount * factor_20y
        monthly_10y = loan_amount * factor_10y

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
            f"(Based on 6.25% fixed for 3 yrs)\n"
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

        # 3. Apply Cash Discount from DB (No longer hardcoded)
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
    response = requests.post(url, json=payload)
    # ADD THIS TO SEE WHY IT FAILS
    print(f"TELEGRAM STATUS: {response.status_code} - {response.text}")

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
        data = json.loads(request.body.decode('utf-8'))
        
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

                        # 2. DEFINE ALL TEXT VARIABLES AT THE TOP
                        user_msg_obj = messaging_event.get('message', {})
                        user_text = user_msg_obj.get('text', '').strip()
                        user_text_lower = user_text.lower()
                        qr_payload = user_msg_obj.get('quick_reply', {}).get('payload')
                        postback_payload = messaging_event.get('postback', {}).get('payload')

                        # 3. FETCH NAME IF MISSING (Fixes "Hi there" and "Name: None")
                        if not lead.full_name:
                            try:
                                profile = get_user_profile(sender_id)
                                if 'first_name' in profile:
                                    lead.full_name = f"{profile['first_name']} {profile.get('last_name', '')}"
                                    lead.save()
                            except Exception as e:
                                print(f"Error fetching profile: {e}")

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

                            # A. PHONE CAPTURE (Highest Priority)
                            if is_ph_phone_number(user_text):
                                lead.phone_number = user_text
                                lead.current_step = 'COMPLETED'
                                lead.save()

                                # Determine what they were doing
                                intent = "RESERVATION" if lead.status == 'HOT' else "TRIPPING"
                                
                                # 1. NOTIFY JERIC
                                alert_msg = (
                                    f"🔥 **HOT LEAD: {intent}**\n"
                                    f"👤 Name: {lead.full_name}\n"
                                    f"📞 Phone: {user_text}\n"
                                    f"🏠 Unit: {lead.interested_house.name if lead.interested_house else 'N/A'}"
                                )
                                send_telegram_alert(alert_msg)

                                # 2. CONFIRM TO USER
                                send_fb_message(sender_id, f"Salamat! Na-save ko na ang number mo. Tatawagan ka ni Jeric para sa iyong {intent.lower()} shortly. 😊")
                                
                                # 3. HANDOVER
                                pass_to_agent(sender_id)
                                return HttpResponse("EVENT_RECEIVED", status=200)

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
                                    lead.current_step = 'ASKED_LOCATION'
                                    lead.save()
                                    send_quick_reply(sender_id, "Saan mo preferred na location?", [
                                        ("Magalang", "LOC_MAGALANG"), ("Tanza", "LOC_TANZA"), ("GenTri", "LOC_GENTRI")
                                    ])
                                elif qr_payload.startswith('LOC_'):
                                    lead.location_pref = user_text
                                    lead.current_step = 'ASKED_FINANCING'
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
                            else: # <--- THIS IS THE FINAL ELSE BLOCK
                                # If the user is mid-funnel but sent a random text, redirect them
                                if lead.current_step != 'COMPLETED' and lead.current_step != 'START':
                                    send_fb_message(sender_id, "Please tap one of the options above para magpatuloy.")
                                else:
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
                                
                                # Tag lead as HOT so the phone capture knows it's a reservation
                                lead.interested_house = house
                                lead.status = 'HOT'
                                lead.save()
                                
                                send_fb_message(sender_id, f"Great choice! Para sa {house.name}, please provide your contact number para ma-assist ka ni Jeric sa reservation process.")
                                return HttpResponse("EVENT_RECEIVED", status=200)

                            # HANDLE TRIPPING INTENT
                            elif payload.startswith('SCHEDULE_TRIPPING_'):
                                house_id = payload.replace('SCHEDULE_TRIPPING_', '')
                                house = HouseModel.objects.get(id=house_id)
                                
                                # Tag lead as WARM for tripping
                                lead.interested_house = house
                                lead.status = 'WARM'
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