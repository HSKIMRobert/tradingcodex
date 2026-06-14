from django.contrib import admin

from apps.integrations.models import AdapterDefinition, BrokerAccount, BrokerConnection, InstrumentMap


admin.site.register([AdapterDefinition, BrokerAccount, BrokerConnection, InstrumentMap])
