from django.db import models
from django.utils import timezone

class HouseModel(models.Model):
    name = models.CharField(max_length=100, help_text="e.g., Unna Model")
    description = models.CharField(max_length=80, help_text="Short description")
    image_url = models.URLField(help_text="Direct link to photo")
    details_link = models.URLField(help_text="Link to property page")
    
    # Financial Fields
    total_contract_price = models.DecimalField(max_digits=12, decimal_places=2)
    reservation_fee = models.DecimalField(max_digits=10, decimal_places=2, default=15000)
    # Field 1: For Bank Financing (Standard 10%)
    downpayment_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=10.00,
        verbose_name="Bank DP %"
    )
    # Field 2: For Pag-IBIG Financing (New Field)
    pagibig_downpayment_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=15.00,
        verbose_name="Pag-IBIG DP % (15 or 20)"
    )
    loan_term_years = models.IntegerField(default=20)
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=7.00)

    cash_discount_percent = models.DecimalField(
        max_digits=5, 
        decimal_places=2,
        default=8.00,
        verbose_name="Cash Discount %(8)"
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    location = models.CharField(
        max_length=100, 
        choices=[
            ('Magalang', 'Magalang, Pampanga'),
            ('Tanza', 'Tanza, Cavite'),
            ('GenTri', 'General Trias, Cavite'),
        ],
        default='Magalang'
    )

    # REMOVED: @property def monthly_amortization
    # Why: It calculates based on the raw price and ignores promos. 
    # We will handle the exact calculation in views.py to ensure accuracy.

    def __str__(self):
        return self.name

class Lead(models.Model):
    # ... (Your Lead model is perfect, no changes needed) ...
    STATUS_CHOICES = [('COLD', 'Inquirer'), ('WARM', 'Interested'), ('HOT', 'Hot Lead')]
    FINANCING_CHOICES = [('BANK', 'Bank'), ('CASH', 'Cash'), ('PAGIBIG', 'Pag-IBIG')]
    STEP_CHOICES = [
        ('START', 'Starting'), ('ASKED_BUDGET', 'Asked Budget'), 
        ('ASKED_LOCATION', 'Asked Location'), ('ASKED_FINANCING', 'Asked Financing'),
        ('ASKED_PHONE', 'Asked Phone'), ('COMPLETED', 'Completed')
    ]

    psid = models.CharField(max_length=100, unique=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    interested_house = models.ForeignKey(HouseModel, on_delete=models.SET_NULL, null=True)
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='COLD')
    score = models.IntegerField(default=0)
    last_alert_sent = models.DateTimeField(null=True, blank=True)
    
    timeline = models.CharField(max_length=50, blank=True, null=True)
    current_step = models.CharField(max_length=50, default='START', choices=STEP_CHOICES)
    financing_type = models.CharField(max_length=20, choices=FINANCING_CHOICES, blank=True, null=True)
    budget_range = models.CharField(max_length=50, blank=True, null=True)
    location_pref = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name or 'Unknown'} - {self.interested_house}"

class Promo(models.Model):
    name = models.CharField(max_length=200, help_text="e.g. Feb-IBIG Month Promo")
    description = models.TextField(help_text="e.g. Less 120k upon reservation!")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Added blank=True to make it optional in admin forms initially
    applicable_houses = models.ManyToManyField(HouseModel, related_name='promos', blank=True)
    
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} (₱{self.discount_amount:,.0f} off)"