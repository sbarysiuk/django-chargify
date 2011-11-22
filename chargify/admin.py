from chargify.models import *
from django.contrib import admin, messages

def update(modeladmin, request, queryset):
    updated = 0
    not_found = 0
    for item in queryset:
        try:
            item.update(commit=False)
            item.enable()
            updated += 1
        except ChargifyNotFound:
            item.disable()
            not_found += 1
    messages.success(request, '%i updated, %i not found in chargify' %(updated, not_found))
update.short_description = "Update selected"

def reload_all(modeladmin, request, queryset, model):
    """ TODO: Remove all of these and add a custom template witha button 
    that will do this at the top, next to the add button"""
    model.objects.reload_all()
    messages.success(request, 'All chargify objects reloaded')
reload_all.short_description = "Reload all from Chargify"

class SubscriptionInline(admin.TabularInline):
    model = Subscription
    raw_id_fields = ('credit_card',)
    extra = 0

class CustomerAdmin(admin.ModelAdmin):
    list_display = ['chargify_id', 'last_name', 'first_name', 'email', 'reference', 'active', 'organization']
    ordering = ['_last_name', '_first_name']
    raw_id_fields = ('user',)
    search_fields = ('_reference', 'chargify_id', 'organization')
    list_filter = ('active', 'chargify_created_at', 'chargify_updated_at')
    actions = [update, 'reload_all_customers']
    inlines = [SubscriptionInline]
    
    def reload_all_customers(self, request, queryset = None):
        return reload_all(self, request, queryset, Customer)
    
admin.site.register(Customer, CustomerAdmin)

class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'price', 'chargify_id', 'handle', 'accounting_code', 'active']
    ordering = ['name']
    actions = [update, 'reload_all_products']
    
    def reload_all_products(self, request, queryset):
        return reload_all(self, request, queryset, Product)

admin.site.register(Product, ProductAdmin)

class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('chargify_id', 'customer', 'state', 'product', 'balance', 'current_period_started_at', 'trial_started_at', 'active', 'next_billing_at')
    raw_id_fields = ('customer', 'credit_card')
    search_fields = ('chargify_id', 'customer___reference')
    list_filter = ('active', 'state', 'current_period_started_at', 'next_billing_at')
    ordering = ['customer']
    actions = [update, 'reload_all_subscriptions']
    
    def reload_all_subscriptions(self, request, queryset = None):
        Subscription.objects.reload_all()

admin.site.register(Subscription, SubscriptionAdmin)

class TransactionAdmin(admin.ModelAdmin):
    list_display = ['chargify_id', 'transaction_type', 'amount_in_cents', 'created_at', 'ending_balance_in_cents',
                    'success', 'product', 'subscription']
    ordering = ['created_at']
    actions = [update, 'reload_all_transactions']
    
    def reload_all_transactions(self, request, queryset = None):
        Transaction.objects.reload_all()

admin.site.register(Transaction, TransactionAdmin)

admin.site.register(CreditCard)
