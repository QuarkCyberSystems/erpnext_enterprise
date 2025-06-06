# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import unittest
from contextlib import contextmanager
from typing import Any, NewType

import frappe
from frappe import _
from frappe.core.doctype.report.report import get_report_module_dotted_path
from frappe.utils import now_datetime

ReportFilters = dict[str, Any]
ReportName = NewType("ReportName", str)


def create_test_contact_and_address():
	frappe.db.sql("delete from tabContact")
	frappe.db.sql("delete from `tabContact Email`")
	frappe.db.sql("delete from `tabContact Phone`")
	frappe.db.sql("delete from tabAddress")
	frappe.db.sql("delete from `tabDynamic Link`")

	frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": "_Test Address for Customer",
			"address_type": "Office",
			"address_line1": "Station Road",
			"city": "_Test City",
			"state": "Test State",
			"country": "India",
			"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
		}
	).insert()

	contact = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": "_Test Contact for _Test Customer",
			"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
		}
	)
	contact.add_email("test_contact_customer@example.com", is_primary=True)
	contact.add_phone("+91 0000000000", is_primary_phone=True)
	contact.insert()

	contact_two = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": "_Test Contact 2 for _Test Customer",
			"links": [{"link_doctype": "Customer", "link_name": "_Test Customer"}],
		}
	)
	contact_two.add_email("test_contact_two_customer@example.com", is_primary=True)
	contact_two.add_phone("+92 0000000000", is_primary_phone=True)
	contact_two.insert()


def execute_script_report(
	report_name: ReportName,
	module: str,
	filters: ReportFilters,
	default_filters: ReportFilters | None = None,
	optional_filters: ReportFilters | None = None,
):
	"""Util for testing execution of a report with specified filters.

	Tests the execution of report with default_filters + filters.
	Tests the execution using optional_filters one at a time.

	Args:
	        report_name: Human readable name of report (unscrubbed)
	        module: module to which report belongs to
	        filters: specific values for filters
	        default_filters: default values for filters such as company name.
	        optional_filters: filters which should be tested one at a time in addition to default filters.
	"""

	if default_filters is None:
		default_filters = {}

	test_filters = []
	report_execute_fn = frappe.get_attr(get_report_module_dotted_path(module, report_name) + ".execute")
	report_filters = frappe._dict(default_filters).copy().update(filters)

	test_filters.append(report_filters)

	if optional_filters:
		for key, value in optional_filters.items():
			test_filters.append(report_filters.copy().update({key: value}))

	for test_filter in test_filters:
		try:
			report_execute_fn(test_filter)
		except Exception:
			print(f"Report failed to execute with filters: {test_filter}")
			raise


def if_lending_app_installed(function):
	"""Decorator to check if lending app is installed"""

	def wrapper(*args, **kwargs):
		if "lending" in frappe.get_installed_apps():
			return function(*args, **kwargs)
		return

	return wrapper


def if_lending_app_not_installed(function):
	"""Decorator to check if lending app is not installed"""

	def wrapper(*args, **kwargs):
		if "lending" not in frappe.get_installed_apps():
			return function(*args, **kwargs)
		return

	return wrapper


class ERPNextTestSuite(unittest.TestCase):
	@classmethod
	def registerAs(cls, _as):
		def decorator(cm_func):
			setattr(cls, cm_func.__name__, _as(cm_func))
			return cm_func

		return decorator

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.make_persistant_master_data()

	@classmethod
	def make_persistant_master_data(cls):
		# presets and default are mandatory for company
		cls.make_warehouse_type()
		cls.make_uom()
		cls.make_address_template()
		cls.make_fiscal_year()
		cls.make_company()
		cls.update_stock_settings()

		frappe.db.commit()

	@classmethod
	def update_stock_settings(cls):
		stock_settings = frappe.get_doc("Stock Settings")
		stock_settings.item_naming_by = "Item Code"
		stock_settings.valuation_method = "FIFO"
		stock_settings.default_warehouse = frappe.db.get_value("Warehouse", {"warehouse_name": _("Stores")})
		stock_settings.stock_uom = "Nos"
		stock_settings.auto_indent = 1
		stock_settings.auto_insert_price_list_rate_if_missing = 1
		stock_settings.update_price_list_based_on = "Rate"
		stock_settings.set_qty_in_transactions_based_on_serial_no_input = 1
		stock_settings.enable_serial_and_batch_no_for_item = 1
		stock_settings.save()

	@classmethod
	def make_price_list(cls):
		records = [
			{
				"doctype": "Price List",
				"price_list_name": _("Standard Buying"),
				"enabled": 1,
				"buying": 1,
				"selling": 0,
				"currency": "INR",
			},
			{
				"doctype": "Price List",
				"price_list_name": _("Standard Selling"),
				"enabled": 1,
				"buying": 0,
				"selling": 1,
				"currency": "INR",
			},
		]
		cls.price_list = []
		for x in records:
			if not frappe.db.exists(
				"Price List",
				{
					"price_list_name": x.get("price_list_name"),
					"enabled": x.get("enabled"),
					"selling": x.get("selling"),
					"buying": x.get("buying"),
					"currency": x.get("currency"),
				},
			):
				cls.price_list.append(frappe.get_doc(x).insert())
			else:
				cls.price_list.append(
					frappe.get_doc(
						"Price List",
						{
							"price_list_name": x.get("price_list_name"),
							"enabled": x.get("enabled"),
							"selling": x.get("selling"),
							"buying": x.get("buying"),
							"currency": x.get("currency"),
						},
					)
				)

	@classmethod
	def make_address_template(cls):
		records = [
			{
				"doctype": "Address Template",
				"country": "India",
				"is_default": True,
				"template": """
				{{ address_line1 }}<br>
				{% if address_line2 %}{{ address_line2 }}<br>{% endif -%}
				{{ city }}<br>
				{% if state %}{{ state }}<br>{% endif -%}
				{% if pincode %}{{ pincode }}<br>{% endif -%}
				{{ country }}<br>
				<br>
				{% if phone %}{{ _("Phone") }}: {{ phone }}<br>{% endif -%}
				{% if fax %}{{ _("Fax") }}: {{ fax }}<br>{% endif -%}
				{% if email_id %}{{ _("Email") }}: {{ email_id }}<br>{% endif -%}
				""",
			}
		]
		cls.address_template = []
		for x in records:
			if not frappe.db.exists("Address Template", {"country": x.get("country")}):
				cls.address_template.append(frappe.get_doc(x).insert())
			else:
				cls.address_template.append(frappe.get_doc("Address Template", {"country": x.get("country")}))

	@classmethod
	def make_uom(cls):
		records = [{"doctype": "UOM", "uom_name": "Nos", "must_be_whole_number": 1, "common_code": "C62"}]
		cls.uom = []
		for x in records:
			if not frappe.db.exists("UOM", {"uom_name": x.get("uom_name")}):
				cls.warehouse_type.append(frappe.get_doc(x).insert())
			else:
				cls.warehouse_type.append(frappe.get_doc("UOM", {"uom_name": x.get("uom_name")}))

	@classmethod
	def make_warehouse_type(cls):
		records = [{"doctype": "Warehouse Type", "name": "Transit"}]
		cls.warehouse_type = []
		for x in records:
			if not frappe.db.exists("Warehouse Type", {"name": x.get("name")}):
				cls.warehouse_type.append(frappe.get_doc(x).insert())
			else:
				cls.warehouse_type.append(frappe.get_doc("Warehouse Type", {"name": x.get("name")}))

	@classmethod
	def make_monthly_distribution(cls):
		records = [
			{
				"doctype": "Monthly Distribution",
				"distribution_id": "_Test Distribution",
				"fiscal_year": "_Test Fiscal Year 2013",
				"percentages": [
					{"month": "January", "percentage_allocation": "8"},
					{"month": "February", "percentage_allocation": "8"},
					{"month": "March", "percentage_allocation": "8"},
					{"month": "April", "percentage_allocation": "8"},
					{"month": "May", "percentage_allocation": "8"},
					{"month": "June", "percentage_allocation": "8"},
					{"month": "July", "percentage_allocation": "8"},
					{"month": "August", "percentage_allocation": "8"},
					{"month": "September", "percentage_allocation": "8"},
					{"month": "October", "percentage_allocation": "8"},
					{"month": "November", "percentage_allocation": "10"},
					{"month": "December", "percentage_allocation": "10"},
				],
			}
		]
		cls.monthly_distribution = []
		for x in records:
			if not frappe.db.exists("Monthly Distribution", {"distribution_id": x.get("distribution_id")}):
				cls.monthly_distribution.append(frappe.get_doc(x).insert())
			else:
				cls.monthly_distribution.append(
					frappe.get_doc("Monthly Distribution", {"distribution_id": x.get("distribution_id")})
				)

	@classmethod
	def make_projects(cls):
		records = [
			{
				"doctype": "Project",
				"company": "_Test Company",
				"project_name": "_Test Project",
				"status": "Open",
			}
		]

		cls.projects = []
		for x in records:
			if not frappe.db.exists("Project", {"project_name": x.get("project_name")}):
				cls.projects.append(frappe.get_doc(x).insert())
			else:
				cls.projects.append(frappe.get_doc("Project", {"project_name": x.get("project_name")}))

	@classmethod
	def make_employees(cls):
		records = [
			{
				"company": "_Test Company",
				"date_of_birth": "1980-01-01",
				"date_of_joining": "2010-01-01",
				"department": "_Test Department - _TC",
				"doctype": "Employee",
				"first_name": "_Test Employee",
				"gender": "Female",
				"naming_series": "_T-Employee-",
				"status": "Active",
				"user_id": "test@example.com",
			},
			{
				"company": "_Test Company",
				"date_of_birth": "1980-01-01",
				"date_of_joining": "2010-01-01",
				"department": "_Test Department 1 - _TC",
				"doctype": "Employee",
				"first_name": "_Test Employee 1",
				"gender": "Male",
				"naming_series": "_T-Employee-",
				"status": "Active",
				"user_id": "test1@example.com",
			},
			{
				"company": "_Test Company",
				"date_of_birth": "1980-01-01",
				"date_of_joining": "2010-01-01",
				"department": "_Test Department 1 - _TC",
				"doctype": "Employee",
				"first_name": "_Test Employee 2",
				"gender": "Male",
				"naming_series": "_T-Employee-",
				"status": "Active",
				"user_id": "test2@example.com",
			},
		]
		cls.employees = []
		for x in records:
			if not frappe.db.exists("Employee", {"first_name": x.get("first_name")}):
				cls.employees.append(frappe.get_doc(x).insert())
			else:
				cls.employees.append(frappe.get_doc("Employee", {"first_name": x.get("first_name")}))

	@classmethod
	def make_sales_person(cls):
		records = [
			{
				"doctype": "Sales Person",
				"employee": "_T-Employee-00001",
				"is_group": 0,
				"parent_sales_person": "Sales Team",
				"sales_person_name": "_Test Sales Person",
			},
			{
				"doctype": "Sales Person",
				"employee": "_T-Employee-00002",
				"is_group": 0,
				"parent_sales_person": "Sales Team",
				"sales_person_name": "_Test Sales Person 1",
			},
			{
				"doctype": "Sales Person",
				"employee": "_T-Employee-00003",
				"is_group": 0,
				"parent_sales_person": "Sales Team",
				"sales_person_name": "_Test Sales Person 2",
			},
		]
		cls.sales_person = []
		for x in records:
			if not frappe.db.exists("Sales Person", {"sales_person_name": x.get("sales_person_name")}):
				cls.sales_person.append(frappe.get_doc(x).insert())
			else:
				cls.sales_person.append(
					frappe.get_doc("Sales Person", {"sales_person_name": x.get("sales_person_name")})
				)

	@classmethod
	def make_leads(cls):
		records = [
			{
				"doctype": "Lead",
				"email_id": "test_lead@example.com",
				"lead_name": "_Test Lead",
				"status": "Open",
				"territory": "_Test Territory",
				"naming_series": "_T-Lead-",
			},
			{
				"doctype": "Lead",
				"email_id": "test_lead1@example.com",
				"lead_name": "_Test Lead 1",
				"status": "Open",
				"naming_series": "_T-Lead-",
			},
			{
				"doctype": "Lead",
				"email_id": "test_lead2@example.com",
				"lead_name": "_Test Lead 2",
				"status": "Lead",
				"naming_series": "_T-Lead-",
			},
			{
				"doctype": "Lead",
				"email_id": "test_lead3@example.com",
				"lead_name": "_Test Lead 3",
				"status": "Converted",
				"naming_series": "_T-Lead-",
			},
			{
				"doctype": "Lead",
				"email_id": "test_lead4@example.com",
				"lead_name": "_Test Lead 4",
				"company_name": "_Test Lead 4",
				"status": "Open",
				"naming_series": "_T-Lead-",
			},
		]
		cls.leads = []
		for x in records:
			if not frappe.db.exists("Lead", {"email_id": x.get("email_id")}):
				cls.leads.append(frappe.get_doc(x).insert())
			else:
				cls.leads.append(frappe.get_doc("Lead", {"email_id": x.get("email_id")}))

	@classmethod
	def make_holiday_list(cls):
		records = [
			{
				"doctype": "Holiday List",
				"from_date": "2013-01-01",
				"to_date": "2013-12-31",
				"holidays": [
					{"description": "New Year", "holiday_date": "2013-01-01"},
					{"description": "Republic Day", "holiday_date": "2013-01-26"},
					{"description": "Test Holiday", "holiday_date": "2013-02-01"},
				],
				"holiday_list_name": "_Test Holiday List",
			}
		]
		cls.holiday_list = []
		for x in records:
			if not frappe.db.exists("Holiday List", {"holiday_list_name": x.get("holiday_list_name")}):
				cls.holiday_list.append(frappe.get_doc(x).insert())
			else:
				cls.holiday_list.append(
					frappe.get_doc("Holiday List", {"holiday_list_name": x.get("holiday_list_name")})
				)

	@classmethod
	def make_company(cls):
		records = [
			{
				"abbr": "_TC",
				"company_name": "_Test Company",
				"country": "India",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
				"allow_account_creation_against_child_company": 1,
			},
			{
				"abbr": "_TC1",
				"company_name": "_Test Company 1",
				"country": "United States",
				"default_currency": "USD",
				"doctype": "Company",
				"domain": "Retail",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "_TC2",
				"company_name": "_Test Company 2",
				"default_currency": "EUR",
				"country": "Germany",
				"doctype": "Company",
				"domain": "Retail",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "_TC3",
				"company_name": "_Test Company 3",
				"is_group": 1,
				"country": "Pakistan",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "_TC4",
				"company_name": "_Test Company 4",
				"parent_company": "_Test Company 3",
				"is_group": 1,
				"country": "Pakistan",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "_TC5",
				"company_name": "_Test Company 5",
				"parent_company": "_Test Company 4",
				"country": "Pakistan",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "TCP1",
				"company_name": "_Test Company with perpetual inventory",
				"country": "India",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				"enable_perpetual_inventory": 1,
				# "default_holiday_list": cls.holiday_list[0].name,
			},
			{
				"abbr": "_TC6",
				"company_name": "_Test Company 6",
				"is_group": 1,
				"country": "India",
				"default_currency": "INR",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
			{
				"abbr": "_TC7",
				"company_name": "_Test Company 7",
				"parent_company": "_Test Company 6",
				"is_group": 1,
				"country": "United States",
				"default_currency": "USD",
				"doctype": "Company",
				"domain": "Manufacturing",
				"chart_of_accounts": "Standard",
				# "default_holiday_list": cls.holiday_list[0].name,
				"enable_perpetual_inventory": 0,
			},
		]
		cls.companies = []
		for x in records:
			if not frappe.db.exists("Company", {"company_name": x.get("company_name")}):
				cls.companies.append(frappe.get_doc(x).insert())
			else:
				cls.companies.append(frappe.get_doc("Company", {"company_name": x.get("company_name")}))

	@classmethod
	def make_fiscal_year(cls):
		records = [
			{
				"doctype": "Fiscal Year",
				"year": "_Test Short Fiscal Year 2011",
				"is_short_year": 1,
				"year_start_date": "2011-04-01",
				"year_end_date": "2011-12-31",
			}
		]

		start = 2012
		this_year = now_datetime().year
		end = now_datetime().year + 25
		# The current year fails to load with the following error:
		# Year start date or end date is overlapping with 2024. To avoid please set company
		# This is a quick-fix: if current FY is needed, please refactor test data properly
		for year in range(start, this_year):
			records.append(
				{
					"doctype": "Fiscal Year",
					"year": f"_Test Fiscal Year {year}",
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			)
		for year in range(this_year + 1, end):
			records.append(
				{
					"doctype": "Fiscal Year",
					"year": f"_Test Fiscal Year {year}",
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
				}
			)

		cls.fiscal_year = []
		for x in records:
			if not frappe.db.exists(
				"Fiscal Year",
				{"year_start_date": x.get("year_start_date"), "year_end_date": x.get("year_end_date")},
			):
				cls.fiscal_year.append(frappe.get_doc(x).insert())
			else:
				cls.fiscal_year.append(
					frappe.get_doc(
						"Fiscal Year",
						{
							"year_start_date": x.get("year_start_date"),
							"year_end_date": x.get("year_end_date"),
						},
					)
				)


@ERPNextTestSuite.registerAs(staticmethod)
@contextmanager
def change_settings(doctype, settings_dict=None, /, **settings) -> None:
	"""Temporarily: change settings in a settings doctype."""
	import copy

	if settings_dict is None:
		settings_dict = settings

	settings = frappe.get_doc(doctype)
	previous_settings = copy.deepcopy(settings_dict)
	for key in previous_settings:
		previous_settings[key] = getattr(settings, key)

	for key, value in settings_dict.items():
		setattr(settings, key, value)
	settings.save(ignore_permissions=True)

	yield

	settings = frappe.get_doc(doctype)
	for key, value in previous_settings.items():
		setattr(settings, key, value)
	settings.save(ignore_permissions=True)
