from django.contrib import admin
from .models import HouseModel, Lead, Promo, HouseImage



class HouseImageInline(admin.TabularInline):
    model = HouseImage
    extra = 1 # Shows one blank row by default


@admin.register(HouseModel)
class HouseModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_contract_price', 'interest_rate', 'bank_interest_rate', 'is_active')
    list_editable = ('interest_rate', 'bank_interest_rate', 'is_active')
    search_fields = ('name',)

    inlines = [HouseImageInline]



# Add this block below:
@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    # CRITICAL FIX: Added phone_number and updated_at. Removed 'score' unless you actually use it.
    list_display = ('full_name', 'phone_number', 'status', 'current_step', 'interested_house', 'updated_at')
    
    # Filter sidebar (Helpful for Jeric to find HOT leads quickly)
    list_filter = ('status', 'current_step', 'financing_type', 'location_pref')
    
    # Search by name or phone
    search_fields = ('full_name', 'phone_number', 'psid')
    
    # Make status editable directly from the list view
    list_editable = ('status',)
    
    # SYSTEM PROTECTION: Prevent Jeric from breaking the bot's state tracking
    readonly_fields = ('psid', 'created_at', 'updated_at', 'last_alert_sent', 'followed_up')

@admin.register(Promo)
class PromoAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_amount', 'start_date', 'end_date', 'is_active')
    filter_horizontal = ('applicable_houses',) # Makes selecting houses easier
    list_filter = ('is_active',)