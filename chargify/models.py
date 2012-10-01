from chargify_settings import CHARGIFY, CHARGIFY_CC_TYPES
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import models
from django.utils.datetime_safe import new_datetime
from pychargify.api import ChargifyNotFound
import logging
import time
import traceback
from django.conf import settings
from datetime import datetime, timedelta

log = logging.getLogger("chargify")
#logging.basicConfig(level=logging.DEBUG)

def unique_reference(prefix = ''):
    return '%s%i' %(prefix, time.time()*1000)

class ChargifyBaseModel(object):
    """ You can change the gateway/subdomain used by
    changing the gateway on an instantiated object """
    gateway = CHARGIFY

    def _api(self):
        raise NotImplementedError()
    api = property(_api)

    def _from_cents(self, value):
        return Decimal(str(float(value)/float(100)))

    def _in_cents(self, value):
        return Decimal(str(float(value)*float(100)))

    def update(self):
        raise NotImplementedError()

    def disable(self, commit=True):
        self.active = False
        if commit:
            self.save()

    def enable(self, commit=True):
        self.active = True
        if commit:
            self.save()

class ChargifyBaseManager(models.Manager):
    def _gateway(self):
        return self.model.gateway
    gateway = property(_gateway)

    def _api(self):
        raise NotImplementedError()
    api = property(_api)

    def _check_api(self):
        if self.api is None:
            raise ValueError('Blank API Not Set on Manager')

    def get_or_load(self, chargify_id):
        self._check_api()
        val = None
        loaded = False
        try:
            val = self.get(chargify_id = chargify_id)
            loaded = False
        except:
            pass
        finally:
            if val is None:
                api = self.api.getById(chargify_id)
                val = self.model().load(api)
                loaded = True
        return val, loaded

    def load_and_update(self, chargify_id):
        self._check_api()
        val, loaded = self.get_or_load(chargify_id)
        if not loaded:
            val.update()
        return val

    def reload_all(self):
        self._check_api()
        items = self.api.getAll()
        for item in items:
            val = self.load_and_update(item.id)
            val.save()

class CustomerManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Customer()
    api = property(_api)

class Customer(models.Model, ChargifyBaseModel):
    """ The following are mapped fields:
        first_name = User.first_name (required)
        last_name = User.last_name (required)
        email = User.email (required)
        reference = Customer.id
    """
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    user = models.ForeignKey(User)
    _first_name = models.CharField(max_length = 50, null=True, blank=False)
    _last_name = models.CharField(max_length = 50, null = True, blank=False)
    _email = models.EmailField(null=True, blank=False)
    _reference = models.CharField(max_length = 50, null=True, blank=True)
    organization = models.CharField(max_length = 75, null=True, blank=True)
    active = models.BooleanField(default=True)

    # Read only chargify fields
    chargify_created_at = models.DateTimeField(null=True)
    chargify_updated_at = models.DateTimeField(null=True)
    updated_at = models.DateTimeField(auto_now=True)
    objects = CustomerManager()

    def full_name(self):
        if not self.last_name:
            return self.first_name
        else:
            return '%s %s' %(self.first_name, self.last_name)

    def __unicode__(self):
        return self.full_name() + u' - ' + str(self.chargify_id )

    def _get_first_name(self):
        if self._first_name is not None:
            return self._first_name
        return self.user.first_name
    def _set_first_name(self, first_name):
        if self.user.first_name != first_name:
            self._first_name = first_name
    first_name = property(_get_first_name, _set_first_name)

    def _get_last_name(self):
        if self._last_name is not None:
            return self._last_name
        return self.user.last_name
    def _set_last_name(self, last_name):
        if self.user.last_name != last_name:
            self._last_name = last_name
    last_name = property(_get_last_name, _set_last_name)

    def _get_email(self):
        if self._email is not None:
            return self._email
        return self.user.email
    def _set_email(self, email):
        if self.user.email != email:
            self._email = email
    email = property(_get_email, _set_email)

    def _get_reference(self):
        """ You must save the customer before you can get the reference number"""
        if getattr(settings, 'TESTING', False) and not self._reference:
            self._reference = unique_reference()

        if self._reference:
            return self._reference
        elif self.id:
            return self.id
        else:
            return ''
    def _set_reference(self, reference):
        self._reference = reference
    reference = property(_get_reference, _set_reference)

    def save(self, save_api = False, **kwargs):
        if save_api:
            if not self.id:
                super(Customer, self).save(**kwargs)
            saved = False
            try:
                saved, customer = self.api.save()
            except ChargifyNotFound, e:
                for error in e.errors:
                    log.exception(error)
                api = self.api
                api.id = None
                saved, customer = api.save()

            if saved:
                log.debug("Customer Saved")
                return self.load(customer, commit=True) # object save happens after load
            else:
                log.debug("Customer Not Saved")
                log.debug(customer)
        self.user.save()
        return super(Customer, self).save(**kwargs)

    def load(self, api, commit=True):
        if self.id or self.chargify_id:# api.modified_at > self.chargify_updated_at:
            customer = self
        else:
#            log.debug('Not loading api')
            customer = Customer()
        log.debug('Loading Customer API: %s' %(api))
        customer.chargify_id = int(api.id)
        if api.reference:
            customer._reference = api.reference
        try:
            if customer.user:
                customer.first_name = api.first_name
                customer.last_name = api.last_name
                customer.email = api.email
            else:
                raise User.DoesNotExist
        except User.DoesNotExist: #@UndefinedVariable
            try:
                user = User.objects.get(email=api.email)
            except:
                # create inactive user when loading from Chargify
                user = User(first_name = api.first_name, last_name = api.last_name,
                            email = api.email, username = api.email, is_active = False)
                user.save()
            customer.user = user
        customer.organization = api.organization
        customer.chargify_updated_at = api.modified_at
        customer.chargify_created_at = api.created_at
        if commit:
            customer.save()
        return customer

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit)

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        customer = self.gateway.Customer(node_name)
        customer.id = str(self.chargify_id)
        customer.first_name = self.first_name
        customer.last_name = self.last_name
        customer.email = self.email
        customer.organization = self.organization
        customer.reference = self.reference
        return customer
    api = property(_api)

class ProductManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Product()
    api = property(_api)

    def reload_all(self):
        products = {}
        for product in self.gateway.Product().getAll():
            try:
                p, loaded = self.get_or_load(product.id)
                if not loaded:
                    p.update()
                p.save()
                products[product.handle] = p
            except:
                log.error('Failed to load product: %s' %(product))
                log.error(traceback.format_exc())

class Product(models.Model, ChargifyBaseModel):
    MONTH = 'month'
    DAY = 'day'
    INTERVAL_TYPES = (
          (MONTH, MONTH.title()),
          (DAY, DAY.title()),
          )
    chargify_id = models.IntegerField(null=True, blank=False, unique=True)
    price = models.DecimalField(decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    name = models.CharField(max_length=75)
    handle = models.CharField(max_length=75, default='')
    product_family = {}
    accounting_code = models.CharField(max_length=30, null=True)
    interval_unit = models.CharField(max_length=10, choices = INTERVAL_TYPES, default=MONTH)
    interval = models.IntegerField(default=1)
    active = models.BooleanField(default=True)
    objects = ProductManager()

    def __unicode__(self):
        return self.name

    def _price_in_cents(self):
        return self._in_cents(self.price)
    def _set_price_in_cents(self, price):
        self.price = self._from_cents(price)
    price_in_cents = property(_price_in_cents, _set_price_in_cents)

    def _set_handle(self, handle):
        self.handle = str(handle)
    product_handle = property(handle, _set_handle)

    def save(self, save_api = False, **kwargs):
        if save_api:
            try:
                saved, product = self.api.save()
                if saved:
                    return self.load(product, commit=True) # object save happens after load
            except:
                pass
#        self.api.save()
        return super(Product, self).save(**kwargs)

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.price_in_cents = api.price_in_cents
        self.name = api.name
        self.handle = api.handle
        self.product_family = api.product_family
        self.accounting_code = api.accounting_code
        self.interval_unit = api.interval_unit
        self.interval = api.interval
        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit = True)

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        product = self.gateway.Product(node_name)
        product.id = str(self.chargify_id)
        product.price_in_cents = self.price_in_cents
        product.name = self.name
        product.handle = self.handle
        product.product_family = self.product_family
        product.accounting_code = self.accounting_code
        product.interval_unit = self.interval_unit
        product.interval = self.interval
        return product
    api = property(_api)

class CreditCardManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.CreditCard()
    api = property(_api)

class CreditCard(models.Model, ChargifyBaseModel):
    """ This data should NEVER be saved in the database """
    CC_TYPES = CHARGIFY_CC_TYPES
    _full_number = ''
    ccv = ''

    first_name = models.CharField(max_length = 50, null=True, blank=False)
    last_name = models.CharField(max_length = 50, null=True, blank=False)
    masked_card_number = models.CharField(max_length=25, null=True)
    expiration_month = models.IntegerField(null=True, blank=True)
    expiration_year = models.IntegerField(null=True, blank=True)
    credit_type = models.CharField(max_length=25, null=True, blank=False, choices=CC_TYPES)
    billing_address = models.CharField(max_length=75, null=True, blank=False, default='')
    billing_city = models.CharField(max_length=75, null=True, blank=False, default='')
    billing_state = models.CharField(max_length=2, null=True, blank=False, default='')
    billing_zip = models.CharField(max_length=15, null=True, blank=False, default='')
    billing_country = models.CharField(max_length=75, null=True, blank=True, default='United States')
    active = models.BooleanField(default=True)
    objects = CreditCardManager()

    def __unicode__(self):
        s = u''
        if self.first_name:
            s += unicode(self.first_name)
        if self.last_name:
            if s:
                s += u' '
            s += unicode(self.last_name)
        if self.masked_card_number:
            if s:
                s += u'-'
            s += unicode(self.masked_card_number)
        return s

    # you have to set the customer if there is no related subscription yet
    _customer = None
    def _get_customer(self):
        if self._customer:
            return self._customer
        try:
            return self.subscription.all().order_by('-updated_at')[0].customer
        except IndexError:
            return None
    def _set_customer(self, customer):
        self._customer = customer
    customer = property(_get_customer, _set_customer)

    def _get_full_number(self):
        return self._full_number
    def _set_full_number(self, full_number):
        self._full_number = full_number

        if len(full_number) > 4:
            self.masked_card_number = u'XXXX-XXXX-XXXX-' + full_number[-4:]
        else: #not a real CC number, probably a testing number
            self.masked_card_number = u'XXXX-XXXX-XXXX-1111'
    full_number = property(_get_full_number, _set_full_number)

    def save(self,  save_api = False, *args, **kwargs):
        if save_api:
            self.api.save()
        return super(CreditCard, self).save(*args, **kwargs)

    def load(self, api, commit=True):
        if api is None:
            return self
        self.masked_card_number = api.masked_card_number
        self.expiration_month = api.expiration_month
        self.expiration_year = api.expiration_year
        self.credit_type = api.type
        if commit:
            self.save(save_api = False)
        return self

    def update(self, commit=True):
        """ Update Credit Card data from chargify """
        if self.subscription:
            return self.subscription.update()
        else:
            return self

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        cc = self.gateway.CreditCard(node_name)
        cc.first_name = self.first_name
        cc.last_name = self.last_name
        cc.full_number = self._full_number
        cc.expiration_month = self.expiration_month
        cc.expiration_year = self.expiration_year
        cc.ccv = self.ccv
        cc.billing_address = self.billing_address
        cc.billing_city = self.billing_city
        cc.billing_state = self.billing_state
        cc.billing_zip = self.billing_zip
        cc.billing_country = self.billing_country
        return cc
    api = property(_api)


class CouponManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Coupon()
    api = property(_api)

    def find(self, code):
        """ Finds and loads a Coupon """
        try:
            return self.filter(code=code)[0]
        except IndexError:
            return self.model().load(
                self.api.find(code))


class Coupon(models.Model, ChargifyBaseModel):
    chargify_id = models.IntegerField(null=True, blank=True, unique=True)
    code = models.CharField(max_length=100, null=True, blank=True)
    name = models.CharField(max_length=100, null=True, blank=True)
    percentage = models.IntegerField(null=True, blank=True)
    amount = models.DecimalField(decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    allow_negative_balance = models.BooleanField(default=False)
    recurring = models.BooleanField(default=True)
    coupon_end_date = models.DateTimeField(null=True, blank=True)

    objects = CouponManager()

    def _amount_in_cents(self):
        return self._in_cents(self.amount)

    def _set_amount_in_cents(self, amount):
        self.amount = self._from_cents(amount)
    amount_in_cents = property(_amount_in_cents, _set_amount_in_cents)

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        try:
            self = Coupon.objects.get(chargify_id=self.chargify_id)
        except Coupon.DoesNotExist:
            pass
        self.code = api.code
        self.name = api.name
        if api.percentage:
            self.percentage = api.percentage
        if api.amount_in_cents:
            self.amount_in_cents = api.amount_in_cents
        if api.coupon_end_date:
            self.coupon_end_date = new_datetime(api.coupon_end_date)
        self.allow_negative_balance = api.allow_negative_balance
        self.recurring = api.recurring
        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit = True)

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        instance = self.gateway.Coupon(node_name)
        instance.id = str(self.chargify_id)
        instance.name = self.name
        instance.code = self.code
        instance.percentage = self.percentage
        instance.allow_negative_balance = self.allow_negative_balance
        instance.coupon_end_date = self.coupon_end_date
        instance.recurring = self.recurring
        instance.amount_in_cents = self.amount_in_cents
        return instance

    api = property(_api)

class SubscriptionManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Subscription()
    api = property(_api)

    def update_list(self, lst):
        for id in lst:
            sub= self.load_and_update(id)
            sub.save()

    def reload_all(self):
        """ You should only run this when you first install the product!
        VERY EXPENSIVE!!! """
        Product.objects.reload_all()
        for customer in Customer.objects.filter(active=True):
            subscriptions = self.api.getByCustomerId(str(customer.chargify_id))
            if not subscriptions:
                continue
            for subscription in subscriptions:
                try:
                    sub = self.get(chargify_id = subscription.id)
                except:
                    sub = self.model()
                    sub.load(subscription)
                sub.save()


class QuantityComponent(models.Model, ChargifyBaseModel):
    component_id = models.IntegerField(blank=True, null=True)
    allocated_quantity = models.IntegerField(default=1)

    def to_dict(self):
        return {
            'component_id': self.component_id,
            'allocated_quantity': self.allocated_quantity
        }


class Subscription(models.Model, ChargifyBaseModel):
    TRIALING = 'trialing'
    ASSESSING = 'assessing'
    ACTIVE = 'active'
    SOFT_FAILURE = 'soft_failure'
    PAST_DUE = 'past_due'
    SUSPENDED = 'suspended'
    CANCELLED = 'canceled'
    EXPIRED = 'expired'
    UNPAID = 'unpaid'
    STATE_CHOICES = (
         (TRIALING, u'Trialing'),
         (ASSESSING, u'Assessing'),
         (ACTIVE, u'Active'),
         (SOFT_FAILURE, u'Soft Failure'),
         (PAST_DUE, u'Past Due'),
         (SUSPENDED, u'Suspended'),
         (CANCELLED, u'Cancelled'),
         (EXPIRED, u'Expired'),
         (UNPAID, u'Unpaid'),
         )
    chargify_id = models.IntegerField(null=True, blank=True, unique=True)
    state = models.CharField(max_length=15, null=True, blank=True, default='', choices=STATE_CHOICES)
    balance = models.DecimalField(decimal_places = 2, max_digits = 15, default=Decimal('0.00'))
    current_period_started_at = models.DateTimeField(null=True, blank=True)
    current_period_ends_at = models.DateTimeField(null=True, blank=True)
    trial_started_at = models.DateTimeField(null=True, blank=True)
    trial_ended_at = models.DateTimeField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    customer = models.ForeignKey(Customer, null=True)
    product = models.ForeignKey(Product, null=True)
    credit_card = models.OneToOneField(CreditCard, related_name='subscription', null=True, blank=True)
    active = models.BooleanField(default=True)
    next_billing_at = models.DateTimeField(null=True, blank=True)
    coupons = models.ManyToManyField(Coupon, related_name='subscriptions', blank=True)
    component = models.OneToOneField(QuantityComponent, blank=True, null=True)

    objects = SubscriptionManager()

    def __unicode__(self):
        s = unicode(self.get_state_display())
        if self.product:
            s += u' ' + self.product.name
        if self.chargify_id:
            s += ' - ' + unicode(self.chargify_id)

        return s

    def _balance_in_cents(self):
        return self._in_cents(self.balance)

    def _set_balance_in_cents(self, value):
        self.balance = self._from_cents(value)
    balance_in_cents = property(_balance_in_cents, _set_balance_in_cents)

    def _product_handle(self):
        return self.product.handle
    product_handle = property(_product_handle)

    def change_component(self, component_id, allocated_quantity):
        reset_component = True
        if not self.component:
            self.component = QuantityComponent.objects.create(component_id=component_id, allocated_quantity=allocated_quantity)
            super(Subscription, self).save()
            reset_component = False

        if reset_component:
            self.api.change_quantity(self.component.component_id, 0)

        self.api.change_quantity(component_id, allocated_quantity)

        if reset_component:
            self.component.component_id = component_id
            self.allocated_quantity = allocated_quantity
            self.component.save()

    def save(self, save_api = False, *args, **kwargs):
        if self.chargify_id is None:
            save_api = True
        if save_api:
            if self.customer.chargify_id is None:
                log.debug('Saving Customer')
                self.customer.save(save_api = True)
                customer = self.customer
                log.debug("Returned Customer: %s" %(customer))
                log.debug('Customer ID: %s' %(customer.chargify_id))
                self.customer = customer
            if self.product and self.product.chargify_id is None:
                log.debug('Saving Product')
                product = self.product.save(save_api = True)
                log.debug("Returned Product : %s" %(product))
                self.product = product
            api = self.api
            log.debug('Saving API')
            saved, subscription = self.save_subscription(api, **kwargs)
            if saved:
                return self.load(subscription, commit=True) # object save happens after load
        return super(Subscription, self).save(*args, **kwargs)

    def save_subscription(self, api, component=None, allocated_quantity=0):
        if component:
            if not self.component:
                self.component = QuantityComponent.objects.create(component_id=component, allocated_quantity=allocated_quantity)
                super(Subscription, self).save()
            component_dict = {
                'component': self.component.to_dict()
            }
            api.components = [component_dict]
        return api.save()

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.state = api.state
        self.balance_in_cents = api.balance_in_cents
        self.current_period_started_at = new_datetime(api.current_period_started_at)
        self.current_period_ends_at = new_datetime(api.current_period_ends_at)
        if api.trial_started_at:
            self.trial_started_at = new_datetime(api.trial_started_at)
        else:
            self.trial_started_at = None
        if api.trial_ended_at:
            self.trial_ended_at = new_datetime(api.trial_ended_at)
        else:
            self.trial_ended_at = None
        if api.activated_at:
            self.activated_at = new_datetime(api.activated_at)
        else:
            self.activated_at = None
        if api.expires_at:
            self.expires_at = new_datetime(api.expires_at)
        else:
            self.expires_at = None
        if api.next_assessment_at:
            self.next_billing_at = new_datetime(api.next_assessment_at)
        elif api.next_billing_at:
            self.next_billing_at = new_datetime(api.next_billing_at)
        else:
            self.next_billing_at = None
        self.created_at = new_datetime(api.created_at)
        self.updated_at = new_datetime(api.updated_at)
        try:
            c = Customer.objects.get(chargify_id = api.customer.id)
        except:
            c = Customer()
            c.load(api.customer)
        self.customer = c

        try:
            p = Product.objects.get(chargify_id = api.product.id)
        except:
            p = Product()
            p.load(api.product)
            p.save()
        self.product = p

        if self.credit_card:
            credit_card = self.credit_card
        else:
            credit_card = CreditCard()
            credit_card.load(api.credit_card)
        if commit:
            self.save()
        return self

    def update(self, commit=True):
        """ Update Subscription data from chargify """
        subscription = self.gateway.Subscription().getBySubscriptionId(self.chargify_id)
        return self.load(subscription, commit)

    def upgrade(self, product, include_trial=1, include_initial_charge=0):
        """ Upgrade / Downgrade products """
        return self.update(self.api.upgrade(product.handle,
                                            include_trial=include_trial,
                                            include_initial_charge=include_initial_charge))
    def reactivate(self):
        """ Reactivates already canceleed subscription. """
        instance =  self.update(self.api.reactivate())
        instance.active = True
        instance.save()
        return instance

    def add_coupon(self, coupon):
        self.api.add_coupon(coupon.code)
        self.coupons.add(coupon)

    def unsubscribe(self, message=""):
        """ Cancels the subscription. """
        instance = self.update(self.api.unsubscribe(message=message))
        instance.active = False
        instance.save()
        return instance

    def renew(self, target_datetime):
        """ Renews the subscription by setting next_billing_at to the given 'target_datetime'. """
        self.next_billing_at = target_datetime
        self._next_billing_at_changed = True
        saved, subscription = self.api.save()
        if saved:
            return self.load(subscription, commit=True)
        return self

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        subscription = self.gateway.Subscription(node_name)
        if self.chargify_id:
            subscription.id = str(self.chargify_id)
        subscription.product = self.product.api
        subscription.product_handle = self.product_handle
        if self.customer.chargify_id is None:
            subscription.customer = self.customer._api('customer_attributes')
        else:
            subscription.customer = self.customer._api('customer_id')
        if self.credit_card:
            subscription.credit_card = self.credit_card._api('credit_card_attributes')
        if getattr(self, '_next_billing_at_changed', False):
            subscription.next_billing_at = self.next_billing_at

        return subscription
    api = property(_api)

class TransactionManager(ChargifyBaseManager):
    def _api(self):
        return self.gateway.Transaction()
    api = property(_api)

    def reload_all(self):
        for t in self.api.getAll():
            try:
                instance = self.get(chargify_id=t.id)
                instance.load(t)
            except Transaction.DoesNotExist:
                self.model().load(t)


class Transaction(models.Model, ChargifyBaseModel):
    CHARGE = 'charge'
    REFUND = 'refund'
    PAYMENT = 'payment'
    CREDIT = 'credit'
    PAYMENT_AUTHORIZATION = 'payment_authorization'
    INFO = 'info'
    ADJUSTMENT = 'adjustment'
    TRANSACTION_TYPE_CHOICES = (
         (CHARGE, u'Charge'),
         (REFUND, u'Refund'),
         (PAYMENT, u'Payment'),
         (CREDIT, u'Credit'),
         (PAYMENT_AUTHORIZATION, u'Payment Authorization'),
         (INFO, u'Suspended'),
         (ADJUSTMENT, u'Cancelled'),
         )

    chargify_id = models.IntegerField(null=True, blank=True, unique=True)
    transaction_type = models.CharField(max_length=15, null=True, blank=True, default='', choices=TRANSACTION_TYPE_CHOICES)
    amount_in_cents = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(null=True, blank=True)
    ending_balance_in_cents = models.IntegerField(null=True, blank=True)
    memo = models.CharField(max_length=250, null=True, blank=False)
    success = models.BooleanField(default=True)
    product = models.ForeignKey(Product, null=True, related_name='transactions')
    subscription = models.ForeignKey(Subscription, null=True, related_name='transactions')

    objects = TransactionManager()

    def load(self, api, commit=True):
        self.chargify_id = int(api.id)
        self.transaction_type = api.transaction_type
        self.amount_in_cents = api.amount_in_cents
        self.ending_balance_in_cents = api.ending_balance_in_cents
        self.memo = api.memo
        self.created_at = new_datetime(api.created_at)
        self.success = api.success == 'true'
        self.subscription, loaded = Subscription.objects.get_or_load(api.subscription_id)
        self.product, loaded = Product.objects.get_or_load(api.product_id)
        if commit:
            self.save()
        return self

    def update(self, commit = True):
        """ Update customer data from chargify """
        api = self.api.getById(self.chargify_id)
        return self.load(api, commit = True)

    def _api(self, node_name = ''):
        """ Load data into chargify api object """
        instance = self.gateway.Transaction(node_name)
        instance.id = str(self.chargify_id)
        instance.amount_in_cents = self.amount_in_cents
        instance.ending_balance_in_cents = self.ending_balance_in_cents
        instance.memo = self.memo
        instance.created_at = self.created_at
        instance.success = self.success
        instance.product = self.product.api
        instance.subscription = self.subscription.api
        return instance
    api = property(_api)

