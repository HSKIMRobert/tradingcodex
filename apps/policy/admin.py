from django.contrib import admin

from apps.policy.models import Capability, PolicyDecision, Principal, RestrictedSymbol


admin.site.register([Capability, PolicyDecision, Principal, RestrictedSymbol])
