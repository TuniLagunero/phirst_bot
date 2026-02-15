from django.contrib import admin
from .models import HouseModel, Lead, Promo

@admin.register(HouseModel)
class HouseModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_contract_price', 'is_active')
    list_editable = ('is_active',)
    search_fields = ('name',)

# Add this block below:
@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    # This determines what columns David sees in the list view
    list_display = ('full_name', 'psid', 'status', 'score', 'interested_house', 'created_at')
    
    # This adds a filter sidebar on the right (Very helpful for David!)
    list_filter = ('status', 'current_step', 'financing_type')
    
    # This allows David to search by name or phone number
    search_fields = ('full_name', 'phone_number', 'psid')
    
    # This makes the "Score" and "Status" editable directly from the list
    list_editable = ('status',)

@admin.register(Promo)
class PromoAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_amount', 'start_date', 'end_date', 'is_active')
    filter_horizontal = ('applicable_houses',) # Makes selecting houses easier
    list_filter = ('is_active',)