import frappe
from frappe.utils import (
	add_days,
	add_months,
	add_years,
	cint,
	cstr,
	date_diff,
	flt,
	get_last_day,
	is_last_day_of_the_month,
)

import erpnext


def get_depreciation_amount(
	asset_depr_schedule,
	asset,
	value_after_depreciation,
	yearly_opening_wdv,
	fb_row,
	schedule_idx=0,
	prev_depreciation_amount=0,
	has_wdv_or_dd_non_yearly_pro_rata=False,
	number_of_pending_depreciations=0,
	prev_per_day_depr=0,
):
	if fb_row.depreciation_method in ("Straight Line", "Manual"):
		return get_straight_line_or_manual_depr_amount(
			asset_depr_schedule,
			asset,
			fb_row,
			schedule_idx,
			value_after_depreciation,
			number_of_pending_depreciations,
		), None
	else:
		return get_wdv_or_dd_depr_amount(
			asset,
			fb_row,
			value_after_depreciation,
			yearly_opening_wdv,
			schedule_idx,
			prev_depreciation_amount,
			has_wdv_or_dd_non_yearly_pro_rata,
			asset_depr_schedule,
			prev_per_day_depr,
		)


def get_straight_line_or_manual_depr_amount(
	asset_depr_schedule,
	asset,
	fb_row,
	schedule_idx,
	value_after_depreciation,
	number_of_pending_depreciations,
):
	if fb_row.shift_based:
		return get_shift_depr_amount(asset_depr_schedule, asset, fb_row, schedule_idx)

	if fb_row.daily_prorata_based:
		amount = flt(asset.gross_purchase_amount) - flt(fb_row.expected_value_after_useful_life)
		return get_daily_prorata_based_straight_line_depr(
			asset, fb_row, schedule_idx, number_of_pending_depreciations, amount
		)
	else:
		return (flt(fb_row.value_after_depreciation) - flt(fb_row.expected_value_after_useful_life)) / (
			flt(number_of_pending_depreciations) / flt(fb_row.frequency_of_depreciation)
		)


def get_daily_prorata_based_straight_line_depr(
	asset, fb_row, schedule_idx, number_of_pending_depreciations, amount
):
	daily_depr_amount = get_daily_depr_amount(asset, fb_row, schedule_idx, amount)

	from_date, total_depreciable_days = _get_total_days(
		fb_row.depreciation_start_date, schedule_idx, fb_row.frequency_of_depreciation
	)
	return daily_depr_amount * total_depreciable_days


def get_daily_depr_amount(asset, fb_row, schedule_idx, amount):
	if cint(frappe.db.get_single_value("Accounts Settings", "calculate_depr_using_total_days")):
		total_days = (
			date_diff(
				get_last_day(
					add_months(
						fb_row.depreciation_start_date,
						flt(
							fb_row.total_number_of_depreciations
							- asset.opening_number_of_booked_depreciations
							- 1
						)
						* fb_row.frequency_of_depreciation,
					)
				),
				add_days(
					get_last_day(
						add_months(
							fb_row.depreciation_start_date,
							(
								fb_row.frequency_of_depreciation
								* (asset.opening_number_of_booked_depreciations + 1)
							)
							* -1,
						),
					),
					1,
				),
			)
			+ 1
		)

		return amount / total_days
	else:
		total_years = (
			flt(
				(fb_row.total_number_of_depreciations - fb_row.total_number_of_booked_depreciations)
				* fb_row.frequency_of_depreciation
			)
			/ 12
		)

		every_year_depr = amount / total_years

		depr_period_start_date = add_days(
			get_last_day(add_months(fb_row.depreciation_start_date, fb_row.frequency_of_depreciation * -1)), 1
		)

		year_start_date = add_years(
			depr_period_start_date, ((fb_row.frequency_of_depreciation * schedule_idx) // 12)
		)
		year_end_date = add_days(add_years(year_start_date, 1), -1)

		return every_year_depr / (date_diff(year_end_date, year_start_date) + 1)


def get_shift_depr_amount(asset_depr_schedule, asset, fb_row, schedule_idx):
	if asset_depr_schedule.get("__islocal") and not asset.flags.shift_allocation:
		return (
			flt(asset.gross_purchase_amount)
			- flt(asset.opening_accumulated_depreciation)
			- flt(fb_row.expected_value_after_useful_life)
		) / flt(fb_row.total_number_of_depreciations - asset.opening_number_of_booked_depreciations)

	asset_shift_factors_map = get_asset_shift_factors_map()
	shift = (
		asset_depr_schedule.schedules_before_clearing[schedule_idx].shift
		if len(asset_depr_schedule.schedules_before_clearing) > schedule_idx
		else None
	)
	shift_factor = asset_shift_factors_map.get(shift) if shift else 0

	shift_factors_sum = sum(
		flt(asset_shift_factors_map.get(schedule.shift))
		for schedule in asset_depr_schedule.schedules_before_clearing
	)

	return (
		(
			flt(asset.gross_purchase_amount)
			- flt(asset.opening_accumulated_depreciation)
			- flt(fb_row.expected_value_after_useful_life)
		)
		/ flt(shift_factors_sum)
	) * shift_factor


def get_asset_shift_factors_map():
	return dict(frappe.db.get_all("Asset Shift Factor", ["shift_name", "shift_factor"], as_list=True))


@erpnext.allow_regional
def get_wdv_or_dd_depr_amount(
	asset,
	fb_row,
	value_after_depreciation,
	yearly_opening_wdv,
	schedule_idx,
	prev_depreciation_amount,
	has_wdv_or_dd_non_yearly_pro_rata,
	asset_depr_schedule,
	prev_per_day_depr,
):
	return get_default_wdv_or_dd_depr_amount(
		asset,
		fb_row,
		value_after_depreciation,
		schedule_idx,
		prev_depreciation_amount,
		has_wdv_or_dd_non_yearly_pro_rata,
		asset_depr_schedule,
		prev_per_day_depr,
	)


def get_default_wdv_or_dd_depr_amount(
	asset,
	fb_row,
	value_after_depreciation,
	schedule_idx,
	prev_depreciation_amount,
	has_wdv_or_dd_non_yearly_pro_rata,
	asset_depr_schedule,
	prev_per_day_depr,
):
	if not fb_row.daily_prorata_based or cint(fb_row.frequency_of_depreciation) == 12:
		return _get_default_wdv_or_dd_depr_amount(
			asset,
			fb_row,
			value_after_depreciation,
			schedule_idx,
			prev_depreciation_amount,
			has_wdv_or_dd_non_yearly_pro_rata,
			asset_depr_schedule,
		), None
	else:
		return _get_daily_prorata_based_default_wdv_or_dd_depr_amount(
			asset,
			fb_row,
			value_after_depreciation,
			schedule_idx,
			prev_depreciation_amount,
			has_wdv_or_dd_non_yearly_pro_rata,
			asset_depr_schedule,
			prev_per_day_depr,
		)


def _get_default_wdv_or_dd_depr_amount(
	asset,
	fb_row,
	value_after_depreciation,
	schedule_idx,
	prev_depreciation_amount,
	has_wdv_or_dd_non_yearly_pro_rata,
	asset_depr_schedule,
):
	if cint(fb_row.frequency_of_depreciation) == 12:
		return flt(value_after_depreciation) * (flt(fb_row.rate_of_depreciation) / 100)
	else:
		if has_wdv_or_dd_non_yearly_pro_rata:
			if schedule_idx == 0:
				return flt(value_after_depreciation) * (flt(fb_row.rate_of_depreciation) / 100)
			elif schedule_idx % (12 / cint(fb_row.frequency_of_depreciation)) == 1:
				return (
					flt(value_after_depreciation)
					* flt(fb_row.frequency_of_depreciation)
					* (flt(fb_row.rate_of_depreciation) / 1200)
				)
			else:
				return prev_depreciation_amount
		else:
			if schedule_idx % (12 / cint(fb_row.frequency_of_depreciation)) == 0:
				return (
					flt(value_after_depreciation)
					* flt(fb_row.frequency_of_depreciation)
					* (flt(fb_row.rate_of_depreciation) / 1200)
				)
			else:
				return prev_depreciation_amount


def _get_daily_prorata_based_default_wdv_or_dd_depr_amount(
	asset,
	fb_row,
	value_after_depreciation,
	schedule_idx,
	prev_depreciation_amount,
	has_wdv_or_dd_non_yearly_pro_rata,
	asset_depr_schedule,
	prev_per_day_depr,
):
	if has_wdv_or_dd_non_yearly_pro_rata:  # If applicable days for ther first month is less than full month
		if schedule_idx == 0:
			return flt(value_after_depreciation) * (flt(fb_row.rate_of_depreciation) / 100), None

		elif schedule_idx % (12 / cint(fb_row.frequency_of_depreciation)) == 1:  # Year changes
			return get_monthly_depr_amount(fb_row, schedule_idx, value_after_depreciation)
		else:
			return get_monthly_depr_amount_based_on_prev_per_day_depr(fb_row, schedule_idx, prev_per_day_depr)
	else:
		if schedule_idx % (12 / cint(fb_row.frequency_of_depreciation)) == 0:  # year changes
			return get_monthly_depr_amount(fb_row, schedule_idx, value_after_depreciation)
		else:
			return get_monthly_depr_amount_based_on_prev_per_day_depr(fb_row, schedule_idx, prev_per_day_depr)


def get_monthly_depr_amount(fb_row, schedule_idx, value_after_depreciation):
	"""
	Returns monthly depreciation amount when year changes
	1. Calculate per day depr based on new year
	2. Calculate monthly amount based on new per day amount
	"""
	from_date, days_in_month = _get_total_days(
		fb_row.depreciation_start_date, schedule_idx, cint(fb_row.frequency_of_depreciation)
	)
	per_day_depr = get_per_day_depr(fb_row, value_after_depreciation, from_date)
	return (per_day_depr * days_in_month), per_day_depr


def get_monthly_depr_amount_based_on_prev_per_day_depr(fb_row, schedule_idx, prev_per_day_depr):
	""" "
	Returns monthly depreciation amount based on prev per day depr
	Calculate per day depr only for the first month
	"""
	from_date, days_in_month = _get_total_days(
		fb_row.depreciation_start_date, schedule_idx, cint(fb_row.frequency_of_depreciation)
	)
	return (prev_per_day_depr * days_in_month), prev_per_day_depr


def get_per_day_depr(
	fb_row,
	value_after_depreciation,
	from_date,
):
	to_date = add_days(add_years(from_date, 1), -1)
	total_days = date_diff(to_date, from_date) + 1
	per_day_depr = (flt(value_after_depreciation) * (flt(fb_row.rate_of_depreciation) / 100)) / total_days
	return per_day_depr


def _get_total_days(depreciation_start_date, schedule_idx, frequency_of_depreciation):
	from_date = add_months(depreciation_start_date, (schedule_idx - 1) * frequency_of_depreciation)
	to_date = add_months(from_date, frequency_of_depreciation)
	if is_last_day_of_the_month(depreciation_start_date):
		to_date = get_last_day(to_date)
		from_date = add_days(get_last_day(from_date), 1)
	return from_date, date_diff(to_date, from_date) + 1
