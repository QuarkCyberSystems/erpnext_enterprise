"""
Welcome to the Deprecation Dumpster: Where Old Code Goes to Party! 🎉🗑️

This file is the final resting place (or should we say, "retirement home"?) for all the deprecated functions and methods of the ERPNext app. It's like a code nursing home, but with more monkey-patching and less bingo.

Each function or method that checks in here comes with its own personalized decorator, complete with:
1. The date it was marked for deprecation (its "over the hill" birthday)
2. The ERPNext version in which it will be removed (its "graduation" to the great codebase in the sky)
3. A user-facing note on alternative solutions (its "parting wisdom")

Warning: The global namespace herein is more patched up than a sailor's favorite pair of jeans. Proceed with caution and a sense of humor!

Remember, deprecated doesn't mean useless - it just means these functions are enjoying their golden years before their final bow. Treat them with respect, and maybe bring them some virtual prune juice.

Enjoy your stay in the Deprecation Dumpster, where every function gets a second chance to shine (or at least, to not break everything).
"""

import sys
import warnings


def colorize(text, color_code):
	if sys.stdout.isatty():
		return f"\033[{color_code}m{text}\033[0m"
	return text


class Color:
	RED = 91
	YELLOW = 93
	CYAN = 96


class ERPNextDeprecationWarning(Warning):
	...


try:
	# since python 3.13, PEP 702
	from warnings import deprecated as _deprecated
except ImportError:
	import functools
	import warnings
	from collections.abc import Callable
	from typing import Optional, TypeVar, Union, overload

	T = TypeVar("T", bound=Callable)

	def _deprecated(message: str, category=ERPNextDeprecationWarning, stacklevel=1) -> Callable[[T], T]:
		def decorator(func: T) -> T:
			@functools.wraps(func)
			def wrapper(*args, **kwargs):
				if message:
					warning_msg = f"{func.__name__} is deprecated.\n{message}"
				else:
					warning_msg = f"{func.__name__} is deprecated."
				warnings.warn(warning_msg, category=category, stacklevel=stacklevel + 1)
				return func(*args, **kwargs)

			return wrapper
			wrapper.__deprecated__ = True  # hint for the type checker

		return decorator


def deprecated(original: str, marked: str, graduation: str, msg: str, stacklevel: int = 1):
	"""Decorator to wrap a function/method as deprecated.

	Arguments:
	        - original: frappe.utils.make_esc  (fully qualified)
	        - marked: 2024-09-13  (the date it has been marked)
	        - graduation: v17  (generally: current version + 2)
	        - msg: additional instructions
	"""

	def decorator(func):
		# Get the filename of the caller
		func.__name__ = original
		wrapper = _deprecated(
			colorize(f"It was marked on {marked} for removal from {graduation} with note: ", Color.RED)
			+ colorize(f"{msg}", Color.YELLOW),
			stacklevel=stacklevel,
		)

		return functools.update_wrapper(wrapper, func)(func)

	return decorator


def deprecation_warning(marked: str, graduation: str, msg: str):
	"""Warn in-place from a deprecated code path, for objects use `@deprecated` decorator from the deprectation_dumpster"

	Arguments:
	        - marked: 2024-09-13  (the date it has been marked)
	        - graduation: v17  (generally: current version + 2)
	        - msg: additional instructions
	"""

	warnings.warn(
		colorize(
			f"This codepath was marked (DATE: {marked}) deprecated"
			f" for removal (from {graduation} onwards); note:\n ",
			Color.RED,
		)
		+ colorize(f"{msg}\n", Color.YELLOW),
		category=ERPNextDeprecationWarning,
		stacklevel=2,
	)


### Party starts here
@deprecated(
	"erpnext.controllers.taxes_and_totals.get_itemised_taxable_amount",
	"2024-11-07",
	"v17",
	"The field item_wise_tax_detail now already contains the net_amount per tax.",
)
def taxes_and_totals_get_itemised_taxable_amount(items):
	import frappe

	itemised_taxable_amount = frappe._dict()
	for item in items:
		item_code = item.item_code or item.item_name
		itemised_taxable_amount.setdefault(item_code, 0)
		itemised_taxable_amount[item_code] += item.net_amount

	return itemised_taxable_amount


@deprecated(
	"erpnext.stock.get_pos_profile_item_details",
	"2024-11-19",
	"v16",
	"Use erpnext.stock.get_pos_profile_item_details_ with a flipped signature",
)
def get_pos_profile_item_details(company, ctx, pos_profile=None, update_data=False):
	from erpnext.stock.get_item_details import get_pos_profile_item_details_

	return get_pos_profile_item_details_(ctx, company, pos_profile=pos_profile, update_data=update_data)


@deprecated(
	"erpnext.stock.get_item_warehouse",
	"2024-11-19",
	"v16",
	"Use erpnext.stock.get_item_warehouse_ with a flipped signature",
)
def get_item_warehouse(item, ctx, overwrite_warehouse, defaults=None):
	from erpnext.stock.get_item_details import get_item_warehouse_

	return get_item_warehouse_(ctx, item, overwrite_warehouse, defaults=defaults)
