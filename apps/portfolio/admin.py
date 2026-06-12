from django.contrib import admin

from apps.portfolio.models import CashBalance, PortfolioSnapshot, Position


admin.site.register([CashBalance, PortfolioSnapshot, Position])
