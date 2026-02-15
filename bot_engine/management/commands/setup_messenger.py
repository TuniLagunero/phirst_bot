import requests
from django.core.management.base import BaseCommand
from decouple import config

class Command(BaseCommand):
    help = "Configures the PHirst Messenger Profile (Greeting, Get Started, and Menu)"

    def handle(self, *args, **options):
        url = f"https://graph.facebook.com/v21.0/me/messenger_profile?access_token={config('FB_PAGE_ACCESS_TOKEN')}"
        
        payload = {
            "get_started": {"payload": "START_CHATTING"},
            "greeting": [
                {
                    "locale": "default",
                    "text": "Hi {{user_first_name}}! Welcome to PHirst Park Homes. Tap Get Started to explore our models!"
                }
            ],
            "persistent_menu": [
                {
                    "locale": "default",
                    "composer_input_disabled": False,
                    "call_to_actions": [
                        {"type": "postback", "title": "View House Models 🏠", "payload": "VIEW_MODELS"},
                        {"type": "postback", "title": "Talk to Agent 📞", "payload": "TALK_TO_AGENT"}
                    ]
                }
            ]
        }
        
        response = requests.post(url, json=payload)
        result = response.json()
        
        if result.get('result') == 'success':
            self.stdout.write(self.style.SUCCESS('Successfully updated Messenger Profile!'))
        else:
            self.stdout.write(self.style.ERROR(f'Failed: {result}'))